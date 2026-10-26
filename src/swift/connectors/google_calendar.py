"""Google Calendar for the calendar-event workflow (ADR-011 W1, §13 #5).

Creates one event in the owner's primary calendar with ``events.insert`` under
``calendar.events`` (verified in spike S4). Nothing else: no reading, no attendees,
so no invitations go out. The sign-in is shared with Gmail (``swift.connectors.google``);
a token from before ``calendar.events`` was added needs signing in again.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from swift.connectors.base import CalendarEvent, CreatedEvent, Manifest
from swift.connectors.google import GoogleSession


def body(event: CalendarEvent) -> dict[str, Any]:
    """The event as the API's ``Event`` resource. Times carry the owner's UTC offset."""
    if event.all_day:
        when = {"start": {"date": event.start.isoformat()}, "end": {"date": event.end.isoformat()}}
    else:
        assert isinstance(event.start, datetime) and isinstance(event.end, datetime)
        when = {
            "start": {"dateTime": event.start.astimezone().isoformat(timespec="seconds")},
            "end": {"dateTime": event.end.astimezone().isoformat(timespec="seconds")},
        }
    out: dict[str, Any] = {"summary": event.title, **when}
    if event.location:
        out["location"] = event.location
    if event.description:
        out["description"] = event.description
    return out


class GoogleCalendarConnector:
    manifest = Manifest("google_calendar", "Google Calendar", auth="oauth")

    def __init__(self) -> None:
        self._google = GoogleSession("Google Calendar")

    async def create_event(self, event: CalendarEvent) -> CreatedEvent:
        def insert() -> CreatedEvent:
            events = self._google.service("calendar", "v3").events()
            created = events.insert(calendarId="primary", body=body(event), sendUpdates="none").execute()
            return CreatedEvent(str(created.get("id", "")), str(created.get("htmlLink", "")))

        return await self._google.call(insert)

