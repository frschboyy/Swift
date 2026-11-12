"""The live roadmap: docs/handoff/roadmap.md's steps, each with where it stands now, written to ROADMAP.md.

Usage (from the repo root):
  uv run python spikes/owner_checks/roadmap.py [--swift-dir PATH] [--days 7]

Reads the plan (docs/handoff/roadmap.md), the owner checks and their ledger (through plan.py), git, Swift's
swift.log (warnings and errors of the last --days days) and interactions.jsonl (days of real use, counts only).
Writes ROADMAP.md at the repo root, which git ignores, and prints its "Next up" section. Read-only otherwise.
From a Claude Code session, pass --swift-dir //localhost/c$/Users/frchi/AppData/Local/Swift (the sandbox's copy is old).
"""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from fnmatch import fnmatch
from pathlib import Path

import importlib.util

sys.path.insert(0, str(Path(__file__).parent))
import plan  # noqa: E402

# spikes/usage/report.py (load, TEST_DAY), by path: its name is the same as the owner-checks report's
_spec = importlib.util.spec_from_file_location("usage_report", plan.ROOT / "spikes" / "usage" / "report.py")
usage = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(usage)  # type: ignore[union-attr]

PLAN = plan.ROOT / "docs" / "handoff" / "roadmap.md"
OUT = plan.ROOT / "ROADMAP.md"
LOCAL = usage.LOCAL
TAG = re.compile(r"\s*<!--\s*(.*?)\s*-->\s*$")
LOG = re.compile(r"^(\d{4}-\d\d-\d\d) [\d:.]+ \| (WARNING|ERROR|CRITICAL)\s*\| ([\w.]+):\w+:\d+ \| ([^|]*)")


def use_days(rows: list[dict], since: date) -> int:
    """Days from `since` with real use: at least one request, and not so many that it was a test day."""
    per_day = Counter(r["_day"] for r in rows if r["_day"] >= since)
    return sum(1 for n in per_day.values() if n <= usage.TEST_DAY)


def problems(log: Path, days: int, today: date) -> list[tuple[str, str, str, int, str, str]]:
    """(level, module, message, count, first day, last day) of each kind of warning or error in the window."""
    if not log.exists():
        return []
    start = f"{today - timedelta(days=days):%Y-%m-%d}"
    seen: dict[tuple[str, str, str], list] = {}
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LOG.match(line)
        if m and m.group(1) >= start:
            key = (m.group(2), m.group(3), re.sub(r"\d+", "N", m.group(4).strip()))
            hit = seen.setdefault(key, [0, m.group(1), m.group(1)])
            hit[0] += 1
            hit[2] = m.group(1)
    return sorted(((*k, *v) for k, v in seen.items()), key=lambda p: (p[0] != "WARNING", p[5], p[3]), reverse=True)  # errors first, then the latest


def module_file(module: str) -> str:
    return "src/swift/backend/__main__.py" if module == "__main__" else "src/" + module.replace(".", "/") + ".py"


def checks_near(module: str, checks: dict) -> list[str]:
    f = module_file(module)
    return [c.id for c in checks.values() if any(fnmatch(f, p) for p in c.paths)]


def step_status(tags: str, ticked: bool, ctx: dict) -> tuple[str, str]:
    """(done | going | failed | todo, what's known) for one plan step's tags."""
    if not tags:
        return ("done" if ticked else "todo"), ""
    parts, done, going, failed = [], True, False, False
    for tag in [t.strip() for t in tags.split(";")]:
        if tag.startswith("checks:"):
            ids = plan.expand([x.strip() for x in tag[7:].split(",")], ctx["checks"])
            kinds = Counter(ctx["states"][i].kind for i in ids if i in ctx["states"])
            passed = kinds["passed"]
            parts.append(f"{passed} of {len(ids)} passed"
                         + (f", {kinds['fixed']} fixed since failing: run again" if kinds["fixed"] else "")
                         + (f", {kinds['failing']} failed, waiting for a fix" if kinds["failing"] else "")
                         + (f", {kinds['stale']} to re-run (code changed)" if kinds["stale"] else ""))
            done &= passed == len(ids)
            going |= passed > 0 or kinds["stale"] > 0 or kinds["partial"] > 0
            failed |= kinds["failing"] > 0
        elif tag.startswith("use:"):
            m = re.match(r"use:\s*(\d+)\s+since\s+(\S+)", tag)
            want, since = int(m.group(1)), date.fromisoformat(m.group(2))  # type: ignore[union-attr]
            got = use_days(ctx["rows"], since) if ctx["today"] >= since else 0
            parts.append(f"{got} of {want} days" + ("" if ctx["today"] >= since else f", starts {since}"))
            done &= got >= want
            going |= got > 0
        elif tag.startswith("branch:"):
            b = tag[7:].strip()
            if b in ctx["unmerged"]:
                parts.append(f"waiting for your OK to merge `{b}`")
                done = False
            else:  # merged, or removed after its merge
                parts.append("merged")
        elif tag.startswith("report since"):
            since = tag[len("report since"):].strip()
            runs = [r for r in ctx["runs"] if str(r["date"])[:10] >= since and r.get("source") == "report"]
            parts.append(f"report recorded {str(runs[-1]['date'])[:16]}" if runs else "no report yet")
            done &= bool(runs)
    if ticked:
        done = True
    return ("done" if done else "failed" if failed else "going" if going else "todo"), "; ".join(parts)


