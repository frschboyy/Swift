"""The card's mic button, and Space on a card that has the keyboard (owner items 4 and 15, 2026-11-18; Space decided
2026-11-23): one capture that ends by itself when the owner stops talking, in the context of the card on screen.

It is a follow-up (source ``followup``): it continues the card's conversation, and its words have the authority of a
hands-free reply, never of a gesture. The click starts listening; it doesn't vouch for the words that follow, the way
holding the hotkey through them does (foundation decision 3). So it never starts while something waits for an answer
(a confirm card, Swift's question) or while a request is going: there, the hotkey answers.
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

from loguru import logger

from swift.endpoint import AutoEnd


async def listen_from_card(session: Any, data: dict[str, Any]) -> None:
    if session.recorder is None or session.transcriber is None:
        reason = "no_mic"
    elif session._deaf():
        reason = "not_listening"  # paused, locked or away: nothing hands-free, and this is no gesture
    elif session._front_busy() or session._capturing() or session._open_confirm() is not None or (
        session._listening_for() is not None
    ):
        reason = "busy"
    else:
        reason = None
    if reason is not None:
        logger.info("card mic ignored", reason=reason)
        return
    session._owner_here()
    session.speaker.stop()
    session._released = asyncio.Event()
    await session._signal_heard("ptt")
    auto = AutoEnd(lead_s=0.0, end_silence_s=session.wake_end_silence_s, start_timeout_s=session.wake_start_timeout_s)
    record = {"source": "followup", "executor": getattr(session.executor, "name", "?"), "card_mic": True}
    session._launch(record, partial(session._capture_voice, auto=auto), session.executor, session.executor.start)


def hearing(session: Any) -> bool:
    """At rest, wake listening is collecting speech now: the orb follows the owner's voice (item 14), so they can see
    Swift hears them before it knows what they said. Never while locked, away or paused, nor during a capture (that
    sends its own level)."""
    return session.in_speech() and not session._capturing() and not session._deaf()
