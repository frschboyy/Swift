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
import time
from typing import Any

import pytest

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
        self._start, self._wall_start = start, time.time()
        self._selector = _Selector(self, self._selector)  # type: ignore[assignment]

    def time(self) -> float:
        return self._virtual_now

    def advance(self, seconds: float) -> None:
        self._virtual_now += max(0.0, seconds)

    def wall(self) -> float:
        """The wall clock (``time.time()``) as it would read on virtual time: real when the loop began."""
        return self._wall_start + self._virtual_now - self._start


def wall_ms() -> int:
    """``protocol.now_ms()`` on the running loop's clock when it is virtual, else the real one."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    return int((loop.wall() if isinstance(loop, VirtualLoop) else time.time()) * 1000)


# ---- a whole test module on virtual time (pytest-asyncio) ------------------------------------------
# In a module: ``from virtual_clock import VIRTUAL, event_loop_policy, one_clock`` and ``pytestmark = VIRTUAL``.
# A question's window (call_later) then can't run out while the test is starved or busy looking (2026-11-13:
# seam tests and S02 failed under load, passed alone).

# shortcut: pytest-asyncio deprecates this override; its hook would move every async test onto a loop factory.
VIRTUAL = pytest.mark.filterwarnings('ignore:Overriding the "event_loop_policy" fixture:DeprecationWarning')


class _VirtualPolicy(asyncio.DefaultEventLoopPolicy):
    def new_event_loop(self) -> asyncio.AbstractEventLoop:
        return VirtualLoop(time.monotonic())


@pytest.fixture
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    return _VirtualPolicy()


@pytest.fixture(autouse=True)
def one_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Utterances and ``until`` stamp ``time.monotonic()``: the loop's virtual clock here, as in Swift."""
    real = time.monotonic

    def now() -> float:
        try:
            return asyncio.get_running_loop().time()
        except RuntimeError:
            return real()

    monkeypatch.setattr(time, "monotonic", now)
    # Messages are stamped with the wall clock (``protocol.now_ms``), and the seam replay's countdown check
    # compares a stamp with now: on the loop's clock too, or a starved replay counts on one side only
    # (2026-11-14: test_a_card_counts_down_…_seen_away_and_back failed 27 of 30 runs beside 8 CPU burners).
    from swift.ipc import protocol

    monkeypatch.setattr(protocol, "now_ms", wall_ms)
