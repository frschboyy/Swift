"""S1: record NEGATIVE audio (no wake phrase) for false-accept measurement (§14.3).

Records continuously in 10-minute WAV chunks (16 kHz mono int16, ~19 MB each)
to %LOCALAPPDATA%\\Swift\\corpus\\wake\\negatives, with a manifest row per
chunk. The target is >= 24 h total, mixing TV/podcasts, normal room activity,
and your own speech that does NOT contain the wake phrase.

Privacy: this writes room audio to disk. Make sure anyone else present is OK
with it, and delete the folder when S1 is done. Ctrl+C stops cleanly.

  uv run --group spikes python spikes/wake/record_negatives.py --hours 8 --label "tv-evening"
"""

from __future__ import annotations

import argparse
import csv
import os
import queue
import wave
from datetime import datetime
from pathlib import Path

RATE = 16_000
CHUNK_S = 600


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=float, required=True)
    ap.add_argument("--label", required=True, help="condition, e.g. tv-evening, office, own-speech")
    args = ap.parse_args()

    import sounddevice as sd

    out = Path(os.environ["LOCALAPPDATA"]) / "Swift" / "corpus" / "wake" / "negatives"
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.csv"
    new = not manifest.exists()
    q: queue.Queue[bytes] = queue.Queue()

    def cb(indata, frames, t, status) -> None:  # noqa: ANN001
        q.put(bytes(indata))

    total_chunks = int(args.hours * 3600 / CHUNK_S + 0.999)
    print(f"input: {sd.query_devices(kind='input')['name']}; {total_chunks} chunks of {CHUNK_S // 60} min -> {out}")
    with manifest.open("a", newline="", encoding="utf-8") as f, sd.RawInputStream(
        samplerate=RATE, channels=1, dtype="int16", blocksize=1280, callback=cb
    ):
        w = csv.writer(f)
        if new:
            w.writerow(["file", "label", "started_at", "seconds"])
        try:
            for n in range(total_chunks):
                name = f"neg_{args.label}_{datetime.now():%Y%m%d-%H%M%S}.wav"
                started = datetime.now().isoformat(timespec="seconds")
                written = 0
                with wave.open(str(out / name), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(RATE)
                    while written < CHUNK_S * RATE:
                        data = q.get()
                        wav.writeframes(data)
                        written += len(data) // 2
                w.writerow([name, args.label, started, round(written / RATE, 1)])
                f.flush()
                print(f"chunk {n + 1}/{total_chunks} saved ({written / RATE / 60:.1f} min)")
        except KeyboardInterrupt:
            print("stopped; the partial chunk is kept but not in the manifest")


if __name__ == "__main__":
    main()
