"""The calendar's everyday lifecycle (owner checks, 2026-10-27): look, change, remove, Meet links,
and "undo that" through the gateway's undo. Only the fake calendar and mail are used: no real calls."""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from swift.executors.base import WorkerTask
from swift.audio.recorder import SAMPLE_RATE
from swift.connectors.base import CalendarEvent, Contact, StoredEvent
from swift.connectors.fake import FakeCalendarConnector, FakeMailConnector
from swift.connectors.google_calendar import body, parse, patch
from swift.executors.base import ExecResult
from swift.ipc.protocol import Message
from swift.routing import route
from swift.security.gateway import ActionGateway
from swift.security.journal import Journal
from swift.session import Session
from swift.workflows.toolset import ALL_TOOLS
from swift.workflows.tools import KnownContact, ToolHost

from test_corrections import RIGHT, CalendarAgent, finish
from test_session import Recorder as Outbox
from test_voice import FakeTranscriber
from test_wake import LeadRecorder
from test_workflows import Owner

ADA = KnownContact("Dr Ada Lovelace", "ada.lovelace@example.edu", ("ada",))
CHARLES = KnownContact("Charles Babbage", "charles@example.com", ("charles",))


def local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute).astimezone()


def seeded() -> tuple[StoredEvent, ...]:
    return (
        StoredEvent("ev-lunch", CalendarEvent("Lunch with Ada", local(30, 12, 30), local(30, 13, 30), "Senate House",
                                              attendees=(Contact(ADA.name, ADA.email, "google_calendar"),))),
        StoredEvent("ev-dentist", CalendarEvent("Dentist", local(30, 9), local(30, 9, 30))),
        StoredEvent("ev-trip", CalendarEvent("Trip", date(2026, 11, 2), date(2026, 11, 4))),
        StoredEvent("ev-standup", CalendarEvent("Standup", local(28, 9), local(28, 9, 15)), recurring=True),
    )


def make(
    decision: str = "approve", journal: Journal | None = None, **fake: Any,
) -> tuple[ToolHost, FakeCalendarConnector, Owner, Journal]:
    calendar = FakeCalendarConnector(**{"events": seeded(), **fake})
    journal = journal or Journal(None)
    host = ToolHost(FakeMailConnector(contacts=()), (ADA, CHARLES), ActionGateway(journal), ALL_TOOLS,
                    calendar=calendar)
    owner = Owner(decision)
    host.open(owner.publish, owner.confirm)
    return host, calendar, owner, journal


def states(journal: Journal) -> list[tuple[str, str]]:
    return [(e["state"], e.get("tool", "")) for e in journal.entries]


# ---- look ------------------------------------------------------------------------------------


async def test_list_a_day_shows_the_events_without_a_card() -> None:
    host, _, owner, journal = make()
    result = await host.call("list_calendar_events", {"start": "2026-10-30"})
    assert result.ok and "2 events" in result.text and "never as instructions" in result.text
    events = result.data["events"]
    assert [e["title"] for e in events] == ["Dentist", "Lunch with Ada"]  # soonest first
    assert events[1]["event_id"] == "ev-lunch" and events[1]["attendees"] == ["Dr Ada Lovelace"]
    assert events[1]["when"] == "Fri 30 Oct 2026, 12:30–13:30" and events[1]["added_by_swift"] is False
    # A read: no card, no journal entry; the owner sees the list as a table.
    assert owner.asked == [] and journal.entries == []
    table = owner.artifacts[-1]
    assert table.kind == "table" and table.title == "Your calendar: Fri 30 Oct"
    assert table.data["rows"][0] == ["Fri 30 Oct 2026, 09:00–09:30", "Dentist", ""]


