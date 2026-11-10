"""Which of the contacts a search found the owner meant, by name (``find_contact``).

A search by one name finds everyone who has it: "Francis" finds Francis Chianu and Muthoni,
Francis. The owner said more than that ("draft an email to Francis Chianu"), so the matches are
narrowed by every word the owner gave, and then by the other names in their own words (owner
checks 2026-11-04: "Which Francis: …, Francis Chianu or Muthoni, Francis (IITA)?" after the
owner had said "Francis Chianu").

Speech gets surnames a little wrong ("Chianu" heard as "Cianu", "Chanu", "Chi Anu"), so a word
counts when it is close to a name (``close``). This only ever chooses among contacts the search
found: a recipient still comes only from the owner's contacts, and is still shown on the card.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Protocol

# How alike a heard word and a name must be ("cianu" ~ "chianu" 0.91, "chanu" 0.91, "ciano" 0.73).
CLOSE = 0.7
# Words too common to tell people apart.
_SKIP = {"the", "and", "for", "about", "with", "email", "mail", "draft", "send", "to", "my", "an", "a", "of",
         # A title says nothing about the name: "Dr Lovelace" names Ada Lovelace.
         "dr", "prof", "professor", "mr", "mrs", "ms", "miss", "mx", "sir", "dame"}


class Named(Protocol):
    name: str
    email: str


def words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())


def close(heard: str, name: str) -> bool:
    """Whether ``heard`` is ``name``, or close enough to be it as speech heard it."""
    if heard == name:
        return True
    if min(len(heard), len(name)) < 4:
        return False
    return SequenceMatcher(None, heard, name).ratio() >= CLOSE


def _said_words(said: str) -> list[str]:
    """The owner's words, and each pair of them joined ("chi anu" -> "chianu")."""
    w = [x for x in words(said) if x not in _SKIP]
    return w + [a + b for a, b in zip(w, w[1:], strict=False)]


def _name_words(contact: Named) -> list[str]:
    local = contact.email.split("@")[0]
    whole = "".join(words(contact.name))  # "Test Me" heard as "Testme"
    return [w for w in [*words(contact.name), *words(local), whole] if len(w) > 1]


def _has(contact: Named, heard: str, exact: bool) -> bool:
    return any(heard == n if exact else close(heard, n) for n in _name_words(contact))


def by_query(query: str, found: Sequence[Named], exact: bool = True) -> list[Named]:
    """The matches with every word of ``query`` in their name: "Francis Chianu" keeps Francis Chianu."""
    q = [w for w in words(query) if w not in _SKIP]
    if not q:
        return list(found)
    return [c for c in found if _all_named(c, q, exact)]


def _all_named(contact: Named, q: list[str], exact: bool) -> bool:
    """Every word of ``q`` is one of the contact's names; as heard, two words may be one ("chi anu")."""
    i = 0
    while i < len(q):
        if _has(contact, q[i], exact):
            i += 1
        elif not exact and i + 1 < len(q) and _has(contact, q[i] + q[i + 1], exact):
            i += 2
        else:
            return False
    return True


# Words that often follow a name and aren't one ("email Francis that I'm late", "… tomorrow").
_AFTER_A_NAME = {
    "that", "saying", "asking", "telling", "re", "regarding", "and", "or", "but", "if", "so", "because", "please",
    "tomorrow", "today", "tonight", "now", "again", "back", "at", "on", "in", "by", "from", "im", "we", "you", "its",
    "it", "is", "are", "was", "will", "can", "cc", "too", "also", "when", "what", "whether", "how", "why", "who",
    "this", "next", "here", "there", "then", "letting", "let", "tell", "ask", "say", "invite", "know",
    "these", "those", "our", "your", "his", "her", "their", "him", "them", "some", "all", "yesterday",
    "thanks", "thank", "thanking", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}


def said_otherwise(query: str, said: str, contact: Named) -> bool:
    """Whether the owner named someone else: a name they said right after the one searched for isn't
    this contact's ("Francis Chianu" said, "Francis" searched, only Muthoni, Francis found: X-01).
    Every place the name was said counts ("Francis, I mean Francis Chianu"). In words with capitals
    (speech is transcribed so), only a capitalised word can be a name: "Francis these photos" isn't."""
    q = [w for w in words(query) if w not in _SKIP]
    tokens = re.findall(r"[A-Za-z]+", said)
    s = [t.lower() for t in tokens]
    cased = any(t[:1].isupper() for t in tokens[1:])
    for i in range(len(s) - len(q) + 1):
        j = i + len(q)
        if not q or j >= len(s) or not all(close(s[i + k], w) for k, w in enumerate(q)):
            continue
        after = s[j]
        if len(after) < 3 or after in _SKIP or after in _AFTER_A_NAME or (cased and not tokens[j][:1].isupper()):
            continue
        if _has(contact, after, exact=False) or (j + 1 < len(s) and _has(contact, after + s[j + 1], exact=False)):
            continue  # this contact's own name, a split one included ("Chi Anu")
        return True
    return False


def narrow(query: str, said: str, found: Sequence[Named]) -> list[Named]:
    """Of several matches, the ones the owner named: by every word searched for, exactly and then
    as heard; then by the other names in the owner's own words. Unchanged when nothing tells them apart."""
    if len(found) < 2:
        return list(found)
    q = [w for w in words(query) if w not in _SKIP]
    if len(q) >= 2:
        for exact in (True, False):
            if kept := by_query(query, found, exact):
                if len(kept) < len(found):
                    found = kept
                break
    if len(found) < 2 or not said.strip():
        return list(found)
    heard = _said_words(said)

    def score(c: Named) -> int:
        # Single names only: the whole name run together ("francischianu") is close to "francis" alone.
        own = {w for w in words(c.name) + words(c.email.split("@")[0]) if len(w) > 2 and w not in q}
        return sum(1 for n in own if any(close(h, n) for h in heard))

    scores = [score(c) for c in found]
    best = max(scores)
    if best == 0:
        return list(found)
    return [c for c, s in zip(found, scores, strict=True) if s == best]
