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

With several requests at once (ADR-013 §5.2) only one card is on screen; the others wait in
line. ``set_queued`` stops a waiting card's countdown the same way, so each card's time starts
when it is shown.

Seen (ADR-015 §4.2): with ``require_seen``, a card counts down only once the overlay says it
has drawn it (``set_seen``, from the overlay's ``screen`` acknowledgement), and stops again when the overlay
hides it. A card the overlay never draws waits like a held card instead of running out unseen.

Expiry (ADR-017, the Capsule redesign): with ``on_expire`` set, a countdown that runs out doesn't
end the wait. ``on_expire(key)`` puts the card aside (the session moves it to the waiting stack)
and returns True; the card then waits like a held one, with its whole countdown again for when it
is opened. It is never approved or rejected for the owner. False (or no ``on_expire``): it times
out as before.
"""

from __future__ import annotations

import asyncio

from swift.clock import now as clock_now
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

HOLD_S = 12 * 3600
# A card set aside into the stack while the owner is here (it ran out, or "Later"): it waits this
# long there, then gives up like a timeout, its conversation parked (2026-11-05: cards for ever).
ASIDE_S = 30 * 60
RETURN_S = 60.0


@dataclass
class _Wait:
    # Seconds of countdown left; while running, counted from ``deadline`` instead.
    left: float
    # When the countdown runs out (clock time); None while held.
    deadline: float | None
    # When the card was put aside (clock time); None while running.
    held_at: float | None
    # The whole countdown, given back when an expired card is set aside (ADR-017).
    full: float = 0.0
    # Set aside into the stack (expired, or "Later"): it waits ``aside_s`` there, not ``hold_s``.
    aside: bool = False


class Attention:
    def __init__(
        self,
        *,
        hold_s: float = HOLD_S,
        aside_s: float = ASIDE_S,
        return_s: float = RETURN_S,
        clock: Callable[[], float] = clock_now,
        require_seen: bool = False,
    ) -> None:
        self.hold_s = hold_s
        self.aside_s = aside_s
        self.require_seen = require_seen
        self.return_s = return_s
        self.clock = clock
        self.held = False
        self._waits: dict[str, _Wait] = {}
        # Cards waiting behind the one on screen: their countdown hasn't started.
        self._queued: set[str] = set()
        # Cards the overlay says are drawn and visible (only matters with ``require_seen``).
        self._seen: set[str] = set()
        self._changed = asyncio.Event()
        # ADR-017: a countdown that ran out; True when the card was set aside instead of timing out.
        self.on_expire: Callable[[str], bool] | None = None

    def set_held(self, held: bool) -> list[str]:
        """The owner left (True) or came back (False). Returns the cards this changed."""
        if held == self.held:
            return []
        self.held = held
        now = self.clock()
        for key, w in self._waits.items():
            if held:
                self._freeze(w, now)
            else:
                w.left = max(w.left, self.return_s)
                if self._runs(key):
                    w.deadline, w.held_at = now + w.left, None
                elif w.aside:
                    w.held_at = now  # back: its time in the stack starts again
        self.check()
        return list(self._waits)

    def set_queued(self, key: str, queued: bool) -> None:
        """A card waits behind another (True), or is now the one on screen (False): its countdown starts."""
        if queued == (key in self._queued):
            return
        now = self.clock()
        w = self._waits.get(key)
        if queued:
            self._queued.add(key)
            if w is not None:
                self._freeze(w, now)
        else:
            self._queued.discard(key)
            if w is not None and self._runs(key):
                w.deadline, w.held_at = now + w.left, None
        self.check()

    def set_seen(self, key: str, seen: bool) -> None:
        """The overlay drew the card and it is visible (True), or it hid it (False)."""
        if seen == (key in self._seen):
            return
        now = self.clock()
        if seen:
            self._seen.add(key)
        else:
            self._seen.discard(key)
        w = self._waits.get(key)
        if w is not None:
            if not seen:
                self._freeze(w, now)
            elif self._runs(key):
                w.deadline, w.held_at = now + w.left, None
        self.check()

    def put_aside(self, key: str) -> None:
        """The card is set aside into the stack: it waits there ``aside_s`` (while the owner is here)."""
        w = self._waits.get(key)
        if w is not None:
            w.aside = True
            self._freeze(w, self.clock())
            self.check()

    def _runs(self, key: str) -> bool:
        """Whether the card's countdown should run now: on screen, seen, and the owner around."""
        return not self.held and key not in self._queued and (not self.require_seen or key in self._seen)

    @staticmethod
    def _freeze(w: _Wait, now: float) -> None:
        if w.deadline is not None:
            w.left = max(0.0, w.deadline - now)
            w.deadline, w.held_at = None, now

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
        frozen = not self._runs(key)
        w = _Wait(timeout_s, None, now, timeout_s) if frozen else _Wait(timeout_s, now + timeout_s, None, timeout_s)
        self._waits[key] = w
        try:
            while True:
                now = self.clock()
                limit = self.aside_s if w.aside and not self.held else self.hold_s
                budget = (w.deadline - now) if w.deadline is not None else (w.held_at or now) + limit - now
                if budget <= 0:
                    if w.deadline is not None and self.on_expire is not None and self.on_expire(key):
                        # Set aside, not ended: it waits in the stack, its whole time back for when it's opened.
                        w.left, w.deadline, w.held_at, w.aside = w.full, None, now, True
                        continue
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
            self._queued.discard(key)
            self._seen.discard(key)


async def wait_answer(attention: Attention | None, key: str, future: asyncio.Future[Any], timeout_s: float) -> Any:
    """Wait for a card's answer: through ``attention`` when there is one, else a plain timeout."""
    if attention is None:
        return await asyncio.wait_for(future, timeout_s)
    return await attention.wait(key, future, timeout_s)