MARK = {"done": "✅", "going": "🔶", "failed": "❌", "todo": "⬜"}


def render_plan(text: str, ctx: dict) -> tuple[str, list[str]]:
    """The plan with each step marked, and the first unfinished steps (the "Next up" list)."""
    out, nxt = [], []
    # the plan's links are relative to docs/handoff; ROADMAP.md sits at the repo root
    text = re.sub(r"\]\((?!https?:|#)([^)]+)\)", lambda m: f"]({posixpath.normpath('docs/handoff/' + m.group(1))})", text)
    for line in text.splitlines():
        m = re.match(r"^- \[( |x)\] (.*)$", line)
        if not m:
            out.append(line)
            continue
        body, tags = m.group(2), ""
        t = TAG.search(body)
        if t:
            body, tags = body[:t.start()], t.group(1)
        state, known = step_status(tags, m.group(1) == "x", ctx)
        row = f"- {MARK[state]} {body}" + (f" *({known})*" if known else "")
        out.append(row)
        if state != "done":
            nxt.append(row)
    return "\n".join(out), nxt


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    ap.add_argument("--swift-dir", type=Path, default=LOCAL, help="where Swift keeps swift.log and interactions.jsonl")
    ap.add_argument("--days", type=int, default=7, help="how far back to read swift.log for problems")
    args = ap.parse_args()
    today = datetime.now().date()

    checks, led = plan.load()
    states, picked, branches, _, head, _ = plan.compute(checks, led)
    unmerged = set(plan.git("branch", "--no-merged", "main", "--format=%(refname:short)").split())
    inter = args.swift_dir / "interactions.jsonl"
    ctx = {"checks": checks, "states": {s.check.id: s for s in states}, "runs": sorted(led["runs"], key=lambda r: str(r["date"])),
           "rows": usage.load(inter) if inter.exists() else [], "today": today, "unmerged": unmerged}
    body, nxt = render_plan(PLAN.read_text(encoding="utf-8"), ctx)
    body = body.split("\n## ", 1)[1] if "\n## " in body else body  # drop the plan's own intro

    found = problems(args.swift_dir / "logs" / "swift.log", args.days, today)
    failing = [s for s in states if s.kind == "failing"]
    lines = [f"# Swift: live roadmap ({today}, `main` at `{head}`)", "",
             "Written by `spikes/owner_checks/roadmap.py` from the plan in [`docs/handoff/roadmap.md`](docs/handoff/roadmap.md),",
             "your owner checks, git and Swift's own logs. Don't edit it: it's rewritten each time. ✅ done · 🔶 under way ·",
             "❌ a check failed · ⬜ to do.", "", "## Next up", ""]
    if found and found[0][5] >= f"{today - timedelta(days=1):%Y-%m-%d}":
        lines.append("- **Swift logged problems in the last day** (below): ask Claude to look at them.")
    lines += nxt[:5] + ["", f"The checks to run first are at the top of [`owner-checks.md`](docs/testing/owner-checks.md#run-these-first)."]

    lines += ["", f"## Problems ({args.days} days of `swift.log`, and your checks)", "",
              "A log problem stays here until it hasn't happened for that long. Ask Claude to look at any of them.", ""]
    if not found and not failing:
        lines.append("None found.")
    for level, module, msg, n, first, last in found:
        near = checks_near(module, checks)
        lines.append(f"- **{level.lower()}** `{module}`: {msg} — {n}×, {first} to {last}"
                     + (f"; its code is behind checks {', '.join(near[:8])}{', …' if len(near) > 8 else ''}" if near else ""))
    for s in failing:
        lines.append(f"- **failed check** [{s.check.id}](docs/testing/owner-checks.md#check-{s.check.id}) {plan.name(s.check)}: "
                     "waiting for a fix")
    if branches:
        lines += ["", "Open branches add checks: " + "; ".join(f"`{b}` {', '.join(new)}" for b, new, _ in branches if new)]
    lines += ["", "## The plan", "", "## " + body]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines[: lines.index(f"## Problems ({args.days} days of `swift.log`, and your checks)")]))
    print(f"Wrote {OUT.name}: {len(found)} kind(s) of problem in the logs, {len(failing)} failed check(s).")


if __name__ == "__main__":
    main()
