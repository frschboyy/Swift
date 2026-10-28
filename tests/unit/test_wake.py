"""Wake phrase matching, utterance cutting, and starting an interaction from one."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from swift.audio.recorder import BLOCK, SAMPLE_RATE
from swift.executors.echo import EchoExecutor
from swift.ipc.protocol import Message
from swift.session import Session
from swift.wake import NoiseGate, WakeListener, match_wake

from test_recorder_preroll import FakeStream, fake_sd, make as make_recorder  # noqa: F401
from test_session import Recorder as Outbox
from test_voice import FakeTranscriber


@pytest.mark.parametrize(
    "text",
    [
        "Hey Swift",
        "hey, swift.",
        "Hello Swift!",
        "Hi Swift",
        "Good afternoon, Swift.",
        "good morning swift",
        "Good evening Swift",
        "OK Swift",
        "Okay, Swift",
        "hey swiff",  # mishearings
        "Hello swifty",
        "hey sift",
        "hallo swift",
        "good mourning swift",
        "Um, hey Swift",
        "Hey Swift's",
    ],
)
def test_wake_phrases_match(text: str) -> None:
    assert match_wake(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "Swift",  # the name alone
        "Hey",
        "Hello there",
        "Good afternoon",
        "I wrote it in Swift last week",
        "Then I said hey and he said swift",
        "hey there swift",  # not a greeting followed directly by the name
        "Good dog Swift",
        "Open the swift project",
        "",
    ],
)
def test_other_speech_does_not_match(text: str) -> None:
    assert match_wake(text) is None


def test_what_follows_the_phrase_is_the_request() -> None:
    m = match_wake("Good afternoon, Swift. What time is it?")
    assert m is not None and m.phrase == "good afternoon swift" and m.remainder == "What time is it?"
    assert match_wake("Hey Swift").remainder == ""  # type: ignore[union-attr]
    assert match_wake("hello swift, open my notes").remainder == "open my notes"  # type: ignore[union-attr]


def test_extra_greetings_from_settings() -> None:
    assert match_wake("wakey wakey swift") is None
    m = match_wake("Wakey wakey, Swift: list the files", ["wakey wakey"])
    assert m is not None and m.remainder == "list the files"


# ---- cutting the stream into utterances --------------------------------------------------


def block(amp: int) -> np.ndarray:
    return np.full((BLOCK, 1), amp, dtype=np.int16)


QUIET, LOUD = 5, 9000  # LOUD is about -11 dBFS


def feed(listener: WakeListener, quiet: int = 0, loud: int = 0) -> None:
    for _ in range(quiet):
        listener.feed(block(QUIET))
    for _ in range(loud):
        listener.feed(block(LOUD))


def test_speech_between_silences_is_one_utterance() -> None:
    got: list[tuple[np.ndarray, float]] = []
    listener = WakeListener(lambda a, t: got.append((a, t)))
    feed(listener, quiet=40)
    feed(listener, loud=30)  # ~1 s
    assert got == []  # not over until the silence has lasted
    feed(listener, quiet=30)
    assert len(got) == 1
    audio, ended = got[0]
    assert audio.dtype == np.int16 and 30 * BLOCK <= len(audio) <= (30 + 10 + 25) * BLOCK  # 0.8 s end pause
    assert abs(ended - time.monotonic()) < 1


def test_a_click_is_not_an_utterance_and_a_conversation_is_dropped() -> None:
    got: list[Any] = []
    listener = WakeListener(lambda a, t: got.append(a))
    feed(listener, quiet=40)
    feed(listener, loud=3)
    feed(listener, quiet=40)
    assert got == []
    feed(listener, loud=400)  # ~13 s of talking
    feed(listener, quiet=40)
    assert got == []
    feed(listener, loud=30)  # and it recovers for the next one
    feed(listener, quiet=40)
    assert len(got) == 1


def test_a_steady_noise_stops_counting_as_speech() -> None:
    gate = NoiseGate()
    assert gate.speech(0.05) is False
    assert gate.speech(0.7) is True
    gate = NoiseGate()
    levels = [gate.speech(0.4) for _ in range(900)]  # a fan: it passes for speech at first
    assert levels[0] is True and levels[-1] is False
    assert gate.speech(0.8) is True  # but real speech over it still counts


# ---- the recorder keeps the stream open and hands out the lead -------------------------------


def test_listening_recorder_taps_blocks_and_prepends_only_the_lead(fake_sd) -> None:  # noqa: F811
    from swift.audio.recorder import MicRecorder

    r = MicRecorder(asyncio.new_event_loop(), keep_open=True, lookback_s=1.0)
    tapped: list[int] = []
    r.tap = lambda b: tapped.append(int(b[0, 0]))
    r._open_stream()
    stream = FakeStream.instances[-1]
    for i in range(1, 41):  # 1.28 s: the ring holds the last 1 s
        stream.feed(i)
    assert tapped == list(range(1, 41))
    r.start(lambda _: None, lead_s=0.2)
    stream.feed(99)
    audio = r.stop()
    lead = int(np.ceil(0.2 * SAMPLE_RATE / BLOCK))
    assert len(audio) == (lead + 1) * BLOCK and audio[0] == 41 - lead
    assert stream.active  # stays open for the next phrase
    r.start(lambda _: None)  # a key press without a lead: no pre-roll configured, none added
    assert len(r.stop()) == 0


def test_a_failing_tap_does_not_stop_recording(fake_sd) -> None:  # noqa: F811
    from swift.audio.recorder import MicRecorder

    r = MicRecorder(asyncio.new_event_loop(), keep_open=True)
    r.tap = lambda b: 1 / 0
    r._open_stream()
    r.start(lambda _: None)
    FakeStream.instances[-1].feed(7)
    assert len(r.stop()) == BLOCK


# ---- starting an interaction -------------------------------------------------------------------


class LeadRecorder:
    """Records nothing; remembers how it was started, and lets the test play the owner's levels."""

    def __init__(self, seconds: float = 2.0) -> None:
        self.seconds = seconds
        self.recording = False
        self.capped = False
        self.lead: float | None = None
        self.on_level: Callable[[float], None] | None = None

    def start(self, on_level: Callable[[float], None], lead_s: float | None = None) -> None:
        self.recording, self.on_level, self.lead = True, on_level, lead_s

    def stop(self) -> np.ndarray:
        self.recording = False
        return np.zeros(int(self.seconds * SAMPLE_RATE), dtype=np.int16)