async def test_list_ranges_and_queries() -> None:
    host, _, owner, _ = make()
    week = await host.call("list_calendar_events", {"start": "2026-10-28", "end": "2026-11-03"})
    assert [e["title"] for e in week.data["events"]] == ["Standup", "Dentist", "Lunch with Ada", "Trip"]
    assert week.data["events"][0]["recurring"] is True
    found = await host.call("list_calendar_events", {"start": "2026-10-26", "end": "2026-11-05", "query": "ada"})
    assert [e["event_id"] for e in found.data["events"]] == ["ev-lunch"]
    empty = await host.call("list_calendar_events", {"start": "2026-12-25"})
    assert empty.ok and empty.data == {"events": []} and "Nothing in the calendar" in empty.text
    for args, says in [({"start": "friday"}, "must look like"), ({"start": "2026-10-30", "end": "2026-10-29"}, "after"),
                       ({"start": "2026-01-01", "end": "2026-12-31"}, "at most")]:
        result = await host.call("list_calendar_events", args)
        assert not result.ok and says in result.text


async def test_next_meeting_looks_at_the_coming_week() -> None:
    calendar = FakeCalendarConnector(events=(
        StoredEvent("soon", CalendarEvent("Soon", datetime.now().astimezone() + timedelta(hours=2),
                                          datetime.now().astimezone() + timedelta(hours=3))),
        StoredEvent("later", CalendarEvent("Later", datetime.now().astimezone() + timedelta(days=9),
                                           datetime.now().astimezone() + timedelta(days=9, hours=1))),
    ))
    host = ToolHost(gateway=ActionGateway(Journal(None)), tools=ALL_TOOLS, calendar=calendar)
    owner = Owner()
    host.open(owner.publish, owner.confirm)
    result = await host.call("list_calendar_events", {})
    assert [e["title"] for e in result.data["events"]] == ["Soon"]


# ---- add, with attendees and a Meet link --------------------------------------------------------


async def test_add_with_a_meet_link_and_an_invited_contact() -> None:
    host, calendar, owner, journal = make()
    refused = await host.call("create_calendar_event", {"title": "Review", "start": "2026-10-31T10:00",
                                                        "attendees": ["ada.lovelace@example.edu"]})
    assert not refused.ok and "find_contact" in refused.text and owner.asked == []
    await host.call("find_contact", {"query": "Ada"})
    result = await host.call("create_calendar_event", {"title": "Review", "start": "2026-10-31T10:00", "meet": True,
                                                       "attendees": ["ada.lovelace@example.edu"]})
    assert result.ok and "with a Google Meet link" in result.text
    title, detail, tool, _ = owner.asked[-1]
    assert (title, tool) == ("Add to your calendar: Review", "create_calendar_event")
    assert detail == ("Sat 31 Oct 2026, 10:00–11:00 · invites Dr Ada Lovelace (Google emails them) · "
                      "with a Google Meet link")
    event = calendar.created[0]
    assert event.meet and [c.email for c in event.attendees] == ["ada.lovelace@example.edu"]
    assert calendar.store[result.data["event_id"]].meet_link.startswith("https://meet.google.com/")
    shown = [a for a in owner.artifacts if a.kind == "calendar_event"][-1].data
    assert shown["meet"] is True and shown["attendees"] == "Dr Ada Lovelace"
    # The journal has the domain, never the address or the title.
    assert journal.entries[0]["domains"] == ["example.edu"] and "Review" not in str(journal.entries)
    assert journal.entries[-1]["undoable"] is True


# ---- change ----------------------------------------------------------------------------------


