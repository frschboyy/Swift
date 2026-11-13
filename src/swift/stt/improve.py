"""The improvement pass over the owner's test set (audit B-06; ``swift.stt.recordings``).

Run on demand (the tray's "Improve speech recognition") and once a week while the owner is idle,
on this PC only. Over the test set (clips whose words the owner gave by repeating or correcting):

1. **Word fixes** (as ``spikes/stt/learn_fixes.py``): each clip is transcribed as Swift would,
   without fixes, lined up against the known words, and the phrases it got wrong become proposed
   fixes ("tori" -> "Tauri"). The same safety rules drop formatting-only differences, errors at
   the very start of a clip, phrases longer than three words, phrases the owner also said for real,
   and fixes already kept or rejected. They are shown on a card; nothing is applied unless the
   owner approves (``approve`` writes them to ``stt.word_fixes_file``, ``reject`` remembers them).
2. **Accuracy check** (as ``spikes/stt/model_compare.py`` and ``noise_bench.py``): the word error
   rate with the fixes in use, clean and with pink noise mixed in at 10 dB, compared clip for clip
   with the last pass. A rise of more than ``DROP`` on the clips both passes saw is reported, and
   so is any sentence that was exactly right last time and isn't now (seams audit W-03).
3. **End-of-speech feed:** per clip, how long it was, the silence before and after the speech
   and the longest pause inside it (``endpoint_feed.json`` in the test set's folder, content-free),
   for end-of-speech tuning (``swift/endpoint.py``, ``spikes/endpointing``).

Logs carry counts and rates only. Nothing is uploaded and no model is trained.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

from swift.stt.recordings import SAMPLE_RATE, Recordings, read_wav

MAX_WORDS = 3
# A rise in word error rate bigger than this, on the clips both passes saw, is reported.
DROP = 0.02
NOISE_SNR_DB = 10.0
STATE = "improve.json"
FEED = "endpoint_feed.json"
NUMBERS = "zero one two three four five six seven eight nine ten eleven twelve".split()
FILLERS = {"um", "umm", "uh", "uhh", "er", "erm", "hmm", "mm", "ah"}
_WORD = re.compile(r"[\w']+")
_ISE = re.compile(r"is(e|ed|es|ing)$")
BLOCK = 512  # 32 ms

# (text with fixes, text without) for 16 kHz int16-scaled samples.
Recognize = Callable[[np.ndarray], tuple[str, str]]


def tokens(text: str) -> list[str]:
    return _WORD.findall(text)


def normalize(text: str) -> list[str]:
    """For scoring: case, punctuation, "3"/"three" and hesitations aside."""
    out = []
    for w in tokens(text.lower().replace("-", " ")):
        if w.isdigit() and int(w) < len(NUMBERS):
            w = NUMBERS[int(w)]
        if w not in FILLERS:
            out.append(_ISE.sub(r"iz\1", w))  # "summarise" is "summarize" spelled, not misheard
    return out


def compact(phrase: str) -> str:
    """Spelling-insensitive form: no spaces or apostrophes, digits for small numbers, -ize for -ise."""
    out = []
    for w in phrase.lower().replace("'", "").split():
        w = str(NUMBERS.index(w)) if w in NUMBERS else w
        out.append(_ISE.sub(r"iz\1", w))
    return "".join(out)


def align(ref: list[str], hyp: list[str]) -> list[tuple[str, int, int, int, int]]:
    """Edit-distance alignment: ``(op, ref_start, ref_end, hyp_start, hyp_end)`` per word, op one
    of equal / sub / del / ins."""
    n, m = len(ref), len(hyp)
    d = np.zeros((n + 1, m + 1), dtype=np.int32)
    d[:, 0] = np.arange(n + 1)
    d[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]))
    ops: list[tuple[str, int, int, int, int]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i, j] == d[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append(("equal" if ref[i - 1] == hyp[j - 1] else "sub", i - 1, i, j - 1, j))
            i, j = i - 1, j - 1
        elif i > 0 and d[i, j] == d[i - 1, j] + 1:
            ops.append(("del", i - 1, i, j, j))
            i -= 1
        else:
            ops.append(("ins", i, i, j - 1, j))
            j -= 1
    return ops[::-1]


def edits(ref: list[str], hyp: list[str]) -> int:
    if "".join(ref) == "".join(hyp):
        return 0  # the same letters spaced differently ("read me" / "readme", "p m" / "pm")
    return sum(op != "equal" for op, *_ in align(ref, hyp)) if ref or hyp else 0


def error_spans(ref_raw: str, hyp_raw: str) -> list[tuple[str, str, int]]:
    """(heard, meant, start index in hyp) for each run of differing words; ``meant`` keeps the
    known words' casing, so "Tauri" stays capitalized."""
    ref_t, hyp_t = tokens(ref_raw), tokens(hyp_raw)
    if not ref_t or not hyp_t:
        return []
    spans: list[tuple[str, str, int]] = []
    run: list[tuple[str, int, int, int, int]] = []

    def flush() -> None:
        if run:
            r0, r1, h0, h1 = run[0][1], run[-1][2], run[0][3], run[-1][4]
            spans.append((" ".join(hyp_t[h0:h1]).lower(), " ".join(ref_t[r0:r1]), h0))
            run.clear()

    for op in align([t.lower() for t in ref_t], [t.lower() for t in hyp_t]):
        if op[0] == "equal":
            flush()
        else:
            run.append(op)
    flush()
    return spans


