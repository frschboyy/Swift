"""Usage report (handoff §4 step 2, product-direction §9): how Swift is used, week by week.

Usage:  uv run python spikes/usage/report.py [--since 2026-10-29] [--exclude 2026-10-27 ...]
        [--interactions PATH]

Reads %LOCALAPPDATA%\\Swift\\interactions.jsonl (read-only) and prints counts only: no
transcript, no request, nothing the owner said. Safe to paste.

What it counts, per ISO week and in total:

- **days used** and **requests per day used**;
- **where requests went**: Swift itself (fast, system and control lanes, no model), the light
  model, the agent, or not heard (no speech, unclear speech: no route);
- **done cleanly**: status done, with no change asked on a card (``revise``), no change mid-run
  (``redirected``) and no "Try again" afterwards (a later record's ``retry_of``);
- **not done**: error, rejected, cancelled;
- **agent time**: median and 90th percentile, press to result, of agent requests done;
- **cost** of agent runs, and the number of escalations to a stronger model;
- **workflows**: requests that ran one.

Days with more than ``TEST_DAY`` requests are flagged as likely testing, not left out: pass
``--exclude`` with their dates to leave them out. Debug runs (``debug.*`` sources) are always left
out. Targets are product-direction §9's.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Swift"

# More requests than this in a day reads as an owner-check or test session.
TEST_DAY = 100
NOT_DONE = ("error", "rejected", "cancelled")
SWIFT_ROUTES = ("local", "control")
AGENT_ROUTES = ("agent", "claude")
TARGETS = {"days": 5, "per_day": 15, "clean": 0.90, "swift": 0.35, "agent_p50_s": 10.0}


def load(path: Path, since: date | None = None, exclude: set[date] | frozenset[date] = frozenset()) -> list[dict[str, Any]]:
    """The log's records with ``_day`` set, oldest first; unreadable lines, debug runs and excluded days left out."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            day = datetime.fromisoformat(r["ts"]).date()
        except (ValueError, KeyError, TypeError):
            continue
        if str(r.get("source", "")).startswith("debug") or day in exclude or (since and day < since):
            continue
        r["_day"] = day
        out.append(r)
    return out


def lane(r: dict[str, Any]) -> str:
    route = r.get("route")
    if route in SWIFT_ROUTES:
        return "swift"
    if route == "light":
        return "light"
    if route in AGENT_ROUTES:
        return "agent"
    return "not_heard"


def clean(r: dict[str, Any], retried: set[str]) -> bool:
    if r.get("status") != "done" or r.get("redirected") or r.get("id") in retried:
        return False
    return not any(a.get("decision") == "revise" for a in r.get("approvals") or [])


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    retried = {str(r["retry_of"]) for r in rows if r.get("retry_of")}
    per_day = Counter(r["_day"] for r in rows)
    lanes = Counter(lane(r) for r in rows)
    agent_ms = sorted(r["interaction_ms"] for r in rows
                      if lane(r) == "agent" and r.get("status") == "done" and r.get("interaction_ms"))
    n = len(rows)
    return {
        "requests": n,
        "days": len(per_day),
        "per_day": n / len(per_day) if per_day else 0.0,
        "test_days": sorted(d for d, c in per_day.items() if c > TEST_DAY),
        "lanes": {k: lanes.get(k, 0) for k in ("swift", "light", "agent", "not_heard")},
        "clean": sum(clean(r, retried) for r in rows),
        "not_done": Counter(str(r.get("status")) for r in rows if r.get("status") in NOT_DONE),
        "agent_p50_s": statistics.median(agent_ms) / 1000 if agent_ms else None,
        "agent_p90_s": agent_ms[min(len(agent_ms) - 1, int(len(agent_ms) * 0.9))] / 1000 if agent_ms else None,
        "cost_usd": sum(float(r.get("cost_usd") or 0) for r in rows),
        "escalations": sum(len(r.get("escalations") or []) for r in rows),
        "workflows": sum(1 for r in rows if r.get("workflow")),
    }


def by_week(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    weeks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        year, week, _ = r["_day"].isocalendar()
        weeks[f"{year}-W{week:02d}"].append(r)
    return dict(sorted(weeks.items()))


def pct(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "-"


def lines(name: str, s: dict[str, Any]) -> list[str]:
    n, lanes = s["requests"], s["lanes"]
    nd = s["not_done"]
    p50 = f"{s['agent_p50_s']:.1f} s" if s["agent_p50_s"] is not None else "-"
    p90 = f"{s['agent_p90_s']:.1f} s" if s["agent_p90_s"] is not None else "-"
    out = [
        f"## {name}",
        f"requests {n} | days used {s['days']} (target {TARGETS['days']}/week) | "
        f"per day used {s['per_day']:.1f} (target {TARGETS['per_day']})",
        f"answered by Swift {pct(lanes['swift'], n)} (target {TARGETS['swift']:.0%}) | light model {pct(lanes['light'], n)} | "
        f"agent {pct(lanes['agent'], n)} | not heard {pct(lanes['not_heard'], n)}",
        f"done cleanly {pct(s['clean'], n)} (target {TARGETS['clean']:.0%}) | not done {sum(nd.values())}: "
        f"error {nd.get('error', 0)}, rejected {nd.get('rejected', 0)}, cancelled {nd.get('cancelled', 0)}",
        f"agent time p50 {p50} (target under {TARGETS['agent_p50_s']:.0f} s) | p90 {p90} | "
        f"escalations {s['escalations']} | cost ${s['cost_usd']:.2f}",
        f"workflows run {s['workflows']}",
    ]
    if s["test_days"]:
        out.append("likely testing (over %d requests): %s; leave out with --exclude" % (
            TEST_DAY, ", ".join(d.isoformat() for d in s["test_days"])))
    return out


def report(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No requests in the range."
    out: list[str] = ["# Swift usage report (counts only)", ""]
    for week, week_rows in by_week(rows).items():
        out += lines(week, summarize(week_rows)) + [""]
    out += lines("All weeks", summarize(rows))
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", type=date.fromisoformat, help="first day to count (YYYY-MM-DD)")
    parser.add_argument("--exclude", type=date.fromisoformat, action="append", default=[],
                        help="a day to leave out, e.g. an owner-check day (repeatable)")
    parser.add_argument("--interactions", type=Path, default=LOCAL / "interactions.jsonl")
    args = parser.parse_args()
    if not args.interactions.exists():
        raise SystemExit(f"No interaction log at {args.interactions}")
    print(report(load(args.interactions, args.since, set(args.exclude))))


if __name__ == "__main__":
    main()
