"""Fixes from the owner checks of 2026-11-04 (checks 50-54).

1. A short answer in the reply window ("Yes.") heard right but below a reply's 0.7: taken.
2. "Hey Swift" said without a pause, written as one word ("Hayswift"): the wake phrase.
(The research answer kept whole is in test_claude_mapping.py.)
"""

from __future__ import annotations

import time

import pytest

from swift.wake import match_wake
from test_hands_free import finish
from test_voice_fixes_1700 import SHORT, answered, wake_session


@pytest.mark.parametrize("said", ["Yes.", "No, leave it.", "Yeah.", "Okay."])
async def test_a_short_answer_said_unsurely_is_still_a_reply(said: str) -> None:
    session, out, records, stt = wake_session()
    await answered(session, stt)
    stt.text = said
    stt.probs = dict.fromkeys(said.split(), 0.55)  # "Yes." at 0.54-0.65 on 2026-11-04
    await session.hear_wake(SHORT, time.monotonic())
    await finish(session)
    assert records[-1]["source"] == "followup" and records[-1].get("error") != "unclear_speech"
    assert records[-1]["transcript"] == said


async def test_a_short_answer_said_very_unsurely_is_not_taken() -> None:
    session, out, records, stt = wake_session()
    await answered(session, stt)
    stt.text, stt.probs = "Yes.", {"Yes.": 0.3}
    await session.hear_wake(SHORT, time.monotonic())
    await finish(session)
    assert len(records) == 1  # only the first request: a guess this unsure is never a reply


async def test_more_than_an_answer_keeps_the_reply_bar() -> None:
    session, out, records, stt = wake_session()
    await answered(session, stt)
    stt.text = "yes add it to friday"
    stt.probs = dict.fromkeys(stt.text.split(), 0.55)
    await session.hear_wake(SHORT, time.monotonic())
    await finish(session)
    assert records[-1]["error"] == "unclear_speech"


@pytest.mark.parametrize(
    ("text", "phrase", "rest"),
    [
        ("Hayswift researched the history of tea", "hayswift", "researched the history of tea"),
        ("Heyswift, what time is it?", "heyswift", "what time is it?"),
        ("um heyswift stop", "heyswift", "stop"),
        ("Okayswift, pause", "okayswift", "pause"),
    ],
)
def test_the_wake_phrase_heard_as_one_word(text: str, phrase: str, rest: str) -> None:
    match = match_wake(text)
    assert match is not None and match.phrase == phrase and match.remainder == rest
    assert len(match.phrase.split()) == 1  # one word the model wrote, dropped before judging the request


@pytest.mark.parametrize("text", ["hayfield is lovely", "heyswiftness", "Swiftly now", "hey there"])
def test_one_word_that_isnt_the_wake_phrase(text: str) -> None:
    assert match_wake(text) is None


async def test_a_joined_wake_phrase_starts_a_request() -> None:
    session, out, records, stt = wake_session()
    stt.text = "Hayswift what time is it"
    await session.hear_wake(SHORT, time.monotonic())
    await finish(session)
    assert records[-1]["source"] == "wake" and records[-1]["transcript"] == "what time is it"
