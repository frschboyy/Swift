"""Executor that only shows what was heard. Nothing leaves the machine.

The default until Claude Code is configured (Milestone 3), so push-to-talk and
transcription can be tried on their own.
"""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator

from swift.executors.base import ExecEvent, ExecResult, UnknownRun


class EchoExecutor:
    name = "echo"

    def __init__(self) -> None:
        self._results: dict[str, ExecResult] = {}
        self._ids = itertools.count(1)

    async def start(self, request: str) -> str:
        run_id = f"echo-{next(self._ids)}"
        self._results[run_id] = ExecResult(
            "done",
            f"“{request}”",
            {"kind": "text", "text": "Transcribed on this PC. No agent is configured yet, so nothing was sent anywhere."},
        )
        return run_id

    async def events(self, run_id: str) -> AsyncIterator[ExecEvent]:
        self._get(run_id)
        return
        yield  # pragma: no cover - makes this an async generator

    async def cancel(self, run_id: str) -> None:
        self._get(run_id)

    async def result(self, run_id: str) -> ExecResult:
        return self._get(run_id)

    async def reply(self, request_id: str, approve: bool) -> None:
        return None

    def _get(self, run_id: str) -> ExecResult:
        try:
            return self._results[run_id]
        except KeyError:
            raise UnknownRun(run_id) from None
