"""Phrase boosting in Parakeet's greedy TDT decoding: does it fix jargon without inventing it?

Usage (from the repo root):
  .venv\\Scripts\\python spikes/stt/boost_bench.py [--bonus 0,1,2,3,4,6] [--lists hand,auto] [--limit N]

Each clip is encoded once; the decoder (a copy of onnx-asr's greedy TDT loop)
then runs once per bonus. Boosting: a prefix trie over the phrases' text (see
Phrases). At a word start, tokens that begin a phrase get `bonus` added to their
logits; inside a phrase, the tokens that continue it do. A phrase counts once a
word boundary follows it. If it is left unfinished and the bonus changed any token
on the way, decoding goes back to where it began and goes on without bonuses
until that attempt is over (the greedy form of NeMo's "take back the bonus").
Log-probabilities come from the unboosted distribution, so Swift's reject_p /
unclear_p checks see what the model thought.

Vocabularies: "hand" (spikes/stt/vocab_hand.txt, drawn from the test sentences,
so it flatters the result) and "auto" (repo file and folder names plus branch
names, from git). Test sets: the clean corpus, the real noisy corpus (tv, music,
far, plus its quiet takes), babble mixes at 5 and 0 dB (noise_bench.py), and
noise with nobody speaking. For WER, "x.y" in a transcript counts as "x dot y",
the way the reference sentences are written ("PLAN dot md").
Results go to spikes/stt/results/ (gitignored).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _util import machine_info  # noqa: E402
from bench import normalize, trim_silence, wer  # noqa: E402
from corpus import SAMPLE_RATE, read_wav  # noqa: E402
from noise_bench import NOISES, load_model, make_noise, mix  # noqa: E402
from real_noise import CLEAN_DIR, NOISY_DIR, refs  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
SPACE = " "  # onnx-asr stores the SentencePiece word marker (U+2581) as a space


def norm(text: str) -> str:
    return normalize(re.sub(r"(\w)\.(\w)", r"\1 dot \2", text))


# --- vocabularies -------------------------------------------------------------------------


def hand_list() -> list[str]:
    lines = (HERE / "vocab_hand.txt").read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def auto_list() -> list[str]:
    """File and folder names tracked by git, their stems, and branch names (as spoken)."""
    files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    branches = subprocess.run(["git", "branch", "-a", "--format=%(refname:short)"], cwd=REPO,
                              capture_output=True, text=True, check=True).stdout.split()
    names: set[str] = set()
    for f in files:
        for part in f.split("/"):
            if part.endswith((".png", ".ico", ".icns", ".lock")):
                continue
            names.add(part)
            if "." in part.strip("."):
                names.add(part.rsplit(".", 1)[0])
    for b in branches:
        tail = re.sub(r"-[0-9a-f]{6}$", "", b.split("/")[-1])  # worktree suffix
        names.add(tail)
    out = set()
    for n in names:
        n = n.strip("._")
        if len(n) < 3 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.\-]*", n):
            continue
        out.add(re.sub(r"[_\-]+", " ", n))  # test_voice.py is said "test voice dot py"
    return sorted(out)


# --- the phrase matcher ---------------------------------------------------------------------


class Phrases:
    """A prefix trie over phrase text, walked a token at a time.

    It matches characters rather than pieces: vocab.txt has no piece scores, the
    model's own spelling of a word isn't the fewest-pieces one (" over" "l" "ay"),
    and with 1024 short pieces a word has many spellings. Any token whose text
    keeps the match on a phrase counts. Matching ignores case beyond these variants:
    as written, lower case, first letter capital, every word capital.
    """

    def __init__(self, phrases: list[str], vocab: dict[int, str]) -> None:
        self.vocab = {i: t for i, t in vocab.items() if t not in ("<unk>", "<blk>")}
        self.ends: set[str] = set()
        for p in phrases:
            for v in (p, p.lower(), p[:1].upper() + p[1:], " ".join(w[:1].upper() + w[1:] for w in p.split())):
                self.ends.add(SPACE + v)
        self.prefixes = {e[:i] for e in self.ends for i in range(1, len(e) + 1)}
        self.longer = {e[:i] for e in self.ends for i in range(1, len(e))}  # can still grow
        self._next: dict[str, dict[int, str]] = {}

    def next(self, matched: str) -> dict[int, str]:
        """Tokens that keep `matched` ("" = at a word start) on a phrase, and the new match."""
        if matched not in self._next:
            out = {}
            for i, tok in self.vocab.items():
                m = matched + tok
                if (matched or tok.startswith(SPACE)) and m in self.prefixes:
                    out[i] = m
            self._next[matched] = out
        return self._next[matched]


# --- decoding -------------------------------------------------------------------------------------


def log_softmax(x: np.ndarray) -> np.ndarray:
    m = x.max()
    return x - m - np.log(np.exp(x - m).sum())


@dataclass
class Decoded:
    ids: list[int]
    steps: list[int]
    logprobs: list[float]  # unboosted
    boosted_logprobs: list[float]
    rollbacks: int
    flips: int  # tokens the bonus changed in the final transcript


_PUNCT_TOKEN = re.compile(r"[^\w'\-]+")


def boundary(tok: str) -> bool:
    """Does this token end the word before it? (A new word, or punctuation other than ' and -.)"""
    return tok.startswith(SPACE) or bool(_PUNCT_TOKEN.fullmatch(tok))


def decode(asr, enc: np.ndarray, length: int, phrases: Phrases | None, bonus: float,
           trace: list | None = None) -> Decoded:
    """onnx-asr's greedy TDT loop (_AsrWithTransducerDecoding._decoding) with phrase boosting.

    A phrase counts as said once its last piece is followed by a word boundary (or
    the end of the clip), so "overlay" doesn't turn "overload" into "overlays". When
    a phrase fails and the bonus changed any token since `start` (where the attempt
    began), decoding goes back there and runs without bonuses until that attempt is
    over. `commit` is the point just after a shorter phrase inside a longer one
    ("git" in "git log"), the place to go back to first.
    """
    blank = asr._blank_idx
    boost = phrases is not None and bonus > 0
    state = asr._create_state()
    ids: list[int] = []
    steps: list[int] = []
    lps: list[float] = []
    blps: list[float] = []
    flipped: list[bool] = []  # the bonus chose this token
    t = emitted = 0
    matched: str | None = None  # text of the partial phrase being matched
    start: tuple | None = None  # (t, emitted, state, len(ids), matched) before the attempt's first token
    commit: tuple | None = None  # same, just after a complete shorter phrase
    quiet = False  # after a rollback: no bonuses until that attempt is over
    rollbacks = 0

    def back_to(snap: tuple) -> None:
        nonlocal t, emitted, state, matched, start, commit, quiet, rollbacks
        t, emitted, state, n, matched = snap
        del ids[n:], steps[n:], lps[n:], blps[n:], flipped[n:]
        if snap is start:
            start = None
        commit, quiet = None, True
        rollbacks += 1
        if trace is not None:
            trace.append(("back", t, n))

    def failed(next_tok: str | None) -> tuple | None:
        """The attempt can't go on with next_tok (None = end of clip): where to go back to, if anywhere."""
        if matched is None or matched in phrases.ends and (next_tok is None or boundary(next_tok)):
            return None
        if commit is not None:
            n = commit[3]
            if any(flipped[n:]):
                return commit
            if boundary(phrases.vocab.get(ids[n], "") if n < len(ids) else next_tok or " "):
                return None  # the shorter phrase stands, unboosted after it
        return start if start is not None and any(flipped[start[3]:]) else None

    while True:
        if t >= length:
            if boost and (snap := failed(None)) is not None:
                back_to(snap)
                continue
            break
        logits, step, new_state = asr._decode(ids, state, enc[t])
        plain = token = int(logits.argmax())
        lsm = None
        if boost and not quiet:
            # Inside a phrase only its continuations get the bonus, so whether the word ends
            # there is the model's own call.
            cand = phrases.next("" if matched is None else matched).keys()
            scores = logits.copy()
            if cand:
                scores[list(cand)] += bonus
            token = int(scores.argmax())
            lsm = log_softmax(scores)

        reached_end = False
        if token != blank:
            cont = phrases.next(matched).get(token) if boost and matched is not None else None
            if cont is not None:
                matched = cont
            elif boost:
                if (snap := failed(phrases.vocab[token])) is not None:
                    back_to(snap)  # the phrase wasn't finished: undo the bonus's tokens
                    continue
                matched = phrases.next("").get(token)
                start = (t, emitted, state, len(ids), None) if matched is not None else None
                commit = None
                quiet = quiet and matched is not None  # same spot, same start: keep it unboosted
            state = new_state
            ids.append(token)
            steps.append(t)
            lp = log_softmax(logits)
            lps.append(float(lp[token]))
            blps.append(float((lp if lsm is None else lsm)[token]))
            flipped.append(token != plain)
            emitted += 1
            if trace is not None:
                trace.append((t, phrases.vocab.get(token) if phrases else token, token != plain, matched, quiet,
                              start[3] if start else None))
            reached_end = matched is not None and matched in phrases.ends and matched in phrases.longer
        if step > 0:
            t += step
            emitted = 0
        elif token == blank or emitted == asr._max_tokens_per_step:
            t += 1
            emitted = 0
        if reached_end:
            commit = (t, emitted, state, len(ids), matched)
    return Decoded(ids, steps, lps, blps, rollbacks, sum(flipped))


# --- the bench -----------------------------------------------------------------------------------


@dataclass
class Clip:
    set: str
    id: str
    ref: str
    enc: np.ndarray
    length: int
    enc_ms: float
    audio_s: float


def encode(asr, audio: np.ndarray) -> tuple[np.ndarray, int, float]:
    w = trim_silence(audio.astype(np.float32))[None, :]
    t0 = time.perf_counter()
    enc, lens = asr._encode(*asr._preprocessor(w, np.array([w.shape[1]], dtype=np.int64)))
    return enc[0], int(lens[0]), (time.perf_counter() - t0) * 1000


def load_clips(asr, limit: int) -> list[Clip]:
    clips: list[Clip] = []

    def add(set_: str, id_: str, ref: str, audio: np.ndarray) -> None:
        enc, n, ms = encode(asr, audio)
        clips.append(Clip(set_, id_, ref, enc, n, ms, len(audio) / SAMPLE_RATE))

    clean_rows = [r for r in refs(CLEAN_DIR) if r["ref"]][: limit or None]
    clean = [read_wav(CLEAN_DIR / r["wav"]).astype(np.float64) / 32768.0 for r in clean_rows]
    for r, a in zip(clean_rows, clean):
        add("clean", r["id"], r["ref"], a)
    for r in refs(NOISY_DIR)[: limit or None]:
        add(r.get("condition") or "noisy", r["id"], r["ref"], read_wav(NOISY_DIR / r["wav"]).astype(np.float64) / 32768.0)
    for snr in (5, 0):
        rng = np.random.default_rng(7)
        for i, (r, a) in enumerate(zip(clean_rows, clean)):
            others = [c for j, c in enumerate(clean) if j != i]
            add(f"babble{snr}", r["id"], r["ref"], mix(a, make_noise("babble", len(a), rng, others), snr))
    rng = np.random.default_rng(11)
    for kind in NOISES:
        for k in range(10):
            noise = make_noise(kind, int(2.5 * SAMPLE_RATE), rng, clean)
            add(f"only-{kind}", f"noise-{k}", "", noise / np.sqrt(np.mean(noise**2)) * 10 ** (-35 / 20))
    return clips


def phrase_words(phrases: list[str]) -> set[str]:
    """Normalized words of the boosted phrases, 3+ letters (to spot insertions)."""
    return {w for p in phrases for w in norm(p).split() if len(w) > 2}


def run_config(asr, clips: list[Clip], phrases: Phrases | None, bonus: float) -> list[dict]:
    from swift.stt.transcriber import Transcription, assess, words_from_tokens

    out = []
    for c in clips:
        t0 = time.perf_counter()
        d = decode(asr, c.enc, c.length, phrases, bonus)
        dec_ms = (time.perf_counter() - t0) * 1000
        res = asr._decode_tokens(d.ids, d.steps, d.logprobs)
        text = res.text.strip()
        words = words_from_tokens(res.tokens, d.logprobs)
        bwords = words_from_tokens(res.tokens, d.boosted_logprobs)
        tr = Transcription(text, 0, c.audio_s, words=words if text else None)
        tb = Transcription(text, 0, c.audio_s, words=bwords if text else None)
        out.append({
            "set": c.set, "id": c.id, "ref": c.ref, "hyp": text,
            "outcome": assess(tr) if text else "empty", "outcome_boosted_p": assess(tb) if text else "empty",
            "unclear": tr.unclear(), "mean_p": round(sum(w.p for w in words) / len(words), 3) if words else None,
            "rollbacks": d.rollbacks, "flips": d.flips, "enc_ms": round(c.enc_ms, 1), "dec_ms": round(dec_ms, 1),
        })
    return out


def summarize(rows: list[dict], base: list[dict], vocab_words: set[str]) -> dict:
    sets = list(dict.fromkeys(r["set"] for r in rows))
    s: dict = {"wer": {}, "invented": {}, "outcomes": {}}
    for name in sets:
        rs = [r for r in rows if r["set"] == name]
        if any(r["ref"] for r in rs):
            sp = [r for r in rs if r["ref"]]
            s["wer"][name] = round(wer([norm(r["ref"]) for r in sp], [norm(r["hyp"]) for r in sp]), 4)
            s["outcomes"][name] = {o: sum(r["outcome"] == o for r in sp) for o in ("clear", "partly", "unclear", "empty")}
        quiet = [r for r in rs if not r["ref"]]
        if quiet:
            s["invented"][name] = sum(bool(r["hyp"]) for r in quiet)
    # New insertions: boosted-vocabulary words that are in neither the reference nor the unboosted transcript.
    ins = []
    for r, b in zip(rows, base):
        new = [w for w in norm(r["hyp"]).split()
               if w in vocab_words and w not in norm(r["ref"]).split() and w not in norm(b["hyp"]).split()]
        if new:
            ins.append({"set": r["set"], "id": r["id"], "words": new, "hyp": r["hyp"], "base": b["hyp"]})
    s["insertions"] = ins
    s["changed"] = [{"set": r["set"], "id": r["id"], "ref": r["ref"], "base": b["hyp"], "hyp": r["hyp"],
                     "outcome": f"{b['outcome']} -> {r['outcome']}"}
                    for r, b in zip(rows, base) if r["hyp"] != b["hyp"]]
    s["outcome_flips"] = sum(r["outcome"] != r["outcome_boosted_p"] for r in rows)
    s["dec_ms_p50"] = float(np.median([r["dec_ms"] for r in rows]))
    s["dec_ms_max"] = float(max(r["dec_ms"] for r in rows))
    s["rollbacks"] = sum(r["rollbacks"] for r in rows)
    return s


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bonus", default="1,2,3,4,6")
    ap.add_argument("--lists", default="hand,auto")
    ap.add_argument("--limit", type=int, default=0, help="first N clips of each corpus (quick check)")
    ap.add_argument("--show", type=float, default=None, help="print every changed transcript at this bonus")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    model = load_model()
    asr = model.asr
    t0 = time.perf_counter()
    clips = load_clips(asr, args.limit)
    print(f"{len(clips)} clips encoded in {time.perf_counter() - t0:.0f}s "
          f"(encoder median {np.median([c.enc_ms for c in clips]):.0f} ms)")

    # The copied loop must reproduce onnx-asr's own output when nothing is boosted.
    probe = clips[0]
    audio = read_wav(CLEAN_DIR / [r for r in refs(CLEAN_DIR) if r["ref"]][0]["wav"]).astype(np.float64) / 32768.0
    lib = model.recognize(trim_silence(audio.astype(np.float32)), sample_rate=SAMPLE_RATE)
    d = decode(asr, probe.enc, probe.length, None, 0)
    assert lib.text == asr._decode_tokens(d.ids, d.steps, d.logprobs).text, lib.text

    base = run_config(asr, clips, None, 0)
    lists = {"hand": hand_list(), "auto": auto_list()}
    bonuses = [float(b) for b in args.bonus.split(",")]
    report: dict = {"baseline": summarize(base, base, set())}
    tries = {}
    for name in args.lists.split(","):
        tries[name] = Phrases(lists[name], asr._vocab)
        print(f"vocab {name}: {len(lists[name])} phrases, {len(tries[name].next(''))} tokens can start one")
    all_rows: dict = {"baseline": base}
    for name in args.lists.split(","):
        for b in bonuses:
            rows = run_config(asr, clips, tries[name], b)
            all_rows[f"{name}@{b:g}"] = rows
            report[f"{name}@{b:g}"] = summarize(rows, base, phrase_words(lists[name]))

    sets = list(report["baseline"]["wer"])
    quiet = list(report["baseline"]["invented"])
    print(f"\n{'config':12}" + "".join(f"{s:>9}" for s in sets) + "  invented(" + ",".join(quiet) + ")"
          + f"{'ins':>5}{'rollb':>6}{'p-flip':>7}{'dec p50/max ms':>16}")
    for k, s in report.items():
        print(f"{k:12}" + "".join(f"{s['wer'][x]:9.3f}" for x in sets)
              + f"  {sum(s['invented'].values()):>3} " + "/".join(str(s["invented"][q]) for q in quiet)
              + f"{len(s['insertions']):>5}{s['rollbacks']:>6}{s['outcome_flips']:>7}"
              + f"{s['dec_ms_p50']:>9.0f} / {s['dec_ms_max']:.0f}")
    print("\noutcomes on clean / tv / music / far (clear, partly, unclear, empty):")
    for k, s in report.items():
        print(f"  {k:12}" + "  ".join(f"{x}: " + "/".join(str(v) for v in s["outcomes"][x].values())
                                      for x in sets if x in ("clean", "tv", "music", "far")))
    print("\nnew insertions of boosted words (not in the reference or the unboosted transcript):")
    for k, s in report.items():
        for i in s["insertions"]:
            print(f"  {k:10} {i['set']:10} {i['id']}: {i['words']}  \"{i['base']}\" -> \"{i['hyp']}\"")
    if args.show is not None:
        for name in args.lists.split(","):
            k = f"{name}@{args.show:g}"
            print(f"\nchanged transcripts, {k}:")
            for c in report[k]["changed"]:
                print(f"  {c['set']:9} {c['id']}: \"{c['base']}\" -> \"{c['hyp']}\"   (ref \"{c['ref']}\"; {c['outcome']})")

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"boost-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"machine": machine_info(), "lists": lists, "report": report, "rows": all_rows},
                              indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
