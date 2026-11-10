"""Wake bench: today's speech-to-text wake matching vs a dedicated wake-word model, on the owner's own clips.

ADR-020 decision 2. Nothing here is imported by src/swift, and nothing leaves the PC: audio is
copied into --out (outside git), transcribed locally with Parakeet, and scored locally.

  build  copy the owner's saved clips into --out and write manifest.jsonl (ids, labels, durations; no text)
  stt    transcribe every clip with Parakeet (+ the owner's word fixes) and score swift.wake.match_wake
  oww    stream every clip through openWakeWord and score it (needs a model: --model NAME_OR_PATH)
  report print the comparison from the files the other steps wrote

Labels. pos: the clip opens with a wake phrase. neg: it doesn't. "wake" clips were started by wake listening,
so today's path accepted them (selection bias: they can't count as today's misses). "wake_miss" clips have no
ground truth; they are labelled by hand in --labels (id -> pos/neg/skip) from two local transcripts
(Parakeet and Whisper small.en, see `stt --whisper`). Read-aloud corpus clips are labelled from their reference text.

  uv run --frozen --group spikes python spikes/wake/wake_bench.py build --out <scratch>
  uv run --frozen --group spikes python spikes/wake/wake_bench.py stt --out <scratch> --whisper
  uv run --frozen --group spikes --with openwakeword==0.6.0 python spikes/wake/wake_bench.py oww --out <scratch> --model hey_jarvis
  uv run --frozen --group spikes python spikes/wake/wake_bench.py report --out <scratch> --labels <labels.json>
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import wave
from pathlib import Path

import numpy as np

RATE = 16_000
SWIFT = Path(os.environ.get("SWIFT_DATA", "//localhost/c$/Users/frchi/AppData/Local/Swift"))
CHUNK = 1280  # openWakeWord's 80 ms frame


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1 and w.getsampwidth() == 2, path
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


# ---- build -------------------------------------------------------------------------------------------

def build(out: Path) -> None:
    from swift.wake import match_wake

    clips = out / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    def add(src: Path, cid: str, source: str, label: str, basis: str, ts: float | None = None) -> None:
        if not src.exists():
            return
        dst = clips / f"{cid}.wav"
        if not dst.exists():
            shutil.copyfile(src, dst)
        rows.append({"id": cid, "source": source, "label": label, "basis": basis, "ts": ts,
                     "audio_s": round(len(read_wav(dst)) / RATE, 2)})

    index = json.loads((SWIFT / "audio" / "index.json").read_text(encoding="utf-8"))["clips"]
    for c in index:
        src = SWIFT / "audio" / f"{c['id']}.wav"
        if c["source"] == "wake":
            add(src, c["id"], "wake", "pos", "started by wake listening", c["ts"])
            # The request after the phrase is ordinary speech: from 3 s on, a negative.
            if src.exists() and len(audio := read_wav(src)) > 5 * RATE:
                tail = clips / f"{c['id']}-tail.wav"
                with wave.open(str(tail), "wb") as w:
                    w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
                    w.writeframes(audio[3 * RATE:].tobytes())
                add(tail, f"{c['id']}-tail", "wake_tail", "neg", "a wake clip from 3 s on", c["ts"])
        elif c["source"] == "wake_miss":
            add(src, c["id"], "wake_miss", "unknown", "hand label", c["ts"])
        elif c["source"] in ("voice", "followup"):
            add(src, c["id"], c["source"], "neg", "hotkey or answer, no wake phrase expected", c["ts"])
    for folder in ("stt_corpus", "stt_noisy"):
        for r in load_jsonl(SWIFT / folder / "refs.jsonl"):
            if not r.get("ref"):
                continue
            label = "pos" if match_wake(r["ref"]) else "neg"
            add(SWIFT / folder / r["wav"], f"{folder}-{r['id']}", folder, label, "reference text")
    seen = {r["id"] for r in rows}
    for c in json.loads((SWIFT / "stt_testset" / "index.json").read_text(encoding="utf-8"))["clips"]:
        if c["id"] not in seen and c.get("known"):
            label = "pos" if match_wake(c["known"]) else "neg"
            add(SWIFT / "stt_testset" / c["wav"], c["id"], "stt_testset", label, "reference text")
    save_jsonl(out / "manifest.jsonl", rows)
    by = {}
    for r in rows:
        by.setdefault((r["source"], r["label"]), [0, 0.0])
        by[(r["source"], r["label"])][0] += 1
        by[(r["source"], r["label"])][1] += r["audio_s"]
    for (s, lab), (n, secs) in sorted(by.items()):
        print(f"{s:12} {lab:8} {n:4} clips {secs / 60:6.1f} min")


# ---- stt: today's path -------------------------------------------------------------------------------

def stt(out: Path, whisper: bool) -> None:
    import psutil

    from swift.stt.fixes import WordFixes
    from swift.stt.transcriber import ParakeetTranscriber, WhisperTranscriber

    rows = load_jsonl(out / "manifest.jsonl")
    proc = psutil.Process()
    rss0 = proc.memory_info().rss
    stt = ParakeetTranscriber(SWIFT / "models", cpu_threads=4, fixes=WordFixes.load(SWIFT / "word_fixes.json"))
    stt._load()
    if stt._error is not None:
        sys.exit(f"{stt._error} {stt._error.hint}")
    rss_loaded = proc.memory_info().rss
    cpu0, wall0 = proc.cpu_times(), time.perf_counter()
    for i, r in enumerate(rows, 1):
        print(f"\rparakeet {i}/{len(rows)}", end="", flush=True)
        t = stt._transcribe_sync(read_wav(out / "clips" / f"{r['id']}.wav"))
        r["parakeet"], r["parakeet_ms"] = t.text, t.stt_ms
    cpu1 = proc.cpu_times()
    audio_s = sum(r["audio_s"] for r in rows)
    perf = {"model_mb": round((rss_loaded - rss0) / 2**20), "peak_rss_mb": round(proc.memory_info().rss / 2**20),
            "cpu_s": round(cpu1.user + cpu1.system - cpu0.user - cpu0.system, 1),
            "wall_s": round(time.perf_counter() - wall0, 1), "audio_s": round(audio_s, 1)}
    print("\n", perf)
    if whisper:  # a second opinion for hand-labelling the misses only
        w = WhisperTranscriber("small.en", SWIFT / "models" / "whisper", cpu_threads=4)
        w._load()
        for r in rows:
            if r["source"] == "wake_miss":
                r["whisper"] = w._transcribe_sync(read_wav(out / "clips" / f"{r['id']}.wav")).text
    save_jsonl(out / "stt.jsonl", rows)
    (out / "stt_perf.json").write_text(json.dumps(perf), encoding="utf-8")


# ---- oww: the candidate ------------------------------------------------------------------------------

def oww(out: Path, model: str, tag: str) -> None:
    import psutil
    from openwakeword.model import Model

    rows = load_jsonl(out / "manifest.jsonl")
    proc = psutil.Process()
    rss0 = proc.memory_info().rss
    m = Model(wakeword_models=[model], inference_framework="onnx")
    name = next(iter(m.models))
    rss_loaded = proc.memory_info().rss
    cpu0, wall0 = proc.cpu_times(), time.perf_counter()
    for i, r in enumerate(rows, 1):
        print(f"\roww {i}/{len(rows)}", end="", flush=True)
        m.reset()
        audio = read_wav(out / "clips" / f"{r['id']}.wav")
        # 1 s of silence first so the model's feature buffer is warm, as it would be when streaming.
        audio = np.concatenate([np.zeros(RATE, np.int16), audio, np.zeros(RATE // 2, np.int16)])
        scores = [m.predict(audio[j:j + CHUNK])[name] for j in range(0, len(audio) - CHUNK + 1, CHUNK)]
        r["scores"] = [round(float(s), 4) for s in scores]  # one per 80 ms, the first second is padding
    cpu1 = proc.cpu_times()
    perf = {"model_mb": round((rss_loaded - rss0) / 2**20), "peak_rss_mb": round(proc.memory_info().rss / 2**20),
            "cpu_s": round(cpu1.user + cpu1.system - cpu0.user - cpu0.system, 1),
            "wall_s": round(time.perf_counter() - wall0, 1),
            "audio_s": round(sum(r["audio_s"] + 1.5 for r in rows), 1)}
    print("\n", perf)
    save_jsonl(out / f"oww_{tag}.jsonl", [{"id": r["id"], "scores": r["scores"]} for r in rows])
    (out / f"oww_{tag}_perf.json").write_text(json.dumps(perf), encoding="utf-8")


# ---- report ------------------------------------------------------------------------------------------

def labelled(out: Path, labels: Path | None) -> list[dict]:
    rows = load_jsonl(out / "stt.jsonl")
    hand = json.loads(labels.read_text(encoding="utf-8")) if labels else {}
    for r in rows:
        if r["id"] in hand:
            r["label"] = hand[r["id"]]
    return [r for r in rows if r["label"] in ("pos", "neg")]


def stt_scores(rows: list[dict]) -> dict:
    from swift.wake import match_wake

    res = {}
    for mode, loose in (("strict", False), ("loose", True)):
        fired = {r["id"]: match_wake(r["parakeet"], loose=loose) is not None for r in rows}
        res[mode] = fired
    return res


def summary(rows: list[dict], fired: dict[str, bool], name: str) -> str:
    pos = [r for r in rows if r["label"] == "pos"]
    neg = [r for r in rows if r["label"] == "neg"]
    miss = [r for r in pos if not fired[r["id"]]]
    fa = [r for r in neg if fired[r["id"]]]
    neg_h = sum(r["audio_s"] for r in neg) / 3600
    by_src = {}
    for r in miss:
        by_src[r["source"]] = by_src.get(r["source"], 0) + 1
    return (f"{name:28} misses {len(miss):3}/{len(pos):3} ({100 * len(miss) / max(len(pos), 1):4.1f}%) {by_src}"
            f" | false wakes {len(fa):2}/{len(neg)} clips = {len(fa) / neg_h:5.1f}/h of negatives")


def report(out: Path, labels: Path | None, tags: list[str], thresholds: list[float], patience: int) -> None:
    rows = labelled(out, labels)
    neg_min = sum(r["audio_s"] for r in rows if r["label"] == "neg") / 60
    print(f"{sum(r['label'] == 'pos' for r in rows)} positives, {sum(r['label'] == 'neg' for r in rows)} negatives"
          f" ({neg_min:.1f} min)")
    for mode, fired in stt_scores(rows).items():
        print(summary(rows, fired, f"parakeet+match_wake {mode}"))
        # The miss clips are what matter: today's path missed them live.
        sub = [r for r in rows if r["source"] == "wake_miss" and r["label"] == "pos"]
        print(f"   of the hand-labelled live misses: caught {sum(fired[r['id']] for r in sub)}/{len(sub)} on replay")
    align = json.loads((out / "align.json").read_text()) if (out / "align.json").exists() else {}
    for tag in tags:
        res = {r["id"]: r for r in load_jsonl(out / f"oww_{tag}.jsonl")}
        for th in thresholds:
            fired, late = {}, []
            for r in rows:
                s = res[r["id"]]["scores"]
                # Score k covers audio up to k * 0.08 + offset s from clip start (streaming: (k+1) chunks - 1 s pad).
                offset = res[r["id"]].get("offset", 0.08 - 1.0)
                hits = [k for k in range(len(s) - patience + 1) if min(s[k:k + patience]) >= th]
                fired[r["id"]] = bool(hits)
                if hits and r["label"] == "pos" and align.get(r["id"]) is not None:
                    late.append((hits[0] + patience - 1) * 0.08 + offset - align[r["id"]])
            line = summary(rows, fired, f"oww {tag} th={th}")
            sub = [r for r in rows if r["source"] == "wake_miss" and r["label"] == "pos"]
            line += f" | live misses caught {sum(fired[r['id']] for r in sub)}/{len(sub)}"
            if late:
                line += f" | fires {np.median(late):+.2f} s after 'swift' ends (median)"
            print(line)
    for p in sorted(out.glob("oww_*_perf.json")):
        perf = json.loads(p.read_text())
        print(f"   {p.stem}: {perf['cpu_s'] / perf['audio_s'] * 100:.1f}% of one core while listening,"
              f" model +{perf['model_mb']} MB, process {perf['peak_rss_mb']} MB")
    perf = json.loads((out / "stt_perf.json").read_text())
    ms = sorted(r["parakeet_ms"] for r in rows if r["label"] == "pos")
    print(f"   parakeet cost: {perf['cpu_s'] / perf['audio_s'] * 100:.1f}% of one core per second of speech,"
          f" model +{perf['model_mb']} MB, transcribe p50 {ms[len(ms) // 2]} ms after the utterance ends")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["build", "stt", "oww", "report"])
    ap.add_argument("--out", type=Path, required=True, help="scratch folder outside git")
    ap.add_argument("--whisper", action="store_true", help="stt: also transcribe the miss clips with Whisper")
    ap.add_argument("--model", default="hey_jarvis", help="oww: a bundled model name or an .onnx path")
    ap.add_argument("--tag", default=None, help="oww: name for the result file (default: the model's)")
    ap.add_argument("--labels", type=Path, default=None, help="report: hand labels for the miss clips")
    ap.add_argument("--oww", nargs="*", default=[], help="report: oww tags to compare")
    ap.add_argument("--thresholds", type=float, nargs="*", default=[0.3, 0.5, 0.7])
    ap.add_argument("--patience", type=int, default=1, help="report: frames in a row over the threshold")
    a = ap.parse_args()
    if a.step == "build":
        build(a.out)
    elif a.step == "stt":
        stt(a.out, a.whisper)
    elif a.step == "oww":
        oww(a.out, a.model, a.tag or Path(a.model).stem)
    else:
        report(a.out, a.labels, a.oww, a.thresholds, a.patience)


if __name__ == "__main__":
    main()
