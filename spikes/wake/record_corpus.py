"""S1: guided recorder for the wake-word POSITIVE corpus (§14.3).

Records one condition cell (distance x noise) per run. Audio goes to
%LOCALAPPDATA%\\Swift\\corpus\\wake\\positives (outside git), one WAV per take
(16 kHz mono int16), plus a manifest.csv row per take.

Takes alternate between:
  alone    : say just the wake phrase, e.g. "Hey Swift"
  command  : say the phrase and run straight into a command, no pause,
             e.g. "Hey Swift open my project"

Modes:
  interactive (default): press Enter for each take, r to redo the last one, q to quit.
  --auto: hands-free for 1.5 m / 3 m. A beep starts each take every --interval
          seconds; one beep = phrase alone, two beeps = phrase + command.

Example (34 takes per cell x 9 cells ~= 306 positives):
  uv run --group spikes python spikes/wake/record_corpus.py --distance 0.5 --noise quiet --count 34 --speaker owner
  uv run --group spikes python spikes/wake/record_corpus.py --distance 3 --noise media --count 34 --speaker owner --auto
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

RATE = 16_000
COMMANDS = [
    "open my project",
    "what time is it",
    "draft an email to my dean",
    "run the tests",
    "remind me every Friday to send an update",
    "find the latest report",
    "schedule a meeting with my supervisor",
    "make it shorter",
    "stop",
    "what can you do",
]
FIELDS = ["file", "speaker", "distance_m", "noise", "kind", "phrase", "command", "recorded_at", "duration_s", "rms_dbfs", "mode"]


def corpus_dir() -> Path:
    d = Path(os.environ["LOCALAPPDATA"]) / "Swift" / "corpus" / "wake" / "positives"
    d.mkdir(parents=True, exist_ok=True)
    return d


def beep(sd, n: int) -> None:
    t = np.linspace(0, 0.12, int(RATE * 0.12), endpoint=False)
    tone = (0.3 * np.sin(2 * np.pi * 880 * t)).astype(np.float32)
    gap = np.zeros(int(RATE * 0.1), dtype=np.float32)
    sig = np.concatenate([np.concatenate([tone, gap]) for _ in range(n)])
    sd.play(sig, RATE)
    sd.wait()


def record(sd, seconds: float) -> np.ndarray:
    audio = sd.rec(int(seconds * RATE), samplerate=RATE, channels=1, dtype="int16")
    sd.wait()
    return audio[:, 0]


def rms_dbfs(a: np.ndarray) -> float:
    x = a.astype(np.float64) / 32768.0
    r = np.sqrt(np.mean(x * x)) if len(x) else 0.0
    return round(20 * np.log10(r), 1) if r > 0 else -120.0


def save(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(audio.tobytes())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--distance", type=float, choices=[0.5, 1.5, 3.0], required=True)
    ap.add_argument("--noise", choices=["quiet", "media", "babble"], required=True)
    ap.add_argument("--count", type=int, default=34)
    ap.add_argument("--speaker", default="owner")
    ap.add_argument("--phrase", default="Hey Swift")
    ap.add_argument("--seconds", type=float, default=4.0, help="recording window per take")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--interval", type=float, default=7.0)
    args = ap.parse_args()

    import sounddevice as sd

    out = corpus_dir()
    manifest = out / "manifest.csv"
    previous: list[dict] = []
    if manifest.exists():
        with manifest.open(newline="", encoding="utf-8") as f:
            previous = list(csv.DictReader(f))
    rows: list[dict] = []

    def write_manifest() -> None:
        with manifest.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(previous + rows)

    rng = random.Random()
    print(f"input device: {sd.query_devices(kind='input')['name']}")
    print(f"saving to {out}")
    print("one beep = say the phrase ALONE; two beeps = phrase + any command with NO pause\n")

    i = 0
    while i < args.count:
        kind = "alone" if i % 2 == 0 else "command"
        cmd = rng.choice(COMMANDS) if kind == "command" else ""
        say = args.phrase if kind == "alone" else f"{args.phrase} {cmd}"
        if args.auto:
            print(f"[{i + 1}/{args.count}] in {args.interval:.0f}s: {say!r}")
            time.sleep(max(0.0, args.interval - args.seconds - 0.5))
        else:
            ans = input(f"[{i + 1}/{args.count}] Enter, then say {say!r}  (r=redo last, q=quit): ").strip().lower()
            if ans == "q":
                break
            if ans == "r" and rows:
                last = rows.pop()
                (out / last["file"]).unlink(missing_ok=True)
                write_manifest()
                i -= 1
                print(f"deleted {last['file']}; redoing that take")
                continue
        beep(sd, 1 if kind == "alone" else 2)
        audio = record(sd, args.seconds)
        name = f"{args.speaker}_d{args.distance}_{args.noise}_{kind}_{datetime.now():%Y%m%d-%H%M%S}_{i:03d}.wav"
        save(out / name, audio)
        level = rms_dbfs(audio)
        rows.append(
            {
                "file": name, "speaker": args.speaker, "distance_m": args.distance, "noise": args.noise,
                "kind": kind, "phrase": args.phrase, "command": cmd,
                "recorded_at": datetime.now().isoformat(timespec="seconds"), "duration_s": args.seconds,
                "rms_dbfs": level, "mode": "auto" if args.auto else "interactive",
            }
        )
        write_manifest()
        warn = "  (very quiet: check the mic)" if level < -55 else ""
        print(f"   saved {name}  level {level} dBFS{warn}")
        i += 1
    print("done")


if __name__ == "__main__":
    main()
