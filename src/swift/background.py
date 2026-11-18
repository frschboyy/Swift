"""A problem with a run nobody asked for (ADR-019 §8.4): Failed, with Swift's origin on the card.

Today the only background runs are the scheduler's due items (timers, alarms, reminders); a due item
that can't be shown is what fails. Assumed (halo-b8 README defaults): that counts as "scheduled", the
item's label is the origin's detail, and the cause is a failures-table kind or one fixed sentence.
Never the exception's own words: they can carry a path or a name, and swift.log keeps no content.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from swift.failures import Failure, classify, failure_text
from swift.ipc.protocol import outbound

_FALLBACK = Failure(
    "background_failed", "Swift couldn't show it", "Something Swift runs on its own came due, but Swift couldn't show it.",
    "It will come up again when Swift restarts.",
)


def failure_for(exc: BaseException) -> Failure:
    """A plain-language cause: the failures table's kind if it knows one, else one fixed sentence (no raw text)."""
    known = classify(failure_text(exc), "Swift")
    return _FALLBACK if known.code == "executor_failed" else Failure(
        known.code, known.title, known.message, known.hint, retry=False, severity=known.severity
    )


def guarded(session: Any, on_fire: Any) -> Any:
    """``on_fire`` for the scheduler: a due item that fails shows Failed with Swift's origin, then is raised as before."""

    async def fire(item: Any, missed: bool) -> None:
        try:
            await on_fire(item, missed)
        except Exception as exc:
            failure = failure_for(exc)
            logger.info("background failure shown", code=failure.code, kind=item.kind, error=type(exc).__name__)
            await session._send(outbound("error", **failure.as_message(), agent=None, origin="scheduled", origin_detail=item.title))
            raise

    return fire
