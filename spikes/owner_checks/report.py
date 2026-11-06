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


def checks(rows: list[dict[str, Any]], log: list[str]) -> list[tuple[str, Outcome, str]]:
    return [(name, ok if isinstance(ok, Outcome) else seen(ok), note) for name, ok, note in _checks(rows, log)]


def _checks(rows: list[dict[str, Any]], log: list[str]) -> list[tuple[str, Outcome | bool, str]]:
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
        ("16 a card that ran out went to the stack, not refused", unless(timed_out, expired),
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
        ("95 Show in Word from the live view", bool(live_app), f"{len(live_app)} time(s)"),
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
        ("168 a second request landed behind a confirm card", seen(side_by_side > 0),
         f"{side_by_side} overlap(s); check on screen: that card didn't move, 'Got it: …', no window opened"),
        ("169 displaced requests on the far end, then +N", LOOK, "check on screen: edges stay put; a dashed mark for one waiting"),
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
    results = checks(rows, log)
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
