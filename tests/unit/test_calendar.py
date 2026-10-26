"""The calendar tool and its gateway path (ADR-011 W1). Only the fake calendar is used."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from test_workflows import Owner

from swift.connectors.base import CalendarEvent
from swift.connectors.fake import FakeCalendarConnector
from swift.connectors.google_calendar import body
from swift.security.gateway import ActionGateway
from swift.security.journal import Journal
from swift.workflows.calendar import when_text
from swift.workflows.toolset import ALL_TOOLS
from swift.workflows.tools import ToolHost


def make(decision: str = "approve", **fake: object) -> tuple[ToolHost, FakeCalendarConnector, Owner, Journal]:
    calendar, journal = FakeCalendarConnector(**fake), Journal(None)  # type: ignore[arg-type]
    host = ToolHost(gateway=ActionGateway(journal), tools=ALL_TOOLS, calendar=calendar)
    owner = Owner(decision)
    host.open(owner.publish, owner.confirm)
    return host, calendar, owner, journal


async def test_event_is_added_after_approval() -> None:
    host, calendar, owner, journal = make()
    result = await host.call("create_calendar_event", {"title": "Lunch with Ada", "start": "2026-10-30T12:30",
                                                       "location": "Senate House"})
    assert result.ok and result.data == {"event_id": "fake-event-1"}
    event = calendar.created[0]
    assert event.title == "Lunch with Ada" and isinstance(event.start, datetime) and event.start.tzinfo is not None
    assert event.end - event.start == timedelta(hours=1)
    # The card shows the event itself.
    assert owner.asked == [("Add to your calendar: Lunch with Ada", "Fri 30 Oct 2026, 12:30–13:30 · Senate House",
                            "create_calendar_event", "event-1")]
    assert [(a.kind, a.phase, a.data.get("state")) for a in owner.artifacts] == [
        ("calendar_event", "drafting", None), ("calendar_event", "confirming", "waiting_approval"),
        ("calendar_event", "sending", "sending"), ("calendar_event", "done", "sent"),
    ]
    assert [e["state"] for e in journal.entries] == ["PENDING", "DONE"]
    assert journal.entries[0]["domains"] == [] and "Lunch" not in str(journal.entries)


async def test_rejected_event_is_not_added() -> None:
    host, calendar, owner, _ = make("reject")
    result = await host.call("create_calendar_event", {"title": "Dentist", "start": "2026-11-02"})
    assert not result.ok and "NOT added" in result.text and calendar.created == []
    assert owner.asked[0][1] == "Mon 02 Nov 2026, all day"


async def test_bad_times_are_refused_before_the_card() -> None:
    host, calendar, owner, _ = make()
    for args, says in [
        ({"title": "x", "start": "next friday"}, "must look like"),
        ({"title": "x", "start": "2026-10-30T12:00", "end": "2026-10-30T11:00"}, "end after it starts"),
        ({"title": "x", "start": "2026-10-30", "end": "2026-10-30T11:00"}, "both be dates"),
        ({"title": "", "start": "2026-10-30"}, "needs a title"),
    ]:
        result = await host.call("create_calendar_event", args)
        assert not result.ok and says in result.text
    assert owner.asked == [] and calendar.created == []


async def test_no_calendar_and_failures() -> None:
    host = ToolHost(tools=ALL_TOOLS)
    owner = Owner()
    host.open(owner.publish, owner.confirm)
    assert "isn't connected" in (await host.call("create_calendar_event", {"title": "x", "start": "2026-10-30"})).text
    host, calendar, _, journal = make(fail="Calendar refused")
    failed = await host.call("create_calendar_event", {"title": "x", "start": "2026-10-30"})
    assert "Adding it failed: Calendar refused" in failed.text
    host, _, _, _ = make(no_id=True)
    assert "didn't confirm" in (await host.call("create_calendar_event", {"title": "x", "start": "2026-10-30"})).text


def test_google_event_body_and_when_text() -> None:
    timed = CalendarEvent("Lunch", datetime(2026, 10, 30, 12, 30).astimezone(), datetime(2026, 10, 30, 14).astimezone())
    out = body(timed)
    assert out["summary"] == "Lunch" and out["start"]["dateTime"].startswith("2026-10-30T12:30:00")
    assert "date" not in out["start"] and "location" not in out
    all_day = CalendarEvent("Trip", date(2026, 11, 2), date(2026, 11, 5), location="Paris")
    assert body(all_day)["start"] == {"date": "2026-11-02"} and body(all_day)["location"] == "Paris"
    assert when_text(all_day) == "Mon 02 Nov 2026 – Wed 04 Nov 2026, all day"
    assert when_text(timed) == "Fri 30 Oct 2026, 12:30–14:00"
