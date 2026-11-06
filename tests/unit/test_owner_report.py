"""The owner-checks report can say FAIL and LOOK, not only PASS or NOT SEEN (seams audit Q-01)."""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("owner_report_q01", ROOT / "spikes" / "owner_checks" / "report.py")
report = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(report)  # type: ignore[union-attr]


def _results(rows: list[dict], log: list[str]) -> dict[str, tuple[object, str]]:
    return {name: (ok, note) for name, ok, note in report.checks(rows, log)}


def _find(results: dict[str, tuple[object, str]], prefix: str) -> tuple[object, str]:
    hits = [v for k, v in results.items() if k.startswith(prefix)]
    assert len(hits) == 1, (prefix, list(results))
    return hits[0]


def test_only_pass_is_truthy() -> None:
    assert report.PASS
    assert not report.FAIL and not report.NOT_SEEN and not report.LOOK


def test_every_check_has_one_of_the_four_outcomes_and_nothing_is_a_bare_bool() -> None:
    for rows, log in (([], []), ([{"source": "wake", "approvals": [{"decision": "approve"}]}], ["x"])):
        for name, ok, _ in report.checks(rows, log):
            assert isinstance(ok, report.Outcome), name


def test_on_screen_checks_say_look_and_never_pass() -> None:
    results = _results([], [])
    looks = [k for k, (ok, _) in results.items() if ok is report.LOOK]
    assert len(looks) >= 10
    assert all(ok is not report.PASS for k, (ok, note) in results.items() if "check on screen" in note
               and not k.startswith(("16b", "41", "49")))


def test_a_logged_failure_condition_prints_fail() -> None:
    t = datetime(2026, 11, 4, 16, 5)
    rows = [
        {"_t": t, "source": "answer", "provider": "claude_code", "transcript": "Swift, yes"},
        {"_t": t, "status": "done", "error": "crashed", "approvals": [{"by": "swift", "decision": "no_answer"}]},
    ]
    results = _results(rows, [])
    assert _find(results, "130")[0] is report.FAIL
    assert _find(results, "8  no card timed out")[0] is report.FAIL
    assert _find(results, "54")[0] is report.FAIL
    assert _find(results, "55")[0] is report.FAIL


def test_nothing_logged_is_not_seen_rather_than_pass() -> None:
    results = _results([], [])
    for prefix in ("8  no card timed out", "13 no microphone pause", "54", "60", "61", "123", "130"):
        assert _find(results, prefix)[0] is report.NOT_SEEN, prefix


def test_check_61_fails_when_something_heard_acted_while_the_screen_was_locked() -> None:
    log = [
        "2026-11-04 16:00:00 | INFO | presence | state='away' reason='locked'",
        "2026-11-04 16:00:30 | INFO | presence | state='here' reason='unlocked'",
    ]
    held = {"_t": datetime(2026, 11, 4, 16, 0, 5), "source": "wake"}
    typed = {"_t": datetime(2026, 11, 4, 16, 0, 6), "source": "typed"}
    just_before = {"_t": datetime(2026, 11, 4, 16, 0, 1), "source": "wake"}
    ok, note = _find(_results([held, typed, just_before], log), "61")
    assert ok is report.FAIL and "16:00:05" in note
    assert _find(_results([typed, just_before], log), "61")[0] is report.PASS


def test_check_123_sees_the_fields_the_audit_found_still_open() -> None:
    line = "2026-11-04 16:00:00 | INFO | interaction finished | transcript_raw='write to Anna about rent'"
    assert _find(_results([], [line]), "123")[0] is report.FAIL
    clean = "2026-11-04 16:00:00 | INFO | interaction finished | transcript_raw='[REDACTED]'"
    assert _find(_results([], [clean]), "123")[0] is report.PASS
    for field in ("target='rent notes.docx'", "escalations=[{'to': 'opus', 'reason': 'rent letter'}]"):
        assert _find(_results([], [f"2026-11-04 16:00:00 | INFO | interaction finished | {field}"]), "123")[0] is report.FAIL
    shape = "2026-11-04 16:00:00 | INFO | interaction finished | transcript_chars=24 escalations=[{'to': 'opus', 'by': 'model'}]"
    assert _find(_results([], [shape]), "123")[0] is report.PASS


def _due_log(sent: int, drawn: int) -> list[str]:
    return ["x | due sent | items=1"] * sent + ["x | due shown | items=1"] * drawn


def test_check_149_fails_when_a_due_card_was_sent_and_not_drawn() -> None:
    """The timer loop of 2026-11-05 printed PASS: 8 sent, 1 drawn, 7 kept for later."""
    assert _find(_results([], _due_log(8, 1)), "149")[0] is report.FAIL
    assert _find(_results([], _due_log(2, 1)), "149")[0] is report.FAIL
    assert _find(_results([], _due_log(1, 1)), "149")[0] is report.PASS
    assert _find(_results([], []), "149")[0] is report.NOT_SEEN
