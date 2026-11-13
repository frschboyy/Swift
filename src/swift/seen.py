"""Whether the owner has seen a request's answer (A4, owner 2026-11-13: a card never presented doesn't run out
because another request took the front). An answer that ended behind the card, or was in front too briefly to be
read, keeps its row until it has been in front ``SEEN_S``; then it ages out as before (``Session._forget_row``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from swift import clock

# An answer counts as seen once it has been in front this long (a card displaced sooner wasn't read).
SEEN_S = 5.0


@dataclass
class Seen:
    front_at: float | None = None  # clock.now() when it last came to the front; None while behind
    read: bool = False


def handover(old: Any, new: Any) -> bool:
    """The front passes from ``old`` (a ``Run`` or None) to ``new``. True if ``old`` ended and its answer was
    read: it needs no row."""
    if old is new:
        return False
    if old is not None:
        if old.ended is not None and old.sight.front_at is not None:
            old.sight.read = old.sight.read or clock.now() - max(old.sight.front_at, old.ended) >= SEEN_S
        old.sight.front_at = None
    new.sight.front_at = clock.now()
    return old is not None and old.ended is not None and not unread(old)


def unread(run: Any) -> bool:
    """It ended with an answer the owner hasn't read (one they stopped is not news to them)."""
    answer = run.answer
    return answer is not None and answer.data.get("status") != "cancelled" and not run.sight.read


def kept(run: Any) -> bool:
    """``unread``, saying so in the log (owner check 256 counts these)."""
    if unread(run):
        logger.info("unseen answer kept behind the card")
        return True
    return False
