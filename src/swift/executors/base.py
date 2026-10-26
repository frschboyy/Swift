"""The executor interface (PLAN.md §4).

A run is driven as::

    run_id = await executor.start(request)
    async for event in executor.events(run_id):
        if event.type == "confirm":
            await executor.reply(event.request_id, approve)
    result = await executor.result(run_id)

``events()`` ends once the run has finished, been cancelled or failed;
``result()`` then returns immediately.

Swift is the assistant the owner talks to; an executor is a *provider* that does
the work for it (ADR-008). Each one describes itself with a ``ProviderInfo`` and
reports progress as normalized ``ExecEvent``s (an ``activity`` from a fixed
vocabulary), so the session and the overlay never need provider-specific code.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, get_args

from swift.failures import Failure

EventType = Literal["step", "confirm", "log"]
Status = Literal["done", "cancelled", "error", "rejected"]
# What a provider is doing, whatever its own event format. The overlay turns it into
# "<provider> is reading"; anything a provider can't classify is "working". "writing" is
# Swift's own, in the owner's app in front of them ("Swift is writing in Word", ADR-012 §6).
Activity = Literal[
    "starting", "reading", "searching", "editing", "running", "browsing",
    "delegating", "planning", "thinking", "waiting", "switching", "blocked", "working", "writing",
]
ACTIVITIES: tuple[str, ...] = get_args(Activity)


@dataclass(frozen=True)
class ProviderInfo:
    """Who does the work for Swift: shown to the owner, never a separate identity (ADR-008)."""

    # Stable id for logs and config ("claude_code").
    id: str
    # What the owner reads: "Claude Code is reading".
    name: str
    # What it can do, so routing can choose without knowing the provider: "files", "commands",
    # "confirm" (asks before side effects), "escalation" (moves to a stronger model), "subagents".
    capabilities: frozenset[str] = frozenset()
    # Shown on the error card when a run fails.
    error_hint: str = "Try again. If it keeps happening, open the logs from Swift's tray menu."
    # Shown when it fails because it isn't signed in: how to sign in to this provider.
    signin_hint: str = ""
    # Swift itself (local answers, the echo stand-in): no hand-off is shown.
    is_swift: bool = False

    def as_agent(self) -> dict[str, str]:
        """The overlay's attribution object (``agent`` in the protocol)."""
        return {"id": self.id, "name": self.name}


SWIFT = ProviderInfo("swift", "Swift", is_swift=True)


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
    activity: Activity = "working"
    # True when a sub-agent the provider started did this step ("Claude Code's helper is reading").
    subagent: bool = False


@dataclass(frozen=True)
class ExecResult:
    status: Status
    summary: str
    # Optional structured payload for the result card: {"kind": "text"|"list"|"table", ...}.
    details: dict[str, Any] | None = None
    # For the interaction log only (cost, turns, ...); never shown on the card.
    meta: dict[str, Any] = field(default_factory=dict)
    # Status "error" only: the provider's own reading of what went wrong. When None,
    # the session classifies ``summary`` (``swift.failures.classify``).
    failure: Failure | None = None


class UnknownRun(KeyError):
    pass


class ExecutorUnavailable(RuntimeError):
    """The executor can't run at all (not installed, not configured). ``hint`` says how to fix it."""

    def __init__(self, message: str, hint: str) -> None:
        super().__init__(message)
        self.hint = hint


class Executor(Protocol):
    name: str
    provider: ProviderInfo

    async def start(self, request: str, *, demand: str | None = None, override: str | None = None) -> str:
        """``demand`` ("light"/"standard") and ``override`` ("opus"/"sonnet"/"haiku") come from the
        router (ADR-007); executors with a single model ignore them."""
        ...

    def events(self, run_id: str) -> AsyncIterator[ExecEvent]: ...

    async def cancel(self, run_id: str) -> None: ...

    async def result(self, run_id: str) -> ExecResult: ...

    async def reply(self, request_id: str, approve: bool) -> None: ...

    # Optional: ``async def change(self, request_id: str, text: str) -> bool``. The owner answered
    # the provider's own confirm card with a change ("no, put it in docs/ instead"): pass it to the
    # provider, which revises and asks again; True if it took it. A provider without it gets the
    # same result generically: Swift rejects the card and sends the change as the next request.
