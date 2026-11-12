"""Google Calendar for the calendar-event workflow (ADR-011 W1, §13 #5).

Works on the owner's primary calendar, all under the ``calendar.events`` scope
(verified in spike S4; it covers reading as well as changing events, so nothing new
needs granting):

| Method | API |
|---|---|
| ``list_events`` | ``events.list`` (repeating events expanded, soonest first) |
| ``get_event`` | ``events.get`` |
| ``create_event`` | ``events.insert`` |
| ``update_event`` | ``events.patch`` |
| ``delete_event`` | ``events.delete`` |

A Google Meet link is asked for with ``conferenceData.createRequest`` and
``conferenceDataVersion=1``. Invitations, changes and cancellations are emailed
(``sendUpdates="all"``) only when the event has attendees, who only ever come from
the owner's contacts; otherwise nobody is told (``"none"``). The sign-in is shared with
Gmail (``swift.connectors.google``); a token from before ``calendar.events`` was added
needs signing in again.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from swift.connectors.base import CalendarEvent, ConnectorError, Contact, CreatedEvent, Manifest, StoredEvent
from swift.connectors.google import GoogleSession, http_status, transient


def _when(moment: datetime | date) -> dict[str, str]:
    if isinstance(moment, datetime):
        return {"dateTime": moment.astimezone().isoformat(timespec="seconds")}
    return {"date": moment.isoformat()}


def meet_request(request_id: str | None = None) -> dict[str, Any]:
    """Asks Google to make a Meet link for the event (needs ``conferenceDataVersion=1``)."""
    return {"createRequest": {"requestId": request_id or uuid.uuid4().hex,
                              "conferenceSolutionKey": {"type": "hangoutsMeet"}}}


def body(event: CalendarEvent, request_id: str | None = None) -> dict[str, Any]:
    """The event as the API's ``Event`` resource. Times carry the owner's UTC offset."""
    out: dict[str, Any] = {"summary": event.title, "start": _when(event.start), "end": _when(event.end)}
    if event.location:
        out["location"] = event.location
    if event.description:
        out["description"] = event.description
    if event.attendees:
        out["attendees"] = [{"email": c.email} for c in event.attendees]
    if event.meet:
        out["conferenceData"] = meet_request(request_id)
    return out


def patch(current: dict[str, Any], event: CalendarEvent, request_id: str | None = None) -> dict[str, Any]:
    """What ``events.patch`` gets to make ``current`` (the API's resource) look like ``event``.

    Attendees still on the event keep their entry (and their answer); a Meet link is
    only ever added, never removed."""
    out: dict[str, Any] = {
        "summary": event.title, "start": _when(event.start), "end": _when(event.end),
        "location": event.location, "description": event.description,
    }
    kept = {str(a.get("email", "")).lower(): a for a in current.get("attendees") or []}
    wanted = [kept.get(c.email.lower(), {"email": c.email}) for c in event.attendees]
    # The owner's own entry and rooms aren't shown as attendees, so they're kept as they are.
    wanted += [a for a in kept.values() if a.get("self") or a.get("resource")]
    if [a.get("email") for a in wanted] != [a.get("email") for a in current.get("attendees") or []]:
        out["attendees"] = wanted
    if event.meet and not _meet_link(current):
        out["conferenceData"] = meet_request(request_id)
    return out


def _moment(raw: dict[str, Any]) -> datetime | date:
    if "dateTime" in raw:
        return datetime.fromisoformat(str(raw["dateTime"])).astimezone()
    return date.fromisoformat(str(raw["date"]))


def _meet_link(raw: dict[str, Any]) -> str:
    if raw.get("hangoutLink"):
        return str(raw["hangoutLink"])
    for entry in (raw.get("conferenceData") or {}).get("entryPoints") or []:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return str(entry["uri"])
    return ""


def parse(raw: dict[str, Any]) -> StoredEvent:
    """An ``Event`` resource as Swift's ``StoredEvent``. The owner and rooms aren't attendees."""
    attendees = tuple(
        Contact(str(a.get("displayName") or a["email"]), str(a["email"]), "google_calendar")
        for a in raw.get("attendees") or [] if a.get("email") and not a.get("self") and not a.get("resource")
    )
    meet = _meet_link(raw)
    event = CalendarEvent(
        str(raw.get("summary") or "(no title)"), _moment(raw.get("start") or {}), _moment(raw.get("end") or {}),
        str(raw.get("location") or ""), str(raw.get("description") or ""), attendees, bool(meet),
    )
    return StoredEvent(str(raw.get("id", "")), event, str(raw.get("htmlLink", "")), meet,
                       bool(raw.get("recurringEventId")))


def _notify(*events: CalendarEvent | dict[str, Any]) -> str:
    """Attendees are told ("all") about a change only when there are any."""
    for event in events:
        if (event.attendees if isinstance(event, CalendarEvent) else event.get("attendees")):
            return "all"
    return "none"


class GoogleCalendarConnector:
    manifest = Manifest("google_calendar", "Google Calendar", auth="oauth")

    def __init__(self) -> None:
        self._google = GoogleSession("Google Calendar")

    def _events(self) -> Any:
        return self._google.service("calendar", "v3").events()

    async def list_events(self, start: datetime, end: datetime, query: str = "", limit: int = 20) -> list[StoredEvent]:
        def fetch() -> list[StoredEvent]:
            args: dict[str, Any] = {
                "calendarId": "primary", "timeMin": start.astimezone().isoformat(timespec="seconds"),
                "timeMax": end.astimezone().isoformat(timespec="seconds"), "singleEvents": True,
                "orderBy": "startTime", "maxResults": limit,
            }
            if query:
                args["q"] = query
            items = self._events().list(**args).execute().get("items") or []
            return [parse(i) for i in items if i.get("status") != "cancelled"]

        return await self._google.call(fetch, retry=True)

    def _get(self, event_id: str) -> dict[str, Any] | None:
        try:
            raw = self._events().get(calendarId="primary", eventId=event_id).execute()
        except Exception as exc:  # noqa: BLE001 - "not found" is an answer, anything else is a failure
            if http_status(exc) in (404, 410):
                return None
            raise
        return None if raw.get("status") == "cancelled" else raw

    async def get_event(self, event_id: str) -> StoredEvent | None:
        def fetch() -> StoredEvent | None:
            raw = self._get(event_id)
            return parse(raw) if raw is not None else None

        return await self._google.call(fetch, retry=True)

    async def create_event(self, event: CalendarEvent) -> CreatedEvent:
        # Swift's own id for the event (threat model T10): if the connection drops, Swift asks Google
        # whether it was added, and a second try can't add it twice (Google answers 409 for that id).
        event_id = uuid.uuid4().hex  # base32hex: 0-9 and a-f are allowed

        def insert() -> CreatedEvent:
            try:
                created = self._events().insert(
                    calendarId="primary", body=body(event, request_id=event_id) | {"id": event_id},
                    sendUpdates=_notify(event), conferenceDataVersion=1 if event.meet else 0,
                ).execute()
            except Exception as exc:
                if not (transient(exc) or http_status(exc) == 409):
                    raise
                found = self._get(event_id)  # did the try whose connection dropped add it?
                if found is None:
                    raise  # not added: trying again is safe
                created = found
            return CreatedEvent(str(created.get("id", "")), str(created.get("htmlLink", "")), _meet_link(created))

        return await self._google.call(insert, retry=True, changes=True)

    async def update_event(self, event_id: str, event: CalendarEvent) -> CreatedEvent:
        def update() -> CreatedEvent:
            current = self._get(event_id)
            if current is None:
                raise ConnectorError("That event isn't in the calendar any more.", code="not_found")
            changes = patch(current, event)
            updated = self._events().patch(
                calendarId="primary", eventId=event_id, body=changes, sendUpdates=_notify(event, current),
                conferenceDataVersion=1 if "conferenceData" in changes else 0,
            ).execute()
            return CreatedEvent(str(updated.get("id", "")), str(updated.get("htmlLink", "")), _meet_link(updated))

        # A patch sets the same fields again: safe to repeat after a dropped connection.
        return await self._google.call(update, retry=True, changes=True)

    async def delete_event(self, event_id: str) -> str:
        tried = False

        def delete() -> str:
            nonlocal tried
            current = self._get(event_id)
            if current is None:
                if tried:  # the try whose connection dropped did remove it
                    return event_id
                raise ConnectorError("That event isn't in the calendar any more.", code="not_found")
            tried = True
            self._events().delete(calendarId="primary", eventId=event_id, sendUpdates=_notify(current)).execute()
            return event_id  # Google answers a delete with an empty body; no error means it's gone

        return await self._google.call(delete, retry=True, changes=True)