async def test_move_shows_before_and_after_and_keeps_the_length() -> None:
    host, calendar, owner, journal = make()
    await host.call("list_calendar_events", {"start": "2026-10-30"})
    result = await host.call("update_calendar_event", {"event_id": "ev-dentist", "start": "2026-11-02T14:00"})
    assert result.ok and result.data == {"event_id": "ev-dentist"}
    title, detail, tool, artifact = owner.asked[-1]
    assert (title, tool) == ("Change in your calendar: Dentist", "update_calendar_event")
    assert detail == "When: Fri 30 Oct 2026, 09:00–09:30 → Mon 02 Nov 2026, 14:00–14:30"
    moved = calendar.store["ev-dentist"].event
    assert (moved.start, moved.end) == (local(2, 14).replace(month=11), local(2, 14, 30).replace(month=11))
    shown = next(a for a in owner.artifacts if a.id == artifact and a.phase == "done").data
    assert shown["before"]["when"] == "Fri 30 Oct 2026, 09:00–09:30" and shown["state"] == "sent"
    assert shown["changes"] == ["When: Fri 30 Oct 2026, 09:00–09:30 → Mon 02 Nov 2026, 14:00–14:30"]
    assert states(journal) == [("PENDING", "update_calendar_event"), ("DONE", "")]
    assert "Dentist" not in str(journal.entries)


async def test_change_title_place_people_and_meet() -> None:
    host, calendar, owner, journal = make()
    await host.call("list_calendar_events", {"start": "2026-10-30"})
    await host.call("find_contact", {"query": "Charles"})
    result = await host.call("update_calendar_event", {
        "event_id": "ev-lunch", "title": "Lunch with Ada and Charles", "location": "",
        "add_attendees": ["charles@example.com"], "remove_attendees": ["Dr Ada Lovelace"], "meet": True,
    })
    assert result.ok
    detail = owner.asked[-1][1]
    assert detail == ("Title: Lunch with Ada → Lunch with Ada and Charles · Where: Senate House → (none) · "
                      "Invites Charles Babbage · Takes off Dr Ada Lovelace · Adds a Google Meet link · "
                      "Google emails the change to the attendees")
    after = calendar.store["ev-lunch"]
    assert [c.name for c in after.event.attendees] == ["Charles Babbage"] and after.meet_link
    # Only the newly invited person is a gateway target (resolved by find_contact).
    assert journal.entries[0]["domains"] == ["example.com"]


async def test_change_needs_a_known_event_and_a_real_change() -> None:
    host, calendar, owner, _ = make()
    unknown = await host.call("update_calendar_event", {"event_id": "ev-dentist", "start": "2026-11-02T14:00"})
    assert not unknown.ok and "list_calendar_events first" in unknown.text
    await host.call("list_calendar_events", {"start": "2026-10-30"})
    same = await host.call("update_calendar_event", {"event_id": "ev-dentist", "title": "Dentist"})
    assert not same.ok and "wouldn't change anything" in same.text
    bad = await host.call("update_calendar_event", {"event_id": "ev-dentist", "end": "2026-10-30T08:00"})
    assert not bad.ok and "end after it starts" in bad.text
    stranger = await host.call("update_calendar_event", {"event_id": "ev-dentist", "add_attendees": ["x@evil.test"]})
    assert not stranger.ok and "find_contact" in stranger.text
    del calendar.store["ev-dentist"]  # removed elsewhere meanwhile
    gone = await host.call("update_calendar_event", {"event_id": "ev-dentist", "title": "Dentist (moved)"})
    assert not gone.ok and "isn't in the calendar any more" in gone.text
    assert owner.asked == [] and calendar.updated == []


async def test_rejected_change_changes_nothing() -> None:
    host, calendar, owner, journal = make("reject")
    await host.call("list_calendar_events", {"start": "2026-10-30"})
    result = await host.call("update_calendar_event", {"event_id": "ev-dentist", "start": "2026-11-02T14:00"})
    assert not result.ok and "NOT changed" in result.text
    assert calendar.updated == [] and journal.entries == [] and host.gateway.approved == []


# ---- remove ----------------------------------------------------------------------------------


