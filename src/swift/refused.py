"""An approval the backend refused because its OK wasn't in front (claude/rule-gaps, gap 1).

CLAUDE.md: nothing approves unless the thing is on screen and in front, and the backend enforces it
(``intake.approves``). A click is on the thing, so a refused click means the screen and the backend disagree:
it approves nothing, and that OK comes to the front with ``STILL_WAITING`` so the next click there approves it.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from swift import intake

STILL_WAITING = "Still waiting: click again to approve."  # a click the backend saw off the front


async def click(session: Any, request_id: str, approve: bool, source: str) -> bool:
    """A click on a card's Approve: True when it was refused (the card is brought forward instead)."""
    if not approve or source != "click":
        return False  # the other doors already asked ``approves`` about the card in front
    in_front = request_id == session._open_confirm() and not (session.attention is not None and session.attention.held)
    verdict = intake.approves(source, named=False, level=intake.CARD, in_front=in_front)
    if verdict.allowed:
        return False
    logger.info("approval refused", reason=verdict.reason, source=source)
    await session._open_card(request_id)  # it comes to the front, unanswered
    await session._confirm_phase(request_id)("hint", STILL_WAITING)
    return True


async def question(session: Any, q: Any, verdict: intake.Verdict, typed_hint: str) -> None:
    """Swift's own approval question refused: typed words get the typed hint; off screen, it comes to the front."""
    hint = STILL_WAITING if verdict.reason == "not_in_front" else typed_hint
    if hint is typed_hint or (q.owner is not None and await session._bring(q.owner)):
        await session._reask(q, f"{hint} {q.text}")  # typed: never a yes
