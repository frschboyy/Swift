"""The usage report (spikes/usage/report.py): counts only, the right lanes, clean runs and weeks."""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("usage_report", ROOT / "spikes" / "usage" / "report.py")
assert _spec is not None and _spec.loader is not None
usage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(usage)


def write(tmp_path: Path, *records: dict) -> Path:
    path = tmp_path / "interactions.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\nnot json\n", encoding="utf-8")
    return path


def rec(id: str, ts: str = "2026-11-02T09:00:00+00:00", **kw) -> dict:
    return {"id": id, "ts": ts, "source": "voice", "status": "done", "approvals": [], "interaction_ms": 1000} | kw


def test_lanes_and_clean_runs(tmp_path: Path) -> None:
    rows = usage.load(write(
        tmp_path,
        rec("a", route="local", action="time"),
        rec("b", route="control", action="approve"),
        rec("c", route="light", action="quick"),
        rec("d", route="agent", interaction_ms=12000, cost_usd=0.05),
        rec("e", route="agent", status="error", interaction_ms=3000),
        rec("f", route="agent", retry_of="e", interaction_ms=8000),
        rec("g", route="agent", approvals=[{"decision": "revise"}], interaction_ms=20000),
        rec("h", route="agent", redirected=1, interaction_ms=15000),
        rec("i", status="error", error="no_speech"),
        rec("j", route="agent", status="rejected"),
    ))
    s = usage.summarize(rows)
    assert s["requests"] == 10
    assert s["lanes"] == {"swift": 2, "light": 1, "agent": 6, "not_heard": 1}
    # a, b, c, d, f are clean; g asked a change, h changed mid-run, e/i/j didn't finish.
    assert s["clean"] == 5
    assert s["not_done"] == {"error": 2, "rejected": 1}
    assert (s["agent_p50_s"], s["agent_p90_s"]) == (13.5, 20.0)  # agent runs done: 8, 12, 15, 20 s
    assert round(s["cost_usd"], 2) == 0.05


def test_retried_run_is_not_clean_even_when_done(tmp_path: Path) -> None:
    rows = usage.load(write(tmp_path, rec("a", route="agent"), rec("b", route="agent", retry_of="a")))
    assert usage.summarize(rows)["clean"] == 1


def test_debug_runs_excluded_days_and_since(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        rec("a", ts="2026-10-27T10:00:00+00:00", route="local"),
        rec("b", ts="2026-10-28T10:00:00+00:00", route="local"),
        rec("c", ts="2026-10-29T10:00:00+00:00", route="local", source="debug.run"),
        rec("d", ts="2026-10-30T10:00:00+00:00", route="local"),
    )
    assert [r["id"] for r in usage.load(path)] == ["a", "b", "d"]
    assert [r["id"] for r in usage.load(path, exclude={date(2026, 10, 28)})] == ["a", "d"]
    assert [r["id"] for r in usage.load(path, since=date(2026, 10, 28))] == ["b", "d"]


def test_weeks_and_days(tmp_path: Path) -> None:
    rows = usage.load(write(
        tmp_path,
        rec("a", ts="2026-11-01T10:00:00+00:00"),  # Sunday, ISO week 44
        rec("b", ts="2026-11-02T10:00:00+00:00"),  # Monday, week 45
        rec("c", ts="2026-11-02T11:00:00+00:00"),
        rec("d", ts="2026-11-03T11:00:00+00:00"),
    ))
    weeks = usage.by_week(rows)
    assert list(weeks) == ["2026-W44", "2026-W45"]
    s = usage.summarize(weeks["2026-W45"])
    assert (s["days"], s["per_day"]) == (2, 1.5)


def test_busy_day_is_flagged_as_testing(tmp_path: Path) -> None:
    rows = usage.load(write(tmp_path, *(rec(str(i), route="local") for i in range(usage.TEST_DAY + 1))))
    s = usage.summarize(rows)
    assert s["test_days"] == [date(2026, 11, 2)]
    assert "likely testing" in usage.report(rows)


def test_report_never_prints_what_was_said(tmp_path: Path) -> None:
    secret = "email Janet that the merger is off"
    rows = usage.load(write(tmp_path, rec("a", route="agent", transcript=secret, transcript_raw=secret,
                                          steps=[{"t_ms": 1, "text": secret}], workflow="email-draft")))
    text = usage.report(rows)
    assert "Janet" not in text and "merger" not in text
    assert "workflows run 1" in text


def test_empty_range() -> None:
    assert usage.report([]) == "No requests in the range."
