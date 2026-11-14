"""Which web addresses the owner gave, beyond this request's own words (C3, owner's decisions of 2026-11-14).

``desktop_open(url=…)`` opens an address in the owner's words for this request. Two more sources, both the
owner's own words and never the agent's text or a page:

- **Pointing at a recent one.** An address the owner said or typed earlier in this conversation, in the last
  10 minutes (``RunScope.earlier``), counts only when this request points back at it: "open that site again",
  "the one I just opened", "open it" (``points_back``). After "open usiu dot ac dot ke", "open my university's
  website" doesn't: the owner never said that site was his university (check 330, 2026-11-14).
- **A description he taught Swift.** "My university's website" counts only through a memory written from his
  words ("remember my university is usiu dot ac dot ke", swift/memory.py): ``remembered`` gives the memories whose
  subject the request names. A memory Swift inferred is never one (the store doesn't keep those).

Otherwise the agent asks the owner to say the address, and doesn't offer one.
"""

from __future__ import annotations

import re
from typing import Any

# The request points back at something already opened or said.
_POINTS_BACK = re.compile(
    r"\bagain\b|\breopen\b"
    r"|\b(?:open|bring up|show|go to|visit|load)\s+(?:it|that|this)\b(?!\s+(?:is|was)\b)|\bbring (?:it|that) up\b"
    r"|\b(?:that|the same|same|this)\s+(?:web ?site|site|page|link|address|url|one)\b"
    r"|\bthe (?:one|site|page|website|address|link) (?:i|we) (?:just |already )?"
    r"(?:opened|said|mentioned|gave|named|asked for|had open)\b",
    re.IGNORECASE,
)
# Words that say what kind of thing it is, not which one: "my university's website" is about "university".
_GENERIC = frozenset({"my", "our", "the", "a", "an", "s", "website", "web", "site", "page", "homepage", "home",
                      "address", "url", "link", "portal", "official"})
_SOURCES = frozenset({"said", "approved"})  # written from the owner's words or a card he approved


def _words(text: str) -> set[str]:
    return set(re.sub(r"[^\w\s]", " ", text.lower().replace("'s", " ")).split())


def points_back(words: str) -> bool:
    """The owner's words point at an address already given ("open that site again", "the one I just opened")."""
    return bool(_POINTS_BACK.search(words))


def remembered(store: Any, words: str) -> list[str]:
    """Texts of the owner's memories whose subject ``words`` name: "open my university's website" names the
    memory "my university is usiu.ac.ke". None without a store, or for a subject of only generic words."""
    if store is None:
        return []
    said = _words(words)
    found = []
    for record in store.all("memory"):
        if record.forgotten or record.source not in _SOURCES:
            continue
        subject = re.split(r"\s+(?:is|are|was|=)\s+", record.text.lower(), maxsplit=1)[0]
        named = _words(subject) - _GENERIC
        if named and named <= said:
            found.append(record.text)
    return found
