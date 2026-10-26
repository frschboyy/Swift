"""The providers Swift hands work to, and how it picks one (ADR-008).

Swift is the assistant; Claude Code (and later Codex, Hermes, ...) are providers
behind the ``Executor`` interface. This module holds their ``ProviderInfo`` and
``Providers``, the ordered set the session starts runs on:

- The first executor is the default. ``start()`` tries them in order and moves
  to the next only when one is unavailable (``ExecutorUnavailable``: not
  installed, not configured), and reports which were skipped so Swift can say so.
- A failure *during* a run is not retried on another provider: the run may
  already have changed files, so Swift reports it instead.

Adding a provider: write an executor with a ``provider = ProviderInfo(...)``,
add its name to ``AGENT_NAMES`` if people might call Swift by it, and build it
in ``backend/__main__.py``. Nothing in the session or the overlay changes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from swift.executors.base import SWIFT, Executor, ExecutorUnavailable, ProviderInfo

CLAUDE_CODE = ProviderInfo(
    "claude_code",
    "Claude Code",
    frozenset({"files", "commands", "confirm", "escalation", "subagents"}),
    error_hint="Try again. If it keeps failing, run `claude` in a terminal to check it starts and is signed in.",
    signin_hint="Open a terminal, run `claude`, and sign in. Then try again.",
)
MOCK = ProviderInfo(
    "mock",
    "Demo agent",
    frozenset({"confirm"}),
    error_hint="This is a scripted failure from the debug scenarios.",
)

# Agent names someone might call Swift by mistake ("hey Claude") -> provider id, or None
# for assistants Swift never works with. The routing rules match these words.
AGENT_NAMES: dict[str, str | None] = {
    "claude": "claude_code",
    "claude code": "claude_code",
    "codex": "codex",
    "hermes": "hermes",
    "chatgpt": None,
    "gpt": None,
}


def provider_of(executor: Executor) -> ProviderInfo:
    """The executor's ``ProviderInfo``; one without (a test double) is named after itself."""
    info = getattr(executor, "provider", None)
    if isinstance(info, ProviderInfo):
        return info
    name = str(getattr(executor, "name", "agent"))
    return ProviderInfo(name, name.replace("_", " ").title())


@dataclass(frozen=True)
class Started:
    executor: Executor
    run_id: str
    # Providers tried first and why they couldn't take the request.
    skipped: tuple[tuple[ProviderInfo, ExecutorUnavailable], ...] = field(default=())

    @property
    def provider(self) -> ProviderInfo:
        return provider_of(self.executor)


class Providers:
    """The executors Swift can hand a request to, in order of preference."""

    def __init__(self, executors: Sequence[Executor]) -> None:
        if not executors:
            raise ValueError("at least one executor is needed")
        self.executors = list(executors)

    @property
    def primary(self) -> Executor:
        return self.executors[0]

    def find(self, provider_id: str) -> Executor | None:
        return next((e for e in self.executors if provider_of(e).id == provider_id), None)

    def agents(self) -> list[ProviderInfo]:
        """The real agents behind Swift, in order (Swift's own stand-ins left out)."""
        return [p for p in map(provider_of, self.executors) if not p.is_swift]

    async def start(
        self, request: str, *, demand: str | None = None, override: str | None = None, prefer: str | None = None
    ) -> Started:
        """Start on the first available executor (``prefer``, a provider id, first if it is one of them).
        Raises the first ``ExecutorUnavailable`` if none is."""
        skipped: list[tuple[ProviderInfo, ExecutorUnavailable]] = []
        order = sorted(self.executors, key=lambda e: provider_of(e).id != prefer) if prefer else self.executors
        for executor in order:
            try:
                run_id = await executor.start(request, demand=demand, override=override)
            except ExecutorUnavailable as exc:
                skipped.append((provider_of(executor), exc))
                continue
            return Started(executor, run_id, tuple(skipped))
        raise skipped[0][1]


__all__ = ["AGENT_NAMES", "CLAUDE_CODE", "MOCK", "SWIFT", "Providers", "Started", "provider_of"]
