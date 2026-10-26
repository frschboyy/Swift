"""The state Swift's tools keep for one run (ADR-010 §3.4).

Swift runs one interaction at a time, so the tool host has at most one open
``RunScope``. The session opens it before the provider starts and closes it when
the run ends; it supplies how artifacts reach the overlay (``publish``), how the
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

from swift.connectors.base import Contact
from swift.workflows.artifacts import Artifact, ArtifactStore, Kind, Phase

Decision = Literal["approve", "reject", "no_answer"]
# (title, detail, tool, artifact_id) -> the owner's answer on the confirm card.
Confirmer = Callable[[str, str, str, str | None], Awaitable[Decision]]
Publisher = Callable[[Artifact], Awaitable[None]]
# (text, activity, app) -> a step on the working card, from Swift itself.
Stepper = Callable[[str, str, str | None], Awaitable[None]]


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
    # Digests already sent: an approval is used once (T10).
    sent: set[str] = field(default_factory=set)
    ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))
    closed: bool = False
    # None: not a workflow run, every tool is available (ADR-010 behaviour).
    grant: Grant | None = None
    step_fn: Stepper | None = None
    # time.monotonic() until which the owner is talking to Swift (push-to-talk held): their
    # key presses then aren't "typing in the window" (ADR-012 §6).
    talking_until: float = 0.0

    def allows(self, tool: str) -> bool:
        return self.grant is None or tool in self.grant.tools

    async def step(self, text: str, activity: str = "working", app: str | None = None) -> None:
        if self.step_fn is not None:
            await self.step_fn(text, activity, app)

    async def publish(self, id: str, kind: Kind, phase: Phase, title: str, data: dict[str, Any]) -> Artifact:
        artifact = self.artifacts.put(id, kind, phase, title, data)
        await self.publish_fn(artifact)
        return artifact