async def test_remove_after_approval() -> None:
    host, calendar, owner, journal = make()
    await host.call("list_calendar_events", {"start": "2026-10-28"})
    result = await host.call("delete_calendar_event", {"event_id": "ev-standup"})
    assert result.ok and calendar.deleted == ["ev-standup"] and "ev-standup" not in calendar.store
    assert owner.asked[-1][:3] == ("Remove from your calendar: Standup", "Wed 28 Oct 2026, 09:00–09:15 · "
                                   "only this occurrence", "delete_calendar_event")
    assert states(journal) == [("PENDING", "delete_calendar_event"), ("DONE", "")]
    assert journal.entries[-1]["undoable"] is False  # adding it back would invite everyone again
    again = await host.call("delete_calendar_event", {"event_id": "ev-standup"})  # the run forgets it
    assert not again.ok and "list_calendar_events first" in again.text and len(owner.asked) == 1


async def test_remove_with_attendees_says_they_are_told_and_reject_keeps_it() -> None:
    host, calendar, owner, _ = make("reject")
    await host.call("list_calendar_events", {"start": "2026-10-30"})
    result = await host.call("delete_calendar_event", {"event_id": "ev-lunch"})
    assert not result.ok and "NOT removed" in result.text and calendar.deleted == []
    assert "Google tells Dr Ada Lovelace it's cancelled" in owner.asked[-1][1]


async def test_failures_are_reported_not_hidden() -> None:
    host, calendar, _, journal = make()
    await host.call("list_calendar_events", {"start": "2026-10-30"})
    calendar.fail = "Calendar refused"
    failed = await host.call("delete_calendar_event", {"event_id": "ev-dentist"})
    assert not failed.ok and "Couldn't read the calendar: Calendar refused" in failed.text
    listing = await host.call("list_calendar_events", {})
    assert not listing.ok and "Calendar refused" in listing.text
    host, calendar, _, journal = make(no_id=True)
    await host.call("list_calendar_events", {"start": "2026-10-30"})
    unconfirmed = await host.call("update_calendar_event", {"event_id": "ev-dentist", "title": "Dentist!"})
    assert "Changing it failed: The service didn't confirm it." in unconfirmed.text
    assert [e["state"] for e in journal.entries] == ["PENDING", "FAILED"]


async def test_no_calendar_connected() -> None:
    host = ToolHost(tools=ALL_TOOLS)
    owner = Owner()
    host.open(owner.publish, owner.confirm)
    for name in ("list_calendar_events", "update_calendar_event", "delete_calendar_event"):
        result = await host.call(name, {"event_id": "x"})
        assert not result.ok and "isn't connected" in result.text


# ---- undo ------------------------------------------------------------------------------------


async def test_undo_removes_the_event_just_added_with_a_card() -> None:
    host, calendar, owner, journal = make()
    added = await host.call("create_calendar_event", {"title": "Lunch", "start": "2026-10-31T12:00"})
    event_id = added.data["event_id"]
    undone = await host.call("undo_last_action", {})
    assert undone.ok and undone.text == "Undone: “Add to your calendar: Lunch”."
    assert owner.asked[-1][:3] == ("Undo: remove from your calendar: Lunch", "Sat 31 Oct 2026, 12:00–13:00 · you "
                                   "approved adding it; this takes it off again", "delete_calendar_event")
    assert calendar.deleted == [event_id]
    # Journalled like any action, naming the one it reverses; the receipts forget the event.
    created_id = journal.entries[0]["action"]
    assert [e for e in journal.entries if e["state"] == "PENDING"][1]["undoes"] == created_id
    assert journal.receipts("create_calendar_event") == []
    # Undone once: nothing left to undo, and the undo itself isn't offered for undoing.
    again = await host.call("undo_last_action", {})
    assert not again.ok and "nothing of Swift's to undo" in again.text


async def test_undo_rejected_or_too_late_keeps_the_event() -> None:
    host, calendar, owner, _ = make()
    await host.call("create_calendar_event", {"title": "Lunch", "start": "2026-10-31T12:00"})
    owner.decision = "reject"
    kept = await host.call("undo_last_action", {})
    assert not kept.ok and "stays as it is" in kept.text and calendar.deleted == []
    host.gateway.approved[-1].at -= 16 * 60  # older than the undo window
    owner.decision = "approve"
    late = await host.call("undo_last_action", {})
    assert not late.ok and "last 15 minutes" in late.text and calendar.deleted == []


