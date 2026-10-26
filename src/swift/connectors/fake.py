"""In-memory email and calendar connectors for tests and debug mode: nothing leaves the machine."""

from __future__ import annotations

import asyncio
import itertools

from swift.connectors.base import (
    CalendarEvent, Contact, ConnectorError, CreatedEvent, Manifest, OutgoingEmail, SentMessage,
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
    ) -> None:
        self.contacts = contacts
        # Set to make the next sends fail with this message, or return no message id.
        self.fail = fail
        self.no_id = no_id
        self.delay = delay
        self.sent: list[OutgoingEmail] = []
        self._ids = itertools.count(1)

    async def directory(self, query: str) -> list[Contact]:
        words = query.lower().split()
        return [c for c in self.contacts if words and all(w in c.name.lower() or w in c.email for w in words)]

    async def send(self, email: OutgoingEmail) -> SentMessage:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectorError(self.fail, "This is the demo connector failing on purpose.")
        self.sent.append(email)
        return SentMessage("" if self.no_id else f"fake-{next(self._ids)}")


class FakeCalendarConnector:
    manifest = Manifest("fake_calendar", "Demo calendar")

    def __init__(self, *, fail: str | None = None, no_id: bool = False) -> None:
        self.fail = fail
        self.no_id = no_id
        self.created: list[CalendarEvent] = []
        self._ids = itertools.count(1)

    async def create_event(self, event: CalendarEvent) -> CreatedEvent:
        if self.fail:
            raise ConnectorError(self.fail, "This is the demo calendar failing on purpose.")
        self.created.append(event)
        return CreatedEvent("" if self.no_id else f"fake-event-{next(self._ids)}")
