"""Swift's one clock for timers and deadlines (seams audit 2026-11, P2 and layer C).

``now()`` is the running event loop's clock: in Swift that is ``time.monotonic()`` exactly (asyncio's
``loop.time()``), so ``call_later`` deadlines and the times Swift compares them with are one clock.
Tests run the session on a loop with virtual time (tests/virtual_clock.py): timers fire without
waiting, and a question's window can be run out in microseconds.
"""

from __future__ import annotations

import asyncio
import time


def now() -> float:
    """Monotonic seconds: the running loop's time, or ``time.monotonic()`` off the loop (a thread)."""
    try:
        return asyncio.get_running_loop().time()
    except RuntimeError:
        return time.monotonic()
