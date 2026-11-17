"""What "stop" does besides stopping the request in front (live run of 2026-11-18, 02-fixes.md F6/F7).

F6: "stop" said while the last request is still being heard or transcribed is recorded as a request of its
own; it stops that one, which says so ("Stopped “…”"), instead of ending in silence while the request
goes on. Esc there stays a silent discard (test_voice). F7: with nothing running, "stop" again stops
nothing, so the card that said the first one stopped it stays and fades on its own.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any


def line(words: str | None, short: Any) -> str:
    """The Stopped card's words: the request's, if they were heard."""
    return f"Stopped “{short(words)}”." if words else "Stopped. Nothing was sent."


async def at_rest(session: Any, action: str) -> bool:
    """A "stop" (or "cancel") routed as a request of its own. True: handled here."""
    me = session._current()
    starting = [r for r in session._live(besides=me) if r.state in ("listening", "transcribing")]
    if starting:
        for r in starting:
            r.said_stop = True  # it shows its Stopped card as it ends (Session._interaction)
            if r.task is not None:
                r.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await r.task
        target = starting[-1]
    else:
        return False
    me.title = ""  # no row of its own
    await session._bring(target)
    return True
