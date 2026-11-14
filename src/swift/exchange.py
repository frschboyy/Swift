"""One exchange with the agent, kept for the follow-ups in its conversation (ADR-007 §9).

A request to the agent within ``followup_s`` of the previous answer carries that exchange as context;
the few before it in the same conversation ride along too (``EARLIER_MAX``). Each exchange also keeps
the owner's own words for its request, as Swift heard or read them, so a web address the owner gave
earlier in the conversation can be opened (C3, owner's decision 2026-11-14): never the agent's answer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from swift import clock
from swift.parked import _clip

EARLIER_MAX = 4


@dataclass(frozen=True)
class Exchange:
    """The previous request to the executor, kept for one follow-up (ADR-007 §9)."""

    id: str
    request: str
    answer: str
    approved: tuple[str, ...]
    at: float
    # The last email or event Swift showed on a card ("To Ada, Subject …"), and whether it went ahead.
    proposed: str = ""
    proposed_done: bool = False
    thread: str | None = None
    # The exchanges before this one in the same conversation, oldest first (none of them nested).
    earlier: tuple[Exchange, ...] = ()
    # The owner's own words for this request, as Swift heard or read them (its transcript, and their
    # answers to its questions), and when (clock.now() as the request began). Never ``request``, which
    # may be a workflow's text, and never ``answer``, the agent's: a web address the owner gave earlier
    # in the conversation may be opened from these (C3, owner's decision 2026-11-14).
    owner: tuple[str, ...] = ()
    heard_at: float = 0.0

    def then(self, before: Exchange | None, now: float, window_s: float) -> Exchange:
        """This exchange, with ``before`` and its earlier ones if the conversation went on (``window_s``)."""
        if before is None or now - before.at > window_s:
            return self
        chain = (*before.earlier, replace(before, earlier=()))[-EARLIER_MAX:]
        return replace(self, earlier=chain)

    def owner_words(self) -> tuple[tuple[float, str], ...]:
        """The owner's own words in this conversation, oldest first, each with when Swift heard it."""
        return tuple((e.heard_at, words) for e in (*self.earlier, self) for words in e.owner)

    def as_context(self, now: float) -> str:
        lines = [
            f"[Context: the previous voice request, {int(now - self.at)} s ago. "
            "Use it only if the current request refers to it.]",
        ]
        if self.earlier:
            lines = [
                "[Context: this voice conversation so far, oldest first. Use it only if the current request "
                "refers to it.]",
            ]
            for e in self.earlier:
                lines += [f"Earlier request ({int(now - e.at)} s ago): {_clip(e.request, 200)}",
                          f"Earlier answer: {_clip(e.answer, 300)}"]
            lines.append(f"[The previous request, {int(now - self.at)} s ago]")
        lines += [
            f"Previous request: {_clip(self.request, 300)}",
            f"Previous answer: {_clip(self.answer, 800)}",
        ]
        if self.approved:
            lines.append("Actions the user approved: " + "; ".join(_clip(a, 120) for a in self.approved[-5:]))
        if self.proposed:
            state = "it went ahead" if self.proposed_done else "the user did NOT approve it"
            lines.append(
                f"What Swift last showed the user ({state}): {_clip(self.proposed, 400)}. If the current request "
                "corrects it, use the correction and keep the rest; the corrected values win over the previous request."
            )
        return "\n".join(lines) + "\n\n[Current request]\n"


def owner_said(record: dict[str, Any], scope: Any, heard_at: float | None) -> dict[str, Any]:
    """``Exchange`` fields for the owner's own words in a request: its transcript (as ``RunScope.said``)
    and their answers to its questions, with when the request began. Nothing the agent wrote or a tool read."""
    words = (str(record.get("transcript") or ""), *(scope.answers if scope is not None else ()))
    return {"owner": tuple(w for w in words if w.strip()), "heard_at": clock.now() if heard_at is None else heard_at}
