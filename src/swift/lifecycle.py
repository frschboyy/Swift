"""What Swift does as the owner comes and goes (ADR-014 L1).

``Lifecycle`` reacts to ``PresenceMonitor`` changes and to a slow tick:

| When | Then |
|---|---|
| Screen locked, or the PC slept | Hands-free listening off and the open microphone closed (T7). The hotkey still works after unlocking. |
| Back (unlocked, resumed, first input after being away) | The speech model made ready (loaded, and run once so it is paged back in) while the microphone is reopened with a fresh device list; a warm Claude Code only a few seconds later, so the two don't compete for the CPU while the owner says "hey Swift". "listening again" logs how long after coming back both were ready |
| Away for ``release_after_s`` (30 min) | Warm Claude Code released. The speech model too, unless hands-free listening still needs it (away only because the keyboard was idle) |
| Here or idle, every few minutes | A warm Claude Code that exited on its own is replaced, so the first request after a quiet spell isn't slow |
| Away, for any reason (L2) | An open confirm card is held: hidden, its countdown stopped (``Session.hold_cards``). Back: shown again |

Each change is also announced to the overlay (``presence``) for the tray tooltip and the capsule.

Paused by the owner (ADR-017, the tray's "Pause listening"): hands-free listening off and the open
microphone closed, as when the screen locks, until they resume. ``presence`` says ``paused``, and
the capsule shows "Not listening · Mic off" for as long as it lasts. Push-to-talk still works: each
press is the owner's own act.

Changes are handled as they come, but the microphone always follows the newest one: a lock
handled late (the audio thread busy) never closes it after the unlock (``MicRecorder.pause``).
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
        # Coming back: (reason, clock() then, what is ready so far: "mic" / "speech" -> seconds after).
        self._back: tuple[str, float, dict[str, float]] | None = None
        # The owner paused listening from the tray (ADR-017).
        self.paused = False

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
        if change.returned:
            # The speech model first: it is the slow part (paged out while locked), and the
            # microphone reopening behind a busy audio thread must not hold it up.
            self._back = (change.reason, self.clock(), {})
            mark = getattr(self.session, "mark_return", None)
            if mark is not None:
                mark(change.reason)
            await self.warm_up()
        elif change.locked_or_asleep:
            self._back = None
        if self.wake_enabled and self.recorder is not None:
            if change.locked_or_asleep:
                await asyncio.to_thread(self.recorder.pause)
            elif self.paused:
                self._ready("mic")  # paused by the owner: the microphone stays closed until they resume
            elif change.returned or (self.recorder.paused and listening):
                await asyncio.to_thread(self.recorder.resume)
                self._ready("mic")
        elif change.returned:
            self._ready("mic")
        await self.announce()

    def _ready(self, part: str) -> None:
        """One part of listening again is ready; when both are, log how long it took since coming back."""
        back = self._back
        if back is None:
            return
        reason, t0, parts = back
        parts.setdefault(part, self.clock() - t0)
        if len(parts) == 2:
            self._back = None
            logger.info(
                "listening again", reason=reason, ms=int(max(parts.values()) * 1000),
                mic_ms=int(parts["mic"] * 1000), speech_ms=int(parts["speech"] * 1000),
            )

    async def set_listening(self, on: bool) -> None:
        """The tray's Pause listening (``on`` False) or Resume: the open microphone closes or reopens."""
        if self.paused == (not on):
            await self.announce()
            return
        self.paused = not on
        self.session.listening_paused = self.wake_enabled and not self.listening
        logger.info("listening paused" if self.paused else "listening resumed")
        if self.wake_enabled and self.recorder is not None:
            if self.paused:
                await asyncio.to_thread(self.recorder.pause)
            elif self.listening and self.recorder.paused:
                await asyncio.to_thread(self.recorder.resume)
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
                self._ready("speech")
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
        return (self.monitor is None or self.monitor.listening_allowed) and not self.paused

    async def announce(self) -> None:
        monitor = self.monitor
        await self.send(
            outbound(
                "presence",
                state=monitor.state if monitor else "here",
                reason=monitor.reason if monitor else "start",
                listening=self.wake_enabled and self.listening,
                wake=self.wake_enabled,
                paused=self.paused,
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
