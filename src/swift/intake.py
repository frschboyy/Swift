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

STEPS = ("presence", "words", "question", "approval", "carry_over", "midrun", "duplicate", "dispatch")

# Where an input came from.
#   voice: the hotkey held; wake / followup / answer / beside: the open microphone (hands-free);
#   typed: the text box; click: a button; over_speech: heard while Swift itself was talking.
Source = Literal["voice", "wake", "followup", "answer", "beside", "typed", "click", "over_speech"]
HANDS_FREE: frozenset[str] = frozenset({"wake", "followup", "answer", "beside", "hands_free"})
# Sources that stand for the owner speaking with the hotkey: debug text "as if spoken", "Try again" on a
# spoken request, and a change said on a card that runs as the next request.
SPOKEN_LIKE: dict[str, str] = {"debug.ask": "voice", "debug.say": "voice", "retry": "voice", "correction": "voice"}

# What is approved: a confirm card (something Swift or an agent will do), or a yes to Swift's own
# question about a reversible change the owner just asked for ("Turn off Wi-Fi?").
Target = Literal["card", "reversible"]


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    # Why not, when not: "typed" (typing never approves), "name" (hands-free needs Swift's name),
    # "over_speech" (nothing said over Swift's voice is a yes).
    reason: str | None = None


ALLOWED = Verdict(True)


def approves(source: str, *, named: bool, target: Target) -> Verdict:
    """Whether a yes or "approve" from ``source`` counts (CLAUDE.md, the product rules):

    | source             | a card           | Swift's reversible question |
    |--------------------|------------------|-----------------------------|
    | click              | yes              | yes                         |
    | voice (hotkey)     | yes              | yes                         |
    | hands-free         | only with name   | yes                         |
    | typed              | never            | only with name              |
    | over Swift's voice | never            | never                       |
    """
    source = SPOKEN_LIKE.get(source, source)
    if source == "over_speech":
        return Verdict(False, "over_speech")
    if source == "click" or source == "voice":
        return ALLOWED
    if source == "typed":
        if target == "card":
            return Verdict(False, "typed")
        return ALLOWED if named else Verdict(False, "name")
    if source in HANDS_FREE:
        if target == "reversible" or named:
            return ALLOWED
        return Verdict(False, "name")
    return Verdict(False, "name")  # a source this table doesn't know: the strict rule


def has_words(text: str | None) -> bool:
    """Whether an utterance said anything at all (a cough or a door comes back as no words: D-06)."""
    return bool(text and any(ch.isalnum() for ch in text))


# Mid-run controls: never an answer to a question while a request runs (D-08).
MIDRUN_CONTROLS: frozenset[str] = frozenset({"stop", "pause", "show", "hide", "resume"})


def for_question(midrun_action: str | None, *, run_working: bool) -> bool:
    """Whether something heard while a question waits is for the question: yes, unless it is a
    mid-run control ("stop", "show me") and a request is running; for any question, not only a run's."""
    return not (run_working and midrun_action in MIDRUN_CONTROLS)
