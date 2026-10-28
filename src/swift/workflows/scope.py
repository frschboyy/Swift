"""The state Swift's tools keep for one run (ADR-010 §3.4).

Every request has its own ``RunScope`` (several can run at once, ADR-013 §5.4). The
session opens it before the provider starts and closes it when the run ends; it supplies how artifacts reach the overlay (``publish``), how the
gateway asks the owner (``confirm``) and how Swift's own steps reach the working
card (``step``, e.g. "Swift is writing in Word").

A workflow run (ADR-011 W1) also carries a ``Grant``: the Swift tools and provider
capabilities its manifest declares. The tool host refuses every other tool.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from swift.connectors.base import Contact, StoredEvent
from swift.workflows.artifacts import Artifact, ArtifactStore, Kind, Phase

# "revise": the owner asked for a change on the card; their words are in ``RunScope.feedback``.
Decision = Literal["approve", "reject", "no_answer", "revise"]
# (title, detail, tool, artifact_id) -> the owner's answer on the confirm card.
Confirmer = Callable[[str, str, str, str | None], Awaitable[Decision]]
Publisher = Callable[[Artifact], Awaitable[None]]
# (text, activity, app) -> a step on the working card, from Swift itself.
Stepper = Callable[[str, str, str | None], Awaitable[None]]
# (question, kind, options) -> the owner's answer (``swift.dialogue.Answer``), or None: no answer (ADR-016 §5.1).
Asker = Callable[[str, str, tuple[str, ...]], Awaitable[Any]]
# An item for the live view (ADR-017 §7): {"kind": "text", "text", "app"}, what Swift just wrote.
Liver = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class Grant:
    """What a workflow run may use: its manifest's ``needs`` (ADR-011 §4.2)."""

    workflow: str
    tools: frozenset[str]
    capabilities: frozenset[str]


@dataclass(frozen=True)
class Draft:
    id: str
    to: tuple[Contact, ...]
    subject: str
    body: str
    version: int = 1

    def digest(self) -> str:
        """What an approval is bound to: recipients, subject and body (threat model T3)."""
        payload = json.dumps([[c.email.lower() for c in self.to], self.subject, self.body], ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class RunScope:
    publish_fn: Publisher
    confirm: Confirmer
    artifacts: ArtifactStore = field(default_factory=ArtifactStore)
    # Addresses find_contact returned in this run (lower-cased) -> the contact.
    resolved: dict[str, Contact] = field(default_factory=dict)
    drafts: dict[str, Draft] = field(default_factory=dict)
    # Calendar events this run looked up or added (event id -> the event): the only ones it may
    # change or remove, besides those the journal says Swift added.
    events: dict[str, StoredEvent] = field(default_factory=dict)
    # Digests already sent: an approval is used once (T10).
    sent: set[str] = field(default_factory=set)
    ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))
    closed: bool = False
    # What the owner said to change on the last confirm card answered "revise".
    feedback: str = ""
    # None: not a workflow run, every tool is available (ADR-010 behaviour).
    grant: Grant | None = None
    step_fn: Stepper | None = None
    live_fn: Liver | None = None
    # time.monotonic() until which the owner is talking to Swift (push-to-talk held): their
    # key presses then aren't "typing in the window" (ADR-012 §6).
    talking_until: float = 0.0
    # Actions the gateway did in this run that needed the owner's approval, as (tool, title):
    # a sent email can't be taken back, so a change of mind afterwards is told so (ADR-014 §7).
    done: list[tuple[str, str]] = field(default_factory=list)
    # The owner's own words for this request (the transcript): ``system_action`` does only what they asked.
    said: str = ""
    # How a tool asks the owner something mid-run (``ask_owner``, ``find_contact``); None: it can't.
    ask_fn: Asker | None = None

    def allows(self, tool: str) -> bool:
        # Asking the owner is never outside what a workflow may do: it does nothing by itself.
        return self.grant is None or tool in self.grant.tools or tool == "ask_owner"

    async def ask(self, question: str, kind: str, options: tuple[str, ...] = ()) -> Any:
        """Ask the owner (ADR-016 §5.1): their answer, or None (away, no answer, or no way to ask)."""
        if self.ask_fn is None:
            return None
        return await self.ask_fn(question, kind, options)

    def carry_from(self, before: RunScope) -> None:
        """Go on from the request before in the same thread: its contacts, drafts and events, so
        "send it" sends that draft and "actually say …" revises it (owner checks, 2026-10-27)."""
        self.resolved.update(before.resolved)
        self.drafts.update(before.drafts)
        self.events.update(before.events)
        self.sent |= before.sent
        self.ids = itertools.count(next(before.ids))  # its ids stay its own: draft-1 is still that draft

    async def step(self, text: str, activity: str = "working", app: str | None = None) -> None:
        if self.step_fn is not None:
            await self.step_fn(text, activity, app)

    async def live(self, item: dict[str, Any]) -> None:
        """For the live view only: shown in the overlay, never logged."""
        if self.live_fn is not None:
            await self.live_fn(item)

    async def publish(self, id: str, kind: Kind, phase: Phase, title: str, data: dict[str, Any]) -> Artifact:
        artifact = self.artifacts.put(id, kind, phase, title, data)
        await self.publish_fn(artifact)
        return artifact
