"""The executor interface (PLAN.md §4).

A run is driven as::

    run_id = await executor.start(WorkerTask(request))
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

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, get_args

from swift.failures import Failure
from swift.ipc.protocol import now_ms

# "live": what the live view shows (``data``): a source found or read, a note (ADR-017 §7).
EventType = Literal["step", "confirm", "log", "live"]
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


@dataclass(frozen=True)
class ExecEvent:
    type: EventType
    text: str
    ts: int = field(default_factory=now_ms)
    # Set on "confirm" events only.
    request_id: str | None = None
    detail: str | None = None
    tool: str | None = None
    # A command card only: what the agent says it's for, in its own words (B1, X-17).
    purpose: str | None = None
    activity: Activity = "working"
    # True when a sub-agent the provider started did this step ("Claude Code's helper is reading").
    subagent: bool = False
    # Set on "live" events only: {"kind": "source", "url", "title", "site", "state"} or {"kind": "note", "text"}.
    data: dict[str, Any] | None = None


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


# "local": data that must stay on this PC (a file the owner marked); cloud workers refuse it
# (product-direction §4.4, rule 1). Nothing sets it yet.
Privacy = Literal["cloud", "local"]


@dataclass(frozen=True)
class ContextPack:
    """What Swift adds around the request (product-direction §4.4). ``thread`` goes before it: the
    previous exchange, or the parked task being resumed. ``notes`` go after it, in order: where the
    owner is, words speech recognition was unsure of, the workflow catalogue, a change of mind."""

    thread: str = ""
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Budget:
    """How much model to spend (ADR-007): the router's ``demand`` ("light"/"standard") and the owner's
    ``override`` ("opus"/"sonnet"/"haiku"). Executors with a single model ignore it. The money cap per
    run stays the executor's own setting (``max_budget_usd``)."""

    demand: str | None = None
    override: str | None = None


@dataclass(frozen=True)
class Grant:
    """What the owner approved ahead for this task: the base for B2 (owner, 2026-11-13).

    One approval covers one coherent ``step`` of a task, with its ``commands`` listed inside it as the
    owner saw them on the card. A command outside the list asks again, and anything irreversible
    (deleting, paying, sending) always gets its own card, so a grant never covers it. Empty, the
    default, covers nothing: every side effect asks, as today. No executor honours a grant yet; B2
    builds the card that makes one and the check that uses it.
    """

    step: str = ""
    commands: tuple[str, ...] = ()

    def covers(self, command: str, *, irreversible: bool) -> bool:
        return not irreversible and command.strip() in self.commands


@dataclass(frozen=True)
class WorkerTask:
    """Everything an executor gets for one run: the request, the context pack Swift built, the grant,
    the budget and the privacy class."""

    request: str
    context: ContextPack = ContextPack()
    grant: Grant = Grant()
    budget: Budget = Budget()
    privacy: Privacy = "cloud"

    @property
    def prompt(self) -> str:
        """The text a model-backed worker is sent: the request inside its context pack."""
        return self.context.thread + self.request + "".join(f"\n\n{note}" for note in self.context.notes)


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

    async def start(self, task: WorkerTask) -> str:
        """Raises ``ExecutorUnavailable`` if it can't run at all, or can't take the task's privacy class."""
        ...

    def events(self, run_id: str) -> AsyncIterator[ExecEvent]: ...

    async def cancel(self, run_id: str) -> None: ...

    async def result(self, run_id: str) -> ExecResult: ...

    async def reply(self, request_id: str, approve: bool) -> None: ...

    # Optional: ``async def change(self, request_id: str, text: str) -> bool``. The owner answered
    # the provider's own confirm card with a change ("no, put it in docs/ instead"): pass it to the
    # provider, which revises and asks again; True if it took it. A provider without it gets the
    # same result generically: Swift rejects the card and sends the change as the next request.
    #
    # Optional: ``async def redirect(self, run_id: str, text: str) -> bool``. The owner changed their
    # mind mid-run ("actually, make it about the deadline"): the provider goes on with the change in
    # the same session; True if it took it. Without it, Swift cancels the run and starts it again
    # with the original request and the change (ADR-014 §7).
