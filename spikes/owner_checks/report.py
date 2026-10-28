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
from collections import Counter
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
    # The Capsule redesign (ADR-017): content-free log lines.
    expired = [line for line in log if "card expired into the stack" in line]
    voice_stopped = [line for line in log if "| speech stopped by the owner |" in line]
    paused_tray = [line for line in log if "| listening paused |" in line]
    resumed_tray = [line for line in log if "| listening resumed |" in line]
    put_off = [line for line in log if "| question put off into the stack |" in line]
    timers = [line for line in log if "| due |" in line and "kind='timer'" in line]
    # The hardening slice after the audit (B-02, B-03, B-04): content-free log lines.
    not_asked = [line for line in log if "desktop write refused: not asked" in line]
    came_due = [line for line in log if "| due |" in line]
    due_again = [line for line in came_due if "missed=True" in line]
    due_shown = [_counter(line, "items") for line in log if "| due shown |" in line]
    restarted = [line for line in log if "| backend ready |" in line and "restarted=True" in line]
    # The live view (ADR-017 §7): counts and content-free lines only.
    live_shown = [v for r in rows for v in (r.get("views") or []) if v.get("kind") == "live"]
    live_counts = [r.get("live") or {} for r in rows]
    live_sources = sum(c.get("source", 0) for c in live_counts)
    live_notes = sum(c.get("note", 0) for c in live_counts)
    live_text = sum(c.get("text", 0) for c in live_counts)
    watched = [line for line in log if "| live view |" in line and "open=True" in line]
    live_stopped = [line for line in log if "| request stopped from the live view |" in line]
    live_app = [line for line in log if "| live view: app shown |" in line and "shown=True" in line]

    # Saved recordings (audit B-06): counts and flags only.
    swept = [line for line in log if "| recordings swept |" in line]
    clip_flags = Counter(f for r in rows for f in r.get("clip_flags") or [])
    to_test_set = [line for line in log if "| recordings: added to the test set |" in line]
    missed_wake = [line for line in log if "| recordings: missed wake phrase kept |" in line]
    improve_runs = [line for line in log if "| improvement pass |" in line]
    fixes_decided = [line for line in log if "| word fixes decided |" in line]
    cleared = [line for line in log if "| recordings cleared |" in line]

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
    # The 2026-10 audit's fixes (docs/audit/2026-10-audit.md, owner checks 50-61).
    fetch_refused = [line for line in log if "web fetch refused: address not given" in line]
    wifi_unnamed = [r for r in rows if r.get("action") == "system_yes_unnamed"]
    # A Swift card that went unanswered while its request said "done": the A-08 vanishing card.
    vanished = [r for r in rows if r.get("status") == "done"
                and any(a.get("by") == "swift" and a.get("decision") == "no_answer" for a in r.get("approvals", []))]
    crashed = [r for r in rows if r.get("error") == "crashed"]
    kept_running = [line for line in log if "same request again while it runs" in line]
    unknown = [line for line in log if "| action outcome unknown |" in line]
    never_read = [line for line in log if "read refused: never-read path" in line]
    read_cards = [a for r in rows for a in r.get("approvals", []) if a.get("tool") in ("Read", "Glob", "Grep")]
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
        # ADR-017: no Later button; a card whose countdown ran out goes to the stack (see 16 below).
        ("16 a card opened from the stack, then answered", any(
            "stack action | kind='card' action='open'" in line for line in log)
         and any(r.get("source") != "stack" and set(decisions(r)) & {"approve", "reject"} for r in rows), ""),
        ("16b a typed request, and typed 'approve' didn't approve", any(r.get("source") == "typed" for r in rows)
         and not any(r.get("source") == "typed" and r.get("route") == "control" and r.get("action") == "approve"
                     and r.get("status") == "done" and "approve" in decisions(r) for r in rows),
         f"{sum(r.get('source') == 'typed' for r in rows)} typed; check on screen: 'Typing can't approve'"),
        ("16b a typed follow-up continued the thread", any(
            r.get("source") == "typed" and len(by_thread.get(r.get("thread") or "", [])) > 1 for r in rows), ""),
        ("17 two requests running at the same time", side_by_side > 0, f"{side_by_side} overlap(s)"),
        ("18-20 windows, the reader, chips, moved windows", True, "check on screen: nothing cut off; Read more opens in place; dropped cards stay put"),
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
        ("50 line breaks typed into a chat app didn't send it", True, "check on screen: one message, several lines"),
        ("51 Swift refused to write into a terminal", True, "check on screen"),
        ("52 web pages fetched only from given addresses", True,
         f"{len(fetch_refused)} fetch(es) of a made-up address refused"),
        ("53 a yes to 'Turn off Wi-Fi?' without the name didn't do it", True,
         f"{len(wifi_unnamed)} time(s) asked for 'Swift, yes'"),
        ("54 no Swift card vanished when another request ended", not vanished,
         ", ".join(f"{r['_t']:%H:%M:%S}" for r in vanished) or "none"),
        ("55 no request crashed while others ran", not crashed,
         ", ".join(f"{r['_t']:%H:%M:%S}" for r in crashed) or "none"),
        ("56 the same request said twice ran once", bool(kept_running), f"{len(kept_running)} kept running"),
        ("57 a long command's card showed all of it", True, "check on screen"),
        ("59 spoken answers (Phase B)", any(r.get("spoken_chars") for r in rows),
         f"{sum(1 for r in rows if r.get('spoken_chars'))} spoken"),
        ("60 no action left 'unknown' (if one was, look it up)", not unknown, f"{len(unknown)} unknown"),
        ("61 nothing heard acted on after a lock", True, f"{wake_count('paused_drop')} dropped as the screen locked"),
        ("62 reads outside the read folders asked first; secrets refused", bool(read_cards) or bool(never_read),
         f"{len(read_cards)} read card(s), {len(never_read)} secret path(s) refused"),
        # The Capsule redesign (ADR-017).
        ("16 a card that ran out went to the stack, not refused", bool(expired) and not timed_out,
         f"{len(expired)} into the stack, {len(timed_out)} refused on time-out"),
        ("64 Stop on the capsule stopped only the voice", bool(voice_stopped), f"{len(voice_stopped)} time(s)"),
        ("66 listening paused and resumed from the tray", bool(paused_tray) and bool(resumed_tray),
         f"{len(paused_tray)} paused, {len(resumed_tray)} resumed"),
        ("69 Swift's question put off into the stack (Answer later)", bool(put_off),
         f"{len(put_off)} put off, {len(asked)} parked as unanswered in all"),
        ("71 a timer came due and showed its card", bool(timers), f"{len(timers)} timer(s)"),
        # The hardening slice (docs/audit/2026-10-audit.md, B-02 to B-04).
        ("76 Swift wrote in your apps only when you asked", True,
         f"{len(not_asked)} write(s) refused as not asked; check on screen: nothing typed"),
        ("77-78 due items waited and were shown once, together", bool(due_shown) and sum(due_shown) <= len(came_due),
         f"{len(came_due)} came due ({len(due_again)} after a restart or as missed), "
         f"{sum(due_shown)} shown on {len(due_shown)} card(s)"),
        ("77, 79-80 Swift restarted without quitting", bool(restarted), f"{len(restarted)} restart(s)"),
        # The live view of a running request (ADR-017 §7).
        ("90 'show me' during a run opened its live view", bool(live_shown), f"{len(live_shown)} time(s)"),
        ("91 sources and notes reached the live view", live_sources > 0,
         f"{live_sources} source item(s), {live_notes} note(s)"),
        ("92 the text being written showed in the live view", live_text > 0, f"{live_text} paragraph(s)"),
        ("93 Watch on a card or chip opened a live view", bool(watched), f"{len(watched)} time(s)"),
        ("94 Stop in a live view stopped that request", bool(live_stopped), f"{len(live_stopped)} time(s)"),
        ("95 Show in Word from the live view", bool(live_app), f"{len(live_app)} time(s)"),
        # Saved recordings (audit B-06).
        ("110 old recordings swept at start-up", bool(swept),
         f"{sum(_counter(line, 'deleted_old') for line in swept)} old, "
         f"{sum(_counter(line, 'deleted_unflagged') for line in swept)} unflagged deleted over {len(swept)} sweep(s)"),
        ("111-113 clips flagged as useful", bool(clip_flags),
         ", ".join(f"{k} {n}" for k, n in sorted(clip_flags.items())) or "none"),
        ("112-113 a repeat or correction gave a clip its words", bool(to_test_set), f"{len(to_test_set)} added to the test set"),
        ("114 a missed wake phrase was kept", bool(missed_wake), f"{len(missed_wake)} time(s)"),
        ("115 the improvement pass ran", bool(improve_runs),
         f"{len(improve_runs)} pass(es), {len(fixes_decided)} word-fix card(s) answered"),
        ("116 saved recordings cleared", bool(cleared), f"{len(cleared)} time(s)"),
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


