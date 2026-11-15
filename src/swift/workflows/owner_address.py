"""Web addresses the owner taught Swift (C3, owner's decision of 2026-11-14).

"My university's website" names an address only through a memory written from the owner's words ("remember my
university is usiu dot ac dot ke", swift/memory.py): ``remembered`` gives the memories whose subject the request
names. A memory Swift inferred is never one (the store doesn't keep those). ``desktop_open`` asks before opening it
(foundation decision 4), as for an address the owner said earlier in the conversation.

Which words point back at an address said a moment ago was a pattern here (``points_back``) until decision 4:
QA kept finding requests it misread (QA-02, QA-04), and a question on screen replaced it.
"""

from __future__ import annotations

import re
from typing import Any

# Words that say what kind of thing it is, not which one: "my university's website" is about "university".
_GENERIC = frozenset({"my", "our", "the", "a", "an", "s", "website", "web", "site", "page", "homepage", "home",
                      "address", "url", "link", "portal", "official"})
_SOURCES = frozenset({"said", "approved"})  # written from the owner's words or a card he approved


def _words(text: str) -> set[str]:
    return set(re.sub(r"[^\w\s]", " ", text.lower().replace("'s", " ")).split())


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
