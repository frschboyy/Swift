"""The owner-checks roadmap (spikes/owner_checks/plan.py) and its ledger stay true to the checks file.

The first group fails when someone adds a check without saying what code it proves, or an area path
stops matching a file: that is how new checks get into the roadmap rather than being forgotten.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("owner_plan", ROOT / "spikes" / "owner_checks" / "plan.py")
plan = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["owner_plan"] = plan  # dataclasses look their module up here
_spec.loader.exec_module(plan)  # type: ignore[union-attr]
_rspec = importlib.util.spec_from_file_location("owner_report_plan", ROOT / "spikes" / "owner_checks" / "report.py")
report = importlib.util.module_from_spec(_rspec)  # type: ignore[arg-type]
_rspec.loader.exec_module(report)  # type: ignore[union-attr]

CHECKS, LEDGER = plan.load()


# --- the ledger matches the checks file ---------------------------------------------------------

def test_every_check_is_in_an_area() -> None:
    lost = [c.id for c in CHECKS.values() if not c.areas]
    assert not lost, f"add these checks to an area in owner-checks-ledger.yaml: {lost}"


def test_every_check_an_area_names_exists() -> None:
    for name, area in LEDGER["areas"].items():
        missing = [i for i in plan.expand(area["checks"], CHECKS) if i not in CHECKS]
        assert not missing, (name, missing)


def test_every_area_path_matches_a_file() -> None:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    patterns = [p for a in LEDGER["areas"].values() for p in a["paths"]] + [i["path"] for i in LEDGER["ignore"]]
    dead = [p for p in patterns if not any(fnmatch(f, p) for f in files)]
    assert not dead, f"these ledger paths match no file (renamed or deleted?): {dead}"


def test_every_run_is_well_formed() -> None:
    for run in LEDGER["runs"]:
        assert run["date"] and run["commit"] and run["source"], run
        assert set(run["checks"]) <= set(plan.VERDICTS), run


def test_the_generated_status_is_its_own_file_and_merges_as_ours() -> None:
    """Foundation decision 12: nothing generated in owner-checks.md, so two branches' checks never conflict there."""
    text = plan.CHECKS.read_text(encoding="utf-8")
    assert ":start -->" not in text and ":end -->" not in text
    assert plan.STATUS.exists()
    rule = subprocess.run(["git", "check-attr", "merge", "--", "docs/testing/owner-checks-status.md"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout
    assert rule.strip().endswith("merge: ours"), rule


def test_the_status_file_links_each_check_in_the_checks_file() -> None:
    top, bottom = plan.render([], [], [], [], [], "abc1234", "2026-11-15")
    assert plan.link(CHECKS["1"]) == "[1](owner-checks.md#check-1)"
    page = plan.status_file(top, bottom)
    assert "## Run these first" in page and "## Where every check stands" in page


# --- reading a pasted report --------------------------------------------------------------------

def test_a_pasted_report_becomes_verdicts() -> None:
    names = {n for n, _, _ in report.checks([], [])}
    text = "\n".join([
        "12 requests since 2026-11-09 21:55",
        "  PASS      1  hands-free request (wake)   (3 times)",
        "  FAIL      13 no microphone pause after an unlock",
        "  PASS      13 the microphone reopened quickly on each return   (420 ms)",
        "  LOOK      18-20 the card, edges behind it, moved windows   (check on screen)",
        "  PASS      77, 79-80 Swift restarted with due items kept",
        "  NOT SEEN  128 a plain yes did it",
        "  PASS      19 a card waited behind another, then answered",  # an old name: skipped
    ])
    when, got, skipped = plan.parse_report(text, names | {"77, 79-80 Swift restarted with due items kept"}, CHECKS)
    assert when == "2026-11-09 21:55"
    assert got["PASS"] == ["1", "77", "79", "80"]
    assert got["FAIL"] == ["13"]  # one failing line fails the check
    assert "18" not in str(got) and "128" not in str(got)  # LOOK alone and NOT SEEN record nothing
    assert skipped == 1


def test_a_range_takes_lettered_checks() -> None:
    assert plan.expand(["18-20"], CHECKS) == ["18", "19", "19b", "20"]


# --- provisional ids on a branch, numbered at merge (foundation decision 11) --------------------

_BRANCH_CHECKS = """### A section

<a id="check-12"></a>**Check 12**
1. Say it.

<a id="check-fix-wake-1"></a>**Check fix-wake-1**
1. Say "Hey Swift".

<a id="check-fix-wake-2"></a>**Check fix-wake-2**
1. Right after check fix-wake-1, say it again. See [fix-wake-1](#check-fix-wake-1).
"""


def test_provisional_ids_are_accepted_on_a_branch() -> None:
    checks = plan.parse_checks(_BRANCH_CHECKS)
    assert list(checks) == ["12", "fix-wake-1", "fix-wake-2"]
    assert plan.provisional("fix-wake-1") and not plan.provisional("19b") and not plan.provisional("43-48")
    assert checks["fix-wake-2"].needs == ["fix-wake-1"]
    assert checks["fix-wake-1"].num > checks["12"].num  # sorts after every numbered check
    assert plan.expand(["10-20", "fix-wake-2"], checks) == ["12", "fix-wake-2"]  # a range never takes one
    assert plan.report_ids("fix-wake-1, fix-wake-2 the wake heard twice", checks) == ["fix-wake-1", "fix-wake-2"]
    assert plan.report_ids("77, 79-80 Swift restarted", CHECKS) == ["77", "79", "80"]
    assert plan.next_free(list(checks), [("claude/x", ["40", "x-1"], [])], given_out=30) == 41
    assert plan.named(checks["fix-wake-1"], _commit("bbb", [], "Wake fix (root)\n\nOwner check fix-wake-1."))
    assert not plan.named(checks["fix-wake-1"], _commit("bbb", [], "Owner check fix-wake-12."))


def test_main_holds_no_provisional_ids() -> None:
    """Provisional ids live on branches only: --renumber numbers them before a branch reaches main."""
    left = [c for c in CHECKS if plan.provisional(c)]
    if plan.current_branch() == "main":
        assert not left, f"run plan.py --renumber before merging: {left}"


def test_the_next_provisional_id_is_the_branch_s_own() -> None:
    assert plan.next_provisional(["12"], "claude/friendly-mestorf-f4f7fb") == "friendly-mestorf-f4f7fb-1"
    assert plan.next_provisional(["fix-wake-1", "fix-wake-2", "other-9"], "claude/Fix_Wake") == "fix-wake-3"
    assert plan.branch_slug("claude/305-fix") == "b-305-fix"


def test_renumbering_rewrites_every_reference_and_nothing_else() -> None:
    text = "\n".join([
        '<a id="check-fix-wake-1"></a>**Check fix-wake-1**, see [fix-wake-1](owner-checks.md#check-fix-wake-1).',
        "    checks: [1, fix-wake-1, fix-wake-12]",
        '        ("fix-wake-1 the wake heard", ok, ""),',
        "Check fix-wake-1's note; not prefix-fix-wake-1 or fix-wake-1b.",
    ])
    got = plan.rewrite_ids(text, {"fix-wake-1": "391", "fix-wake-12": "392"})
    assert got.splitlines() == [
        '<a id="check-391"></a>**Check 391**, see [391](owner-checks.md#check-391).',
        "    checks: [1, 391, 392]",
        '        ("391 the wake heard", ok, ""),',
        "Check 391's note; not prefix-fix-wake-1 or fix-wake-1b.",
    ]


def test_renumber_numbers_a_branch_s_checks_in_every_file(tmp_path: Path, monkeypatch) -> None:
    files = {
        "docs/testing/owner-checks.md": _BRANCH_CHECKS,
        "docs/testing/owner-checks-ledger.yaml": "areas:\n  wake:\n    checks: [12, fix-wake-1, fix-wake-2]\n",
        "spikes/owner_checks/report.py": 'LINES = [("fix-wake-1 heard", True), ("fix-wake-2 heard again", True)]\r\n',
        "notes.bin": "fix-wake-1",  # not a text file it rewrites
    }
    for name, body in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(body.encode())
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    monkeypatch.setattr(plan, "ROOT", tmp_path)
    monkeypatch.setattr(plan, "CHECKS", tmp_path / "docs/testing/owner-checks.md")

    mapping, changed = plan.renumber(plan.parse_checks(_BRANCH_CHECKS), 391)

    assert mapping == {"fix-wake-1": "391", "fix-wake-2": "392"}
    assert sorted(changed) == sorted(n for n in files if n != "notes.bin")
    checks = plan.parse_checks(plan.CHECKS.read_text(encoding="utf-8"))
    assert list(checks) == ["12", "391", "392"] and checks["392"].needs == ["391"]
    assert "[391](#check-391)" in checks["392"].text
    assert "checks: [12, 391, 392]" in (tmp_path / "docs/testing/owner-checks-ledger.yaml").read_text(encoding="utf-8")
    assert (tmp_path / "spikes/owner_checks/report.py").read_bytes().endswith(b'("392 heard again", True)]\r\n')
    assert (tmp_path / "notes.bin").read_text() == "fix-wake-1"


# --- what goes stale, and the order -------------------------------------------------------------

def _check(cid: str, text: str = "1. Say it.", rules: list[str] | None = None) -> object:
    return plan.Check(cid, f"Check {cid}", "A section (X-08)", text, areas=["a"], rules=rules or [],
                      paths=["src/swift/stack.py"])


def _commit(sha: str, files: list[str], message: str = "Something") -> object:
    return plan.Commit(sha, "2026-11-11", message, message, files)


def _states(checks: dict, runs: list[dict], changes: list, born: dict | None = None) -> dict:
    today = datetime(2026, 11, 12)
    since = {"aaa": changes}
    return {s.check.id: s for s in plan.assess(checks, runs, since, changes, born or {}, today)}


def test_a_pass_goes_stale_when_its_code_changes_and_not_otherwise() -> None:
    checks = {"1": _check("1"), "2": _check("2")}
    checks["2"].paths = ["overlay/src/orb.ts"]
    runs = [{"date": "2026-11-09 21:55", "commit": "aaa", "source": "report", "checks": {"PASS": ["1", "2"]}}]
    s = _states(checks, runs, [_commit("bbb", ["src/swift/stack.py"])])
    assert s["1"].kind == "stale" and s["2"].kind == "passed"


def test_a_failure_comes_back_once_something_names_it() -> None:
    checks = {"5": _check("5"), "6": _check("6")}
    runs = [{"date": "2026-11-09 21:55", "commit": "aaa", "source": "owner", "checks": {"FAIL": ["5", "6"]}}]
    s = _states(checks, runs, [_commit("bbb", ["src/swift/session.py"], "Fix the thing (root)\n\nOwner checks 4-5.")])
    assert s["5"].kind == "fixed" and s["6"].kind == "failing"
    assert s["5"].score > 0 and s["6"].score == 0  # nothing for the owner to run until it's fixed


def test_a_finding_named_in_a_commit_reaches_its_checks() -> None:
    c = _check("7")
    assert plan.named(c, _commit("bbb", [], "Five seconds to stop an email (X-08)"))
    assert not plan.named(c, _commit("bbb", [], "Something about X-17"))


def test_the_order_puts_fixes_then_new_product_rule_checks_first() -> None:
    checks = {"1": _check("1"), "2": _check("2", rules=["typing never approves"]), "3": _check("3"),
              "4": _check("4", "1. Nothing to do, unless it happens.")}
    runs = [{"date": "2026-11-09 21:55", "commit": "aaa", "source": "owner", "checks": {"FAIL": ["1"]}}]
    s = _states(checks, runs, [_commit("bbb", ["src/swift/stack.py"])],
                born={"2": "2026-11-11", "3": "2026-10-01", "4": "2026-11-11"})
    order = [x.check.id for x in plan.run_list(list(s.values()), 10)]
    assert order == ["1", "2", "3"]  # 4 can't be run on demand
    assert s["4"].kind == "passive"


def test_a_check_that_builds_on_another_comes_after_it() -> None:
    checks = {"2": _check("2"), "3": _check("3", "1. Right after check 2, say it again.")}
    runs = [{"date": "2026-11-09 21:55", "commit": "aaa", "source": "owner", "checks": {"FAIL": ["3"], "PASS": ["2"]}}]
    s = _states(checks, runs, [_commit("bbb", ["src/swift/other.py"], "Check 3 fixed")])
    assert not plan.touches(checks["3"], _commit("ccc", ["docs/audit/x.md"], "Why check 3 failed"))
    assert [x.check.id for x in plan.run_list(list(s.values()), 1)] == ["2", "3"]


def test_a_focus_entry_moves_a_check_up_and_says_why() -> None:
    checks = {"8": _check("8"), "9": _check("9")}
    checks["9"].focus = ["ADR-020 asks for it"]
    s = _states(checks, [], [], born={"8": "2026-11-11", "9": "2026-11-11"})
    assert [x.check.id for x in plan.run_list(list(s.values()), 1)] == ["9"]
    assert "ADR-020 asks for it" in s["9"].why
