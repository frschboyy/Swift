"""Listen to Swift's saved wake misses and label each one: did you say "Hey Swift"?

Plays each `*-miss.wav` clip in %LOCALAPPDATA%\\Swift\\audio, oldest first, and asks for a label. It shows
the date, the time and the length, never a transcript, so the label is what you heard and not what a model
wrote. Answers are saved after every clip to %LOCALAPPDATA%\\Swift\\corpus\\wake\\miss_labels.json (outside
git), so you can stop and come back. Nothing leaves the PC.

  y  yes, I said "Hey Swift" (or tried to)
  n  no: room sound, another sentence, a filler
  s  a voice, but you can't tell what it said
  r  play it again       b  back one clip       q  save and quit

  uv run --group spikes python spikes/wake/label_misses.py            # the clips not labelled yet
  uv run --group spikes python spikes/wake/label_misses.py --all      # go over every clip again

Then rescore with the labels:
  uv run --frozen --group spikes python spikes/wake/wake_bench.py report --out <bench folder> \
      --labels %LOCALAPPDATA%\\Swift\\corpus\\wake\\miss_labels.json --oww head_owner
"""

from __future__ import annotations

import argparse
import json
import os
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

KEYS = {"y": "pos", "n": "neg", "s": "skip"}


def swift_dir() -> Path:
    return Path(os.environ.get("SWIFT_DATA") or Path(os.environ["LOCALAPPDATA"]) / "Swift")


def play(path: Path) -> None:
    import sounddevice as sd

    with wave.open(str(path)) as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        rate = w.getframerate()
    sd.play(audio, rate)
    sd.wait()


def misses(audio_dir: Path) -> list[dict]:
    index = json.loads((audio_dir / "index.json").read_text(encoding="utf-8"))["clips"]
    found = [c for c in index if c["source"] == "wake_miss" and (audio_dir / f"{c['id']}.wav").exists()]
    return sorted(found, key=lambda c: c["ts"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="also the clips already labelled")
    ap.add_argument("--labels", type=Path, default=None, help="where to save (default: corpus\\wake\\miss_labels.json)")
    a = ap.parse_args()

    audio_dir = swift_dir() / "audio"
    out = a.labels or swift_dir() / "corpus" / "wake" / "miss_labels.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    labels: dict[str, str] = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    clips = [c for c in misses(audio_dir) if a.all or c["id"] not in labels]
    print(f"{len(clips)} clips to label, {len(labels)} labelled already. Saving to {out}")

    i = 0
    while 0 <= i < len(clips):
        c = clips[i]
        when = datetime.fromtimestamp(c["ts"]).strftime("%a %d %b %H:%M:%S")
        had = f" (was: {labels[c['id']]})" if c["id"] in labels else ""
        print(f"\n[{i + 1}/{len(clips)}] {when}, {c.get('audio_s', '?')} s{had}")
        play(audio_dir / f"{c['id']}.wav")
        while True:
            key = input("Hey Swift?  y(yes) / n(no, or just noise) / s(a voice, can't tell) / r(again) / b(back) / q(quit): ").strip().lower()[:1]
            if key == "r":
                play(audio_dir / f"{c['id']}.wav")
            elif key in KEYS:
                labels[c["id"]] = KEYS[key]
                out.write_text(json.dumps(labels, indent=1), encoding="utf-8")
                i += 1
                break
            elif key == "b":
                i = max(i - 1, 0)
                break
            elif key == "q":
                i = -1
                break
    counts = {v: list(labels.values()).count(v) for v in KEYS.values()}
    print(f"\nSaved {len(labels)} labels to {out}: {counts['pos']} yes, {counts['neg']} no, {counts['skip']} can't tell")


if __name__ == "__main__":
    main()
