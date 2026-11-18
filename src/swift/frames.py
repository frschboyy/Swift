"""Small inbound frames handled outside ``session.py`` (its line ratchet): each handler takes the session and the
frame's data, already checked by ``ipc/protocol.py``. ``Session.handle`` looks here for any type it doesn't match."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from swift import asking, files, timers


async def _snooze(session: Any, data: dict[str, Any]) -> None:
    timers.snooze(session, data["run_id"])  # "+5 min" on a timer's Due card (B14)


async def _asking(session: Any, data: dict[str, Any]) -> None:
    await asking.from_tray(session)  # the tray's "Stop asking about everything" (modes §3): a click, asks less


async def _speak(session: Any, data: dict[str, Any]) -> None:
    """A8, "Speak answers" in the tray: this PC's choice over config.yaml's speech.replies ("default" puts that back).
    Speech turned off in config.yaml (no voice) stays off: ``speech_config`` is None then."""
    chosen = getattr(session, "speech_config", None)
    if chosen is None:
        return
    session.speech_replies = chosen if data["replies"] == "default" else data["replies"]
    logger.info("speak answers", replies=session.speech_replies)


async def _watch(session: Any, data: dict[str, Any]) -> None:
    # The live view opened (a click on Watch) or closed: content-free, for the log.
    logger.info("live view", run_id=data["run_id"], open=data["open"])


HANDLERS: dict[str, Callable[[Any, dict[str, Any]], Awaitable[None]]] = {
    "due.snooze": _snooze,
    "asking": _asking,
    "watch": _watch,
    "speak": _speak,
    "tree.open": files.open_from_tree,  # B13: Open / Show in folder on a file tree's row
}
