"""Timers and due items on screen (Halo B14, 2026-11-18): no card while a timer counts, the overlay shows it on the orb.

``attach`` (each new overlay, from ``Session._resync``) makes every change to the schedule send the overlay the
timers still counting (``timers``); ``snooze`` is "+5 min" on a timer's Due card (``due.snooze``): the same
timer again, five minutes from now. Its label comes from the card's own items, never from the overlay. ``heard``:
"done" or "5 more" said while that card is in front; ``stack_action``: Cancel on the stack's RUNNING row.
"""

from __future__ import annotations

import re
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


def stack_action(session: Any, kind: str, key: str) -> bool:
    """Open or End on a due item, or Cancel on a running timer's row (B14, ``timer:<id>``). True: handled."""
    if kind == "due":
        cleared(session, key)
        return True
    if session.system is not None and key.isdigit():
        session.system.scheduler.remove(int(key))  # on_change sends the overlay the timers left
    return False


# B14: what the owner may say while a timer's Due card is in front. Whole utterance only.
_LEAD = re.compile(r"^\s*(?:(?:hey|ok|okay)\s+)?(?:swift\b[\s,.:!-]*)?", re.I)
_DONE = re.compile(r"(?:ok(?:ay)?[\s,]+)?(?:done|i'?m done|(?:stop|turn off)(?: the)? (?:timer|alarm)|got it|thanks?(?: you)?)", re.I)
_MORE = re.compile(r"(?:(?:give me|another|add)\s+)?(?:5|five) more(?: minutes?| mins?)?(?: please)?|snooze(?: it)?|\+?5 min(?:utes)?", re.I)


def heard(session: Any, text: str) -> tuple[str, None] | None:
    """"done" or "5 more" said while a timer's Due card is in front: what Swift says back (no details), else None."""
    run_id = session._drawn.front
    items = [i for i in _recent.get(run_id or "", []) if i.kind == "timer"]
    if not items:
        return None
    said = _LEAD.sub("", text).strip().rstrip(".!?")
    if _MORE.fullmatch(said):
        snooze(session, run_id)
        return "Okay, 5 more minutes.", None
    if _DONE.fullmatch(said):
        _recent.pop(run_id, None)
        name = f"{items[0].label} timer" if items[0].label else "timer"
        return f"Done: {name[:1].upper()}{name[1:]}.", None  # the same words as the overlay's Edge · Got it
    return None
