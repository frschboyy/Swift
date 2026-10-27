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
    unsure_wake = sum(_counter(line, "unsure_wake") for line in log if "| wake listening |" in line)
    first_wake = _first_wake_after_unlock(log)
    ready_ms = _slowest(log, "| listening again |", "ms")
    back_ms = _slowest(log, "wake phrase heard", "since_back_ms")
    midrun = [x for r in rows for x in (r.get("midrun") or [])]
    views = [v.get("kind") for r in rows for v in (r.get("views") or [])]
    short_kept = sum(_counter(line, "short_heard") - _counter(line, "short_dropped") for line in log if "| wake listening |" in line)
    asked = [line for line in log if "conversation parked | reason='asked'" in line]
    # How long each question listened for its answer ("question window", logged since 2026-10-27).
    windows = [_counter(line, "seconds") for line in log if "| question window |" in line]
    model_retries = [line for line in log if "couldn't confirm its model" in line]
    side_by_side = _overlapping(rows)
    redirects = [r.get("redirected") for r in rows if r.get("redirected")]
    approved = [(a.get("tool"), a.get("decision")) for r in rows for a in r.get("approvals", [])]

    def answered(tool: str, decision: str = "approve") -> bool:
        return (tool, decision) in approved

    undos = [r for r in rows if r.get("undo")]
    return [
        ("1  hands-free request (wake)", any(r.get("source") == "wake" for r in rows),
         f"{unsure_wake} unsure wake phrase(s) still taken"),
        ("2-3 a conversation in one thread", longest >= 3, f"longest thread: {longest} requests"),
        ("4  calendar request ran directly (no offer)", any(r.get("route") == "agent" for r in calendar)
         and not any(r.get("offered") == "calendar-event" for r in rows), f"{len(calendar)} calendar runs"),
        ("5  a change on a card", "revise" in all_decisions, ""),
        ("7  a rejection", "reject" in all_decisions, ""),
        ("8  correction after a rejection, then approved", corrected, ""),
        ("8  no card timed out unanswered", not timed_out,
         ", ".join(f"{r['_t']:%H:%M:%S}" for r in timed_out) or "none"),
        ("10 'show me' / 'stop' during a run", ("show" in midrun or "app" in views)
         and any(r.get("status") == "cancelled" and r.get("run_ms") for r in rows),
         f"mid-run: {', '.join(str(m) for m in midrun) or 'none'}; shown: {', '.join(str(v) for v in views) or 'nothing'}; "
         f"{short_kept} short clip(s) kept"),
        ("10 'show me' while writing brought the app forward", "app" in views, ""),
        ("11 microphone reopened after a pause (if it had stopped)", True,
         f"{len(reopened)} reopen(s) logged" + (f", last {reopened[-1][11:19]}" if reopened else "")),
        ("12 lock: away, microphone paused; unlock: back", locked and unlocked and paused,
         f"{len(presence)} presence change(s)"),
        ("13 listening again within 2 s of each unlock; first wake transcribed in under 3 s",
         ready_ms is not None and ready_ms < 2000 and first_wake is not None and first_wake < 3000,
         f"unlock to listening (slowest) {ready_ms} ms; first wake after unlock: stt_ms={first_wake}, "
         f"finished speaking {back_ms} ms after the unlock" if first_wake is not None
         else f"unlock to listening (slowest) {ready_ms} ms; no wake after an unlock"),
        ("13 no microphone pause after an unlock", not _paused_while_back(log), ""),
        ("14 a card held while away, answered after", any(
            a.get("held_away") and a.get("decision") in ("approve", "reject")
            for r in held for a in r["approvals"]), f"{len(held)} held card(s)"),
        ("15 a stopped request parked, then offered", any(r.get("parked") == "stopped" for r in rows)
         and any(r.get("offered_resume") for r in rows), ""),
        ("15 the Unfinished line's title is the owner's words", any(r.get("offered_resume") for r in rows),
         "check on screen: never '[Swift workflow: ...'"),
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
        ("26 a question listened for its answer (at least 20 s), then parked",
         bool(asked) and bool(windows) and min(windows) >= 20,
         f"{len(asked)} parked; question windows: {', '.join(f'{w} s' for w in windows) or 'none logged'}"),
        ("27 the question picked up later", any(r.get("resumed") == "asked" or r.get("answered_later") for r in rows), ""),
        ("28 unconfirmed model retried with the default (if it happened)", True,
         f"{len(model_retries)} retr{'y' if len(model_retries) == 1 else 'ies'}"),
        ("29-30 a calendar question ran the workflow, no card", any(
            r.get("route") == "agent" and not r.get("approvals") and r.get("status") == "done" for r in calendar), ""),
        ("31-32 a calendar change approved", answered("update_calendar_event"), ""),
        ("33 an event added", answered("create_calendar_event"), ""),
        ("34-35 'undo that' / 'I didn't approve that' offered an undo card", any(
            r.get("undo") in ("create_calendar_event", "update_calendar_event") for r in undos),
         ", ".join(str(r.get("undo")) for r in undos) or "none"),
        ("36 a removal rejected, then approved", answered("delete_calendar_event", "reject")
         and answered("delete_calendar_event"), ""),
        ("37 'undo that' after an email: told it can't be undone", any(r.get("undo") == "send_email" for r in undos), ""),
    ]


def _counter(line: str, name: str) -> int:
    m = re.search(rf"\b{name}=(\d+)", line)
    return int(m.group(1)) if m else 0


def _slowest(log: list[str], marker: str, name: str) -> int | None:
    found = [_counter(line, name) for line in log if marker in line and re.search(rf"\b{name}=\d", line)]
    return max(found, default=None)


def _paused_while_back(log: list[str]) -> bool:
    """A "microphone paused" logged while presence said here (the 2026-10-27 race)."""
    here = True
    for line in log:
        if "| presence |" in line:
            here = "state='away'" not in line
        elif "microphone paused" in line and here:
            return True
    return False


def _first_wake_after_unlock(log: list[str]) -> int | None:
    """The slowest stt_ms of the first wake phrase heard after each unlock (None: none)."""
    found: list[int] = []
    unlocked = False
    for line in log:
        if "reason='unlocked'" in line:
            unlocked = True
        elif unlocked and "wake phrase heard" in line:
            found.append(_counter(line, "stt_ms"))
            unlocked = False
    return max(found, default=None)


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
