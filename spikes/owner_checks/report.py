"""Owner checks report (docs/testing/owner-checks.md): what Swift's own logs say happened.

Usage:  uv run python spikes/owner_checks/report.py --since 20:00 [--date 2026-10-26]
        [--interactions PATH] [--log PATH]

Reads %LOCALAPPDATA%\\Swift\\interactions.jsonl and logs\\swift.log (read-only), lists each
request since the given time, and marks each check:

  PASS      the evidence is in the logs and the failure condition is not;
  FAIL      the failure condition is in the logs (look at the times it names);
  NOT SEEN  neither: the check wasn't done, or the logs can't tell;
  LOOK      only your eyes can tell: the note says what to look for. Never printed as PASS.

Prints to the terminal only. Transcripts are shown because they are the owner's own data, on the owner's machine.
"""

from __future__ import annotations

import argparse
import sys
import json
import os
import re
from collections import Counter
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Swift"


class Outcome(Enum):
    """One check's result. Only PASS is truthy, so `if ok:` still means "passed"."""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_SEEN = "NOT SEEN"
    LOOK = "LOOK"

    def __bool__(self) -> bool:
        return self is Outcome.PASS


PASS, FAIL, NOT_SEEN, LOOK = Outcome.PASS, Outcome.FAIL, Outcome.NOT_SEEN, Outcome.LOOK


def seen(evidence: object) -> Outcome:
    """PASS when the evidence is there, NOT SEEN when it isn't."""
    return PASS if evidence else NOT_SEEN


def unless(failed: object, evidence: object = True) -> Outcome:
    """FAIL when the failure condition was logged; otherwise PASS with evidence, else NOT SEEN."""
    return FAIL if failed else seen(evidence)


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
              f"{(r.get('transcript') or r.get('transcript_heard') or '')[:60]}")  # unclear: what was heard (D-10)


def _stack(log: list[str], action: str) -> int:
    """How many times the owner opened, skipped or ended something in the waiting stack."""
    return sum("stack action |" in line and f"action='{action}'" in line for line in log)


def checks(rows: list[dict[str, Any]], log: list[str], runs_dir: Path | None = None) -> list[tuple[str, Outcome, str]]:
    return [(name, ok if isinstance(ok, Outcome) else seen(ok), note) for name, ok, note in _checks(rows, log, runs_dir)]


