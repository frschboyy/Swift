"""Whether what the owner said while Swift's own yes/no question is open is that question's request, said again.

A7, check 204 (owner's run of 2026-11-13, 14:44:20): "Turn off Wi-Fi?" was opened from the stack, and the owner
said the request again ("He has turn off Wi Fi.", misheard). It was taken as a new request: the question went
to the stack and the request went to the agent, behind an approval card.

The owner's decision of 2026-11-14 (A+B; a product rule: a bare "yes" approves only Swift's own question about
a reversible change, open and on screen):

- "same": it parses to exactly the intents and slots the question asks about ("turn off the Wi-Fi" to "Turn off
  Wi-Fi?"). Spoken, it is the owner's yes; typed, it never is (typing never approves). The session decides that.
- "like": it only sounds like the request (``same_request``) and parses to no system intent of its own: it
  approves nothing, and the question is asked once more.
- None: anything else, including another system intent ("turn on the Wi-Fi"), which is a request of its own.
"""

from __future__ import annotations

from typing import Any, Literal

from swift.routing.rules import strip_wake
from swift.same_request import same_request
from swift.system import intents as system_intents

Restated = Literal["same", "like"]


def restated(text: str, question: Any) -> Restated | None:
    """How ``text`` restates ``question``'s request: "same", "like", or None (see the module)."""
    if not getattr(question, "own", False) or question.kind != "yes_no" or not question.payload:
        return None
    said = strip_wake(text) or text
    found = system_intents.parse(said)
    if found is not None:
        return "same" if list(found) == list(question.payload) else None
    if question.request and same_request(said, question.request):
        return "like"
    return None


__all__ = ["Restated", "restated"]
