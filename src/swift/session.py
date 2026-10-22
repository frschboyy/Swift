"""Interaction state machine (PLAN.md §1, §3).

The backend is authoritative: the overlay only renders the ``state`` and
content messages sent from here. One interaction runs at a time:

    idle -> listening -> transcribing -> working <-> confirm -> result | error

``result`` and ``error`` count as at rest: a new interaction may start from
them, and the overlay fades the card on its own timer.

Push-to-talk (``ptt`` down/up) records from the microphone, transcribes
locally and hands the transcript to the configured executor. ``debug.run``
plays a scripted interaction (fake mic level, canned transcript) through
``MockExecutor`` instead.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from datetime import datetime
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from swift.audio.recorder import MAX_SECONDS, SAMPLE_RATE, MicError, Recorder
from swift.executors.base import ExecResult, Executor, ExecutorUnavailable
from swift.executors.mock import MockExecutor
from swift.ipc.protocol import Message, outbound
from swift.stt.transcriber import SttUnavailable, Transcriber

Send = Callable[[Message], Awaitable[None]]
OnFinish = Callable[[dict[str, Any]], None]

DEMO_TRANSCRIPTS = {
    "happy": "Find the open to-dos in this project.",
    "confirm": "Add a next steps section to my notes.",
    "error": "Check which packages are out of date.",
    "long": "Run the tests and tell me how it went.",
}

# Hint on the error card when a run fails, by executor name.
ERROR_HINTS = {
    "claude_code": "Try again. If it keeps failing, run `claude` in a terminal to check it's signed in.",
    "mock": "This is a scripted failure from the debug scenarios.",
}
DEFAULT_ERROR_HINT = "Try again. Details are in swift.log."

MIN_SPEECH_S = 0.3


class UserFacingError(Exception):
    """A failure the owner can act on: shown as an error card with a hint."""

    def __init__(self, code: str, message: str, hint: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


class Session:
    def __init__(
        self,
        send: Send,
        executor: Executor,
        *,
        debug_executor: MockExecutor | None = None,
        recorder: Recorder | None = None,
        transcriber: Transcriber | None = None,
        ptt_label: str = "the push-to-talk hotkey",
        demo_speed: float = 1.0,
        max_record_s: float = MAX_SECONDS,
        on_finish: OnFinish | None = None,
    ) -> None:
        self._send = send
        self.executor = executor
        self.debug_executor = debug_executor
        self.recorder = recorder
        self.transcriber = transcriber
        self.ptt_label = ptt_label
        self.demo_speed = demo_speed
        self.max_record_s = max_record_s
        self.on_finish = on_finish
        self._released: asyncio.Event | None = None
        self.state = "idle"
        self._task: asyncio.Task[None] | None = None
        self._active: tuple[Executor, str] | None = None
        self._confirm_ids: set[str] = set()
        self._record: dict[str, Any] | None = None
        self._run_started: float | None = None

    @property
    def busy(self) -> bool:
        """True while an interaction task is running, even before its first state change."""
        return self._task is not None and not self._task.done()

    # ---- inbound -----------------------------------------------------------

    async def handle(self, msg: Message) -> None:
        match msg.type:
            case "debug.run":
                await self._start_demo(msg.data["scenario"])
            case "debug.ask":
                await self._start_text(msg.data["text"])
            case "ready":
                logger.info("overlay ready", startup_ms=msg.data["startup_ms"], backend_ms=msg.data.get("backend_ms"))
            case "cancel":
                await self.cancel()
            case "confirm.reply":
                await self._confirm_reply(msg.data["request_id"], msg.data["decision"] == "approve")
            case "ptt" if msg.data["state"] == "down":
                await self._start_voice()
            case "ptt":
                if self._released is not None:
                    self._released.set()
            case _:
                logger.warning("unhandled message", kind=msg.type)

    async def cancel(self) -> None:
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def close(self) -> None:
        await self.cancel()

    # ---- interaction -------------------------------------------------------

    async def _set_state(self, state: str, **extra: Any) -> None:
        self.state = state
        await self._send(outbound("state", state=state, **extra))

    async def _start_demo(self, scenario: str) -> None:
        if self.debug_executor is None:
            logger.warning("debug.run ignored: debug mode is off")
            return
        if self.busy:
            logger.info("debug.run ignored: busy", state=self.state)
            return
        transcript = DEMO_TRANSCRIPTS[scenario]
        record: dict[str, Any] = {"source": "debug.run", "executor": "mock", "scenario": scenario}

        async def capture(rec: dict[str, Any]) -> str:
            await self._set_state("listening")
            await self._fake_listening(transcript)
            await self._set_state("transcribing")
            t0 = time.monotonic()
            await asyncio.sleep(0.6 * self.demo_speed)
            rec["stt_ms"] = int((time.monotonic() - t0) * 1000)
            return transcript

        async def start(text: str) -> str:
            assert self.debug_executor is not None
            return await self.debug_executor.start(text, scenario=scenario)

        self._task = asyncio.create_task(self._interaction(record, capture, self.debug_executor, start))

    async def _start_text(self, text: str) -> None:
        """Debug mode only: run the configured executor on typed text."""
        if self.debug_executor is None:
            logger.warning("debug.ask ignored: debug mode is off")
            return
        if self.busy or not text.strip():
            return
        record: dict[str, Any] = {"executor": getattr(self.executor, "name", "?"), "source": "debug.ask"}

        async def capture(rec: dict[str, Any]) -> str:
            return text.strip()

        self._task = asyncio.create_task(self._interaction(record, capture, self.executor, self.executor.start))

    async def _start_voice(self) -> None:
        if self.recorder is None or self.transcriber is None:
            logger.warning("ptt ignored: no recorder or transcriber")
            return
        if self.busy:
            logger.info("ptt ignored: busy", state=self.state)
            return
        # Created before the task so a quick release can't be missed.
        self._released = asyncio.Event()
        record: dict[str, Any] = {"source": "voice", "executor": getattr(self.executor, "name", "?")}
        self._task = asyncio.create_task(
            self._interaction(record, self._capture_voice, self.executor, self.executor.start)
        )

    async def _capture_voice(self, record: dict[str, Any]) -> str | None:
        """Record while the hotkey is held, then transcribe. None means 'nothing to do'."""
        assert self.recorder is not None and self.transcriber is not None and self._released is not None
        await self._set_state("listening")
        levels: asyncio.Queue[float] = asyncio.Queue()
        try:
            self.recorder.start(levels.put_nowait)
        except MicError as exc:
            raise UserFacingError("mic_unavailable", str(exc), exc.hint) from None

        async def forward_levels() -> None:
            while True:
                await self._send(outbound("level", rms=round(await levels.get(), 3)))

        forwarder = asyncio.create_task(forward_levels())
        try:
            try:
                await asyncio.wait_for(self._released.wait(), self.max_record_s)
            except TimeoutError:
                logger.info("recording reached the time limit")
        finally:
            forwarder.cancel()
            audio = self.recorder.stop()

        record["audio_s"] = round(len(audio) / SAMPLE_RATE, 2)
        record["first_audio_ms"] = getattr(self.recorder, "first_audio_ms", None)
        if record["audio_s"] < MIN_SPEECH_S:
            record["reason"] = "too_short"
            await self._set_state("idle")
            return None

        await self._set_state("transcribing")
        try:
            result = await self.transcriber.transcribe(audio)
        except SttUnavailable as exc:
            raise UserFacingError("stt_unavailable", str(exc), exc.hint) from None
        record["stt_ms"] = result.stt_ms
        if not result.text:
            raise UserFacingError(
                "no_speech",
                "I didn't catch that.",
                f"Hold {self.ptt_label} while you speak, and release when you're done.",
            )
        return result.text

    async def _interaction(
        self,
        record: dict[str, Any],
        capture: Callable[[dict[str, Any]], Awaitable[str | None]],
        executor: Executor,
        start: Callable[[str], Awaitable[str]],
    ) -> None:
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "id": uuid.uuid4().hex,
            **record,
            "steps": [],
            "approvals": [],
        }
        self._record = record
        started = time.monotonic()
        try:
            transcript = await capture(record)
            if transcript is None:
                record["status"] = "cancelled"
                return
            record["transcript"] = transcript
            await self._send(outbound("transcript", text=transcript, final=True))

            try:
                run_id = await start(transcript)
            except ExecutorUnavailable as exc:
                raise UserFacingError("executor_unavailable", str(exc), exc.hint) from None
            result = await self._run(executor, run_id, record)
            await self._finish(result, record)
        except asyncio.CancelledError:
            record["status"] = "cancelled"
            if self._active is not None:
                active_executor, run_id = self._active
                await active_executor.cancel(run_id)
                await self._send_result(run_id, ExecResult("cancelled", "Cancelled."))
            else:
                await self._set_state("idle")
            raise
        except UserFacingError as exc:
            record["status"] = "error"
            record["error"] = exc.code
            await self._set_state("error")
            await self._send(outbound("error", code=exc.code, message=exc.message, hint=exc.hint))
        except Exception:
            logger.exception("interaction failed")
            record["status"] = "error"
            await self._set_state("error")
            await self._send(
                outbound("error", code="internal", message="Swift hit an internal error.", hint="Details are in swift.log.")
            )
        finally:
            if self._run_started is not None and "run_ms" not in record:
                record["run_ms"] = int((time.monotonic() - self._run_started) * 1000)
            self._run_started = None
            self._active = None
            self._record = None
            self._released = None
            self._confirm_ids.clear()
            record["interaction_ms"] = int((time.monotonic() - started) * 1000)
            record.setdefault("status", "error")
            if self.on_finish is not None:
                self.on_finish(record)

    async def _fake_listening(self, transcript: str) -> None:
        """Synthesize a speech-like mic level and a growing partial transcript."""
        words = transcript.split()
        frames = max(1, int(1.8 * 30 * min(self.demo_speed, 1.0))) if self.demo_speed else 1
        for i in range(frames):
            phase = i / 30
            rms = 0.15 + 0.55 * abs(math.sin(phase * 7.0)) * (0.6 + 0.4 * math.sin(phase * 2.3))
            await self._send(outbound("level", rms=round(max(0.0, min(1.0, rms)), 3)))
            if i % 6 == 5:
                shown = words[: min(len(words), (i + 1) // 6 * max(1, len(words) // 8))]
                await self._send(outbound("transcript", text=" ".join(shown), final=False))
            await asyncio.sleep(self.demo_speed / 30)

    async def _run(self, executor: Executor, run_id: str, record: dict[str, Any]) -> ExecResult:
        self._active = (executor, run_id)
        await self._set_state("working", run_id=run_id)
        started = self._run_started = time.monotonic()
        async for event in executor.events(run_id):
            t_ms = int((time.monotonic() - started) * 1000)
            if event.type == "step":
                record["steps"].append({"t_ms": t_ms, "text": event.text})
                await self._send(outbound("step", run_id=run_id, text=event.text, kind="tool", ts=event.ts))
            elif event.type == "confirm" and event.request_id is not None:
                self._confirm_ids.add(event.request_id)
                record["approvals"].append({"tool": event.tool, "request_id": event.request_id, "asked_ms": t_ms})
                await self._set_state("confirm", run_id=run_id)
                await self._send(
                    outbound(
                        "confirm.request",
                        request_id=event.request_id,
                        run_id=run_id,
                        title=event.text,
                        detail=event.detail or "",
                        tool=event.tool or "",
                    )
                )
        result = await executor.result(run_id)
        record["run_ms"] = int((time.monotonic() - started) * 1000)
        return result

    async def _confirm_reply(self, request_id: str, approve: bool) -> None:
        if self._active is None or request_id not in self._confirm_ids:
            logger.warning("confirm.reply for an unknown request ignored")
            return
        self._confirm_ids.discard(request_id)
        executor, run_id = self._active
        if self._record is not None:
            answered = int((time.monotonic() - self._run_started) * 1000) if self._run_started else None
            for c in self._record["approvals"]:
                if c["request_id"] == request_id:
                    c["decision"] = "approve" if approve else "reject"
                    c["answered_ms"] = answered
        await executor.reply(request_id, approve)
        if approve:
            await self._set_state("working", run_id=run_id)

    async def _finish(self, result: ExecResult, record: dict[str, Any]) -> None:
        record["status"] = result.status
        record.update(result.meta)
        assert self._active is not None
        await self._send_result(self._active[1], result)

    async def _send_result(self, run_id: str, result: ExecResult) -> None:
        if result.status == "error":
            name = getattr(self._active[0], "name", "") if self._active else ""
            await self._set_state("error", run_id=run_id)
            await self._send(
                outbound(
                    "error",
                    code="executor_failed",
                    message=result.summary,
                    hint=ERROR_HINTS.get(name, DEFAULT_ERROR_HINT),
                )
            )
            return
        await self._set_state("result", run_id=run_id)
        await self._send(
            outbound("result", run_id=run_id, status=result.status, summary=result.summary, details=result.details)
        )
