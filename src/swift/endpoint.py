"""When the owner has finished speaking (ADR-016 §5.1, "better endpointing").

Swift ends an utterance after a pause (``end_silence_s``, 0.8 to 0.9 s). People pause mid-thought
("set a timer for twenty … five minutes", "remind me to call Sam and … the dentist"), so a pause
alone cut them off. ``more_coming`` reads the words heard so far: a trailing "and", "uh", "the",
"for", or a number cut off mid-way ("twenty", "point") means the owner is still going, and Swift
keeps listening a little longer (``EndOfTurn.extend_s``), up to ``EndOfTurn.cap_s`` in all. When
the question Swift asked expects free text ("What should the message say?"), the pause that ends
it is longer (``EndOfTurn.free_s``): the owner is composing, not picking.

Pure functions and numbers only; the session and wake listening apply them. Measured against the
owner's saved recordings by ``spikes/endpointing/measure.py`` (counts only, nothing uploaded).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Words that can't end a request: a conjunction, a filler, an article, a preposition, a possessive.
TRAILING = frozenset(
    "and or but so because then plus also uh um er erm hmm like the a an to for with at in on of from into "
    "about my your his her their our this that these those is are was were be if when while which who whose "
    "than as by via per minus times over under after before until till".split()
)
# A number said in parts: "twenty" (five?), "two hundred" (and fifty?), "three point" (five?).
NUMBER_PARTS = frozenset(
    "twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million point oh".split()
)
_WORD = re.compile(r"[a-z']+|\d+")


def more_coming(text: str) -> bool:
    """Whether ``text`` (what was heard up to a pause) reads as cut off mid-thought."""
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.endswith(("?", "!")):
        return False
    if stripped.endswith((",", "...", "…", "-", "–", "—")):
        return True
    words = _WORD.findall(stripped.lower().replace("’", "'"))
    if not words:
        return False
    last = words[-1]
    if last in TRAILING:
        return True
    # "Twenty" alone is a whole answer ("For how long?" "Twenty."); after other words it may go on.
    return last in NUMBER_PARTS and len(words) > 1


@dataclass(frozen=True)
class EndOfTurn:
    """How long a pause ends what the owner says."""

    # The pause that ends an utterance (wake listening's default).
    silence_s: float = 0.8
    # ...when Swift asked a question that expects free text.
    free_s: float = 1.3
    # How much longer Swift waits each time the words so far say more is coming...
    extend_s: float = 1.2
    # ...and at most this much longer in all.
    cap_s: float = 3.0

    def silence(self, free_text: bool = False) -> float:
        return max(self.silence_s, self.free_s) if free_text else self.silence_s

    def extend(self, text: str, waited_s: float) -> float:
        """How much longer to wait after a pause, given the words so far (0: the turn is over)."""
        if not more_coming(text):
            return 0.0
        return max(0.0, min(self.extend_s, self.cap_s - waited_s))


__all__ = ["NUMBER_PARTS", "TRAILING", "EndOfTurn", "more_coming"]
