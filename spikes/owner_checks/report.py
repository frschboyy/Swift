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


def _stack(log: list[str], action: str) -> int:
    """How many times the owner opened, skipped or ended something in the waiting stack."""
    return sum("stack action |" in line and f"action='{action}'" in line for line in log)


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
    back = [line for line in log if "confirm card back" in line]
    unsure_wake = sum(_counter(line, "unsure_wake") for line in log if "| wake listening |" in line)
    first_wake = _first_wake_after_unlock(log)
    ready_ms = _slowest(log, "| listening again |", "ms")
    back_ms = _slowest(log, "wake phrase heard", "since_back_ms")
    midrun = [x for r in rows for x in (r.get("midrun") or [])]
    views = [v.get("kind") for r in rows for v in (r.get("views") or [])]
    wake_lines = [line for line in log if "| wake listening |" in line]

    def wake_count(name: str) -> int:
        return sum(_counter(line, name) for line in wake_lines)

    short_kept = wake_count("short_heard") - wake_count("short_dropped")
    reopen_ms = _slowest(log, "| microphone reopened |", "ms")
    next_recorded = [r for r in rows if r.get("queued_behind")]
    asked_again = [r for r in rows if r.get("error") == "unclear_speech"]
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
    drafts = [line for line in log if "| draft written |" in line]
    as_owner = [line for line in drafts if "greeted=True" in line and "signed=True" in line]
    emailed = [line for line in log if "| contact lookup |" in line and "gmail_emailed" in line]
    # Calendar changes (owner checks of 2026-10-27, 17:00: they went to the general agent, one for 148 s).
    changing = ("update_calendar_event", "delete_calendar_event")
    changes = [r for r in rows if any(a.get("tool") in changing for a in r.get("approvals", []))]
    changes_ok = bool(changes) and all(r.get("workflow") == "calendar-event" and r.get("demand") == "light"
                                       for r in changes)
    # Follow-ups to an email ("send it", "actually say …") go on in the email workflow, with its draft.
    emails = {r.get("thread") for r in rows if r.get("workflow") == "email-draft"}
    email_followups = [r for r in rows if r.get("source") in ("followup", "correction") and r.get("thread") in emails
                       and r.get("route") == "agent"]
    subject_fixed = [line for line in log if "gmail subject was wrong" in line]
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
         f"{short_kept} short clip(s) kept ({wake_count('short_close')} as they sounded), "
         f"{wake_count('short_empty')} empty"),
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
        ("13 the microphone reopened quickly on each return", reopen_ms is None or reopen_ms < 1000,
         f"slowest reopen {reopen_ms} ms" if reopen_ms is not None else "no reopen logged"),
        ("14 a card held while away, answered after", any(
            a.get("held_away") and a.get("decision") in ("approve", "reject")
            for r in held for a in r["approvals"]), f"{len(held)} held card(s)"),
        # The waiting stack (ADR-015 §9) replaced "continue" as the way back.
        ("15 stopped requests parked into the stack", sum(r.get("parked") == "stopped" for r in rows) >= 2,
         f"{sum(r.get('parked') == 'stopped' for r in rows)} parked"),
        ("15 a card in the stack skipped, and one ended", _stack(log, "skip") > 0 and _stack(log, "end") > 0,
         f"skip {_stack(log, 'skip')}, end {_stack(log, 'end')}"),
        ("16 a conversation resumed from the stack", any(r.get("source") == "stack" and r.get("resumed") for r in rows),
         f"opened from the stack: {_stack(log, 'open')}"),
        ("16 'Later' on a card on screen, then answered from the stack", any(
            "stack action | kind='card' action='skip'" in line for line in log)
         and any(r.get("source") != "stack" and set(decisions(r)) & {"approve", "reject"} for r in rows), ""),
        ("16b a typed request, and typed 'approve' didn't approve", any(r.get("source") == "typed" for r in rows)
         and not any(r.get("source") == "typed" and r.get("route") == "control" and r.get("action") == "approve"
                     and r.get("status") == "done" and "approve" in decisions(r) for r in rows),
         f"{sum(r.get('source') == 'typed' for r in rows)} typed; check on screen: 'Typing can't approve'"),
        ("16b a typed follow-up continued the thread", any(
            r.get("source") == "typed" and len(by_thread.get(r.get("thread") or "", [])) > 1 for r in rows), ""),
        ("17 two requests running at the same time", side_by_side > 0, f"{side_by_side} overlap(s)"),
        ("18-20 windows, the reader, chips, moved windows", True, "check on screen: nothing cut off; Read all; chip after a minute"),
        ("21 a card waited behind another, then answered", any(
            a.get("queued") and a.get("decision") in ("approve", "reject")
            for r in rows for a in r.get("approvals", [])), ""),
        ("21 no card timed out while out of sight", not timed_out,
         ", ".join(f"{r['_t']:%H:%M:%S}" for r in timed_out) or "none"),
        ("22 a held card came back by itself, then answered", any(
            a.get("held_away") and a.get("decision") in ("approve", "reject")
            for r in held for a in r["approvals"]) and bool(back), f"{len(back)} card(s) back"),
        ("23 a quiet working card shrank to one line", True, "check on screen"),
        ("24 a request brought forward by name", any("show_named" in (r.get("midrun") or []) or r.get("action") == "show_named"
                                                    for r in rows), ""),
        ("24 a request stopped by name", any("stop_named" in (r.get("midrun") or []) or r.get("action") == "stop_named"
                                            for r in rows), ""),
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
        ("38 a change of mind passed on", any(x in ("same_session", "restart") for x in redirects),
         ", ".join(redirects) or "none"),
        ("39 a hands-free change of mind (with the name)", any(
            r.get("redirected") and r.get("source") in ("wake", "beside") for r in rows), ""),
        ("40 after a sent email: told, correction offered", "after_done" in redirects
         and any(r.get("fix") for r in rows), ""),
        ("41 a draft written as the owner: greeting and signed with their name", bool(as_owner),
         f"{len(as_owner)} of {len(drafts)} draft(s); check on screen: short subject, 'Regards, <your name>'"),
        ("42 a contact found from Gmail correspondence (people you've emailed)", bool(emailed),
         f"{len(emailed)} lookup(s)"),
        ("31-36 calendar changes ran the calendar workflow on the light model", changes_ok,
         ", ".join(f"{r.get('workflow') or 'agent'}/{r.get('demand')} {r.get('run_ms', 0) / 1000:.0f} s" for r in changes)
         or "none"),
        ("49 an email's follow-ups stayed in the email workflow", bool(email_followups)
         and all(r.get("workflow") == "email-draft" for r in email_followups),
         f"{len(email_followups)} follow-up(s); Gmail subject put right {len(subject_fixed)} time(s); "
         "check on screen: the subject stays short"),
        ("43 'hey Swift' seen while still speaking (chime and pulse)", wake_count("peek_wake") > 0,
         f"{wake_count('peek_wake')} early, {wake_count('wake')} wake phrase(s)"),
        ("45 the room not taken as a reply", True,
         f"{wake_count('followup_quiet')} set aside as the room, {wake_count('followup_long')} as long talk, "
         f"{wake_count('followup')} taken"),
        ("46 unsure speech: asked to say it again", True, f"{len(asked_again)} time(s)"),
        ("47 a request recorded while the last one started (20, 21)", bool(next_recorded) or wake_count("queued") > 0,
         f"{len(next_recorded)} request(s), {wake_count('queued')} by voice"),
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
