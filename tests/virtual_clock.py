"""An event loop with virtual time (seams audit 2026-11, layer C).

``loop.time()`` starts at ``start`` and moves only when the loop would otherwise wait: when nothing is
ready and a timer is due in ``t`` seconds, time jumps ``t`` at once. So ``call_later(25, …)`` fires
without 25 real seconds passing, in order, and ``swift.clock.now()`` (the running loop's time) moves
with it. Something real (a thread finishing, a socket) still wakes the loop as usual.

No dependency: a ``SelectorEventLoop`` whose selector never sleeps while a timer is pending.
"""

from __future__ import annotations

import asyncio
import selectors
from typing import Any

# With nothing scheduled, how long to wait for something real before calling the loop stuck.
STALL_S = 5.0


class _Selector:
    def __init__(self, loop: VirtualLoop, real: selectors.BaseSelector) -> None:
        self._loop, self._real = loop, real

    def select(self, timeout: float | None = None) -> list[Any]:
        ready = self._real.select(0)
        if ready or timeout == 0:
            return ready
        if timeout is None:
            # No timer: only something real can wake the loop (a thread's result, a socket).
            ready = self._real.select(STALL_S)
            if not ready:
                raise RuntimeError(f"virtual loop stalled: nothing scheduled and nothing real for {STALL_S} s")
            return ready
        self._loop.advance(timeout)
        return []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class VirtualLoop(asyncio.SelectorEventLoop):
    def __init__(self, start: float = 10_000.0) -> None:
        super().__init__()
        self._virtual_now = start
        self._selector = _Selector(self, self._selector)  # type: ignore[assignment]

    def time(self) -> float:
        return self._virtual_now

    def advance(self, seconds: float) -> None:
        self._virtual_now += max(0.0, seconds)