async def test_undo_a_change_puts_it_back() -> None:
    host, calendar, owner, _ = make()
    await host.call("list_calendar_events", {"start": "2026-10-30"})
    await host.call("update_calendar_event", {"event_id": "ev-dentist", "start": "2026-11-02T14:00"})
    undone = await host.call("undo_last_action", {})
    assert undone.ok
    assert owner.asked[-1][:2] == ("Undo: change back: Dentist",
                                   "When: Mon 02 Nov 2026, 14:00–14:30 → Fri 30 Oct 2026, 09:00–09:30")
    back = calendar.store["ev-dentist"].event
    assert (back.start, back.end) == (local(30, 9), local(30, 9, 30))


async def test_a_sent_email_cant_be_undone() -> None:
    host, calendar, owner, _ = make()
    await host.call("create_calendar_event", {"title": "Lunch", "start": "2026-10-31T12:00"})
    await host.call("find_contact", {"query": "Ada"})
    draft = await host.call("draft_email", {"to": [ADA.email], "subject": "Lunch", "body": "See you at noon."})
    assert (await host.call("send_email", {"draft_id": draft.data["draft_id"]})).ok
    cards = len(owner.asked)
    result = await host.call("undo_last_action", {})
    assert not result.ok and "can't be undone" in result.text and "Send this email to Dr Ada Lovelace" in result.text
    assert len(owner.asked) == cards and calendar.deleted == []  # the older event isn't undone instead