def make(text: str, seconds: float = 2.0, **kw: Any) -> tuple[Session, Outbox, list[dict[str, Any]], LeadRecorder, FakeTranscriber]:
    out, records, rec, stt = Outbox(), [], LeadRecorder(seconds), FakeTranscriber(text=text)
    session = Session(
        out, EchoExecutor(), recorder=rec, transcriber=stt, on_finish=records.append, tail_s=0.0,
        wake_end_silence_s=0.05, wake_start_timeout_s=0.2, **kw,
    )
    return session, out, records, rec, stt


AUDIO = np.zeros(SAMPLE_RATE, dtype=np.int16)


async def finish(session: Session) -> None:
    assert session._task is not None
    await asyncio.wait_for(session._task, 2)


async def test_phrase_with_request_runs_the_request_without_recording() -> None:
    session, out, records, rec, stt = make("Hey Swift, what time is it?")
    await session.hear_wake(AUDIO, time.monotonic())
    await finish(session)
    assert rec.lead is None and not rec.recording
    assert out.last("transcript") == {"text": "what time is it?", "final": True, "typed": False}
    assert out.states()[-1] == "result" and "It's " in out.last("result")["summary"]
    assert records[0]["source"] == "wake" and records[0]["status"] == "done"


async def test_bare_phrase_records_until_the_owner_stops_talking() -> None:
    session, out, records, rec, stt = make("")
    session_stt = FakeTranscriber(text="Hey Swift")
    session.transcriber = session_stt
    await session.hear_wake(AUDIO, time.monotonic() - 0.5)
    await asyncio.sleep(0)
    assert session.state == "listening" and rec.recording
    assert rec.lead is not None and 1.5 <= rec.lead < 2.5  # the 1 s phrase plus the 0.5 s since
    session_stt.text = "Hey Swift what time is it"
    assert rec.on_level is not None
    rec.on_level(0.8)  # talking...
    await asyncio.sleep(0.15)
    rec.on_level(0.0)  # ...and stops
    await finish(session)
    assert out.last("transcript")["text"] == "what time is it"
    assert out.states() == ["listening", "transcribing", "result"]


