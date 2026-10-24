"""Swift's own identity (ADR-008).

The owner talks to Swift. Claude Code and the other providers work for Swift and
are named only to say who is doing the work, so when someone calls Swift by an
agent's name ("hey Claude"), Swift says once, lightly, who it is, and carries on.
Everything here only states facts about the configured providers: an agent that
isn't set up is never described as one Swift works with.
"""

from __future__ import annotations

from collections.abc import Sequence

from swift.executors.base import ProviderInfo
from swift.executors.providers import AGENT_NAMES

NAME = "Swift"


def _join(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def introduction(agents: Sequence[ProviderInfo]) -> str:
    """Answer to "who are you?"."""
    if not agents:
        return f"I'm {NAME}, your voice assistant. No agent is set up yet, so for now I only show what I heard."
    names = _join([a.name for a in agents])
    verb = "is the agent" if len(agents) == 1 else "are the agents"
    return f"I'm {NAME}, your voice assistant. {names} {verb} I hand work to; I bring the results back to you."


def clarification(called: str, agents: Sequence[ProviderInfo]) -> str:
    """Swift was addressed as ``called`` (a key of ``AGENT_NAMES``): say who it is, once."""
    provider_id = AGENT_NAMES.get(called)
    match = next((a for a in agents if a.id == provider_id), None)
    if match is not None:
        return f"No, I'm {NAME}. {match.name} is one of the agents I work with."
    if agents:
        noun = "agents I work with right now are" if len(agents) > 1 else "agent I work with right now is"
        return f"No, I'm {NAME}. The {noun} {_join([a.name for a in agents])}."
    return f"No, I'm {NAME}, your voice assistant."
