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

# The request points back at something already opened or said only when all of it is pointing words: "open that
# site again", "open it in Edge", "the one I just opened". A request that names anything else isn't, whatever
# pointing word it contains: "show this week's timetable on my university's website (again)", "open that one drive
# folder", "find my university's website and open it" (QA-02 and QA-04, 2026-11-15: a pointing word followed by
# anything, or "again" anywhere, opened the address said a moment ago). Each clause is stripped of what doesn't
# change which thing it means (the wake word, "please", "can you", "again", "in Edge", "for me"); then every clause
# left must be one pointing phrase.
_CLAUSES = re.compile(r"\s*(?:[.,!?;:()\"]|[—–-]\s|\b(?:and then|and|then)\b)\s*")
_HESITATION = re.compile(r"\b(?:um+|uh+|er+|erm|hmm+)\b")
_FILLER = r"(?:hey|hi|ok|okay|so|now|just|please|swift|yes|yeah|right|real quick|thanks|thank you)"
_LEAD = re.compile(rf"^(?:(?:{_FILLER}|can you|could you|would you|will you|i want you to|go ahead and|i said)\s+)+")
_TRAIL = re.compile(
    rf"(?:\s+(?:{_FILLER}|again|for me|to me|once more|one more time|right now|"
    r"(?:in|on|with) (?:edge|chrome|firefox|brave|opera|the browser|my browser|a new tab|new tab|another tab|"
    r"a new window|new window|the same tab))\b)+$"
)
_THING = r"(?:web ?site|site|web ?page|page|home ?page|link|address|url|one|tab)"
# A noun phrase can point by itself ("that site again"); a bare "it", "that" or "the same" needs a verb before it, or
# an answer "that" to "Which one?" would point at the address too.
_NAMED = (
    rf"(?:(?:that|this|the same|same|the last|that last|the previous) {_THING}|the last one"
    rf"|(?:the|that) {_THING} (?:i|we|you) (?:just |already )?"
    r"(?:opened|said|mentioned|gave|named|asked for|had open|were on)(?: earlier| before| a moment ago| just now)?)"
)
_POINTING_CLAUSE = re.compile(
    r"(?:(?:re)?open|show(?: me)?|visit|load|go(?: back)? to|take me(?: back)? to|bring up|pull up)\s+"
    rf"(?:it|that|this|the same|{_NAMED})|(?:bring|pull) (?:it|that) (?:back )?up|reopen|{_NAMED}"
)


def _bare_clauses(words: str) -> list[str]:
    """The request's clauses, lower case, each without the words that don't change which thing it means."""
    text = " ".join(_HESITATION.sub(" ", words.lower()).replace("’", "'").replace("‘", "'").split())
    clauses = (_TRAIL.sub("", _LEAD.sub("", f"{part} ").rstrip()).strip() for part in _CLAUSES.split(text))
    return [clause for clause in clauses if clause and not re.fullmatch(_FILLER, clause)]


# Words that say what kind of thing it is, not which one: "my university's website" is about "university".
_GENERIC = frozenset({"my", "our", "the", "a", "an", "s", "website", "web", "site", "page", "homepage", "home",
                      "address", "url", "link", "portal", "official"})
_SOURCES = frozenset({"said", "approved"})  # written from the owner's words or a card he approved


def _words(text: str) -> set[str]:
    return set(re.sub(r"[^\w\s]", " ", text.lower().replace("'s", " ")).split())


def points_back(words: str) -> bool:
    """The owner's words point at an address already given, and at nothing else ("open that site again", "the one
    I just opened"); "find my university's website and open it" doesn't."""
    clauses = _bare_clauses(words)
    return bool(clauses) and all(_POINTING_CLAUSE.fullmatch(clause) for clause in clauses)


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
