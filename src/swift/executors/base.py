"""The executor interface (PLAN.md §4).

A run is driven as::

    run_id = await executor.start(request)
    async for event in executor.events(run_id):
        if event.type == "confirm":
            await executor.reply(event.request_id, approve)
    result = await executor.result(run_id)

``events()`` ends once the run has finished, been cancelled or failed;
``result()`` then returns immediately.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

EventType = Literal["step", "confirm", "log"]
Status = Literal["done", "cancelled", "error", "rejected"]


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class ExecEvent:
    type: EventType
    text: str
    ts: int = field(default_factory=now_ms)
    # Set on "confirm" events only.
    request_id: str | None = None
    detail: str | None = None
    tool: str | None = None


@dataclass(frozen=True)
class ExecResult:
    status: Status
    summary: str
    # Optional structured payload for the result card: {"kind": "text"|"list"|"table", ...}.
    details: dict[str, Any] | None = None
    # For the interaction log only (cost, turns, ...); never shown on the card.
    meta: dict[str, Any] = field(default_factory=dict)


class UnknownRun(KeyError):
    pass


class ExecutorUnavailable(RuntimeError):
    """The executor can't run at all (not installed, not configured). ``hint`` says how to fix it."""

    def __init__(self, message: str, hint: str) -> None:
        super().__init__(message)
        self.hint = hint


class Executor(Protocol):
    name: str

    async def start(self, request: str) -> str: ...

    def events(self, run_id: str) -> AsyncIterator[ExecEvent]: ...

    async def cancel(self, run_id: str) -> None: ...

    async def result(self, run_id: str) -> ExecResult: ...

    async def reply(self, request_id: str, approve: bool) -> None: ...
