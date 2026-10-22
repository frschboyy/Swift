"""Interaction state machine (PLAN.md §1, §3).

The backend is authoritative: the overlay only renders the ``state`` and
content messages sent from here. One interaction runs at a time:

    idle -> listening -> transcribing -> working <-> confirm -> result | error

``result`` and ``error`` count as at rest: a new interaction may start from
them, and the overlay fades the card on its own timer.

Milestone 1 has no microphone: ``debug.run`` plays a scripted interaction
(fake mic level, canned transcript) through ``MockExecutor``.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from swift.executors.base import ExecResult, Executor
from swift.executors.mock import MockExecutor
from swift.ipc.protocol import Message, outbound

Send = Callable[[Message], Awaitable[None]]
OnFinish = Callable[[dict[str, Any]], None]

DEMO_TRANSCRIPTS = {
    "happy": "Find the open to-dos in this project.",
    "confirm": "Add a next steps section to my notes.",
    "error": "Check which packages are out of date.",
    "long": "Run the tests and tell me how it went.",
}

ERROR_HINTS = {
    "error": "Check that Claude Code is installed and signed in, then try again.",
}


class Session:
    def __init__(
        self,
        send: Send,
        executor: Executor,
        *,
        debug_executor: MockExecutor | None = None,
        demo_speed: float = 1.0,
        on_finish: OnFinish | None = None,
    ) -> None:
        self._send = send
        self.executor = executor
        self.debug_executor = debug_executor
        self.demo_speed = demo_speed
        self.on_finish = on_finish
        self.state = "idle"
        self._task: asyncio.Task[None] | None = None
        self._active: tuple[Executor, str] | None = None
        self._confirm_ids: set[str] = set()
        self._record: dict[str, Any] | None = None

    @property
    def busy(self) -> bool:
        """True while an interaction task is running, even before its first state change."""
        return self._task is not None and not self._task.done()

    # ---- inbound -----------------------------------------------------------

    async def handle(self, msg: Message) -> None:
        match msg.type:
            case "debug.run":
                await self._start_demo(msg.data["scenario"])
            case "cancel":
                await self.cancel()
            case "confirm.reply":
                await self._confirm_reply(msg.data["request_id"], msg.data["decision"] == "approve")
            case "ptt":
                # Push-to-talk arrives in Milestone 2.
                logger.debug("ptt ignored: no recorder", state=msg.data["state"])
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
        self._task = asyncio.create_task(self._demo(scenario))

    async def _demo(self, scenario: str) -> None:
        record: dict[str, Any] = {"executor": "mock", "scenario": scenario, "steps": [], "confirmations": []}
        self._record = record
        started = time.monotonic()
        try:
            transcript = DEMO_TRANSCRIPTS[scenario]
            await self._set_state("listening")
            await self._fake_listening(transcript)

            await self._set_state("transcribing")
            t0 = time.monotonic()
            await asyncio.sleep(0.6 * self.demo_speed)
            record["transcript"] = transcript
            record["stt_ms"] = int((time.monotonic() - t0) * 1000)
            await self._send(outbound("transcript", text=transcript, final=True))

            assert self.debug_executor is not None
            run_id = await self.debug_executor.start(transcript, scenario=scenario)
            result = await self._run(self.debug_executor, run_id, record)
            await self._finish(result, record)
        except asyncio.CancelledError:
            record["status"] = "cancelled"
            if self._active is not None:
                executor, run_id = self._active
                await executor.cancel(run_id)
                await self._send_result(run_id, ExecResult("cancelled", "Cancelled."))
            else:
                await self._set_state("idle")
            raise
        except Exception:
            logger.exception("interaction failed")
            record["status"] = "error"
            await self._set_state("error")
            await self._send(
                outbound("error", code="internal", message="Swift hit an internal error.", hint="Details are in swift.log.")
            )
        finally:
            self._active = None
            self._record = None
            self._confirm_ids.clear()
            record["run_ms"] = int((time.monotonic() - started) * 1000)
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
        started = time.monotonic()
        async for event in executor.events(run_id):
            t_ms = int((time.monotonic() - started) * 1000)
            if event.type == "step":
                record["steps"].append({"t_ms": t_ms, "text": event.text})
                await self._send(outbound("step", run_id=run_id, text=event.text, kind="tool", ts=event.ts))
            elif event.type == "confirm" and event.request_id is not None:
                self._confirm_ids.add(event.request_id)
                record["confirmations"].append({"tool": event.tool, "request_id": event.request_id, "asked_ms": t_ms})
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
        return await executor.result(run_id)

    async def _confirm_reply(self, request_id: str, approve: bool) -> None:
        if self._active is None or request_id not in self._confirm_ids:
            logger.warning("confirm.reply for an unknown request ignored")
            return
        self._confirm_ids.discard(request_id)
        executor, run_id = self._active
        if self._record is not None:
            for c in self._record["confirmations"]:
                if c["request_id"] == request_id:
                    c["decision"] = "approve" if approve else "reject"
        await executor.reply(request_id, approve)
        if approve:
            await self._set_state("working", run_id=run_id)

    async def _finish(self, result: ExecResult, record: dict[str, Any]) -> None:
        record["status"] = result.status
        assert self._active is not None
        await self._send_result(self._active[1], result)

    async def _send_result(self, run_id: str, result: ExecResult) -> None:
        if result.status == "error":
            await self._set_state("error", run_id=run_id)
            await self._send(
                outbound("error", code="executor_failed", message=result.summary, hint=ERROR_HINTS["error"])
            )
            return
        await self._set_state("result", run_id=run_id)
        await self._send(
            outbound("result", run_id=run_id, status=result.status, summary=result.summary, details=result.details)
        )