@dataclass(frozen=True)
class Proposal:
    heard: str
    meant: str
    count: int


def candidates(rows: list[tuple[str, str]], known: set[tuple[str, str]]) -> list[Proposal]:
    """Word fixes from (known words, heard without fixes) pairs, most seen first."""
    said = " " + " | ".join(" ".join(tokens(ref.lower())) for ref, _ in rows) + " "
    counts: Counter[tuple[str, str]] = Counter()
    for ref, hyp in rows:
        for heard, meant, start in error_spans(ref, hyp):
            if not heard or not meant or start == 0:
                continue  # the start is usually the mic missing a syllable, not a word problem
            if len(heard.split()) > MAX_WORDS or len(meant.split()) > MAX_WORDS:
                continue
            if compact(heard) == compact(meant) or f" {heard} " in said:
                continue
            counts[(heard, meant)] += 1
    return [Proposal(h, m, n) for (h, m), n in counts.most_common() if (h, m) not in known]


def pink_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    spectrum = np.fft.rfft(rng.standard_normal(n))
    spectrum /= np.sqrt(np.maximum(np.arange(len(spectrum)), 1))
    noise = np.fft.irfft(spectrum, n)
    return noise / (np.std(noise) or 1.0)


def with_noise(audio: np.ndarray, snr_db: float, seed: int) -> np.ndarray:
    """``audio`` with pink noise ``snr_db`` below its speech (the loudest half of its blocks)."""
    x = audio.astype(np.float64)
    blocks = x[: len(x) // BLOCK * BLOCK].reshape(-1, BLOCK)
    if not len(blocks):
        return audio
    rms = np.sqrt(np.mean(blocks**2, axis=1))
    speech = float(np.sqrt(np.mean(np.sort(rms)[len(rms) // 2:] ** 2))) or 1.0
    noise = pink_noise(len(x), np.random.default_rng(seed)) * speech / 10 ** (snr_db / 20)
    return np.clip(x + noise, -32768, 32767).astype(np.float32)


def pauses(audio: np.ndarray) -> dict[str, float]:
    """Content-free timing of a clip: its length, the silence before and after the speech, and the
    longest pause inside it (blocks more than 30 dB under the loudest count as silence)."""
    x = audio.astype(np.float64)
    blocks = x[: len(x) // BLOCK * BLOCK].reshape(-1, BLOCK)
    out = {"audio_s": round(len(x) / SAMPLE_RATE, 2), "lead_s": 0.0, "trail_s": 0.0, "longest_pause_s": 0.0}
    if not len(blocks):
        return out
    db = 20 * np.log10(np.maximum(np.sqrt(np.mean(blocks**2, axis=1)), 1e-9))
    loud = np.flatnonzero(db >= db.max() - 30)
    first, last = int(loud[0]), int(loud[-1])
    block_s = BLOCK / SAMPLE_RATE
    longest = int(np.max(np.diff(loud)) - 1) if len(loud) > 1 else 0
    return out | {"lead_s": round(first * block_s, 2), "trail_s": round((len(db) - 1 - last) * block_s, 2),
                  "longest_pause_s": round(longest * block_s, 2)}


@dataclass
class Report:
    clips: int = 0
    wer: float | None = None
    wer_noisy: float | None = None
    # On the clips this pass and the last one both saw: then, and now.
    compared: int = 0
    wer_before: float | None = None
    wer_noisy_before: float | None = None
    wer_after: float | None = None
    wer_noisy_after: float | None = None
    # Clip ids that were exactly right last pass and aren't now (W-03). Clean audio only: a clip's
    # noise depends on its place in the set, so its noisy result can change with nothing else changed.
    regressed: list[str] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)

    @property
    def dropped(self) -> bool:
        if not self.compared:
            return False
        if self.regressed:
            return True
        clean = self.wer_before is not None and self.wer_after is not None and self.wer_after - self.wer_before > DROP
        noisy = (self.wer_noisy_before is not None and self.wer_noisy_after is not None
                 and self.wer_noisy_after - self.wer_noisy_before > DROP)
        return clean or noisy

    def counts(self) -> dict[str, Any]:
        """For the log: numbers only."""
        return {"clips": self.clips, "wer": self.wer, "wer_noisy": self.wer_noisy, "compared": self.compared,
                "wer_before": self.wer_before, "wer_after": self.wer_after, "dropped": self.dropped, "regressed": len(self.regressed),
                "proposals": len(self.proposals)}

    def summary(self) -> str:
        """The card's text (no transcripts)."""
        if not self.clips:
            return ("No clips to check yet. Swift keeps a clip when you say something again or correct it; "
                    "come back after a few days of use.")
        pct = lambda v: f"{round(v * 100)}%"  # noqa: E731
        lines = [f"Checked {self.clips} of your recordings: {pct(1 - (self.wer or 0))} of words right"
                 f" ({pct(1 - (self.wer_noisy or 0))} with noise added)."]
        if self.regressed:
            n = len(self.regressed)
            lines.append(f"{n} sentence{'s' if n > 1 else ''} Swift got right last time "
                         f"{'are' if n > 1 else 'is'} wrong now. "
                         "Something changed in speech recognition: worth a look.")
        elif self.dropped:
            lines.append(f"That's worse than last time on the same clips ({pct(1 - (self.wer_after or 0))}, "
                         f"was {pct(1 - (self.wer_before or 0))}). "
                         "Something changed in speech recognition: worth a look.")
        elif self.compared:
            lines.append("No worse than last time.")
        if not self.proposals:
            lines.append("No new word fixes.")
        return " ".join(lines)


def load_store(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"fixes": [], "rejected": []}
    data.setdefault("fixes", [])
    data.setdefault("rejected", [])
    return data


def save_store(path: Path, store: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def decide(path: Path, proposals: list[Proposal], approve: bool) -> None:
    """The owner's answer: approved fixes are added to the learned file, rejected ones never asked again."""
    store = load_store(path)
    for p in proposals:
        if approve:
            store["fixes"].append({"heard": p.heard, "meant": p.meant, "count": p.count, "enabled": True})
        else:
            store["rejected"].append([p.heard, p.meant])
    save_store(path, store)
    logger.info("word fixes decided", approved=approve, fixes=len(proposals))


def run_pass(recognize: Recognize, recordings: Recordings, fixes_file: Path) -> Report:
    """Blocking: transcribes every clip of the test set twice (clean, noisy). Run it in a thread."""
    folder = recordings.test_dir
    state_path = folder / STATE
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        state = {}
    before: dict[str, list[int]] = state.get("clips", {})
    report = Report()
    per_clip: dict[str, list[int]] = {}
    rows: list[tuple[str, str]] = []
    feed: list[dict[str, Any]] = []
    for entry in recordings.test_set():
        path = folder / entry["wav"]
        if not path.exists() or not entry.get("known"):
            continue
        audio = read_wav(path)
        text, raw = recognize(audio)
        noisy, _ = recognize(with_noise(audio, NOISE_SNR_DB, seed=len(per_clip)))
        ref = normalize(entry["known"])
        per_clip[entry["id"]] = [len(ref), edits(ref, normalize(text)), edits(ref, normalize(noisy))]
        rows.append((entry["known"], raw))
        feed.append({"id": entry["id"], "flags": entry.get("flags", []), "words": len(ref), **pauses(audio)})
    for entry in recordings.entries():  # clips not (yet) in the test set: timing only
        path = recordings.audio_dir / f"{entry['id']}.wav"
        if entry["id"] not in per_clip and path.exists():
            feed.append({"id": entry["id"], "flags": entry.get("flags", []), **pauses(read_wav(path))})

    def rate(clips: dict[str, list[int]], ids: set[str], col: int) -> float | None:
        words = sum(clips[i][0] for i in ids)
        return round(sum(clips[i][col] for i in ids) / words, 3) if words else None

    ids = set(per_clip)
    report.clips = len(ids)
    report.wer, report.wer_noisy = rate(per_clip, ids, 1), rate(per_clip, ids, 2)
    common = ids & set(before)
    if common:
        report.compared = len(common)
        report.wer_before, report.wer_noisy_before = rate(before, common, 1), rate(before, common, 2)
        report.wer_after, report.wer_noisy_after = rate(per_clip, common, 1), rate(per_clip, common, 2)
        report.regressed = sorted(i for i in common if before[i][1] == 0 and per_clip[i][1] > 0)
    store = load_store(fixes_file)
    known = {(f["heard"], f["meant"]) for f in store["fixes"]} | {tuple(r) for r in store["rejected"]}
    report.proposals = candidates(rows, known)  # type: ignore[arg-type]
    if ids:
        folder.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"clips": per_clip}, indent=0), encoding="utf-8")
    if feed:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / FEED).write_text(json.dumps({"clips": feed}, indent=1), encoding="utf-8")
    logger.info("improvement pass", **report.counts())
    return report


__all__ = ["Proposal", "Report", "candidates", "decide", "error_spans", "pauses", "run_pass", "with_noise"]
