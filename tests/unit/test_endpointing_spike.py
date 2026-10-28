"""The end-of-speech measurement spike (spikes/endpointing/measure.py): counts only, right pauses."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("endpointing_measure", ROOT / "spikes" / "endpointing" / "measure.py")
assert _spec is not None and _spec.loader is not None
measure = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(measure)


def clip(*parts: tuple[str, float]) -> np.ndarray:
    rng = np.random.default_rng(0)
    out = []
    for kind, seconds in parts:
        n = int(seconds * measure.SAMPLE_RATE)
        level = 8000 if kind == "talk" else 30
        out.append((rng.standard_normal(n) * level).astype(np.int16))
    return np.concatenate(out)


def test_only_pauses_inside_speech_count() -> None:
    pauses = measure.inner_pauses(clip(("room", 1.0), ("talk", 0.6), ("room", 0.9), ("talk", 0.5), ("room", 2.0)))
    assert len(pauses) == 1 and 0.8 < pauses[0] < 1.0  # the lead-in and the end aren't pauses


def test_the_summary_is_counts_only() -> None:
    s = measure.summarize([[0.9], [0.3, 1.4], []])
    assert s["clips"] == 3 and s["with_pause"] == 2
    assert s["split"] == {0.6: 2, 0.8: 2, 1.0: 1, 1.3: 1, 2.0: 0}
    assert s["longest_pause"]["0.75-1s"] == 1 and s["longest_pause"]["1-1.5s"] == 1
