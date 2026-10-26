"""What Swift does as the owner comes and goes (ADR-014 L1).

``Lifecycle`` reacts to ``PresenceMonitor`` changes and to a slow tick:

| When | Then |
|---|---|
| Screen locked, or the PC slept | Hands-free listening off and the open microphone closed (T7). The hotkey still works after unlocking. |
| Back (unlocked, resumed, first input after being away) | Microphone reopened with a fresh device list, speech model and warm Claude Code made ready, before the owner speaks |
| Away for ``release_after_s`` (30 min) | Warm Claude Code released. The speech model too, unless hands-free listening still needs it (away only because the keyboard was idle) |
| Here or idle, every few minutes | A warm Claude Code that exited on its own is replaced, so the first request after a quiet spell isn't slow |

Each change is also announced to the overlay (``presence``) for the tray tooltip.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from swift.ipc.protocol import Message, outbound
from swift.presence import Change, PresenceMonitor

RELEASE_AFTER_S = 30 * 60
SPARE_CHECK_S = 5 * 60
TICK_S = 60.0


class Lifecycle:
    def __init__(
        self,
        session: Any,
        send: Callable[[Message], Awaitable[None]],
        *,
        recorder: Any = None,
        transcriber: Any = None,
        executor: Any = None,
        wake_enabled: bool = False,
        release_after_s: float = RELEASE_AFTER_S,
        spare_check_s: float = SPARE_CHECK_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session
        self.send = send
        self.recorder = recorder
        self.transcriber = transcriber
        self.executor = executor
        self.wake_enabled = wake_enabled
        self.release_after_s = release_after_s
        self.spare_check_s = spare_check_s
        self.clock = clock
        self.monitor: PresenceMonitor | None = None
        self.released = False
        self._last_spare_check = clock()
        self._tasks: set[asyncio.Task[None]] = set()

    def attach(self, monitor: PresenceMonitor) -> None:
        self.monitor = monitor

    # ---- presence changes ---------------------------------------------------------------

    def on_change(self, change: Change) -> None:
        """From the monitor (on the event loop): handle it without blocking the poll."""
        task = asyncio.get_running_loop().create_task(self.handle(change))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def handle(self, change: Change) -> None:
        listening = self.listening
        self.session.listening_paused = self.wake_enabled and not listening
        if self.wake_enabled and self.recorder is not None:
            if change.locked_or_asleep:
                await asyncio.to_thread(self.recorder.pause)
            elif change.returned or (self.recorder.paused and listening):
                await asyncio.to_thread(self.recorder.resume)
        if change.returned:
            await self.warm_up()
        await self.announce()

    async def warm_up(self) -> None:
        """The owner is back: get the slow parts ready before they speak."""
        self.released = False
        if self.transcriber is not None and hasattr(self.transcriber, "start_loading"):
            self.transcriber.start_loading()
        await self._ensure_spare()
        logger.info("warming up: the owner is back")

    # ---- the slow tick ----------------------------------------------------------------

    async def tick(self) -> None:
        monitor = self.monitor
        if monitor is None:
            return
        if monitor.state == "away":
            if not self.released and monitor.away_for() >= self.release_after_s:
                await self.release()
        elif self.clock() - self._last_spare_check >= self.spare_check_s:
            self._last_spare_check = self.clock()
            await self._ensure_spare()

    async def release(self) -> None:
        """Away for a while: free the heavy parts. Re-warmed on return (``warm_up``)."""
        self.released = True
        release_spare = getattr(self.executor, "release_spare", None)
        if release_spare is not None:
            await release_spare()
        # Hands-free listening (away only because the keyboard is idle) still needs the speech model.
        if self.transcriber is not None and hasattr(self.transcriber, "release") and not (self.wake_enabled and self.listening):
            await asyncio.to_thread(self.transcriber.release)
        logger.info("released memory while away")

    async def _ensure_spare(self) -> None:
        ensure = getattr(self.executor, "ensure_spare", None)
        if ensure is not None:
            await ensure()

    # ---- telling the overlay ---------------------------------------------------------------

    @property
    def listening(self) -> bool:
        return self.monitor is None or self.monitor.listening_allowed

    async def announce(self) -> None:
        monitor = self.monitor
        await self.send(
            outbound(
                "presence",
                state=monitor.state if monitor else "here",
                reason=monitor.reason if monitor else "start",
                listening=self.wake_enabled and self.listening,
                wake=self.wake_enabled,
            )
        )

    async def run(self, every_s: float = TICK_S) -> None:
        while True:
            await asyncio.sleep(every_s)
            try:
                await self.tick()
                await self.announce()
            except Exception:  # noqa: BLE001 - the lifecycle must outlive any one failure
                logger.exception("lifecycle tick failed")
