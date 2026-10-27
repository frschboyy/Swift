"""What waits for the owner: the waiting stack (ADR-015 §9, owner design of 2026-10-27).

One list of the cards that need attending to, shown as a compressed stack in a bottom corner
of the screen. Double-clicked it expands; each card can be opened (it comes back, or the
conversation resumes), skipped (back to the stack, last in line) or ended (gone).

What is in it:

- **waiting:** confirm cards in line behind the one on screen (ADR-013 §5.2);
- **later:** a confirm card the owner skipped ("Later"): off screen, its countdown paused;
- **held:** the card on screen while the owner is away (ADR-014 §4);
- **parked:** conversations left unfinished: stopped, a card unanswered, or Swift's question
  left unanswered (swift/parked.py), including a question pushed off the screen by a card.

Pure: the session says what exists, this orders it. Titles are the owner's own words; nothing
here is logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Kinds and what each action does with them (session.py ``_stack_action``).
CARD_KINDS = frozenset({"waiting", "later", "held"})
ACTIONS = ("open", "skip", "end")
# Parked conversations shown at most (swift/parked.py keeps 10).
MAX_PARKED = 10


@dataclass(frozen=True)
class StackItem:
    # "card:<request id>" or "parked:<thread>": what ``stack.action`` names.
    id: str
    # "waiting" | "later" | "held" | "parked"
    kind: str
    title: str
    # Why it waits: "waiting", "later", "held", or the parked reason ("stopped", "unanswered", "asked").
    reason: str
    # When it started waiting (ms since the epoch).
    since_ms: int
    thread_id: str | None = None

    def as_message(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "reason": self.reason,
            "since_ms": self.since_ms, "thread_id": self.thread_id,
        }


def card_id(request_id: str) -> str:
    return f"card:{request_id}"


def parked_id(thread: str) -> str:
    return f"parked:{thread}"


def split_id(item_id: str) -> tuple[str, str] | None:
    """("card", request id) or ("parked", thread); None for anything else."""
    kind, sep, key = item_id.partition(":")
    return (kind, key) if sep and key and kind in ("card", "parked") else None


def order(items: list[StackItem], skipped: dict[str, float]) -> list[StackItem]:
    """Cards first (in the order they were asked), then conversations, newest first. Skipped
    items go last, in the order they were skipped. ``skipped``: item id -> when (any clock)."""
    rank = {"held": 0, "waiting": 1, "later": 1, "parked": 2}

    def key(i: tuple[int, StackItem]) -> tuple[float, ...]:
        n, item = i
        if item.id in skipped:
            return (1, skipped[item.id], 0, 0)
        when = item.since_ms if item.kind != "parked" else -item.since_ms
        return (0, rank.get(item.kind, 3), when, n)

    return [item for _, item in sorted(enumerate(items), key=key)]
