"""Confirming a reversible change without friction (owner checks 2026-11-04, check 124).

"Turn off Wi-Fi?" is its own card: the question, a quiet line on what it means, Yes and No. A plain
"yes" said, or a click on Yes, does it at once; typed, it doesn't (typing never approves). The answer
ends on the question's own card. Not said aloud unless ``speech.read_confirms``.
"""

from __future__ import annotations

import asyncio

from swift.ipc.protocol import Message
from swift.stt.transcriber import Transcription
from test_audit_2026_10 import _settle, _wifi_asked
from test_routing import ask
from test_system_lane import _session


async def _until(check, tries: int = 100) -> None:  # type: ignore[no-untyped-def]
    for _ in range(tries):
        if check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out")


async def test_the_answer_ends_on_the_questions_own_card() -> None:
    session, rec, _ = await _wifi_asked()
    card = rec.last("ask")["run_id"]
    assert rec.last("state")["state"] == "working" and rec.last("state")["run_id"] == card
    await session.handle(Message("ask.reply", {"ask_id": rec.last("ask")["ask_id"], "text": "Yes"}))
    await _settle(session)
    assert rec.last("result")["run_id"] == card and rec.last("result")["summary"] == "Wi-Fi off."
    await _until(lambda: rec.last("ask")["open"] is False)


async def test_a_click_on_no_leaves_it() -> None:
    session, rec, _ = await _wifi_asked()
    await session.handle(Message("ask.reply", {"ask_id": rec.last("ask")["ask_id"], "text": "No"}))
    await _settle(session)
    assert rec.last("result")["summary"] == "Okay, I've left it as it is."
    assert session.system.control.radio_state["wifi"] is True  # type: ignore[union-attr]


async def test_no_answer_says_so_on_the_card_and_waits_in_the_stack() -> None:
    session, rec, spy, records = await _session()
    session.wake_question_s = 0.05
    await ask("turn off bluetooth", session)
    card = rec.last("ask")["run_id"]
    await _until(lambda: rec.last("ask")["open"] is False)
    await _until(lambda: bool([m for m in rec.messages if m.type == "result"]))
    assert rec.last("result")["run_id"] == card
    assert rec.last("result")["summary"] == "No answer, so I've left it as it is."
    assert session.system.control.radio_state["bluetooth"] is True  # type: ignore[union-attr]


async def test_the_question_is_short_and_not_said_by_default() -> None:
    from test_dialogue import FakeSpeaker

    session, rec, spy, records = await _session()
    speaker = FakeSpeaker()
    session.speaker = speaker
    session._start_followup(Transcription("turn off the wifi", 300, 0.95))  # spoken
    await _settle(session)
    assert rec.last("ask")["question"] == "Turn off Wi-Fi?"
    assert not any("Wi-Fi" in s for s in speaker.said)
    session.read_confirms = True
    session._start_followup(Transcription("turn off bluetooth", 300, 0.95))
    await _settle(session)
    assert any(s == "Turn off Bluetooth?" for s in speaker.said)  # the question only, never the note
