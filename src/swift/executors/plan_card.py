"""Modes §2 (decision 5): the plan card. One card for a multi-step task: each step in words, which of them Swift
covers, and which will still ask, and why.

Swift decides, never the agent: a step is covered only when it lists commands and every one is ``reversible``
(``step_grant``): commands only, never a file edit, and nothing that deletes, sends, publishes or pays (those keep
their own card, always). A step with any other command, or with none listed yet, asks on its own cards: all or
nothing, so the card's "covered" is exactly what the grant holds.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from swift.executors.base import Grant
from swift.executors.claude_mapping import command_purpose

MIN_STEPS = 2  # one step is B2's step card
MAX_STEPS = 8  # a card that has to be read whole stays readable

_DELETES = ("rm", "del", "erase", "rmdir", "rd", "remove-item")
_SENDS = ("push", "send", "mail", "sendmail")


def _why(commands: list[str]) -> str:
    """Why a step will ask, in Swift's words from the commands' leading words, never the agent's."""
    if not commands:
        return "its commands aren't known yet"
    for command in commands:
        words = command.lower().split()
        if (words[:1] and words[0].removesuffix(".exe") in _DELETES) or "delete" in words or "clean" in words:
            return "it deletes"
        if any(w in _SENDS for w in words[:3]):
            return "it sends"
        if words[:3] in (["gh", "repo", "create"], ["gh", "release", "create"]) or words[:2] in (["npm", "publish"], ["gh", "pr"]):
            return "it publishes"
    return "Swift can't tell it can be undone"


def build(
    steps: Any, okay: Callable[[str], bool], reversible: Callable[[str], bool],
) -> tuple[list[dict[str, Any]], tuple[Grant, ...]] | None:
    """The card's rows and the grants they stand for, in order; None if this isn't a plan Swift can show."""
    if not isinstance(steps, list) or not MIN_STEPS <= len(steps) <= MAX_STEPS:
        return None
    rows: list[dict[str, Any]] = []
    grants: list[Grant] = []
    for raw in steps:
        words = command_purpose("Bash", {"description": raw.get("step")}) if isinstance(raw, dict) else ""
        listed = raw.get("commands") if isinstance(raw, dict) else None
        commands = list(dict.fromkeys(c for c in listed if isinstance(c, str))) if isinstance(listed, list) else []
        if not words:
            return None  # a step with no words of its own can't lead its row
        covered = bool(commands) and all(reversible(c) and okay(c) for c in commands)
        rows.append({"step": words, "commands": commands if covered else [], "covered": covered,
                     "asks": "" if covered else _why(commands)})
        if covered:
            grants.append(Grant(words, tuple(commands)))
    return rows, tuple(grants)
