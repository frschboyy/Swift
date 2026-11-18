"""Timers and due items on screen (Halo B14, 2026-11-18): no card while a timer counts, the overlay shows it on the orb.

``attach`` (each new overlay, from ``Session._resync``) makes every change to the schedule send the overlay the
timers still counting (``timers``); ``snooze`` is "+5 min" on a timer's Due card (``due.snooze``): the same
timer again, five minutes from now. Its label comes from the card's own items, never from the overlay.
"""

from __future__ import annotations

from typing import Any

from swift.ipc.protocol import outbound

SNOOZE_S = 5 * 60
# Due cards drawn recently, by their card's run id: what "+5 min" sets again.
_recent: dict[str, list[Any]] = {}


def rows(scheduler: Any) -> list[dict[str, Any]]:
    """The timers still counting, soonest first: what the orb's ring and pill show."""
    return [{"id": i.id, "title": i.title, "due_ms": int(i.due * 1000), "set_ms": int((i.created or i.due) * 1000)}
            for i in scheduler.pending("timer")]


def attach(session: Any) -> None:
    """Send the timers now, and again whenever the schedule changes."""
    if session.system is None:
        return
    scheduler = session.system.scheduler

    def changed() -> None:
        session._background(session._raw_send(outbound("timers", items=rows(scheduler))))

    scheduler.on_change = changed
    changed()


def remember(run_id: str, items: list[Any]) -> None:
    """A Due card for ``items`` was sent: "+5 min" on it sets its timers again."""
    _recent[run_id] = items
    while len(_recent) > 8:
        _recent.pop(next(iter(_recent)))


def snooze(session: Any, run_id: str) -> bool:
    """"+5 min" on a Due card: each timer it showed counts again from now. False: nothing to set again."""
    items = [i for i in _recent.pop(run_id, []) if i.kind == "timer"]
    if session.system is None or not items:
        return False
    for item in items:
        session.system.scheduler.add("timer", session.system.scheduler.clock() + SNOOZE_S, item.label)
    return True


def cleared(session: Any, key: str) -> None:
    """A due item cleared from the stack: the owner has seen it, so it won't come up as a card too."""
    kept = [entry for entry in session._due if str(entry[0].id) != key]
    for item, _, _ in session._due:
        if str(item.id) == key and session.system is not None:
            session.system.scheduler.shown(item.id)
    session._due = kept
