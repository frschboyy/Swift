"""Waiting in tests for a request to have gone as far as it can on its own."""

from __future__ import annotations

import asyncio
import time
from typing import Any


async def settled(session: Any, timeout: float = 2.0) -> None:
    """The request in front has ended, or waits for the owner's answer to Swift's own question: it stays
    alive until then (reliability review, item 7)."""
    deadline = time.monotonic() + timeout
    task = session._task
    while True:
        await asyncio.sleep(0)
        q = session.dialogue.pending
        if task is None or task.done() or (q is not None and q.own and q.window is not None):
            return
        if time.monotonic() > deadline:
            raise TimeoutError
        await asyncio.sleep(0.005)
