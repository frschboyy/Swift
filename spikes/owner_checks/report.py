"""Owner checks report (docs/testing/owner-checks.md): what Swift's own logs say happened.

Usage:  uv run python spikes/owner_checks/report.py --since 20:00 [--date 2026-10-26]
        [--interactions PATH] [--log PATH]

Reads %LOCALAPPDATA%\\Swift\\interactions.jsonl and logs\\swift.log (read-only), lists each
request since the given time, and marks each check PASS or NOT SEEN. Prints to the terminal
only. Transcripts are shown because they are the owner's own data, on the owner's machine.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Swift"


def load(path: Path, since: datetime) -> list[dict[str, Any]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            ts = datetime.fromisoformat(r["ts"]).replace(tzinfo=None)
        except (ValueError, KeyError, TypeError):
            continue
        if ts >= since:
            r["_t"] = ts
            out.append(r)
    return out


def log_lines(path: Path, since: datetime) -> list[str]:
    if not path.exists():
        return []
    keep = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", line)
        if m and datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") >= since:
            keep.append(line)
    return keep


def decisions(r: dict[str, Any]) -> list[str]:
    return [str(a.get("decision")) for a in r.get("approvals", [])]


def show(rows: list[dict[str, Any]]) -> None:
    threads: dict[str, str] = {}
    print(f"{'time':8}  {'thread':6}  {'source':10}  {'route / workflow':22}  {'status':9}  cards        request")
    for r in rows:
        thread = r.get("thread")
        tag = threads.setdefault(thread, chr(ord("A") + len(threads))) if thread else "-"
        what = r.get("workflow") or r.get("route") or "-"
        if r.get("offered"):
            what = f"offered {r['offered']}"
        cards = ",".join(decisions(r)) or "-"
        print(f"{r['_t']:%H:%M:%S}  {tag:6}  {r.get('source', '-'):10}  {what[:22]:22}  {r.get('status', '-'):9}  {cards[:12]:12} "
              f"{(r.get('transcript') or '')[:60]}")


def checks(rows: list[dict[str, Any]], log: list[str]) -> list[tuple[str, bool, str]]:
    by_thread: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("thread"):
            by_thread.setdefault(r["thread"], []).append(r)
    longest = max((len(v) for v in by_thread.values()), default=0)
    calendar = [r for r in rows if r.get("workflow") == "calendar-event"]
    all_decisions = [d for r in rows for d in decisions(r)]
    corrected = any(
        any("reject" in decisions(a) for a in group[:i]) and r.get("source") in ("followup", "correction")
        and "approve" in decisions(r)
        for group in by_thread.values() for i, r in enumerate(group)
    )
    timed_out = [r for r in rows if "no_answer" in decisions(r)]
    reopened = [line for line in log if "microphone stream stopped delivering audio" in line]
    presence = [line for line in log if "| presence |" in line]
    locked = any("reason='locked'" in line for line in presence)
    unlocked = any("reason='unlocked'" in line for line in presence)
    paused = any("microphone paused" in line for line in log)
    held = [r for r in rows if any(a.get("held_away") for a in r.get("approvals", []))]
    side_by_side = _overlapping(rows)
    redirects = [r.get("redirected") for r in rows if r.get("redirected")]
    return [
        ("1  hands-free request (wake)", any(r.get("source") == "wake" for r in rows), ""),
        ("2-3 a conversation in one thread", longest >= 3, f"longest thread: {longest} requests"),
        ("4  calendar request ran directly (no offer)", any(r.get("route") == "agent" for r in calendar)
         and not any(r.get("offered") == "calendar-event" for r in rows), f"{len(calendar)} calendar runs"),
        ("5  a change on a card", "revise" in all_decisions, ""),
        ("7  a rejection", "reject" in all_decisions, ""),
        ("8  correction after a rejection, then approved", corrected, ""),
        ("8  no card timed out unanswered", not timed_out,
         ", ".join(f"{r['_t']:%H:%M:%S}" for r in timed_out) or "none"),
        ("10 'show me' / 'stop' during a run", any(r.get("midrun") for r in rows)
         or any(r.get("status") == "cancelled" and r.get("run_ms") for r in rows), ""),
        ("11 microphone reopened after a pause (if it had stopped)", True,
         f"{len(reopened)} reopen(s) logged" + (f", last {reopened[-1][11:19]}" if reopened else "")),
        ("12 lock: away, microphone paused; unlock: back", locked and unlocked and paused,
         f"{len(presence)} presence change(s)"),
        ("14 a card held while away, answered after", any(
            a.get("held_away") and a.get("decision") in ("approve", "reject")
            for r in held for a in r["approvals"]), f"{len(held)} held card(s)"),
        ("15 a stopped request parked, then offered", any(r.get("parked") == "stopped" for r in rows)
         and any(r.get("offered_resume") for r in rows), ""),
        ("16 a parked request resumed", any(r.get("resumed") for r in rows), ""),
        ("17 two requests running at the same time", side_by_side > 0, f"{side_by_side} overlap(s)"),
        ("19 a card waited behind another, then answered", any(
            a.get("queued") and a.get("decision") in ("approve", "reject")
            for r in rows for a in r.get("approvals", [])), ""),
        ("20 a request brought forward by name", any("show_named" in (r.get("midrun") or []) or r.get("action") == "show_named"
                                                    for r in rows), ""),
        ("21 a request stopped by name", any("stop_named" in (r.get("midrun") or []) or r.get("action") == "stop_named"
                                            for r in rows), ""),
        ("22 a change of mind passed on", any(x in ("same_session", "restart") for x in redirects),
         ", ".join(redirects) or "none"),
        ("23 a hands-free change of mind (with the name)", any(
            r.get("redirected") and r.get("source") in ("wake", "beside") for r in rows), ""),
        ("24 after a sent email: told, correction offered", "after_done" in redirects
         and any(r.get("fix") for r in rows), ""),
        ("25 a fourth request waited for a slot", any(r.get("queued") for r in rows), ""),
    ]


def _overlapping(rows: list[dict[str, Any]]) -> int:
    """How many requests started while another was still running (from start time and duration)."""
    spans = []
    for r in rows:
        if "_t" in r and r.get("interaction_ms"):
            start = r["_t"].timestamp()
            spans.append((start, start + r["interaction_ms"] / 1000))
    spans.sort()
    return sum(1 for i, (start, _) in enumerate(spans) if any(s < start < e for s, e in spans[:i]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="HH:MM, the time you started the checks")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--interactions", type=Path, default=LOCAL / "interactions.jsonl")
    ap.add_argument("--log", type=Path, default=LOCAL / "logs" / "swift.log")
    args = ap.parse_args()
    since = datetime.strptime(f"{args.date} {args.since}", "%Y-%m-%d %H:%M")
    if not args.interactions.exists():
        raise SystemExit(f"No interaction log at {args.interactions}")
    rows = load(args.interactions, since)
    log = log_lines(args.log, since)
    print(f"\n{len(rows)} requests since {since:%Y-%m-%d %H:%M}\n")
    show(rows)
    print("\nChecks (docs/testing/owner-checks.md)\n")
    for name, ok, note in checks(rows, log):
        print(f"  {'PASS    ' if ok else 'NOT SEEN'}  {name}" + (f"   ({note})" if note else ""))
    problems = [line for line in log if "| WARNING" in line or "| ERROR" in line]
    print(f"\nWarnings and errors in swift.log: {len(problems)}")
    for line in problems[-10:]:
        print("  " + line[11:230])


if __name__ == "__main__":
    main()
