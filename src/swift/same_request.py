"""Whether two requests are one: the same words said again, misheard in small ways, or cut off.

A7 (owner's run, 2026-11-13; owner checks 197, 250-252): comparing the exact words made "research the history
of T" and "...of tea" two requests, and "How are you? Can you turn off the" a second one beside "...the Wi-Fi?".
Tolerant only where it can't join two different requests: a system action is compared by what it does ("turn
it on" and "turn it off" never match), words by what is left once the words that change nothing are set aside.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9']+")
# Words that never change what a request asks for.
FILLER = frozenset({
    "a", "an", "the", "please", "can", "could", "would", "will", "you", "hey", "ok", "okay", "so", "just", "um", "uh",
    "swift",
})
# The speech model writes a word that sounds like a letter's name as the letter ("the history of T").
SOUNDS = {
    "t": "tea", "tee": "tea", "c": "see", "sea": "see", "b": "be", "bee": "be", "p": "pea", "pee": "pea",
    "u": "you", "r": "are", "y": "why", "q": "queue", "cue": "queue", "j": "jay", "k": "kay",
}
# Before the request said again, a few words that don't change it ("yes, turn off the Wi-Fi", heard as
# "He has turn off Wi Fi"); never these, which do.
LEAD_MAX = 2
TURNS = frozenset({"no", "not", "don't", "dont", "never", "stop", "cancel", "undo", "instead", "back", "again"})
# A cut-off copy has at least this many words that count, and at least half of the whole request's.
CUT_MIN = 3


def words(text: str) -> list[str]:
    """The words that say what a request asks for: case, punctuation, sound-alike letters and filler aside."""
    raw = _WORD.findall(text.lower().replace("wi-fi", "wifi").replace("wi fi", "wifi"))
    out = [SOUNDS.get(w, w) for w in raw]
    return [w for w in out if w not in FILLER]


def _intents(text: str) -> str | None:
    from swift.system import intents as it  # the grammar the lane uses, so "the same" means the same

    found = it.parse(text) if text.strip() else None
    if not found:
        return None
    return repr(sorted((i.name, sorted(i.slots.items())) for i in found))


def same_request(new: str, old: str, *, cut_off: bool = False) -> bool:
    """Whether ``new`` asks for what ``old`` asked: said again, a word misheard as its letter, filler words or a
    short lead-in more or less ("he has turn off Wi Fi"). ``cut_off``: also when ``new`` is the start of ``old``,
    cut short (the earlier one already has all of it, so nothing is lost by keeping only that one)."""
    a, b = _intents(new), _intents(old)
    if a is not None and b is not None:
        return a == b  # what it does decides: "turn on" and "turn off" are two requests
    wn, wo = words(new), words(old)
    if not wn or not wo:
        return False
    if wn == wo:
        return True
    extra = len(wn) - len(wo)
    if 0 < extra <= LEAD_MAX and len(wo) >= 2 and wn[extra:] == wo and not TURNS & set(wn[:extra]):
        return True
    return cut_off and len(wn) >= CUT_MIN and 2 * len(wn) >= len(wo) and wo[: len(wn)] == wn


__all__ = ["same_request", "words"]