async def test_bare_phrase_then_silence_ends_quietly() -> None:
    session, out, records, rec, stt = make("Hey Swift")
    await session.hear_wake(AUDIO, time.monotonic())
    await asyncio.sleep(0)
    assert rec.on_level is not None
    rec.on_level(0.0)
    await asyncio.sleep(0.3)
    rec.on_level(0.0)  # past start_timeout_s
    await finish(session)
    assert out.states() == ["listening", "transcribing", "idle"]
    assert not [m for m in out.messages if m.type == "error"]
    assert records[0]["reason"] == "silence" and records[0]["status"] == "cancelled"


async def test_other_speech_is_dropped() -> None:
    session, out, records, rec, stt = make("I think swift is a nice language")
    await session.hear_wake(AUDIO, time.monotonic())
    assert stt.calls == 1 and out.messages == [] and records == [] and not rec.recording


async def test_a_wake_phrase_the_model_was_unsure_of_still_wakes() -> None:
    # Owner checks, 2026-10-27: the unsure filter ran before the match and dropped real wake phrases.
    words = "hey swift what time is it"
    session, out, records, rec, stt = make(words)
    probs = {"hey": 0.01, "swift": 0.01, "what": 0.7, "time": 0.7, "is": 0.7, "it": 0.75}  # mean 0.48 < 0.5
    session.transcriber = FakeTranscriber(text=words, probs=probs)
    await session.hear_wake(AUDIO, time.monotonic())
    await finish(session)
    assert records[0]["source"] == "wake" and records[0]["transcript"] == "what time is it"
    stats = session.take_wake_stats()
    assert stats["wake"] == 1 and stats["unsure_wake"] == 1 and stats["unsure"] == 0


async def test_a_request_after_the_wake_phrase_said_too_unsurely_asks_to_say_it_again() -> None:
    # Owner checks, 2026-10-27: acted on guesses; now the card says "Try saying it again".
    words = "hey swift ride a haiku about rain"
    session, out, records, rec, stt = make(words)
    session.transcriber = FakeTranscriber(text=words, probs=dict.fromkeys(words.split(), 0.35))
    await session.hear_wake(AUDIO, time.monotonic())
    await finish(session)
    assert records[0]["status"] == "error" and records[0]["error"] == "unclear_speech"
    assert out.last("error")["hint"] == "Try saying it again."


async def test_a_wake_phrase_below_the_lower_bar_is_still_ignored() -> None:
    words = "hey swift what time is it"
    session, out, records, rec, stt = make(words)
    session.transcriber = FakeTranscriber(text=words, probs=dict.fromkeys(words.split(), 0.1))
    await session.hear_wake(AUDIO, time.monotonic())
    assert out.messages == [] and records == [] and session._task is None
    assert session.take_wake_stats()["unsure"] == 1


async def test_unsure_speech_that_is_not_a_wake_phrase_keeps_the_bar_even_in_a_followup() -> None:
    words = "add it for tuesday"
    session, out, records, rec, stt = make(words)
    session.transcriber = FakeTranscriber(text=words, probs=dict.fromkeys(words.split(), 0.35))
    now = time.monotonic()
    session._followup = (now - 5, now + 5)
    await session.hear_wake(AUDIO, now)
    assert records == [] and session._task is None
    stats = session.take_wake_stats()
    assert stats["unsure"] == 1 and stats["followup"] == 0


async def test_nothing_starts_while_the_microphone_records_a_request() -> None:
    session, out, records, rec, stt = make("Hey Swift, what time is it?")
    await session.handle(Message("ptt", {"state": "down"}))
    await asyncio.sleep(0.01)
    assert session.state == "listening"
    await session.hear_wake(AUDIO, time.monotonic())
    assert stt.calls == 0  # its own words (or talk over them): not even transcribed
    await session.handle(Message("ptt", {"state": "up"}))
    await finish(session)


