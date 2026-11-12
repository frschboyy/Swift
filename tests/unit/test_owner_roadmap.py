"""The live roadmap (spikes/owner_checks/roadmap.py): each plan step's status, log problems, and the plan's own tags."""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "spikes" / "owner_checks"))
_spec = importlib.util.spec_from_file_location("owner_roadmap", ROOT / "spikes" / "owner_checks" / "roadmap.py")
roadmap = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["owner_roadmap"] = roadmap
_spec.loader.exec_module(roadmap)  # type: ignore[union-attr]
plan = roadmap.plan


class _S:
    def __init__(self, kind: str) -> None:
        self.kind = kind


def _ctx(**kw: object) -> dict:
    checks, _ = plan.load()
    base = {"checks": checks, "states": {}, "runs": [], "rows": [], "today": date(2026, 11, 20), "unmerged": set()}
    return {**base, **kw}


def test_a_checks_step_is_done_only_when_each_passed() -> None:
    ctx = _ctx(states={"201": _S("passed"), "202": _S("fixed"), "203": _S("failing")})
    state, known = roadmap.step_status("checks: 201-203", False, ctx)
    assert state == "failed"
    assert "1 of 3 passed" in known and "fixed since failing" in known and "waiting for a fix" in known
    ctx["states"] = {"201": _S("passed"), "202": _S("passed"), "203": _S("passed")}
    assert roadmap.step_status("checks: 201-203", False, ctx)[0] == "done"


def test_a_use_step_counts_real_days_and_not_test_days() -> None:
    rows = [{"_day": date(2026, 11, 14)}, {"_day": date(2026, 11, 15)}] + [{"_day": date(2026, 11, 16)}] * 150
    state, known = roadmap.step_status("use: 14 since 2026-11-13", False, _ctx(rows=rows))
    assert (state, known) == ("going", "2 of 14 days")
    assert roadmap.step_status("use: 14 since 2026-11-25", False, _ctx(rows=rows))[1] == "0 of 14 days, starts 2026-11-25"


def test_branch_and_report_steps() -> None:
    ctx = _ctx(unmerged={"claude/x"}, runs=[{"date": "2026-11-13 20:00", "source": "report"}])
    assert roadmap.step_status("branch: claude/x", False, ctx)[0] == "todo"
    assert roadmap.step_status("branch: claude/y", False, ctx) == ("done", "merged")
    assert roadmap.step_status("report since 2026-11-12", False, ctx)[0] == "done"
    assert roadmap.step_status("report since 2026-11-14", False, ctx)[0] == "todo"
    assert roadmap.step_status("", True, ctx) == ("done", "")


def test_log_problems_are_grouped_by_kind_and_kept_to_the_window(tmp_path: Path) -> None:
    log = tmp_path / "swift.log"
    log.write_text("\n".join([
        "2026-11-01 09:00:00.000 | WARNING  | swift.speech:_overdue:176 | speech never said it was done; taken as over",
        "2026-11-18 09:00:00.000 | WARNING  | swift.audio.recorder:_check_stream:372 | quiet for 12 s; reopening | x=1",
        "2026-11-19 10:00:00.000 | WARNING  | swift.audio.recorder:_check_stream:372 | quiet for 40 s; reopening | x=2",
        "2026-11-19 10:00:01.000 | INFO     | swift.session:_x:1 | ready",
        "2026-11-19 11:00:00.000 | ERROR    | __main__:_make_acoustic:95 | acoustic wake is off",
    ]), encoding="utf-8")
    got = roadmap.problems(log, 7, date(2026, 11, 20))
    assert [(p[1], p[2], p[3]) for p in got] == [
        ("__main__", "acoustic wake is off", 1), ("swift.audio.recorder", "quiet for N s; reopening", 2)]
    assert roadmap.module_file("__main__") == "src/swift/backend/__main__.py"


def test_the_plan_marks_steps_and_fixes_its_links() -> None:
    text = "## Week\n\n- [ ] See [the checks](../testing/owner-checks.md). <!-- report since 2026-11-12 -->\n- [x] Done by hand."
    body, nxt = roadmap.render_plan(text, _ctx())
    assert "(docs/testing/owner-checks.md)" in body and "✅ Done by hand." in body
    assert nxt == ["- ⬜ See [the checks](docs/testing/owner-checks.md). *(no report yet)*"]


def test_every_tag_in_the_real_plan_reads() -> None:
    checks, _ = plan.load()
    for tags in re.findall(r"<!--\s*(.*?)\s*-->", roadmap.PLAN.read_text(encoding="utf-8")):
        for tag in [t.strip() for t in tags.split(";")]:
            if tag.startswith("checks:"):
                ids = plan.expand([x.strip() for x in tag[7:].split(",")], checks)
                assert ids and all(i in checks for i in ids), tag
            else:
                assert re.fullmatch(r"use: \d+ since \d{4}-\d\d-\d\d|branch: \S+|report since \d{4}-\d\d-\d\d", tag), tag
