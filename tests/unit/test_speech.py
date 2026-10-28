"""Swift speaks (ADR-016 §4, Phase B): the spoken form, when to speak, barge-in, and never hearing itself."""

from __future__ import annotations

import asyncio
import time

import pytest
from test_routing import ask
from test_system_lane import NOW, _session
from test_wake import AUDIO, finish, make

from swift.ipc.protocol import Message
from swift.speech import MAX_SPOKEN, FakeSpeaker, Speaker, spoken

# ---- the spoken form ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("Volume 50.", "Volume 50."),
        ("## Result\n\nI've **updated** `session.py` and the [docs](http://x). Tests pass. Then more.",
         "I've updated session.py and the docs. Tests pass."),
        ("- one\n- two", "one two"),
        ("See https://example.com/a?b=c for more.", "See a link for more."),
        ("Done ✅", "Done"),
        ("```python\nprint(1)\n```\nThat prints one.", "That prints one."),
    ],
)
def test_spoken_form(text: str, said: str) -> None:
    assert spoken(text) == said


def test_a_long_answer_is_cut_at_a_sentence_and_never_too_long() -> None:
    long = " ".join(f"Sentence number {i} says something fairly ordinary here." for i in range(20))
    said = spoken(long)
    assert len(said) <= MAX_SPOKEN and said.endswith(".") and said.count(".") <= 2
    one = "word " * 200
    assert len(spoken(one)) <= MAX_SPOKEN + 1 and spoken(one).endswith("…")


def test_recently_covers_the_tail_after_speaking() -> None:
    s = FakeSpeaker()
    s.speak("hello")
    assert s.recently(time.monotonic())
    s.finish()
    assert s.recently(time.monotonic()) and not s.recently(time.monotonic() + 5)
    assert not Speaker().recently(time.monotonic() + 5)


# ---- when Swift speaks ----------------------------------------------------------------------


def _speaking_session(**kw):  # type: ignore[no-untyped-def]
    session, out, records, rec, stt = make("Hey Swift, what time is it?", **kw)
    speaker = FakeSpeaker()
    session.speaker = speaker
    speaker.on_done = session.speech_done
    return session, out, records, speaker


async def test_a_spoken_request_gets_a_spoken_answer() -> None:
    session, out, records, speaker = _speaking_session()
    await session.hear_wake(AUDIO, time.monotonic())
    await finish(session)
    assert speaker.said and speaker.said[0].startswith("It's ")
    assert records[0]["spoken_chars"] == len(speaker.said[0])


async def test_a_typed_or_debug_request_is_silent_on_auto() -> None:
    session, rec, _, _ = await _session(volume=40)
    session.speaker = FakeSpeaker()
    await ask("volume up", session)  # debug.ask: like typing
    assert rec.last("result")["summary"] == "Volume 50." and session.speaker.said == []  # type: ignore[attr-defined]


async def test_always_speaks_everything_and_never_nothing() -> None:
    session, _, _, _ = await _session(volume=40)
    session.speaker = FakeSpeaker()
    session.speech_replies = "always"
    await ask("volume up", session)
    assert session.speaker.said == ["Volume 50."]  # type: ignore[attr-defined]
    session.speech_replies = "never"
    await ask("volume up", session)
    assert session.speaker.said == ["Volume 50."]  # type: ignore[attr-defined]


async def test_nothing_is_said_while_the_owner_is_away() -> None:
    session, out, _, speaker = _speaking_session()
    await session.hold_cards(True)
    await session.hear_wake(AUDIO, time.monotonic())
    if session._task is not None:
        await finish(session)
    assert speaker.said == []


async def test_a_failure_is_said_too() -> None:
    session, _, _, _ = await _session(brightness=None)
    session.speaker = FakeSpeaker()
    session.speech_replies = "always"
    await ask("brightness down", session)
    assert session.speaker.said == ["This display doesn't let Windows change its brightness."]  # type: ignore[attr-defined]


async def test_a_due_timer_is_said_even_though_nobody_asked_by_voice() -> None:
    session, _, _, _ = await _session()
    session.speaker = FakeSpeaker()
    assert session.system is not None
    item = session.system.scheduler.add("timer", NOW.timestamp(), "tea")
    await session.notify_due(item, False)
    assert session.speaker.said == ["Your tea timer is up."]  # type: ignore[attr-defined]


# ---- barge-in -------------------------------------------------------------------------------


async def test_the_hotkey_and_esc_cut_swift_off() -> None:
    session, _, _, speaker = _speaking_session()
    speaker.speak("A long answer")
    await session.handle(Message("cancel", {}))
    assert not speaker.speaking and speaker.stopped == 1
    speaker.speak("Another")
    session.recorder = None  # the press stops speech before anything is recorded
    await session.handle(Message("ptt", {"state": "down"}))
    assert not speaker.speaking and speaker.stopped == 2


async def test_typing_cuts_swift_off() -> None:
    session, _, _, speaker = _speaking_session()
    speaker.speak("A long answer")
    await session.handle(Message("text", {"text": "what time is it"}))
    assert not speaker.speaking


# ---- half-duplex: Swift never hears itself ---------------------------------------------------


async def test_what_the_microphone_hears_while_swift_talks_is_dropped() -> None:
    session, out, records, speaker = _speaking_session()
    speaker.speak("It's 14:05.")  # the room now has Swift's own voice in it
    await session.hear_wake(AUDIO, time.monotonic())
    assert session._task is None and records == [] and session.wake_stats["own_voice"] == 1
    assert not session.wants_short() and not session.wants_peek()
    speaker.finish()
    await asyncio.sleep(0)
    await session.hear_wake(AUDIO, time.monotonic() + 2.0)  # began a second after Swift stopped: heard again
    await finish(session)
    assert records and records[0]["status"] == "done"


async def test_the_reply_window_starts_when_swift_stops_talking() -> None:
    session, out, _, speaker = _speaking_session(wake_followup_s=6.0)
    await session.hear_wake(AUDIO, time.monotonic())
    await finish(session)
    assert session._followup is not None and speaker.speaking
    first = session._followup
    await asyncio.sleep(0.05)
    speaker.finish()
    await asyncio.sleep(0.01)
    assert session._followup is not None and session._followup[0] > first[0]  # reopened after the voice
