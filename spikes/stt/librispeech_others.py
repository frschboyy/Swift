"""Make "other people" clips for speaker_bench.py from Mini LibriSpeech.

Usage:
  python spikes/stt/librispeech_others.py TARBALL OUT_DIR [--per-speaker 8]

TARBALL is dev-clean-2.tar.gz from https://www.openslr.org/31/ (126 MB,
CC BY 4.0: volunteer LibriVox readers). Each speaker gets up to --per-speaker
clips, each a random 2-5 s window of an utterance (the length of a spoken
request), written as OUT_DIR/<speaker>-<utterance>.wav, 16 kHz mono int16.
"""

from __future__ import annotations

import argparse
import io
import tarfile
import wave
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE = 16_000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tarball", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--per-speaker", type=int, default=8)
    args = ap.parse_args()

    rng = np.random.default_rng(1)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    taken: dict[str, int] = defaultdict(int)
    with tarfile.open(args.tarball, "r:gz") as tar:
        for member in tar:  # read in memory; nothing is extracted to disk
            if not (member.isfile() and member.name.endswith(".flac")):
                continue
            utt = Path(member.name).stem  # <speaker>-<chapter>-<n>
            speaker = utt.split("-")[0]
            if taken[speaker] >= args.per_speaker:
                continue
            f = tar.extractfile(member)
            assert f is not None
            audio, sr = sf.read(io.BytesIO(f.read()), dtype="int16")
            if sr != SAMPLE_RATE or audio.ndim != 1 or len(audio) < 2 * SAMPLE_RATE:
                continue
            n = int(rng.uniform(2.0, 5.0) * SAMPLE_RATE)
            start = int(rng.integers(0, max(1, len(audio) - n)))
            clip = audio[start : start + n]
            with wave.open(str(args.out_dir / f"{speaker}-{utt.split('-', 1)[1]}.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLE_RATE)
                w.writeframes(clip.tobytes())
            taken[speaker] += 1
    print(f"{sum(taken.values())} clips from {len(taken)} speakers -> {args.out_dir}")


if __name__ == "__main__":
    main()