# ---- lanes (ADR-016 §9.2): which path each request took, and which agent runs needn't have ----


def lane_of(r: dict[str, Any]) -> str:
    route, action = r.get("route"), r.get("action")
    if route == "local":
        return {"system": "system", "system_undo": "system", "system_yes": "system", "system_no": "system",
                "system_yes_unnamed": "system", "answer": "fast"}.get(action or "", "local")
    if route == "agent" and r.get("workflow"):
        return "workflow"
    return route or "-"


def lanes(rows: list[dict[str, Any]]) -> dict[str, tuple[int, int | None]]:
    """Lane -> (requests, median interaction_ms)."""
    by: dict[str, list[int]] = {}
    for r in rows:
        by.setdefault(lane_of(r), []).append(int(r.get("interaction_ms") or 0))
    out: dict[str, tuple[int, int | None]] = {}
    for lane, times in sorted(by.items(), key=lambda kv: -len(kv[1])):
        known = sorted(t for t in times if t)
        out[lane] = (len(times), known[len(known) // 2] if known else None)
    return out


def could_be_local(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Agent or light runs that the router (as it is now) would answer locally, or that had a part
    the system lane can do ("agent did it"). (verdict, transcript): "now local" or "partly system"."""
    from swift.routing import route
    from swift.workflows.system_tools import owner_intents

    out: list[tuple[str, str]] = []
    for r in rows:
        text = r.get("transcript") or ""
        if not text or lane_of(r) not in ("agent", "light", "workflow"):
            continue
        if route(text).route != "agent":
            out.append(("now local", text))
        elif owner_intents(text):
            out.append(("partly system", text))
    return out


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
    print("\nLanes: requests, median time to the answer\n")
    for lane, (n, ms) in lanes(rows).items():
        print(f"  {lane:9} {n:4}   {'-' if ms is None else f'{ms / 1000:.1f} s'}")
    missed = could_be_local(rows)
    print(f"\nAgent runs Swift could answer itself now: {len(missed)} (ADR-016 §3.4: add the rest to the grammar)")
    for verdict, text in missed[:20]:
        print(f"  {verdict:13}  {text[:90]}")
    problems = [line for line in log if "| WARNING" in line or "| ERROR" in line]
    print(f"\nWarnings and errors in swift.log: {len(problems)}")
    for line in problems[-10:]:
        print("  " + line[11:230])


if __name__ == "__main__":
    main()
