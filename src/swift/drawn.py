"""What the overlay has drawn (reliability review, item 9). Every frame to the overlay goes out
through ``send``, numbered in order; the overlay answers with ``screen``, what it has drawn as of
a frame, after each frame that can change the card. That one acknowledgement replaces the two it
had (``card.seen`` for a confirm card's countdown, ``due.shown`` for a due card) and says what
neither could: that a frame was refused. A due card the overlay didn't draw goes back in line,
where before it was lost until the next overlay.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from loguru import logger

from swift.ipc.protocol import Message


class Drawn:
    def __init__(self, send: Callable[[Message], Awaitable[None]]) -> None:
        self._out = send
        # The last frame sent, and what the overlay last said it drew.
        self.n = 0
        self.stage = "idle"
        self.seen: str | None = None
        # Due cards sent and not yet drawn, by their card's run id: the number of their result frame
        # (0 until it goes out) and their items.
        self.due: dict[str, tuple[int, list[Any]]] = {}

    async def send(self, msg: Message) -> None:
        self.n += 1
        run_id = msg.data.get("run_id")
        if msg.type == "result" and run_id in self.due and not self.due[run_id][0]:
            self.due[run_id] = (self.n, self.due[run_id][1])
        await self._out(replace(msg, n=self.n))

    def ack(self, screen: dict[str, Any]) -> tuple[list[tuple[str, bool]], list[Any], list[Any], bool]:
        """The overlay's ``screen``: the confirm cards now seen or no longer seen, the items of due cards
        drawn, those of due cards it didn't draw (back in line), and whether it just came to rest."""
        seen = screen["confirm"] or None
        changes = [(key, key == seen) for key in (self.seen, seen) if key is not None and self.seen != seen]
        drawn: list[Any] = []
        refused: list[Any] = []
        for run_id, (n, items) in list(self.due.items()):
            if run_id == screen["run_id"] or 0 < n <= screen["n"]:
                del self.due[run_id]
                (drawn if run_id == screen["run_id"] else refused).extend(items)
        if refused:
            logger.info("due card not drawn", items=len(refused), stage=screen["stage"])
        rest = screen["stage"] == "idle" and self.stage != "idle"
        self.seen, self.stage = seen, screen["stage"]
        return changes, drawn, refused, rest

    def gone(self) -> list[Any]:
        """The overlay went: nothing is seen, and due cards sent and not drawn go back in line."""
        sent, self.due, self.seen, self.stage = self.due, {}, None, "idle"
        return [item for _, items in sent.values() for item in items]
