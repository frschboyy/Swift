"""Swift's calendar tool (ADR-011 W1, §13 #5): add an event, after the owner approves it.

| Tool | Side effect |
|---|---|
| ``create_calendar_event(title, start, end?, location?, description?)`` | external: through ``ActionGateway`` and the confirm card |

The event is shown as a ``calendar_event`` artifact, and the confirm card shows it:
what is approved is what is added (its digest is checked again just before). There are
no attendees, so nobody else is invited or emailed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any

from swift.connectors.base import CalendarEvent
from swift.security.gateway import Action
from swift.workflows.scope import RunScope
from swift.workflows.tools import ToolHost, ToolResult, ToolSpec, _obj, revise_text

MAX_TITLE = 200
MAX_TEXT = 2000


def parse_when(text: str) -> datetime | date:
    """``2026-10-30`` (all day) or ``2026-10-30T12:30`` (local time unless an offset is given)."""
    text = text.strip()
    if len(text) == 10:
        return date.fromisoformat(text)
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.astimezone()


def when_text(event: CalendarEvent) -> str:
    """"Thu 30 Oct 2026, 12:30–13:30", or "Thu 30 Oct 2026, all day"."""
    if event.all_day:
        last = event.end - timedelta(days=1)  # the API's end date is exclusive
        first = f"{event.start:%a %d %b %Y}"
        return f"{first}, all day" if last == event.start else f"{first} – {last:%a %d %b %Y}, all day"
    start, end = event.start, event.end
    assert isinstance(start, datetime) and isinstance(end, datetime)
    if end.date() == start.date():
        return f"{start:%a %d %b %Y, %H:%M}–{end:%H:%M}"
    return f"{start:%a %d %b %Y, %H:%M} – {end:%a %d %b %Y, %H:%M}"


def _digest(event: CalendarEvent) -> str:
    payload = json.dumps(
        [event.title, event.start.isoformat(), event.end.isoformat(), event.location, event.description],
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _event(args: dict[str, Any]) -> CalendarEvent | str:
    """The event from the tool's arguments, or what is wrong with them."""
    title = " ".join(str(args.get("title", "")).split())
    if not title:
        return "An event needs a title."
    if len(title) > MAX_TITLE:
        return f"The title is too long (over {MAX_TITLE} characters)."
    try:
        start = parse_when(str(args.get("start", "")))
        end = parse_when(str(args["end"])) if args.get("end") else None
    except ValueError:
        return "start and end must look like 2026-10-30 (all day) or 2026-10-30T12:30."
    if end is None:
        end = start + (timedelta(hours=1) if isinstance(start, datetime) else timedelta(days=1))
    if isinstance(start, datetime) != isinstance(end, datetime):
        return "start and end must both be dates (all day) or both be times."
    if end <= start:  # type: ignore[operator]
        return "The event must end after it starts."
    location = " ".join(str(args.get("location", "")).split())[:MAX_TITLE]
    description = str(args.get("description", "")).strip()[:MAX_TEXT]
    return CalendarEvent(title, start, end, location, description)


async def create_calendar_event(host: ToolHost, scope: RunScope, args: dict[str, Any]) -> ToolResult:
    calendar = host.calendar
    if calendar is None:
        return ToolResult(False, "The calendar isn't connected in Swift (connectors.calendar in config.yaml). "
                          "Nothing was added.")
    event = _event(args)
    if isinstance(event, str):
        return ToolResult(False, event)
    event_id = f"event-{next(scope.ids)}"
    when = when_text(event)
    shown = {"title": event.title, "when": when, "location": event.location, "all_day": event.all_day,
             "start": event.start.isoformat(), "end": event.end.isoformat()}
    await scope.publish(event_id, "calendar_event", "drafting", event.title, shown)
    phases = {"waiting_approval": "confirming", "sending": "sending", "sent": "done", "failed": "failed",
              "rejected": "done"}

    async def on_status(state: str, extra: dict[str, str]) -> None:
        await scope.publish(event_id, "calendar_event", phases[state], event.title,  # type: ignore[arg-type]
                            {**shown, "state": state, **extra})

    async def perform() -> str:
        # Only ever called by the gateway, after approval and the digest check.
        created = await calendar.create_event(event)
        return created.event_id

    action = Action(
        tool="create_calendar_event",
        targets=(),
        title=f"Add to your calendar: {event.title}",
        detail=when + (f" · {event.location}" if event.location else ""),
        artifact_id=event_id,
        digest=lambda: _digest(event),
        perform=perform,
        on_status=on_status,  # type: ignore[arg-type]
        targets_required=False,
    )
    outcome = await host.gateway.execute(scope, action)
    match outcome.status:
        case "done":
            return ToolResult(True, f"Added “{event.title}”, {when}.", {"event_id": outcome.receipt})
        case "rejected":
            return ToolResult(False, f"{outcome.reason}: the event was NOT added. Don't retry or try another way; "
                              "stop and tell the owner it wasn't added.")
        case "revise":
            return ToolResult(False, revise_text(outcome.reason, "create_calendar_event", "added"))
        case "denied":
            return ToolResult(False, f"Not added: {outcome.reason}")
        case _:
            return ToolResult(False, f"Adding it failed: {outcome.reason} Don't retry; tell the owner.")


CALENDAR_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "create_calendar_event",
        "Add an event to the owner's Google Calendar. Swift shows the owner the event on a confirm card and adds "
        "it only if they approve. start/end: '2026-10-30T12:30' (local time) or '2026-10-30' (all day); "
        "end defaults to an hour (a day) later.",
        _obj(
            ["title", "start"],
            title={"type": "string"},
            start={"type": "string"},
            end={"type": "string"},
            location={"type": "string"},
            description={"type": "string"},
        ),
        "external", create_calendar_event,
    ),
)