def _checks(rows: list[dict[str, Any]], log: list[str], runs_dir: Path | None = None) -> list[tuple[str, Outcome | bool, str]]:
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
    reopens = [line for line in log if "| microphone reopened |" in line]
    cards = [a for r in rows for a in r.get("approvals", [])]
    acted_away = _acted_while_away(rows, log)
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
    # ADR-016 Phase C, the dialogue: content-free log lines (kinds, how answered) and record fields.
    lane_asked = [line for line in log if "| question asked |" in line and "source='lane'" in line]
    run_asked = [line for line in log if "| question asked |" in line and "source='run'" in line]
    answered = [line for line in log if "| question answered |" in line]
    reasked = [line for line in answered if "turn='reask'" in line]
    shelved = [line for line in answered if "turn='shelve'" in line]
    clicked = [line for line in answered if "source='click'" in line]
    typed_answers = [line for line in answered if "source='typed'" in line]
    unanswered = [line for line in log if "| question unanswered in time |" in line]
    carried = [r for r in rows if r.get("carried")]
    read_aloud = [line for line in log if "| confirm card read aloud |" in line]
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
    # Sign-ins (2026-11-04): checked, offered on a card, signed in again; and words kept out of the log.
    # The fixes from the checks of 2026-11-04 (124-127).
    short_answers = [r for r in rows if r.get("source") in ("followup", "answer")
                     and re.fullmatch(r"(yes|yeah|yep|ok|okay|no|nope)\W*", str(r.get("transcript") or "").lower())]
    answers_refused = [r for r in rows if r.get("error") == "unclear_speech"
                       and re.fullmatch(r"(yes|yeah|yep|ok|okay|no|nope)\W*", str(r.get("transcript_heard") or "").lower())]
    wake_rows = [r for r in rows if r.get("source") == "wake"]
    missed_wakes = [line for line in log if "missed wake phrase kept" in line]
    signin_checked = [line for line in log if "| sign-in checked |" in line]
    signin_offered = [line for line in log if "| sign-in offered |" in line]
    signed_in = [line for line in signin_offered if "signed_in=True" in line]
    # The three fields cd7eec8 fixed, and the ones the 2026-11 audit found still open (X-03).
    words_logged = [line for line in log
                    if re.search(r"\b(asked_unanswered|transcript_heard|unclear|transcript_raw|addressed_as)="
                                 r"(?!'\[REDACTED)(?!\[\])(?!None)(?!'')", line)
                    or ("| interaction finished |" in line and re.search(r"\btarget=|'reason':", line))
                    or ("| open failed |" in line and "target=" in line)
                    or (re.search(r"\| action (failed|denied) \|", line) and "reason=" in line)
                    or ("| action done |" in line and "domains=" in line)
                    or (re.search(r"\| (failure shown|claude run failed) \|", line) and "detail=" in line)]
    fixes_decided = [line for line in log if "| word fixes decided |" in line]
    set_aside = [line for line in log if "| question set aside for another |" in line]
    resynced = [line for line in log if "| overlay told what is on screen |" in line]
    resynced_card = [line for line in resynced if "card=True" in line]
    due_sent = [line for line in log if "| due sent |" in line]
    due_drawn = [line for line in log if "| due shown |" in line]
    due_refused = [line for line in log if "| due card not drawn |" in line]
    lost_mid_run = [line for line in log if "| internet lost during a request |" in line]
    stalled = [line for line in log if "| claude run stalled |" in line]
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
    # Confirming without friction (2026-11-04, 128-131).
    lane_yes = [r for r in rows if r.get("action") == "system_yes" and r.get("confirmed")]
    yes_said = [r for r in lane_yes if r.get("source") in ("followup", "answer", "voice", "wake")]
    yes_clicked = [r for r in lane_yes if r.get("source") == "click"]
    yes_to_agent = [r for r in rows if r.get("source") == "answer" and r.get("provider") == "claude_code"
                    and re.match(r"\W*swift\W+yes\b", str(r.get("transcript") or "").lower())]
    # Offline, contacts, said over Swift's voice (2026-11-04 evening, 132-138).
    switched_back = [r for r in rows if r.get("action") == "system_carry" and "radio" in (r.get("intents") or [])]
    offline = [r for r in rows if r.get("action") == "offline"]
    offline_help = [r for r in rows if r.get("action") == "offline_help"]
    over_speech = [line for line in log if "a refusal heard over Swift's voice" in line]
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
        ("8  no card timed out unanswered", unless(timed_out, cards),
         ", ".join(f"{r['_t']:%H:%M:%S}" for r in timed_out) or "none"),
        ("10 'show me' / 'stop' during a run", ("show" in midrun or "app" in views)
         and any(r.get("status") == "cancelled" and r.get("run_ms") for r in rows),
         f"mid-run: {', '.join(str(m) for m in midrun) or 'none'}; shown: {', '.join(str(v) for v in views) or 'nothing'}; "
         f"{short_kept} short clip(s) kept ({wake_count('short_close')} as they sounded), "
         f"{wake_count('short_empty')} empty"),
        ("10 'show me' while writing brought the app forward", "app" in views, ""),
        ("11 microphone reopened after a pause (if it had stopped)", unless(len(reopens) < len(reopened), reopened),
         f"{len(reopened)} stop(s), {len(reopens)} reopen(s) logged" + (f", last {reopened[-1][11:19]}" if reopened else "")),
        ("12 lock: away, microphone paused; unlock: back", locked and unlocked and paused,
         f"{len(presence)} presence change(s)"),
        ("13 listening again within 2 s of each unlock; first wake transcribed in under 3 s",
         unless((ready_ms or 0) >= 2000 or (first_wake or 0) >= 3000, ready_ms is not None and first_wake is not None),
         f"unlock to listening (slowest) {ready_ms} ms; first wake after unlock: stt_ms={first_wake}, "
         f"finished speaking {back_ms} ms after the unlock" if first_wake is not None
         else f"unlock to listening (slowest) {ready_ms} ms; no wake after an unlock"),
        ("13 no microphone pause after an unlock", unless(_paused_while_back(log), unlocked), ""),
        ("13 the microphone reopened quickly on each return", unless((reopen_ms or 0) >= 1000, reopen_ms is not None),
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
        ("16b a typed request, and typed 'approve' didn't approve", unless(
            any(r.get("source") == "typed" and r.get("route") == "control" and r.get("action") == "approve"
                and r.get("status") == "done" and "approve" in decisions(r) for r in rows),
            any(r.get("source") == "typed" for r in rows)),
         f"{sum(r.get('source') == 'typed' for r in rows)} typed; check on screen: 'Typing can't approve'"),
        ("16b a typed follow-up continued the thread", any(
            r.get("source") == "typed" and len(by_thread.get(r.get("thread") or "", [])) > 1 for r in rows), ""),
        ("17 two requests running at the same time", side_by_side > 0, f"{side_by_side} overlap(s)"),
        ("18-20 the card, edges behind it, moved windows", LOOK, "check on screen: nothing cut off; Read more opens in place; a dropped card stays put, with its edges"),
        ("21 a card waited behind another, then answered", any(
            a.get("queued") and a.get("decision") in ("approve", "reject")
            for r in rows for a in r.get("approvals", [])), ""),
        ("21 no card timed out while out of sight", unless(timed_out, cards),
         ", ".join(f"{r['_t']:%H:%M:%S}" for r in timed_out) or "none"),
        ("22 a held card came back by itself, then answered", any(
            a.get("held_away") and a.get("decision") in ("approve", "reject")
            for r in held for a in r["approvals"]) and bool(back), f"{len(back)} card(s) back"),
        ("23 a quiet working card shrank to one line", LOOK, "check on screen"),
        ("24 a request brought forward by name", any("show_named" in (r.get("midrun") or []) or r.get("action") == "show_named"
                                                    for r in rows), ""),
        ("24 a request stopped by name", any("stop_named" in (r.get("midrun") or []) or r.get("action") == "stop_named"
                                            for r in rows), ""),
        ("25 a fourth request waited for a slot", any(r.get("queued") for r in rows), ""),
        ("26 a question listened for its answer (at least 20 s), then parked",
         unless(windows and min(windows) < 20, asked and windows),
         f"{len(asked)} parked; question windows: {', '.join(f'{w} s' for w in windows) or 'none logged'}"),
        ("27 the question picked up later", any(r.get("resumed") == "asked" or r.get("answered_later") for r in rows), ""),
        ("28 unconfirmed model retried with the default (if it happened)", seen(model_retries),
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
        ("31-36 calendar changes ran the calendar workflow on the light model", unless(changes and not changes_ok, changes),
         ", ".join(f"{r.get('workflow') or 'agent'}/{r.get('demand')} {r.get('run_ms', 0) / 1000:.0f} s" for r in changes)
         or "none"),
        ("49 an email's follow-ups stayed in the email workflow", unless(
            any(r.get("workflow") != "email-draft" for r in email_followups), email_followups),
         f"{len(email_followups)} follow-up(s); Gmail subject put right {len(subject_fixed)} time(s); "
         "check on screen: the subject stays short"),
        ("43 'hey Swift' seen while still speaking (chime and pulse)", wake_count("peek_wake") > 0,
         f"{wake_count('peek_wake')} early, {wake_count('wake')} wake phrase(s)"),
        ("45 the room not taken as a reply", seen(wake_count("followup_quiet") + wake_count("followup_long")),
         f"{wake_count('followup_quiet')} set aside as the room, {wake_count('followup_long')} as long talk, "
         f"{wake_count('followup')} taken"),
        ("46 unsure speech: asked to say it again", seen(asked_again), f"{len(asked_again)} time(s)"),
        ("47 a request recorded while the last one started (20, 21)", bool(next_recorded) or wake_count("queued") > 0,
         f"{len(next_recorded)} request(s), {wake_count('queued')} by voice"),
        ("50 line breaks typed into a chat app didn't send it", LOOK, "check on screen: one message, several lines"),
        ("51 Swift refused to write into a terminal", LOOK, "check on screen"),
        ("52 web pages fetched only from given addresses", seen(fetch_refused),
         f"{len(fetch_refused)} fetch(es) of a made-up address refused"),
        ("53 'no, leave it' to 'Turn off Wi-Fi?' left it on", LOOK, "check on screen; a plain yes does it since 2026-11-04 (128)"),
        ("54 no Swift card vanished when another request ended", unless(vanished, cards),
         ", ".join(f"{r['_t']:%H:%M:%S}" for r in vanished) or "none"),
        ("55 no request crashed while others ran", unless(crashed, side_by_side),
         ", ".join(f"{r['_t']:%H:%M:%S}" for r in crashed) or "none"),
        ("56 the same request said twice ran once", bool(kept_running), f"{len(kept_running)} kept running"),
        ("57 a long command's card showed all of it", LOOK, "check on screen"),
        ("59 spoken answers (Phase B)", any(r.get("spoken_chars") for r in rows),
         f"{sum(1 for r in rows if r.get('spoken_chars'))} spoken"),
        ("60 no action left 'unknown' (if one was, look it up)", unless(unknown, rows), f"{len(unknown)} unknown"),
        ("61 nothing heard acted on after a lock", unless(acted_away, locked and unlocked),
         f"{wake_count('paused_drop')} dropped as the screen locked; acted while away: "
         + (", ".join(f"{r['_t']:%H:%M:%S}" for r in acted_away) or "none")),
        ("62 reads outside the read folders asked first; secrets refused", bool(read_cards) or bool(never_read),
         f"{len(read_cards)} read card(s), {len(never_read)} secret path(s) refused"),
        # The Capsule redesign (ADR-017).
        ("68 a card that ran out went to the stack, not refused", unless(timed_out, expired),
         f"{len(expired)} into the stack, {len(timed_out)} refused on time-out"),
        ("64 Stop on the capsule stopped only the voice", bool(voice_stopped), f"{len(voice_stopped)} time(s)"),
        ("66 listening paused and resumed from the tray", bool(paused_tray) and bool(resumed_tray),
         f"{len(paused_tray)} paused, {len(resumed_tray)} resumed"),
        ("69 Swift's question put off into the stack (Answer later)", bool(put_off),
         f"{len(put_off)} put off, {len(asked)} parked as unanswered in all"),
        ("71 a timer came due and showed its card", bool(timers), f"{len(timers)} timer(s)"),
        # The hardening slice (docs/audit/2026-10-audit.md, B-02 to B-04).
        ("76 Swift wrote in your apps only when you asked", LOOK,
         f"{len(not_asked)} write(s) refused as not asked; check on screen: nothing typed"),
        ("77-78 due items waited and were shown once, together", unless(sum(due_shown) > len(came_due), due_shown),
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
        ("92 Show in Word from the live view", bool(live_app), f"{len(live_app)} time(s)"),
        ("95 a finished live view: Open the answer, ENDED after a stop", LOOK,
         "check on screen: Open the answer showed the whole answer even after its card faded; a stopped view says ENDED"),
        # ADR-016 Phase C: the dialogue.
        ("100-101 a lane asked for what was missing", bool(lane_asked), f"{len(lane_asked)} question(s)"),
        ("102 carried on from the last request", bool(carried), f"{len(carried)} time(s)"),
        ("103 Swift waited for the end of a sentence", wake_count("held") > 0 or any(r.get("endpoint_waits") for r in rows),
         f"{wake_count('held')} held, {wake_count('stitched')} joined, "
         f"{sum(r.get('endpoint_waits', 0) for r in rows)} wait(s) while recording"),
        ("104 a request asked you something", bool(run_asked), f"{len(run_asked)} question(s), {len(clicked)} answered by a click"),
        ("105 an answer it couldn't work out: asked once more, then set aside", bool(reasked),
         f"{len(reasked)} asked again, {len(shelved)} set aside"),
        ("106 a question unanswered in time went to the stack", bool(unanswered), f"{len(unanswered)} time(s)"),
        ("107 a confirm card was read aloud", bool(read_aloud), f"{len(read_aloud)} time(s)"),
        ("108 a typed request's question was answered by typing", bool(typed_answers), f"{len(typed_answers)} time(s)"),
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
        # Fixes from the checks of 2026-11-04.
        ("124 a short 'yes' or 'no' heard as a reply", unless(answers_refused, short_answers),
         f"{len(short_answers)} taken, {len(answers_refused)} refused as unclear"),
        ("125 'hey Swift' said without a pause started requests", bool(wake_rows),
         f"{len(wake_rows)} hands-free request(s), {len(missed_wakes)} wake phrase(s) missed"),
        ("126-127 the whole research answer; the live view inside the screen", LOOK,
         "check on screen: Read more shows every line, no 'Blocked: WebFetch', the live view's buttons visible"),
        # Confirming without friction (2026-11-04).
        ("128 a plain yes did it", bool(yes_said), f"{len(yes_said)} time(s)"),
        ("129 a click on Yes did it", bool(yes_clicked), f"{len(yes_clicked)} time(s)"),
        ("130 'Swift, yes' reached the question, never the agent", unless(yes_to_agent, lane_yes),
         f"{len(yes_to_agent)} sent to the agent"),
        # Offline, contacts, overlay, said over Swift's voice (2026-11-04 evening).
        ("132 'turn it back on' done here", bool(switched_back), f"{len(switched_back)} time(s)"),
        ("133 offline: answered at once, no agent", bool(offline), f"{len(offline)} time(s)"),
        ("134 'what works offline' listed", bool(offline_help), f"{len(offline_help)} time(s)"),
        ("135 the whole name kept one contact", LOOK, "check on screen: no 'Which Francis' after 'Francis Chianu'"),
        ("136 a 'no' said while Swift talked", bool(over_speech), f"{len(over_speech)} time(s)"),
        ("137 a card taller than the window scrolled", LOOK, "check on screen: a scrollbar, the buttons in sight"),
        ("138 Change opened the text box beside the card", LOOK, "check on screen"),
        # Sign-ins checked and offered again (swift/signin.py).
        ("120 sign-ins checked", bool(signin_checked),
         ", ".join(sorted({m.group(1) for line in signin_checked if (m := re.search(r"status='(\w+)'", line))}))
         or "none"),
        ("121-122 a sign-in offered on a card", bool(signin_offered),
         f"{len(signin_offered)} card(s), {len(signed_in)} signed in again"),
        ("123 swift.log kept your words out", unless(words_logged, log), f"{len(words_logged)} line(s) with words"),
        # The seams audit's first fixes (2026-11-05).
        ("139 a held 'Swift, approve and…' did nothing after a lock", unless(acted_away, locked and unlocked),
         f"{wake_count('paused_drop')} dropped as the screen locked; check on screen: the card still waiting"),
        # One window per question (seams audit S3).
        ("141 a question set aside for another came back", seen(set_aside),
         f"{len(set_aside)} set aside; check on screen: it came back with a whole countdown"),
        ("142-145 each question's countdown", LOOK,
         "check on screen: an answer begun in time counts; the countdown starts after Swift speaks, 25 s"),
        # One owner of what is on screen (seams audit S1).
        ("146 the overlay was told what is on screen (a reload or restart)", seen(resynced_card),
         f"{len(resynced)} time(s), {len(resynced_card)} with a card; check on screen: the same card, its countdown"),
        ("147-148 a restart and two cards", LOOK, "check on screen: the timer card after the restart; one card at a time"),
        # Every card sent should be drawn: "kept for later" still means the overlay refused it (8 sent,
        # 1 drawn printed PASS while "Your timer is up" repeated, 2026-11-05).
        ("270 each timer card sent was drawn, or waited in the stack", unless(
            len(due_sent) > len(due_drawn) + len(due_refused), due_drawn),
         f"{len(due_sent)} sent, {len(due_drawn)} drawn, {len(due_refused)} not drawn and back in the stack"),
        ("271 an approval card counted down only while seen", LOOK,
         "check on screen: stopped after two idle minutes, went on from there"),
        ("149 due cards drawn before leaving the schedule", unless(len(due_sent) > len(due_drawn), due_drawn),
         f"{len(due_sent)} sent, {len(due_drawn)} drawn"),
        # Nothing waits for ever (seams audit S4).
        ("152 a quick command beside three requests", LOOK, "check on screen: done at once, not 'That's waiting'"),
        ("153 the internet went during a request", seen(lost_mid_run), f"{len(lost_mid_run)} time(s)"),
        ("154 a silent request ended by itself (if one went silent)", seen(stalled), f"{len(stalled)} time(s)"),
        # One set of rules for every way in (seams audit S2).
        ("156 a wordy yes and 'hold on'", LOOK, "check on screen: Wi-Fi off; 'Okay, take your time', the card stays"),
        ("160 a cough wasn't an answer", seen(wake_count("no_words")), f"{wake_count('no_words')} with no words"),
        ("161 an unsure answer was asked again", seen(wake_count("unsure_answer")),
         f"{wake_count('unsure_answer')} time(s)"),
        ("162 'stop' during a run stopped it, not a question", LOOK, "check on screen: the research stopped"),
        ("163-164 a question out of sight wasn't answered", LOOK,
         f"check on screen: Wi-Fi stayed on after 'yes'; 'Swift, yes' brought it back "
         f"{sum(r.get('action') == 'question_not_shown' for r in rows)} time(s)"),
        # ADR-018, the Deck: how it looks is the point, so only the eyes can tell.
        ("168 a second request landed behind the card", seen(side_by_side > 0),
         f"{side_by_side} overlap(s); check on screen: the card didn't move, 'Got it: …', no window opened"),
        ("169 new requests on the far end, then +N", LOOK, "check on screen: edges stay put; a dashed mark for one waiting"),
        ("170 an edge clicked swapped with the card; Watch brought nothing forward", LOOK,
         f"check on screen; clicks that couldn't bring it forward: {sum('focus ignored' in line for line in log)}"),
        ("171 an instant answer flashed no edge", LOOK, "check on screen"),
        ("172 a card due moved to the front", LOOK, "check on screen: it moved rather than cross-faded"),
        ("173 Read more folded the deck to one edge", LOOK, "check on screen: '2 more running', and the answer isn't squeezed"),
        ("174 the orb while a card is open", LOOK, "check on screen: paused still says so over a card"),
        ("175 the stack's amber only when an OK waits", LOOK, "check on screen: neutral for a stopped request"),
        ("176 the deck at all six positions", LOOK, "check on screen: on the far side of the card, nothing cut off"),
        ("177 edges move with the card; an old overlay.json still loads", LOOK, "check on screen"),
        ("178 the moves are smooth on the real screen", LOOK, "check on screen: also with animation effects off"),
        ("179 'stop' asked which, with the one just said behind the card",
         seen(any("mid-run words could mean either request" in line for line in log)),
         f"{sum('mid-run words could mean either request' in line for line in log)} time(s); check on screen: nothing stopped"),
        ("180 an answer finishing behind the card came forward", LOOK, "check on screen"),
        ("181 a hidden question ignored 'Swift, yes turn it off' and typing", LOOK, "check on screen: Wi-Fi stayed on"),
        ("182 a correction offer took a yes only on screen, typed only with the name", LOOK, "check on screen: nothing started when refused"),
        ("183 a file change's card showed all of it and scrolled to the end", LOOK, "check on screen"),
        ("184 a change too long for a card came in pieces, each on its own card", LOOK, "check on screen"),
        ("191 the first 'hey Swift' registered", LOOK, "your count of 10 decides whether Swift needs a wake model"),
        ("192 only 'Hello' said aloud, and not in your words", LOOK, "check on screen"),
        ("193 the weather needed no card", LOOK, "check on screen: no command, no asking where"),
        ("194 a bare 'hey Swift' during a run was heard", LOOK, "check on screen: it landed behind the card"),
        ("195 a new request on a card ran beside it; a change stayed a change", LOOK, "check on screen: no 'Changing it' for the research"),
        ("196 the same request three times was one", LOOK, "check on screen: 'Still on it', no extra edge"),
        ("197 asking again replaced the unfinished one in the stack", LOOK, "check on screen"),
        ("198 the stack kept its corner", LOOK, "check on screen: all six positions, and no drag"),
        ("199 a command's card said what it is", LOOK, "check on screen"),
        ("200 a yes to 'It sounded like …' went ahead with it", LOOK, "check on screen: not with the word 'yes'"),
        # The checks of 2026-11-09.
        ("201 your answer to Swift's question counted as what you asked",
         seen(sum("system action asked for in an answer" in line for line in log)),
         f"{sum('system action asked for in an answer' in line for line in log)} time(s)"),
        ("202 airplane mode said what it really did", LOOK,
         "check on screen: 'Turn off Wi-Fi and Bluetooth instead?', then which radios are off"),
        ("203 'Hey Swift' brought the overlay in front", LOOK, "check on screen: in front of an always-on-top window"),
        ("204 a greeting before a command kept Swift's own question",
         unless([r for r in rows if r.get("route") == "agent" and any(
             a.get("tool") == "system_action_disruptive" for a in r.get("approvals") or [])]),
         "an agent's approval card for a radio is a FAIL"),
        ("303 a request begun again kept Swift's own question",
         unless([r for r in rows if r.get("route") == "agent" and any(
             "system_action" in (s.get("text") or "") for s in r.get("steps") or [])]),
         "a system change done by the agent is a FAIL; check on screen: 'Turn off Wi-Fi?' with Yes and No"),
        ("205 asked again in other words: one fresh card, one item in the stack", LOOK,
         "check on screen: the old item left the stack when the new card came"),
        ("206 waiting for your answer never said 'Working on it'", LOOK,
         "check on screen: 'Waiting for your answer' on the edge or the pill"),
        ("207 the stack opened and closed in its corner", LOOK, "check on screen: three times, same corner"),
        ("208 a question out of sight kept its time", seen(sum("its countdown paused" in line for line in log)),
         f"{sum('its countdown paused' in line for line in log)} time(s) paused out of sight"),
        ("209 offline: one sentence, the list only when asked", LOOK, "check on screen"),
        ("256 an answer that ended behind a card waited until it was seen",
         seen(sum("unseen answer kept behind the card" in line for line in log)),
         f"{sum('unseen answer kept behind the card' in line for line in log)} time(s) kept; check on screen it went once read"),
        ("257 a card from the stack carried on where it was", LOOK,
         "check on screen: its last step, its timer from the start, an ended one shows its answer"),
        ("210 a ring on each stack item showed its time left", LOOK, "check on screen: shorter a few minutes later"),
        ("212 a new request sent Swift's question to the stack; Wi-Fi stayed on", LOOK, "check on screen"),
        ("213 Swift's interaction log was refused with no card",
         seen([line for line in log if "| read refused: never-read path |" in line]), "and no card asked first"),
        ("214 a surname the only match doesn't have was asked about, not drafted to", LOOK, "check on screen"),
        ("215 a stop in the first 5 seconds kept the email",
         seen([line for line in log if "| action stopped before it went |" in line]), "and nothing arrived"),
        ("211 'yes, but hold on' waited; a wordy reply stayed with the question", LOOK,
         "check on screen: 'Okay, take your time', Wi-Fi still on, no new request"),
        ("216 Halo's glass is readable over real apps and wallpapers", LOOK, "check on screen: dark and light"),
        ("217 Halo's tail points at the orb at all six positions", LOOK, "check on screen: also at 150% scaling"),
        ("218 Halo's amber and accent halos are never confused", LOOK, "check on screen: side by side"),
        ("219 Halo's edges are distinct from the card at a glance", LOOK, "check on screen: dark and light"),
        ("220 the sleeping orb reads as not listening", LOOK, "check on screen: from normal viewing distance"),
        ("221 a card grows from the orb and the tail settles last", LOOK, "check on screen: also with animation effects off"),
        ("250 'add lunch next week' after two requests showed its question, not 'Working on it'", LOOK,
         "check on screen: 'Waiting for you' and the question"),
        ("251 the spinner kept turning, also on the one-line card after 20 s", LOOK,
         "check on screen: no jump back once a second; say whether animation effects were on"),
        # A second way in for "Hey Swift" (ADR-021).
        ("228 the second way in woke Swift (calm voice, close and at 1.5 m)", seen(wake_count("acoustic_wake")),
         f"{wake_count('acoustic_wake')} through the second way in, {wake_count('wake')} wake phrases in all;"
         " tell us how many of each 10 didn't register"),
        ("230 a request after a calm 'Hey Swift' kept its first word", LOOK,
         "check on screen: no 'Swift' or piece of it in front"),
        ("231 the detector fired, and what came of it", LOOK,
         f"{wake_count('acoustic_hits')} checked, {wake_count('acoustic_wake')} woke Swift,"
         f" {wake_count('acoustic_rejected')} turned down; only you know whether any wake was by itself"),
        ("232 nothing woke through the second way in while locked", unless(acted_away, locked and unlocked),
         "acted while away: " + (", ".join(f"{r['_t']:%H:%M:%S}" for r in acted_away) or "none")),
        *_rigid(rows),
        *_grounded(rows),
        *_memory(rows),
        *_health(log),
        _gmail(log),
        *_front_and_web(rows),
        *_command_cards(rows),
        *_step_cards(rows),
        *_runs(rows, runs_dir),
    ]


def _runs(rows: list[dict[str, Any]], folder: Path | None) -> list[tuple[str, Outcome | bool, str]]:
    """Check 280: every request since the start left its run record (``runs.py``), started and ended, with none of
    the owner's words in it. 281: a timer's card still comes up as one (now known by its origin, ADR-019 N2)."""
    look = ("281 a timer's card still came up as a timer", LOOK, "check on screen: the timer card, not an answer card")
    if folder is None or not folder.is_dir():
        return [("280 every request left a run record", NOT_SEEN, "no runs folder: restart Swift on this version"), look]
    ids = [r for r in rows if r.get("id") and r.get("thread")]
    missing, unended, worded = [], [], []
    for r in ids:
        path = folder / f"{r['id']}.jsonl"
        if not path.is_file():
            missing.append(r)
            continue
        text = path.read_text(encoding="utf-8")
        events = [json.loads(line) for line in text.splitlines() if line.strip()]
        if not events or events[0].get("event") != "started" or events[-1].get("event") != "ended":
            unended.append(r)
        said = str(r.get("transcript") or "").strip().lower()
        if len(said) > 8 and said in text.lower():
            worded.append(r)

    def times(found: list[dict[str, Any]]) -> str:
        return ", ".join(f"{r['_t']:%H:%M:%S}" for r in found) or "none"

    return [
        ("280 every request left a run record, started and ended, without your words",
         unless(missing or unended or worded, ids),
         f"{len(ids)} requests; no record: {times(missing)}; not ended: {times(unended)}; with words: {times(worded)}"),
        look,
    ]


def _gmail(log: list[str]) -> tuple[str, Outcome | bool, str]:
    """Check 252 (A9, 2026-11-13): Gmail filled in with the cursor elsewhere. The detail is the proof of the
    cause: which step put the cursor in each field, and the code of each fill that failed."""
    fills = [line for line in log if "tool='fill_in_email'" in line]
    done = [line for line in fills if "| action done |" in line]
    failed = [m.group(1) for line in fills if "| action failed |" in line
              for m in [re.search(r"code='(\w+)'", line)] if m]
    hows = [re.sub(r".*field='(\w+)' how='(\w+)'.*", r"\1 by \2", line) for line in log
            if "| gmail field focused |" in line]
    forward = sum("| gmail compose brought forward |" in line for line in log)
    return ("252 Gmail filled in without the cursor already in the body", unless(failed, done),
            f"{len(done)} filled, failed: {', '.join(failed) or 'none'}; cursor: {', '.join(hows) or 'first try'};"
            f" brought forward {forward} time(s)")


def _rigid(rows: list[dict[str, Any]]) -> list[tuple[str, Outcome | bool, str]]:
    """Checks 233-239: requests in the owner's own words. Matched by their phrases, so a misheard one is NOT SEEN.
    243: a misheard "turn off the Wi-Fi" ("wafer", 2026-11-13) gets Swift's own question, not the agent."""

    def said(pattern: str) -> list[dict[str, Any]]:
        return [r for r in rows if re.search(pattern, r.get("transcript") or "", re.I)]

    def answer(r: dict[str, Any]) -> str:
        steps = r.get("steps") or []
        return str(steps[-1].get("text") or "") if steps else ""

    def times(found: list[dict[str, Any]]) -> str:
        return ", ".join(f"{r['_t']:%H:%M:%S}" for r in found) or "none"

    sentence = said(r"in one sentence")
    first = said(r"ask(ed)? about first")
    ways = said(r"switch the wi.?fi|kill the bluetooth|bluetooth.+bluetooth|some music|too loud|on the clock")
    words = said(r"file called notes|in outlook|subject line")
    cant = said(r"my birthday|my manager|every monday|downloads folder|on my screen")
    stalled = [r for r in cant if r.get("status") != "done" or int(r.get("interaction_ms") or 0) > 30_000]
    misheard = said(r"\b(wafer|wofo|waffle|why fi)\b")
    tried = [r for r in rows if r.get("route") == "agent"
             and any("system_action" in str(s.get("text")) for s in r.get("steps") or [])]
    refused = [r for r in tried if re.match(r"I (didn.t|couldn.t|haven.t)", answer(r))]
    return [
        ("233 a follow-up was given the answer before it", unless([r for r in sentence if not r.get("context")], sentence),
         "without it: " + times([r for r in sentence if not r.get("context")])),
        ("234 the third answer remembered the first question",
         unless([r for r in first if "claudia" not in answer(r).lower()], first), "it should name Claudia"),
        ("235 a command said another way stayed fast", unless([r for r in ways if r.get("route") == "agent"], ways),
         f"{sum(r.get('route') != 'agent' for r in ways)} of {len(ways)} heard; slow lane: "
         + times([r for r in ways if r.get("route") == "agent"])),
        ("236 a workflow's word in another request didn't start the workflow",
         unless([r for r in words if r.get("workflow")], words),
         "ran a workflow: " + times([r for r in words if r.get("workflow")])),
        ("237 a request Swift can't do yet didn't stall", unless(stalled, cant),
         f"stalled: {times(stalled)}; tell us which were done and which Swift said it can't do"),
        ("238 ten requests of your own", LOOK, "tell us the ten and your tally"),
        ("239 a command Swift understood was done", unless(refused, tried), "understood and not done: " + times(refused)),
        ("262 'play some music' with no music app said nothing played", LOOK,
         "check on screen: 'Nothing started playing', never 'Playing.'"),
        ("243 a misheard Wi-Fi got Swift's own question, not the agent",
         unless([r for r in misheard if r.get("route") == "agent"], misheard),
         f"{len(misheard)} heard; went to the agent: " + times([r for r in misheard if r.get("route") == "agent"])),
    ]


def _front_and_web(rows: list[dict[str, Any]]) -> list[tuple[str, Outcome | bool, str]]:
    """Checks 253-254: Swift in front of an always-on-top window (A10). 255: a spoken web address opens (C3)."""
    spoken = [r for r in rows if re.search(r"\bopen\b.*\b\w+ dot (com|org|net|edu|ac|co|io)\b", r.get("transcript") or "", re.I)]

    def opened(r: dict[str, Any]) -> bool:
        return any("desktop_open" in str(s.get("text")) for s in r.get("steps") or [])

    missed = [r for r in spoken if not opened(r)]
    return [
        ("253 Swift came in front of an ordinary always-on-top window", LOOK,
         "tell us whether Swift was in front of the test window, and whether Notepad kept the cursor"),
        ("254 Task Manager's band", LOOK, "paste window_bands.py's last lines; was Swift in front of Task Manager?"),
        ("255 a spoken web address was opened", unless(missed, spoken),
         f"{len(spoken)} heard; not opened: " + (", ".join(f"{r['_t']:%H:%M:%S}" for r in missed) or "none")),
    ]


def _command_cards(rows: list[dict[str, Any]]) -> list[tuple[str, Outcome | bool, str]]:
    """Checks 263-264 (B1): a command card leads with a plain sentence, the command folded under it."""
    cards = [(r, a) for r in rows for a in r.get("approvals", []) if a.get("tool") in ("Bash", "PowerShell")]
    bare = [r for r, a in cards if a.get("explained") is False]
    approved = [r for r, a in cards if a.get("decision") == "approve"]
    return [
        ("263 every command card led with what it does", unless(bare, cards),
         f"{len(cards)} command card(s); with no sentence (command shown open): "
         + (", ".join(f"{r['_t']:%H:%M:%S}" for r in bare) or "none")),
        ("264 a command card approves as before", LOOK,
         f"{len(approved)} approved; tell us whether a bare 'yes' or typing ever approved one"),
    ]


def _step_cards(rows: list[dict[str, Any]]) -> list[tuple[str, Outcome | bool, str]]:
    """Checks 300-302 (B2): one card approves a step's commands; a delete, a send or anything unlisted asks again."""
    steps = [(r, a) for r in rows for a in r.get("approvals", []) if a.get("step")]
    granted = [r for r in rows if (r.get("step_grant") or {}).get("steps")]
    covered = sum((r.get("step_grant") or {}).get("covered", 0) for r in rows)
    again = sum((r.get("step_grant") or {}).get("asked_again", 0) for r in rows)
    return [
        ("300 one step card, then its commands ran without more cards", seen(granted and covered),
         f"{len(steps)} step card(s), {len(granted)} approved; {covered} command(s) ran on a step's approval"),
        ("301 a delete still asked on its own card", LOOK,
         f"{again} command(s) asked again during an approved step; tell us whether the delete had its own card"),
        ("302 a step card approves as before", LOOK,
         "tell us whether a bare 'yes' or typing ever approved a step card"),
    ]


def _grounded(rows: list[dict[str, Any]]) -> list[tuple[str, Outcome | bool, str]]:
    """Checks 259-261: Swift doesn't know where the owner is (C1, 2026-11-13: "about 4 km" from the weather's area)."""

    def said(pattern: str) -> list[dict[str, Any]]:
        return [r for r in rows if re.search(pattern, r.get("transcript") or "", re.I)]

    def steps(r: dict[str, Any]) -> list[str]:
        return [str(s.get("text") or "") for s in r.get("steps") or []]

    def answer(r: dict[str, Any]) -> str:
        return (steps(r) or [""])[-1]

    def times(found: list[dict[str, Any]]) -> str:
        return ", ".join(f"{r['_t']:%H:%M:%S}" for r in found) or "none"

    figure = re.compile(r"\d\s*(km|kilomet|miles?|minutes?|mins?|hours?)\b|you (appear|seem) to be in", re.I)
    unplaced = said(r"(how far|how long).*(my (current )?location|from here|where i am)")
    guessed = [r for r in unplaced if figure.search(answer(r)) and "?" not in answer(r)]
    weather = said(r"\b(rain|weather|forecast)\b")
    asked_back = [r for r in weather if any("ask_owner" in t for t in steps(r)) or answer(r).rstrip().endswith("?")]
    between = said(r"how far is .+ from (?!my |here|where)\w+")
    return [
        ("259 no distance was given without a starting point", unless(guessed, unplaced),
         f"{len(unplaced)} asked; answered with a guessed place: " + times(guessed)),
        ("260 the weather was answered without asking where", unless(asked_back, weather),
         "asked where: " + times(asked_back)),
        ("261 a distance between two places you named", LOOK,
         f"{len(between)} asked ({times(between)}); tell us whether it was about right"),
    ]


def _memory(rows: list[dict[str, Any]]) -> list[tuple[str, Outcome | bool, str]]:
    """Checks 290-293: the memory store (swift/memory.py, C7). Only the owner's words write it."""

    def said(pattern: str) -> list[dict[str, Any]]:
        return [r for r in rows if re.search(pattern, r.get("transcript") or "", re.I)]

    def times(found: list[dict[str, Any]]) -> str:
        return ", ".join(f"{r['_t']:%H:%M:%S}" for r in found) or "none"

    kept = said(r"\bremember (that )?my manager is")
    forgot = said(r"\bforget (that )?my manager")
    errands = said(r"\bremember to\b")
    return [
        ("290 'remember that my manager is …' was Swift's own, not the agent",
         unless([r for r in kept if r.get("action") != "remember"], kept), "went elsewhere: " + times(
             [r for r in kept if r.get("action") != "remember"])),
        ("291 'forget that my manager …' was Swift's own", unless([r for r in forgot if r.get("action") != "forget"], forgot),
         "went elsewhere: " + times([r for r in forgot if r.get("action") != "forget"])),
        ("292 nothing a page or a note said was remembered", LOOK,
         "check on screen: 'what do you know about me' never lists Mallory"),
        ("293 'remember to …' stayed a reminder, not a memory",
         unless([r for r in errands if r.get("action") == "remember"], errands),
         "kept as a memory: " + times([r for r in errands if r.get("action") == "remember"])),
    ]


def _health(log: list[str]) -> list[tuple[str, Outcome | bool, str]]:
    """Checks 240-241: fixes from the health audit (2026-11-12). 242: the stuck card of 2026-11-13."""
    # The overlay asked to stop a request the backend had already ended: its card was still on screen.
    ghosts = [line for line in log if "| stop from the live view ignored |" in line and "known=True" in line]
    stops = [line for line in log if "| request stopped from" in line]
    chosen = [line for line in log if "contact chosen by the owner" in line and _counter(line, "options") > 1]
    return [
        ("240 of several matching contacts, the one you picked was used", seen(chosen), "pick one when Swift asks which"),
        ("241 no chime straight after a lock", LOOK, "tell us whether Swift chimed or showed 'heard' while locked"),
        ("242 no card left working after its request ended", unless(ghosts, stops),
         f"{len(stops)} stop(s); pressed on a request already over: {len(ghosts)}"),
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


def _stamp(line: str) -> datetime | None:
    m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", line)
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") if m else None


def _acted_while_away(rows: list[dict[str, Any]], log: list[str]) -> list[dict[str, Any]]:
    """Requests from something heard that started while the screen was locked (owner check 61, T-07).

    Typed and hotkey requests are the owner's own act at the keyboard and don't count. A request
    within 2 s of the lock is allowed: it may have started just before it."""
    spans: list[tuple[datetime, datetime]] = []
    start: datetime | None = None
    for line in log:
        if "| presence |" not in line or (t := _stamp(line)) is None:
            continue
        if "reason='locked'" in line and start is None:
            start = t
        elif "reason='unlocked'" in line and start is not None:
            spans.append((start, t))
            start = None
    if start is not None:
        spans.append((start, datetime.max))
    heard = ("wake", "followup", "answer", "voice", "beside")
    return [r for r in rows if r.get("source") in heard and isinstance(r.get("_t"), datetime)
            and any((r["_t"] - a).total_seconds() > 2 and r["_t"] < b for a, b in spans)]


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
    # A Windows console is cp1252: one transcript character outside it stopped the report (2026-11-10).
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
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
    results = checks(rows, log, args.interactions.parent / "runs")
    for name, ok, note in results:
        print(f"  {ok.value:8}  {name}" + (f"   ({note})" if note else ""))
    tally = Counter(ok for _, ok, _ in results)
    print("\n  " + ", ".join(f"{tally[o]} {o.value}" for o in Outcome))
    if tally[FAIL]:
        print("  Look at each FAIL first: the times in its note say where.")
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
