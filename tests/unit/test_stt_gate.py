"""The speech gate (eval/stt/gate.py): its comparison and its baseline."""

import importlib.util
import json
from pathlib import Path

GATE = Path(__file__).resolve().parents[2] / "eval" / "stt" / "gate.py"
spec = importlib.util.spec_from_file_location("stt_gate", GATE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def test_a_sentence_that_was_right_and_went_wrong_fails_whatever_the_rest_does() -> None:
    before = {"a": [8, 0, 1], "b": [8, 3, 1], "c": [8, 0, 1], "gone": [5, 0, 1]}
    now = {"a": [8, 1, 0], "b": [8, 0, 1], "c": [8, 0, 1], "new": [5, 4, 0]}  # b improved more than a lost
    assert gate.compare(before, now) == {"wrong_now": ["a"], "routes_differently_now": ["a"]}
    assert not any(gate.compare(before, before).values())


def test_measure_counts_words_errors_and_whether_swift_would_do_the_same() -> None:
    assert gate.measure("What time is it?", "what time is it") == [4, 0, 1]
    assert gate.measure("What time is it?", "Write time is in") == [4, 2, 0]


def test_the_baseline_holds_counts_only() -> None:
    path = GATE.parent / "baseline.json"
    if path.exists():
        for key, row in json.loads(path.read_text(encoding="utf-8")).items():
            assert key.split("/")[0] in ("stt_corpus", "stt_noisy", "stt_testset")
            assert len(row) == 3 and all(isinstance(v, int) for v in row)
