"""In-memory email and calendar connectors for tests and debug mode: nothing leaves the machine."""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import replace
from datetime import date, datetime, time

from swift.connectors.base import (
    CalendarEvent, Contact, ConnectorError, CreatedEvent, Manifest, OutgoingEmail, SentMessage, StoredEvent,
)

DEMO_CONTACTS = (
    Contact("Dr Ada Lovelace", "ada.lovelace@example.edu", "fake"),
    Contact("Charles Babbage", "charles@example.com", "fake"),
)


class FakeMailConnector:
    manifest = Manifest("fake_mail", "Demo mail")

    def __init__(
        self,
        contacts: tuple[Contact, ...] = DEMO_CONTACTS,
        *,
        fail: str | None = None,
        no_id: bool = False,
        delay: float = 0.0,
        owner: str = "",
    ) -> None:
        self.contacts = contacts
        self.owner = owner
        # Set to make the next sends fail with this message, or return no message id.
        self.fail = fail
        self.no_id = no_id
        self.delay = delay
        self.sent: list[OutgoingEmail] = []
        self._ids = itertools.count(1)

    async def directory(self, query: str) -> list[Contact]:
        words = query.lower().split()
        return [c for c in self.contacts if words and all(w in c.name.lower() or w in c.email for w in words)]

    async def owner_name(self) -> str:
        return self.owner

    async def send(self, email: OutgoingEmail) -> SentMessage:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectorError(self.fail, "This is the demo connector failing on purpose.")
        self.sent.append(email)
        return SentMessage("" if self.no_id else f"fake-{next(self._ids)}")


def _moment(when: datetime | date) -> datetime:
    """A comparable local time: an all-day event starts at midnight."""
    return when if isinstance(when, datetime) else datetime.combine(when, time()).astimezone()


class FakeCalendarConnector:
    """A calendar in memory. ``events`` seeds it; ``created``/``updated``/``deleted`` record what the gateway did."""

    manifest = Manifest("fake_calendar", "Demo calendar")

    def __init__(
        self, *, fail: str | None = None, no_id: bool = False, events: tuple[StoredEvent, ...] = (),
    ) -> None:
        self.fail = fail
        self.no_id = no_id
        self.store: dict[str, StoredEvent] = {e.event_id: e for e in events}
        self.created: list[CalendarEvent] = []
        self.updated: list[tuple[str, CalendarEvent]] = []
        self.deleted: list[str] = []
        self._ids = itertools.count(1)

    def _check(self) -> None:
        if self.fail:
            raise ConnectorError(self.fail, "This is the demo calendar failing on purpose.")

    async def list_events(self, start: datetime, end: datetime, query: str = "", limit: int = 20) -> list[StoredEvent]:
        self._check()
        words = query.lower().split()
        found = [
            e for e in self.store.values()
            if _moment(e.event.start) < end and _moment(e.event.end) > start
            and all(w in f"{e.event.title} {e.event.location} {e.event.description}".lower() for w in words)
        ]
        return sorted(found, key=lambda e: _moment(e.event.start))[:limit]

    async def get_event(self, event_id: str) -> StoredEvent | None:
        self._check()
        return self.store.get(event_id)

    def _meet(self, event_id: str, event: CalendarEvent) -> str:
        return f"https://meet.google.com/fake-{event_id}" if event.meet else ""

    async def create_event(self, event: CalendarEvent) -> CreatedEvent:
        self._check()
        self.created.append(event)
        if self.no_id:
            return CreatedEvent("")
        event_id = f"fake-event-{next(self._ids)}"
        meet = self._meet(event_id, event)
        self.store[event_id] = StoredEvent(event_id, event, f"https://calendar.example/{event_id}", meet)
        return CreatedEvent(event_id, meet_link=meet)

    async def update_event(self, event_id: str, event: CalendarEvent) -> CreatedEvent:
        self._check()
        stored = self.store.get(event_id)
        if stored is None:
            raise ConnectorError("That event isn't in the calendar any more.", code="not_found")
        self.updated.append((event_id, event))
        if self.no_id:
            return CreatedEvent("")
        meet = stored.meet_link or self._meet(event_id, event)
        self.store[event_id] = replace(stored, event=replace(event, meet=bool(meet)), meet_link=meet)
        return CreatedEvent(event_id, stored.link, meet)

    async def delete_event(self, event_id: str) -> str:
        self._check()
        if self.store.pop(event_id, None) is None:
            raise ConnectorError("That event isn't in the calendar any more.", code="not_found")
        self.deleted.append(event_id)
        return "" if self.no_id else event_id
