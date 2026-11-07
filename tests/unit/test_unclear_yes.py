"""A yes to "It sounded like …" goes ahead with what it sounded like (owner, 2026-11-08: "Yes, that's
correct." reached the agent on its own, which asked what was meant)."""

from __future__ import annotations

from typing import Any

import pytest
from settling import settled
from test_wake import make as make_wake

from swift.failures import Failure
from swift.session import PLAIN_YES


@pytest.mark.parametrize("text", ["Yes, that's correct.", "yes", "Yeah, go ahead.", "Correct.", "That's right" if False else "Right.", "Yes please"])
def test_a_plain_yes(text: str) -> None:
    assert PLAIN_YES.match(text)


@pytest.mark.parametrize("text", ["Yes, research the history of coffee", "No.", "yes and also email Sam", "What time is it?"])
def test_not_a_plain_yes(text: str) -> None:
    assert PLAIN_YES.match(text) is None


async def _offer(session: Any, heard_as: str) -> None:
    await session._send_failure(Failure("unclear_speech", "I didn't catch that", "x", ""), {"source": "wake", "transcript_heard": heard_as})


async def _say(session: Any, words: str, source: str = "followup") -> dict[str, Any]:
    async def capture(rec: dict[str, Any]) -> str:
        return words

    run = session._launch({"source": source, "executor": "echo"}, capture, session.executor, session.executor.start)
    await settled(session)
    assert run is not None
    return run.record or {}


async def test_yes_goes_ahead_with_what_it_sounded_like() -> None:
    session, out, records, _, _ = make_wake("")
    await _offer(session, "research the history of tea")
    await _say(session, "Yes, that's correct.")
    assert records[-1]["transcript"] == "research the history of tea" and records[-1]["confirmed_unclear"]


async def test_anything_else_ends_the_offer() -> None:
    session, out, records, _, _ = make_wake("")
    await _offer(session, "research the history of tea")
    await _say(session, "What time is it?")
    await _say(session, "yes")
    assert records[-1]["transcript"] == "yes"


async def test_typed_yes_is_not_taken() -> None:
    session, out, records, _, _ = make_wake("")
    await _offer(session, "research the history of tea")
    await _say(session, "yes", source="typed")
    assert records[-1]["transcript"] == "yes"


@pytest.mark.parametrize("heard_as", ["approve", "Swift, approve", "stop", "reject"])
async def test_a_yes_never_stands_for_a_control_phrase(heard_as: str) -> None:
    # A yes to "approve" would be a bare yes approving.
    session, out, records, _, _ = make_wake("")
    await _offer(session, heard_as)
    assert session._unclear_offer is None


async def test_a_lock_ends_the_offer() -> None:
    session, out, records, _, _ = make_wake("")
    await _offer(session, "research the history of tea")
    session._drop_heard()  # what a lock does with what was heard
    await _say(session, "yes")
    assert records[-1]["transcript"] == "yes"


async def test_a_card_on_screen_takes_the_yes_not_the_offer() -> None:
    session, out, records, _, _ = make_wake("")
    await _offer(session, "research the history of tea")
    session._open_confirm = lambda: "card-1"  # type: ignore[method-assign]
    await _say(session, "yes")
    assert records[-1]["transcript"] == "yes" and not records[-1].get("confirmed_unclear")