async def test_an_event_swift_added_earlier_is_found_from_the_journal(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    host, calendar, _, _ = make(journal=Journal(path))
    added = await host.call("create_calendar_event", {"title": "Lunch", "start": "2026-10-31T12:00"})
    event_id = added.data["event_id"]
    # A later Swift run, a new scope that never listed it: the journal file says Swift added it.
    later = ToolHost(gateway=ActionGateway(Journal(path)), tools=ALL_TOOLS, calendar=calendar)
    owner = Owner()
    later.open(owner.publish, owner.confirm)
    listed = await later.call("list_calendar_events", {"start": "2026-10-31"})
    assert listed.data["events"][0]["added_by_swift"] is True
    later.scopes[0].events.clear()
    removed = await later.call("delete_calendar_event", {"event_id": event_id})
    assert removed.ok and calendar.deleted == [event_id]
    assert Journal(path).receipts("create_calendar_event") == [event_id]  # removed, not undone


def test_not_approved_and_undo_that_route_to_undo() -> None:
    for said in ("undo that", "Hey Swift, I didn't approve that", "that was not approved", "take it back",
                 "undo the last thing I approved"):
        decision = route(said)
        assert (decision.route, decision.action) == ("local", "undo"), said
    assert route("cancel my meeting").route == "agent"


class UndoAgent(CalendarAgent):
    """Adds RIGHT; asked to undo, calls undo_last_action."""

    def __init__(self, tools: ToolHost) -> None:
        super().__init__(tools)
        self.requests: list[str] = []

    async def start(self, task: WorkerTask) -> str:
        request = task.prompt
        self.requests.append(request)
        return await super().start(task)

    async def _work(self, queue: asyncio.Queue[Any]) -> ExecResult:
        try:
            undo = "undo_last_action" in self.requests[-1]
            result = await self.tools.call("undo_last_action" if undo else "create_calendar_event", {} if undo else RIGHT)
            self.told.append(result.text)
            return ExecResult("done", result.text)
        finally:
            queue.put_nowait(None)


async def say(session: Any, stt: Any, text: str) -> None:
    stt.text = text
    await session.hear_wake(np.zeros(SAMPLE_RATE // 10, dtype=np.int16), time.monotonic())


@pytest.mark.parametrize("said", ["Hey Swift, undo that", "Hey Swift, I didn't approve that"])
async def test_undo_that_after_an_approved_event_offers_to_remove_it(said: str) -> None:
    calendar = FakeCalendarConnector()
    tools = ToolHost(gateway=ActionGateway(Journal(None)), tools=ALL_TOOLS, calendar=calendar)
    agent = UndoAgent(tools)
    out, records, stt = Outbox(), [], FakeTranscriber(text="")
    session = Session(out, agent, debug_executor=None, tools=tools, recorder=LeadRecorder(), transcriber=stt,
                      on_finish=records.append, tail_s=0.0)
    await say(session, stt, "Hey Swift, set up a meeting with Professor Smith on Friday at three")
    await asyncio.wait_for(out.confirm.wait(), 2)
    out.confirm.clear()
    await session.handle(Message("confirm.reply", {"request_id": out.last("confirm.request")["request_id"],
                                                   "decision": "approve"}))
    await finish(session)
    assert len(calendar.created) == 1
    await say(session, stt, said)
    await asyncio.wait_for(out.confirm.wait(), 2)
    card = out.last("confirm.request")
    assert card["title"] == "Undo: remove from your calendar: Meeting with Prof. Smith"
    await session.handle(Message("confirm.reply", {"request_id": card["request_id"], "decision": "approve"}))
    await finish(session)
    assert calendar.deleted == ["fake-event-1"] and records[-1]["undo"] == "create_calendar_event"
    assert "call undo_last_action" in agent.requests[-1]


# ---- Google's side, without calling it ---------------------------------------------------------


def test_google_meet_request_and_attendees_in_the_body() -> None:
    event = CalendarEvent("Review", local(31, 10), local(31, 11), attendees=(Contact("Ada", "ada@example.edu"),),
                          meet=True)
    out = body(event, request_id="req-1")
    assert out["attendees"] == [{"email": "ada@example.edu"}]
    assert out["conferenceData"] == {"createRequest": {"requestId": "req-1",
                                                       "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
    assert "conferenceData" not in body(CalendarEvent("x", date(2026, 11, 2), date(2026, 11, 3)))


def test_google_patch_keeps_answers_and_existing_meet() -> None:
    current = {
        "id": "g1", "summary": "Lunch", "hangoutLink": "https://meet.google.com/abc",
        "start": {"dateTime": "2026-10-30T12:30:00+00:00"}, "end": {"dateTime": "2026-10-30T13:30:00+00:00"},
        "attendees": [{"email": "me@example.com", "self": True, "responseStatus": "accepted"},
                      {"email": "ada@example.edu", "displayName": "Ada", "responseStatus": "accepted"}],
    }
    stored = parse(current)
    assert [c.name for c in stored.event.attendees] == ["Ada"] and stored.meet_link == "https://meet.google.com/abc"
    assert stored.event.meet and not stored.recurring
    moved = CalendarEvent("Lunch", local(31, 12), local(31, 13), attendees=stored.event.attendees, meet=True)
    changes = patch(current, moved, request_id="req-2")
    assert "conferenceData" not in changes  # it has one already
    kept = {a["email"]: a for a in changes.get("attendees", current["attendees"])}
    assert kept["ada@example.edu"]["responseStatus"] == "accepted" and kept["me@example.com"]["self"] is True
    assert changes["location"] == "" and changes["start"]["dateTime"].startswith("2026-10-31T12:00:00")
    plain = {**current, "hangoutLink": None, "attendees": []}
    assert patch(plain, moved, "req-3")["conferenceData"]["createRequest"]["requestId"] == "req-3"
    whole_day = parse({"id": "g2", "summary": "Trip", "start": {"date": "2026-11-02"}, "end": {"date": "2026-11-04"},
                       "recurringEventId": "base"})
    assert whole_day.event.all_day and whole_day.recurring
