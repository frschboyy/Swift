"""Check Swift's noise thresholds on real noisy recordings (docs/stt-noise.md, "Not done").

Usage (from the repo root):
  $env:SWIFT_STT_CORPUS = "$env:LOCALAPPDATA\\Swift\\stt_noisy"
  .venv\\Scripts\\python spikes/stt/corpus.py read --prompts spikes/stt/prompts_noisy.txt --condition tv
  .venv\\Scripts\\python spikes/stt/real_noise.py

Runs each clip through Swift's own transcriber (engine, word fixes and the
reject_p / unclear_p thresholds from config.yaml) and reports, per condition:
WER, how often Swift would act / name unclear words / refuse, and, for clips with
nobody speaking, whether anything was invented. The same sentences from the clean
corpus are the baseline. With --speaker it also scores each clip against an owner
profile enrolled on the clean corpus (WeSpeaker, as in speaker_bench.py).
Results go to spikes/stt/results/ (gitignored).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _util import machine_info, models_dir  # noqa: E402
from bench import normalize, wer  # noqa: E402
from corpus import SAMPLE_RATE, SWIFT_DIR, read_wav  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RESULTS = Path(__file__).resolve().parent / "results"
CLEAN_DIR = SWIFT_DIR / "stt_corpus"
NOISY_DIR = Path(os.environ.get("SWIFT_STT_CORPUS") or SWIFT_DIR / "stt_noisy")
SWEEP = [0.5, 0.6, 0.65, 0.7, 0.75, 0.8]
SPEAKER_T = 0.3
# What Swift would do: act, act but name the guessed words, refuse, or hear nothing.
OUTCOME = {"clear": "acted", "partly": "noted", "unclear": "refused"}


def refs(folder: Path) -> list[dict]:
    path = folder / "refs.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
    return [r for r in rows if r.get("ref") is not None]


def transcriber():
    from swift.backend.__main__ import _make_transcriber
    from swift.settings import load_settings

    settings = load_settings(REPO / "config.yaml")
    t = _make_transcriber(settings)
    t._load()
    if t._error is not None:
        raise SystemExit(str(t._error))
    return t, settings.stt


def mean_p(t) -> float | None:
    return round(sum(w.p for w in t.words) / len(t.words), 3) if t.words else None


def run(t, stt, folder: Path, rows: list[dict], condition: str | None = None) -> list[dict]:
    from swift.stt.transcriber import assess

    out = []
    for r in rows:
        audio = read_wav(folder / r["wav"])
        res = t._transcribe_sync(audio)
        out.append({
            "id": r["id"], "condition": condition or r.get("condition") or "?", "ref": r["ref"], "hyp": res.text,
            "wer": round(wer([normalize(r["ref"])], [normalize(res.text)]), 3) if r["ref"] else None,
            "outcome": OUTCOME[assess(res, stt.unclear_p, stt.reject_p)] if res.text else "empty", "mean_p": mean_p(res),
            "n_words": len(res.words or ()), "unclear": res.unclear(stt.unclear_p),
            "peak_db": res.peak_db, "audio": audio,
        })
    return out


def speaker_scores(results: list[dict], clean: list[dict]) -> None:
    from onnx_asr.loader import Manager

    from bench import trim_silence

    se = Manager().create_se(None, models_dir() / "wespeaker-resnet34")

    def emb(audio: np.ndarray) -> np.ndarray:
        v = se.embedding(trim_silence(audio.astype(np.float32) / 32768.0))
        return v / (np.linalg.norm(v) + 1e-9)

    profile = np.mean([emb(read_wav(CLEAN_DIR / r["wav"])) for r in clean[::4]], axis=0)
    profile /= np.linalg.norm(profile) + 1e-9
    for r in results:
        r["speaker"] = round(float(emb(r["audio"]) @ profile), 3)


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[int(q * (len(s) - 1))]


def report(results: list[dict], stt, speaker: bool) -> None:
    conditions = list(dict.fromkeys(r["condition"] for r in results))
    print(f"thresholds from config.yaml: reject_p {stt.reject_p}, unclear_p {stt.unclear_p}\n")
    print("acted: Swift acts; noted: acts and names the guessed words; refused: \"I couldn't make that out\"; "
          "empty: \"I didn't catch that\"\n")
    print(f"{'condition':12} {'n':>3} {'WER':>6}  {'acted':>6} {'noted':>6} {'refused':>8} {'empty':>6}  "
          f"{'mean p p10/p50':>15}" + ("  speaker p10/p50  <0.3" if speaker else ""))
    for c in conditions:
        rs = [r for r in results if r["condition"] == c and r["ref"]]
        if not rs:
            continue
        n = len(rs)
        ps = [r["mean_p"] for r in rs if r["mean_p"] is not None]
        line = (f"{c:12} {n:3} {wer([normalize(r['ref']) for r in rs], [normalize(r['hyp']) for r in rs]):6.3f}  "
                + " ".join(f"{sum(r['outcome'] == o for r in rs) / n:{w}.0%}"
                           for o, w in (("acted", 6), ("noted", 6), ("refused", 8), ("empty", 6)))
                + "  "
                + f"{(f'{pct(ps, .1):.2f} / {pct(ps, .5):.2f}' if ps else '-'):>15}")
        if speaker:
            ss = [r["speaker"] for r in rs]
            line += f"  {pct(ss, .1):5.2f} / {pct(ss, .5):.2f}  {sum(s < SPEAKER_T for s in ss) / n:4.0%}"
        print(line)

    quiet = [r for r in results if not r["ref"]]
    if quiet:
        print("\nnobody speaking:")
        for r in quiet:
            what = f"invented \"{r['hyp']}\" (mean p {r['mean_p']}) -> {r['outcome']}" if r["hyp"] else "nothing transcribed"
            spk = f", speaker {r['speaker']:.2f}" if speaker else ""
            print(f"  {r['condition']:12} {r['id']}: {what}{spk}")

    noisy = [r for r in results if r["condition"] != "clean" and r["ref"] and r["n_words"] > 1]
    if noisy:
        print("\nreject_p sweep on noisy speech (2+ words): refused when right / refused when badly wrong (WER >= 0.5)")
        good = [r for r in noisy if r["wer"] == 0]
        bad = [r for r in noisy if r["wer"] >= 0.5]
        for t in SWEEP:
            g = f"{sum((r['mean_p'] or 0) < t for r in good) / len(good):5.0%}" if good else "    -"
            b = f"{sum((r['mean_p'] or 0) < t for r in bad) / len(bad):5.0%}" if bad else "    -"
            mark = "  <- current" if t == stt.reject_p else ""
            print(f"  {t:.2f}: {g} of {len(good)} right   {b} of {len(bad)} badly wrong{mark}")

    print("\nper clip (noisy):")
    for r in results:
        if r["condition"] != "clean" and r["ref"]:
            flag = f" unclear: {', '.join(r['unclear'])}" if r["unclear"] else ""
            print(f"  {r['condition']:10} wer {r['wer']:.2f} p {r['mean_p'] or 0:.2f} {r['outcome']:8} "
                  f"\"{r['hyp']}\"{flag}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--speaker", action="store_true", help="also score each clip against the owner's voice")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # transcripts aren't always cp1252

    noisy = refs(NOISY_DIR)
    if not noisy:
        raise SystemExit(f"No recordings in {NOISY_DIR}. Record some first (see the usage above).")
    wanted = {r["ref"] for r in noisy if r["ref"]}
    clean_all = [r for r in refs(CLEAN_DIR) if r["ref"]]
    clean = [r for r in clean_all if r["ref"] in wanted]

    t0 = time.perf_counter()
    t, stt = transcriber()
    results = run(t, stt, CLEAN_DIR, clean, "clean") + run(t, stt, NOISY_DIR, noisy)
    if args.speaker:
        speaker_scores(results, clean_all)
    report(results, stt, args.speaker)

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"real_noise-{time.strftime('%Y%m%d-%H%M%S')}.json"
    rows = [{k: v for k, v in r.items() if k != "audio"} for r in results]
    out.write_text(json.dumps({"machine": machine_info(), "reject_p": stt.reject_p, "unclear_p": stt.unclear_p,
                               "rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(results)} clips in {time.perf_counter() - t0:.0f}s; saved {out}")


if __name__ == "__main__":
    main()
