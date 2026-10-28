"""End of speech (ADR-016 Phase C): how long the owner's own pauses are, from their saved clips.

Reads the 16 kHz mono WAV clips Swift kept on this PC (``%LOCALAPPDATA%/Swift/audio``, the
recordings loop, and ``stt_corpus/clips``), finds the speech in each with Swift's own noise gate,
and measures the pauses *inside* it: the silences a fixed end-of-speech pause would cut at.
Prints counts only: no transcripts, no file names, nothing leaves the PC, no model is loaded.

    uv run python spikes/endpointing/measure.py [folder ...]

Read with ``swift.endpoint.EndOfTurn``: ``silence_s`` (0.8 s) ends an utterance, ``free_s``
(1.3 s) a free-text answer; a clip "split" at a pause would have lost its end without the
words-so-far check (``more_coming``).
"""

from __future__ import annotations

import os
import sys
import wave
from collections.abc import Iterable
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from swift.audio.recorder import BLOCK, SAMPLE_RATE, level_from_block  # noqa: E402
from swift.wake import NoiseGate  # noqa: E402

BLOCK_S = BLOCK / SAMPLE_RATE
THRESHOLDS_S = (0.6, 0.8, 1.0, 1.3, 2.0)
BUCKETS_S = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)


def inner_pauses(samples: np.ndarray) -> list[float]:
    """The pauses (s) between the first and the last speech in ``samples`` (int16, 16 kHz)."""
    gate = NoiseGate()
    speech = [gate.speech(level_from_block(samples[i:i + BLOCK])) for i in range(0, len(samples) - BLOCK + 1, BLOCK)]
    pauses, run, started = [], 0, False
    for loud in speech:
        if loud:
            if started and run:
                pauses.append(run * BLOCK_S)
            started, run = True, 0
        elif started:
            run += 1
    return pauses  # a trailing run (after the last speech) is the end, not a pause


def read_clip(path: Path) -> np.ndarray | None:
    try:
        with wave.open(str(path), "rb") as w:
            if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
                return None
            return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    except (OSError, wave.Error, EOFError):
        return None


def summarize(clips: Iterable[list[float]]) -> dict[str, object]:
    """Counts over clips' inner pauses: how many clips each threshold would split, and a histogram."""
    longest = [max(p, default=0.0) for p in clips]
    split = {t: sum(1 for m in longest if m > t) for t in THRESHOLDS_S}
    edges = (0.0, *BUCKETS_S, float("inf"))
    hist = {f"{lo:g}-{hi:g}s": sum(1 for m in longest if m > 0 and lo < m <= hi) for lo, hi in zip(edges, edges[1:])}
    return {"clips": len(longest), "with_pause": sum(1 for m in longest if m > 0), "split": split, "longest_pause": hist}


def default_folders() -> list[Path]:
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Swift"
    return [base / "audio", base / "stt_corpus" / "clips"]


def main(argv: list[str]) -> int:
    folders = [Path(a) for a in argv] or default_folders()
    clips, skipped = [], 0
    for folder in folders:
        for path in sorted(folder.rglob("*.wav")) if folder.is_dir() else []:
            samples = read_clip(path)
            if samples is None:
                skipped += 1
                continue
            clips.append(inner_pauses(samples))
    s = summarize(clips)
    print(f"Clips: {s['clips']} ({skipped} skipped: not 16 kHz mono int16); with a pause inside speech: {s['with_pause']}")
    if not s["clips"]:
        print("No saved clips yet: run again after some days of the recordings loop.")
        return 0
    print("Clips a fixed end-of-speech pause would cut short:")
    for t, n in s["split"].items():  # type: ignore[union-attr]
        print(f"  {t:>4.1f} s  {n:>4}  ({100 * n / s['clips']:.0f}%)")  # type: ignore[operator]
    print("Longest pause inside speech, per clip:")
    for bucket, n in s["longest_pause"].items():  # type: ignore[union-attr]
        print(f"  {bucket:>10}  {n:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
