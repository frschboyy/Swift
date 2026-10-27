"""What Swift does as the owner comes and goes (ADR-014 L1).

``Lifecycle`` reacts to ``PresenceMonitor`` changes and to a slow tick:

| When | Then |
|---|---|
| Screen locked, or the PC slept | Hands-free listening off and the open microphone closed (T7). The hotkey still works after unlocking. |
| Back (unlocked, resumed, first input after being away) | Microphone reopened with a fresh device list and the speech model made ready first (loaded, and run once so it is paged back in); a warm Claude Code only a few seconds later, so the two don't compete for the CPU while the owner says "hey Swift" |
| Away for ``release_after_s`` (30 min) | Warm Claude Code released. The speech model too, unless hands-free listening still needs it (away only because the keyboard was idle) |
| Here or idle, every few minutes | A warm Claude Code that exited on its own is replaced, so the first request after a quiet spell isn't slow |
| Away, for any reason (L2) | An open confirm card is held: hidden, its countdown stopped (``Session.hold_cards``). Back: shown again |

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
# After coming back, the warm Claude Code starts this long after the speech model is ready
# (owner checks, 2026-10-27: both at once made the first "hey Swift" take 9 s to transcribe).
SPARE_AFTER_SPEECH_S = 5.0
# ...but never later than this after coming back, whatever the speech model is doing.
SPARE_AT_MOST_S = 60.0
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
        spare_after_speech_s: float = SPARE_AFTER_SPEECH_S,
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
        self.spare_after_speech_s = spare_after_speech_s
        self.clock = clock
        self.monitor: PresenceMonitor | None = None
        self.released = False
        self._last_spare_check = clock()
        self._tasks: set[asyncio.Task[None]] = set()
        self._warming: asyncio.Task[None] | None = None

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
        hold_cards = getattr(self.session, "hold_cards", None)
        if hold_cards is not None:
            await hold_cards(change.new == "away")
        if self.wake_enabled and self.recorder is not None:
            if change.locked_or_asleep:
                await asyncio.to_thread(self.recorder.pause)
            elif change.returned or (self.recorder.paused and listening):
                await asyncio.to_thread(self.recorder.resume)
        if change.returned:
            await self.warm_up()
        await self.announce()

    async def warm_up(self) -> None:
        """The owner is back: get the slow parts ready before they speak, the speech model first.

        Returns at once; the warm Claude Code follows in the background (``_spare_after_speech``).
        """
        self.released = False
        logger.info("warming up: the owner is back")
        if self.transcriber is not None and hasattr(self.transcriber, "start_loading"):
            self.transcriber.start_loading()
        if self._warming is not None:
            self._warming.cancel()
        self._warming = asyncio.get_running_loop().create_task(self._spare_after_speech())

    async def _spare_after_speech(self) -> None:
        t0 = self.clock()
        try:
            async with asyncio.timeout(SPARE_AT_MOST_S):
                await self._speech_ready()
                await asyncio.sleep(self.spare_after_speech_s)
                # Not in the middle of a transcription: the owner may be talking right now.
                while getattr(self.transcriber, "busy", False):
                    await asyncio.sleep(0.2)
        except TimeoutError:
            pass
        except Exception:  # noqa: BLE001 - the speech model's own failure is reported where it's used
            logger.exception("speech model warm-up failed")
        await self._ensure_spare()
        logger.info("warm claude after the speech model", after_s=round(self.clock() - t0, 1))

    async def _speech_ready(self) -> None:
        """The speech model loaded, and run once so its memory is paged back in after a lock or sleep."""
        stt = self.transcriber
        if stt is None:
            return
        if (wait := getattr(stt, "wait_loaded", None)) is not None:
            await wait()
        if (prime := getattr(stt, "prime", None)) is not None:
            await asyncio.to_thread(prime)

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
