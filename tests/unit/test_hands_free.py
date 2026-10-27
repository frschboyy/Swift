"""Hands-free with wake listening on: answers during a run, and the follow-up window after one.

During a run the open microphone acts on "show me", "hide that", "stop" and "reject" without
the wake phrase; approving needs "Swift, approve" (threat model T2). After an answer it
takes a reply without the wake phrase for ``wake_followup_s``. Other speech is ignored.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

import numpy as np

from swift.audio.recorder import SAMPLE_RATE
from swift.executors.echo import EchoExecutor
from swift.executors.mock import MockExecutor
from swift.ipc.protocol import Message
from swift.session import HANDS_FREE_APPROVE_HINT, Session

from test_session import Recorder as Outbox
from test_voice import FakeTranscriber
from test_wake import LeadRecorder

# A short utterance, so it starts after the follow-up window opened.
SHORT = np.zeros(SAMPLE_RATE // 10, dtype=np.int16)


def make(scenario: str = "confirm", speed: float = 0.0, **kw: Any) -> tuple[Session, Outbox, list[dict[str, Any]], FakeTranscriber]:
    out, records, stt = Outbox(), [], FakeTranscriber(text="")
    mock = MockExecutor(speed=speed, default_scenario=scenario)
    session = Session(
        out, mock, debug_executor=mock, demo_speed=speed, recorder=LeadRecorder(), transcriber=stt,
        on_finish=records.append, tail_s=0.0, **kw,
    )
    return session, out, records, stt


async def say(session: Session, stt: FakeTranscriber, text: str) -> None:
    """Something said near the open microphone."""
    stt.text = text
    await session.hear_wake(SHORT, time.monotonic())


async def until_confirm(session: Session, out: Outbox) -> None:
    await session.handle(Message("debug.run", {"scenario": "confirm"}))
    await asyncio.wait_for(out.confirm.wait(), 2)
    assert session.state == "confirm"


async def finish(session: Session) -> None:
    assert session._task is not None
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(asyncio.shield(session._task), 2)


def voice(out: Outbox) -> list[dict[str, Any]]:
    return [m.data for m in out.messages if m.type == "confirm.voice"]


# ---- confirm cards ------------------------------------------------------------------------


async def test_a_bare_approve_is_not_enough() -> None:
    session, out, records, stt = make()
    await until_confirm(session, out)
    await say(session, stt, "Approve.")
    assert session.state == "confirm" and voice(out)[-1] == {
        "request_id": out.last("confirm.request")["request_id"], "phase": "hint", "text": HANDS_FREE_APPROVE_HINT,
    }
    await say(session, stt, "Swift, approve.")
    await finish(session)
    assert out.last("result")["status"] == "done"
    approval = records[0]["approvals"][0]
    assert approval["decision"] == "approve" and approval["source"] == "voice" and approval["hands_free"]


async def test_an_unsure_swift_approve_on_a_card_keeps_the_bar() -> None:
    # The lower bar for wake phrases is only for starting at rest: approving keeps it (T2).
    session, out, records, stt = make()
    await until_confirm(session, out)
    stt.probs = {"Swift,": 0.3, "approve.": 0.3}
    await say(session, stt, "Swift, approve.")
    assert session.state == "confirm" and session.take_wake_stats()["unsure"] == 1
    await session.cancel()


async def test_no_and_stop_work_without_the_wake_phrase() -> None:
    session, out, records, stt = make()
    await until_confirm(session, out)
    await say(session, stt, "No.")
    await finish(session)
    assert out.last("result")["status"] == "rejected"
    assert records[0]["approvals"][0]["decision"] == "reject"

    session, out, records, stt = make()
    await until_confirm(session, out)
    await say(session, stt, "stop")
    await finish(session)
    assert out.last("result")["status"] == "cancelled"


async def test_other_speech_near_a_card_is_ignored() -> None:
    session, out, records, stt = make()
    await until_confirm(session, out)
    before = len(out.messages)
    await say(session, stt, "did you see the game last night")
    assert len(out.messages) == before and session.state == "confirm"
    await session.cancel()


async def test_show_me_on_a_card_works_hands_free() -> None:
    session, out, records, stt = make()
    await until_confirm(session, out)
    await say(session, stt, "show me")
    assert out.last("view")["open"] is True and session.state == "confirm"
    await session.cancel()


# ---- during a run --------------------------------------------------------------------------


async def test_show_me_and_stop_during_a_run() -> None:
    session, out, records, stt = make("long", speed=0.2)
    await session.handle(Message("debug.run", {"scenario": "long"}))
    for _ in range(200):
        if session.state == "working":
            break
        await asyncio.sleep(0.01)
    await say(session, stt, "Show me.")
    assert out.last("view")["open"] is True
    before = len(out.messages)
    await say(session, stt, "anyway I was saying")  # not for Swift
    assert not [m for m in out.messages[before:] if m.type in ("run.voice", "view")]
    await say(session, stt, "stop")
    await finish(session)
    assert out.last("result")["status"] == "cancelled"
    assert records[0]["midrun"] == ["show", "stop"]


async def test_nothing_is_heard_while_the_hotkey_is_recording() -> None:
    session, out, records, stt = make()
    await until_confirm(session, out)
    session._confirm_voice = asyncio.create_task(asyncio.sleep(10))  # push-to-talk capture going
    try:
        await say(session, stt, "No.")
        assert stt.calls == 0 and session.state == "confirm"
    finally:
        session._confirm_voice.cancel()
        await session.cancel()


# ---- the follow-up window --------------------------------------------------------------------


def wake_session(followup_s: float) -> tuple[Session, Outbox, list[dict[str, Any]], FakeTranscriber]:
    out, records, stt = Outbox(), [], FakeTranscriber(text="")
    session = Session(
        out, EchoExecutor(), recorder=LeadRecorder(), transcriber=stt, on_finish=records.append, tail_s=0.0,
        wake_followup_s=followup_s,
    )
    return session, out, records, stt


async def test_a_reply_without_the_wake_phrase_just_after_an_answer() -> None:
    session, out, records, stt = wake_session(8.0)
    await say(session, stt, "Hey Swift, what time is it?")
    await finish(session)
    assert out.last("followup") == {"open": True, "seconds": 8.0, "question": False}
    await say(session, stt, "what's the date")
    await finish(session)
    assert records[1]["source"] == "followup" and records[1]["transcript"] == "what's the date"
    assert "It's " in out.last("result")["summary"]
    # The new request closed the window, and its own answer opened a new one.
    followups = [m.data["open"] for m in out.messages if m.type == "followup"]
    assert followups == [True, False, True]


async def test_after_the_window_speech_needs_the_wake_phrase_again() -> None:
    session, out, records, stt = wake_session(0.05)
    await say(session, stt, "Hey Swift, what time is it?")
    await finish(session)
    await asyncio.sleep(0.3)  # well past the window, including the utterance's own length
    await say(session, stt, "and what's the date")
    assert len(records) == 1 and not session.busy


async def test_speech_that_began_before_the_answer_is_not_a_reply() -> None:
    session, out, records, stt = wake_session(8.0)
    await say(session, stt, "Hey Swift, what time is it?")
    await finish(session)
    stt.text = "so as I was telling you"
    # A 3-second utterance ending now started before the window opened.
    await session.hear_wake(np.zeros(3 * SAMPLE_RATE, dtype=np.int16), time.monotonic())
    assert len(records) == 1 and not session.busy


async def test_no_window_unless_configured() -> None:
    session, out, records, stt = wake_session(0.0)
    await say(session, stt, "Hey Swift, what time is it?")
    await finish(session)
    assert not [m for m in out.messages if m.type == "followup"]
    await say(session, stt, "and what's the date")
    assert len(records) == 1


def test_the_name_alone_addresses_swift_only_for_answers() -> None:
    from swift.wake import match_address, match_wake

    assert match_wake("Swift, approve") is None  # never starts an interaction
    assert match_address("Swift, approve").remainder == "approve"  # type: ignore[union-attr]
    assert match_address("Hey Swift approve").remainder == "approve"  # type: ignore[union-attr]
    assert match_address("swiff approve").remainder == "approve"  # type: ignore[union-attr]
    assert match_address("I approve of Swift") is None


# ---- threads (ADR-013 §4) -----------------------------------------------------------------------


def threads(out: Outbox, kind: str = "result") -> list[str]:
    return [m.data["thread_id"] for m in out.messages if m.type == kind]


async def test_a_follow_up_continues_the_thread_and_a_new_request_starts_one() -> None:
    session, out, records, stt = wake_session(8.0)
    await say(session, stt, "Hey Swift, what time is it?")
    await finish(session)
    await say(session, stt, "what's the date")  # a reply in the follow-up window
    await finish(session)
    await asyncio.sleep(0)
    session._followup = None  # the window has closed
    await say(session, stt, "Hey Swift, what's the date")  # a new request
    await finish(session)
    first, reply, new = threads(out)
    assert first == reply != new
    assert [r["thread"] for r in records] == [first, first, new]
    # Every run message of a request carries its thread.
    assert all(m.data.get("thread_id") for m in out.messages if m.type in ("state", "result"))
