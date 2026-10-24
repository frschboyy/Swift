"""Run artifacts: typed, versioned snapshots of what a run is working on (ADR-010 §5).

A run's ``ArtifactStore`` keeps the latest version of each artifact and the run's
phase (the phase of the newest update). ``pick`` chooses what "show me" opens:
the artifact that matters for the current phase, or the one asked for by kind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["email_draft", "recipient", "send_status", "text", "list", "table"]
Phase = Literal["resolving", "drafting", "confirming", "sending", "done", "failed"]

# What "show me" opens first in each phase; the newest artifact when none of these exists.
PHASE_KINDS: dict[str, tuple[str, ...]] = {
    "resolving": ("recipient",),
    "drafting": ("email_draft",),
    "confirming": ("email_draft",),
    "sending": ("send_status", "email_draft"),
    "done": ("send_status",),
    "failed": ("send_status",),
}


@dataclass(frozen=True)
class Artifact:
    id: str
    kind: Kind
    phase: Phase
    version: int
    title: str
    data: dict[str, Any]

    def as_message(self, run_id: str, agent: dict[str, str] | None = None) -> dict[str, Any]:
        return {
            "run_id": run_id, "id": self.id, "kind": self.kind, "phase": self.phase, "version": self.version,
            "title": self.title, "data": self.data, "agent": agent,
        }


@dataclass
class ArtifactStore:
    latest: dict[str, Artifact] = field(default_factory=dict)
    # Ids in the order they were last updated (newest last).
    order: list[str] = field(default_factory=list)
    phase: Phase | None = None

    def put(self, id: str, kind: Kind, phase: Phase, title: str, data: dict[str, Any]) -> Artifact:
        previous = self.latest.get(id)
        artifact = Artifact(id, kind, phase, (previous.version + 1) if previous else 1, title, data)
        self.latest[id] = artifact
        if id in self.order:
            self.order.remove(id)
        self.order.append(id)
        self.phase = phase
        return artifact

    def get(self, id: str) -> Artifact | None:
        return self.latest.get(id)

    def newest(self, kind: str | None = None) -> Artifact | None:
        for id in reversed(self.order):
            if kind is None or self.latest[id].kind == kind:
                return self.latest[id]
        return None

    def pick(self, kind: str | None = None) -> Artifact | None:
        """What "show me" opens: ``kind`` if asked for, else the phase's most relevant artifact."""
        if kind is not None:
            return self.newest(kind)
        for preferred in PHASE_KINDS.get(self.phase or "", ()):
            if (found := self.newest(preferred)) is not None:
                return found
        return self.newest()
