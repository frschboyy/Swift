"""Whether the owner is around to answer a card (ADR-014 §4).

A confirm card used to stop its request after ``confirm_timeout_s`` (120 s) without an answer,
so a card left while the owner stepped away was simply lost. ``Attention.wait`` runs that
countdown only while the owner is here or idle:

- **Away** (locked, asleep, or no input for a while): the card is held. Its countdown stops,
  and the overlay hides it.
- **Back:** the countdown goes on from where it stopped, with at least ``return_s`` left, so
  the owner has time to read the card again.
- **Held for ``hold_s``** (12 h): it gives up like a timeout. The session parks the
  conversation (swift/parked.py), so it can still be picked up later.

Swift's own cards (the gateway's) and Claude Code's cards both wait through here; a provider
without it keeps the plain timeout.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

HOLD_S = 12 * 3600
RETURN_S = 60.0


@dataclass
class _Wait:
    # Seconds of countdown left; while running, counted from ``deadline`` instead.
    left: float
    # When the countdown runs out (clock time); None while held.
    deadline: float | None
    # When the card was put aside (clock time); None while running.
    held_at: float | None


class Attention:
    def __init__(
        self,
        *,
        hold_s: float = HOLD_S,
        return_s: float = RETURN_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.hold_s = hold_s
        self.return_s = return_s
        self.clock = clock
        self.held = False
        self._waits: dict[str, _Wait] = {}
        self._changed = asyncio.Event()

    def set_held(self, held: bool) -> list[str]:
        """The owner left (True) or came back (False). Returns the cards this changed."""
        if held == self.held:
            return []
        self.held = held
        now = self.clock()
        for w in self._waits.values():
            if held:
                w.left = max(0.0, (w.deadline or now) - now)
                w.deadline, w.held_at = None, now
            else:
                w.left = max(w.left, self.return_s)
                w.deadline, w.held_at = now + w.left, None
        self.check()
        return list(self._waits)

    def left(self, key: str) -> float | None:
        """Seconds of countdown the card has left (frozen while held); None: not waiting."""
        w = self._waits.get(key)
        if w is None:
            return None
        return w.left if w.deadline is None else max(0.0, w.deadline - self.clock())

    def check(self) -> None:
        """Wake the waits so they look at the clock again (a state change, or a slow tick)."""
        self._changed.set()
        self._changed = asyncio.Event()

    async def wait(self, key: str, future: asyncio.Future[Any], timeout_s: float) -> Any:
        """``future``'s result. TimeoutError when the countdown runs out, or the card was held too long."""
        now = self.clock()
        w = _Wait(timeout_s, None, now) if self.held else _Wait(timeout_s, now + timeout_s, None)
        self._waits[key] = w
        try:
            while True:
                now = self.clock()
                budget = (w.deadline - now) if w.deadline is not None else (w.held_at or now) + self.hold_s - now
                if budget <= 0:
                    raise TimeoutError
                changed = asyncio.ensure_future(self._changed.wait())
                try:
                    await asyncio.wait({future, changed}, timeout=budget, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    changed.cancel()
                if future.done():
                    return future.result()
        finally:
            self._waits.pop(key, None)


async def wait_answer(attention: Attention | None, key: str, future: asyncio.Future[Any], timeout_s: float) -> Any:
    """Wait for a card's answer: through ``attention`` when there is one, else a plain timeout."""
    if attention is None:
        return await asyncio.wait_for(future, timeout_s)
    return await attention.wait(key, future, timeout_s)