async def test_a_wake_phrase_while_the_last_request_starts_is_the_next_one() -> None:
    # Owner checks 20 and 21, 2026-10-27: dropped while the first was transcribed or started.
    session, out, records, rec, stt = make("Hey Swift, what time is it?")
    session._task = asyncio.create_task(asyncio.sleep(10))  # the last one, before its transcript
    try:
        await session.hear_wake(AUDIO, time.monotonic())
        assert stt.calls == 1 and session.take_wake_stats()["queued"] == 1
        assert out.last("heard")["source"] == "queued"
        await asyncio.wait_for(asyncio.gather(*(r.task for r in session._runs if r.task)), 2)
        assert records[-1]["queued_behind"] is True and records[-1]["transcript"] == "what time is it?"
    finally:
        session._task.cancel()


async def test_hotkey_pressed_while_transcribing_wins() -> None:
    session, out, records, rec, stt = make("Hey Swift, what time is it?")
    session.transcriber = FakeTranscriber(text="Hey Swift, what time is it?", delay=0.05)
    first = asyncio.create_task(session.hear_wake(AUDIO, time.monotonic()))
    await asyncio.sleep(0.01)
    await session.handle(Message("ptt", {"state": "down"}))  # the owner pressed the hotkey instead
    await first
    assert [r for r in records if r.get("source") == "wake"] == [] and session.wake_stats["skipped_busy"] == 1
    await session.handle(Message("ptt", {"state": "up"}))
    await finish(session)


# ---- staying responsive over hours (owner report, 2026-10-27) -----------------------------------


def test_continuous_sound_never_leaves_it_deaf_for_long() -> None:
    got: list[Any] = []
    listener = WakeListener(lambda a, t: got.append(a))
    feed(listener, quiet=40)
    for i in range(int(45 * SAMPLE_RATE / BLOCK)):  # 45 s of TV or a call: varying, never a pause
        listener.feed(block(LOUD if i % 2 == 0 else QUIET))
    assert listener.stats["forced_resets"] >= 1
    feed(listener, quiet=40)
    feed(listener, loud=30)
    feed(listener, quiet=40)
    assert len(got) >= 1 and len(got[-1]) <= (30 + 10 + 25) * BLOCK  # the next request is still heard


def test_counters_and_reset() -> None:
    listener = WakeListener(lambda a, t: None)
    feed(listener, quiet=40)
    feed(listener, loud=3)  # a click
    feed(listener, quiet=40)
    feed(listener, loud=30)
    feed(listener, quiet=40)
    stats = listener.take_stats()
    assert stats["utterances"] == 1 and stats["too_short"] == 1 and stats["blocks"] == 153 and stats["loudest"] > 0.5
    assert listener.take_stats()["blocks"] == 0  # counted since the last report
    feed(listener, loud=10)
    listener.reset()  # e.g. the stream was reopened mid-utterance
    feed(listener, quiet=40)
    assert listener.stats["utterances"] == 0


async def test_session_counts_where_each_utterance_went() -> None:
    session, out, records, rec, stt = make("I think swift is a nice language")
    await session.hear_wake(AUDIO, time.monotonic())
    words = "hey swift what time is it"
    session.transcriber = FakeTranscriber(text=words, probs=dict.fromkeys(words.split(), 0.1))  # all guesses
    await session.hear_wake(AUDIO, time.monotonic())
    stats = session.take_wake_stats()
    assert stats["heard"] == 2 and stats["other_speech"] == 1 and stats["unsure"] == 1 and stats["wake"] == 0
    assert session.take_wake_stats()["heard"] == 0


async def test_a_hung_transcription_doesnt_leave_wake_listening_deaf(monkeypatch: pytest.MonkeyPatch) -> None:
    import swift.session as session_module

    monkeypatch.setattr(session_module, "WAKE_STT_TIMEOUT_S", 0.05)
    session, out, records, rec, stt = make("Hey Swift, what time is it?")
    session.transcriber = FakeTranscriber(text="Hey Swift, what time is it?", delay=10)
    await session.hear_wake(AUDIO, time.monotonic())
    assert session.wake_stats["stt_timeout"] == 1 and session._hearing is False
    session.transcriber = FakeTranscriber(text="Hey Swift, what time is it?")
    await session.hear_wake(AUDIO, time.monotonic())  # the next one goes through
    await finish(session)
    assert records and records[-1]["source"] == "wake"
