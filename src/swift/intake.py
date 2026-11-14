"""The steps every input passes, in one order, and the rules each step applies (seams audit 2026-11, S2).

Swift hears and reads the owner through many doors: the hotkey, the open microphone (a wake phrase, a
reply, an answer to a question), typing, clicks. Each door used to carry its own copy of the rules, and
the copies drifted (D-01): "Swift, yes" reached the agent, a cough was an answer, "stop" answered a
question instead of stopping the run. The rules live here once; every door calls them.

The order (``STEPS``):

1. **presence**: nothing heard acts while the screen is locked or listening is paused (T-07);
2. **words**: an utterance with no words is nothing, never an answer (D-06); one the model was unsure
   of, while a question listens, is asked again on its card, never dropped in silence (T-06);
3. **question**: what is said while a question waits is for it, except a mid-run control during a
   run ("stop", "show me": D-08); a click on a question answers that question (D-07);
4. **approval**: who may approve what, from where (``approves``);
5. **carry-over**: "turn it back on", from the last change, beside a run too (D-04, D-05);
6. **mid-run**: the mid-run grammar;
7. **duplicate**: the same request again while it runs starts nothing (A-11);
8. **dispatch**: routing, after which only the agent needs a slot or the internet (S4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from swift.stt.transcriber import FILLERS, _bare

STEPS = ("presence", "words", "question", "approval", "carry_over", "midrun", "duplicate", "dispatch")

# Where an input came from.
#   voice: the hotkey held; wake / followup / answer / beside: the open microphone (hands-free);
#   typed: the text box; click: a button; over_speech: heard while Swift itself was talking.
Source = Literal["voice", "wake", "followup", "answer", "beside", "typed", "click", "over_speech"]
HANDS_FREE: frozenset[str] = frozenset({"wake", "followup", "answer", "beside", "hands_free"})
# Sources that stand for the owner speaking with the hotkey: debug text "as if spoken", "Try again" on a
# spoken request, and a change said on a card that runs as the next request.
SPOKEN_LIKE: dict[str, str] = {"debug.ask": "voice", "debug.say": "voice", "retry": "voice", "correction": "voice"}

# How an approval arrived (docs/product/action-authority.md §1): a gesture (a click on Swift's own button, or
# speech with the hotkey held: foundation decision 3), the open microphone with Swift's name, without it, or
# typed words (the name adds nothing for typing).
Channel = Literal["gesture", "named_voice", "plain_voice", "typed"]
# The level of what is approved (CLAUDE.md's table): 0 do it, 1 ask once (Swift's own question or offer),
# 2 a card, 3 its own card.
Level = Literal[0, 1, 2, 3]
# A confirm card. Levels 2 and 3 take the same channels except paying, which isn't built (decision 9);
# a paying card passes ``paying=True``.
CARD: Level = 2

# CLAUDE.md's "What approves" column, cell by cell (test_intake.py reads the table and checks this against it).
APPROVES: dict[int, frozenset[str]] = {
    0: frozenset({"gesture", "named_voice", "plain_voice", "typed"}),  # nothing needed
    1: frozenset({"gesture", "named_voice", "plain_voice"}),
    2: frozenset({"gesture", "named_voice"}),
    3: frozenset({"gesture", "named_voice"}),
}
PAYING: frozenset[str] = frozenset({"gesture"})  # level 3, paying: a gesture only (decision 9)


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    # Why not, when not: "typed" (typing never approves), "name" (hands-free needs Swift's name),
    # "gesture" (only a gesture pays), "over_speech" (nothing said over Swift's voice is a yes),
    # "source" (a door this table doesn't know: the strict rule).
    reason: str | None = None


ALLOWED = Verdict(True)


def channel(source: str, *, named: bool) -> Channel | None:
    """The channel an input from ``source`` arrived by; None for over Swift's voice or a door not known."""
    source = SPOKEN_LIKE.get(source, source)
    if source in ("click", "voice"):
        return "gesture"
    if source == "typed":
        return "typed"
    if source in HANDS_FREE:
        return "named_voice" if named else "plain_voice"
    return None


def approves(source: str, *, named: bool, level: Level, paying: bool = False) -> Verdict:
    """Whether a yes or "approve" from ``source`` approves something at ``level``: the one place approval is
    decided (foundation decision 10). Every door calls it; ``APPROVES`` is CLAUDE.md's table."""
    if SPOKEN_LIKE.get(source, source) == "over_speech":
        return Verdict(False, "over_speech")
    way = channel(source, named=named)
    if way is None:
        return Verdict(False, "source")
    if way in (PAYING if paying else APPROVES[level]):
        return ALLOWED
    return Verdict(False, "typed" if way == "typed" else "name" if way == "plain_voice" else "gesture")


def has_words(text: str | None) -> bool:
    """Whether an utterance said anything at all (a cough or a door comes back as no words: D-06)."""
    return bool(text and any(ch.isalnum() for ch in text))


# Mid-run controls: never an answer to a question while a request runs (D-08).
MIDRUN_CONTROLS: frozenset[str] = frozenset({"stop", "pause", "show", "hide", "resume"})


def for_question(midrun_action: str | None, *, run_working: bool) -> bool:
    """Whether something heard while a question waits is for the question: yes, unless it is a
    mid-run control ("stop", "show me") and a request is running; for any question, not only a run's."""
    return not (run_working and midrun_action in MIDRUN_CONTROLS)


def fragment(text: str | None) -> bool:
    """Nothing to give the agent: no words but hesitations ("Ah."). One word is a request like any
    other, even an unsure one: the model's confidence doesn't tell a misheard word from a clear one
    (a clean "Stop." scored 0.46, a misheard "Sure." 0.71: ``1a0ff5d``). Measure it on saved clips
    before adding a bar here (reliability review, 2026-11-05)."""
    return not [w for w in (_bare(t) for t in (text or "").split()) if w and w not in FILLERS]


def _norm(text: str) -> str:
    return " ".join(t.strip(" ,.!?;:-–—\"'").lower() for t in text.split() if t.strip(" ,.!?;:-–—\"'"))


def collapse_repeats(text: str) -> str:
    """The same request said twice in one breath, as the first saying ("Turn on Bluetooth. Turn on
    Bluetooth." went to the agent, which refused, 2026-11-05). Anything else is left as it is."""
    import re

    parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    if len(parts) > 1 and len({_norm(p) for p in parts}) == 1 and _norm(parts[0]):
        return parts[0]
    words = text.split()
    half = len(words) // 2
    if len(words) >= 4 and len(words) % 2 == 0 and _norm(" ".join(words[:half])) == _norm(" ".join(words[half:])):
        return " ".join(words[:half])
    return text
