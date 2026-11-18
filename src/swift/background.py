"""A problem with a run nobody asked for (ADR-019 §8.4): Failed, with Swift's origin on the card.

Two kinds of run start unasked today: the scheduler's due items (timers, alarms, reminders: this module) and the
weekly improvement pass (``Session.start_own``, source "improve": its failure card carries the same origin, from
``origin_of``). Assumed (halo-b8 README defaults): a due item counts as "scheduled", and its label is the origin's
detail. The cause is one fixed sentence, never the failures table (its causes are about the AI service, wrong for a
timer: review note 5) and never the exception's words (they can carry a path or a name; swift.log keeps no content).

The card is Swift's own: sent outside any request (never the thread of the request in front, review item 2) and
only when a due card could be shown (``Session._due_blocked``), so it never replaces a card or question in front.
With the overlay gone it is dropped (logged): the item was fired but never shown, so it comes back at restart.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from swift.failures import Failure
from swift.ipc.protocol import outbound

FAILED = Failure(
    "background_failed", "Swift couldn't show it", "Something Swift runs on its own came due, but Swift couldn't show it.",
    "It will come up again when Swift restarts.", retry=False,
)
IMPROVE = {"origin": "scheduled", "origin_detail": "Improve speech recognition"}
WAIT_S = 1.0


def origin_of(record: dict[str, Any] | None) -> dict[str, str]:
    """The origin fields of a failure card: Swift's own for the improvement pass, else none (the owner asked)."""
    return IMPROVE if (record or {}).get("source") == "improve" else {}


async def show(session: Any, label: str) -> None:
    """The Failed card for a due item labelled ``label``, once nothing is in front of it."""
    message = outbound("error", **FAILED.as_message(), agent=None, origin="scheduled", origin_detail=label)
    while (blocked := session._due_blocked()) is not None:
        if blocked == "overlay":
            logger.info("background failure dropped", why="overlay")
            return
        await asyncio.sleep(WAIT_S)
    with session._as(session._none):  # Swift's own: no request's thread, never in a request's replay
        await session._send(message)


def guard(session: Any) -> Any:
    """Wire it in (``backend._make_system``): returns the scheduler's ``on_fire``, and covers the later path too
    (a due card shown after the request in front ends: ``_wait_due``, ``ready``, ``screen``)."""
    show_due = session._show_queued_due

    async def show_queued_due() -> None:
        labels = [item.title for item, _, _ in session._due]
        try:
            await show_due()
        except Exception as exc:  # not raised into a task nobody awaits: shown, and logged by class
            await _failed(session, labels[0] if labels else "", exc)

    session._show_queued_due = show_queued_due

    async def fire(item: Any, missed: bool) -> None:
        try:
            await session.notify_due(item, missed)
        except Exception as exc:
            await _failed(session, item.title, exc)
            raise  # the scheduler logs it, as before

    return fire


async def _failed(session: Any, label: str, exc: BaseException) -> None:
    logger.info("background failure shown", code=FAILED.code, error=type(exc).__name__)
    session._background(show(session, label))
