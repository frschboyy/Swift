"""Clean-up that a second cancel can't cut short (the owner's run of 2026-11-13, 10:49).

A stopped request tells its agent to stop, then tells the overlay "Cancelled". Stopping a real agent
takes a moment, and a second Stop or Esc in that moment cancelled the task again, inside its own
clean-up: the overlay was never told, and the card stayed "working" on a request that was over.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


async def in_turn(*work: Coroutine[Any, Any, Any]) -> None:
    """One after the other: tell the agent to stop, then tell the overlay."""
    try:
        for step in work:
            await step
    finally:
        for step in work:
            step.close()  # one that never started, because an earlier one raised


async def to_the_end[T](work: Coroutine[Any, Any, T]) -> T:
    """Run ``work`` to its end, however often the caller is cancelled meanwhile. The caller is one that
    is already being cancelled and re-raises when this returns, so nothing is swallowed."""
    # Started here and now, as an inline await would be, not on the loop's next turn.
    task = asyncio.Task(work, loop=asyncio.get_running_loop(), eager_start=True)
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                raise
