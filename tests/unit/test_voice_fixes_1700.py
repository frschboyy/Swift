"""The voice problems from the owner checks of 2026-10-27, 17:00.

1. Noise taken as speech, words missed: a speech gate that follows the room, replies without the
   wake phrase that must sound like the owner, "try saying it again" instead of a guess, and
   hesitations or the name not counted against a request.
2. A sign the moment Swift hears its name or the hotkey: "heard" (and the chime), before any
   transcription; from the start of a long utterance too.
3. A second request while the first is recorded or transcribed: recorded and run beside it.
4. Brisk control phrases: taken as they sounded ("so me": "show me"), and "no" on a card.
5. "Stop the research one" just after it finished: said so, never sent on as a request.
6. Coming back: the microphone reopens without re-listing every audio device first.
"""

from __future__ import annotations

from settling import settled

import asyncio
import io
import time
import wave
from typing import Any

import numpy as np

from swift.audio.chime import VOLUME, chime_wav
from swift.audio.recorder import BLOCK, SAMPLE_RATE
from swift.executors.echo import EchoExecutor
from swift.ipc.protocol import Message
from swift.session import Session
from swift.stt.transcriber import Transcription, Word, assess
from swift.wake import NoiseGate, WakeListener, close_control

from test_hands_free import finish, make as make_hands_free, say, until_confirm
from test_recorder_preroll import FakeStream, fake_sd  # noqa: F401 - the fake sounddevice fixture
from test_runs import finish_all, make as make_runs, started, until
from test_session import Recorder as Outbox
from test_voice import FakeTranscriber
from test_wake import LOUD, QUIET, LeadRecorder, feed

SHORT = np.zeros(SAMPLE_RATE // 10, dtype=np.int16)
AUDIO = np.zeros(SAMPLE_RATE, dtype=np.int16)


def wake_session(**kw: Any) -> tuple[Session, Outbox, list[dict[str, Any]], FakeTranscriber]:
    out, records, stt = Outbox(), [], FakeTranscriber(text="")
    heard: list[str] = []
    session = Session(
        out, EchoExecutor(), recorder=LeadRecorder(), transcriber=stt, on_finish=records.append, tail_s=0.0,
        wake_followup_s=8.0, on_heard=heard.append, wake_end_silence_s=0.05, wake_start_timeout_s=0.2, **kw,
    )
    session.heard_sounds = heard  # type: ignore[attr-defined]
    return session, out, records, stt


async def answered(session: Session, stt: FakeTranscriber) -> None:
    """"Hey Swift, what time is it" answered: the reply window is open."""
    await say(session, stt, "Hey Swift, what time is it?")
    await finish(session)


# ---- 1. noise, and words missed -----------------------------------------------------------------


def test_the_speech_gate_follows_the_room_not_a_fixed_level() -> None:
    quiet_room = NoiseGate()
    for _ in range(200):
        quiet_room.speech(0.02)  # about -59 dBFS between words
    assert quiet_room.speech(0.25)  # a normal voice (-48 dBFS): under the old fixed 0.3, never heard
    tv_room = NoiseGate()
    for _ in range(1000):
        tv_room.speech(0.4)  # half a minute of a TV in the room
    assert not tv_room.speech(0.5) and tv_room.speech(0.75)
    assert -61 < quiet_room.room_db < -57


def test_a_slow_request_with_a_pause_stays_one_utterance() -> None:
    got: list[Any] = []
    listener = WakeListener(lambda a, t, *_: got.append(a))
    feed(listener, quiet=40)
    feed(listener, loud=20)
    feed(listener, quiet=20)  # a 0.64 s pause between words: cut at 0.6 s before
    feed(listener, loud=20)
    feed(listener, quiet=40)
    assert len(got) == 1
    feed(listener, loud=250)  # 8 s: a slow, long request (dropped as too long over 6 s before)
    feed(listener, quiet=40)
    assert len(got) == 2 and listener.stats["too_long"] == 0


async def test_a_reply_quieter_than_the_room_allows_is_ignored() -> None:
    # 17:31:39: a TV's "We'll push west, haven't been through there..." in the reply window.
    session, out, records, stt = wake_session()
    await answered(session, stt)
    stt.text, stt.peak_db, stt.noise_db = "we'll push west, going house to house", -38.0, -50.0
    await session.hear_wake(SHORT, time.monotonic())
    assert len(records) == 1 and not session.busy
    assert session.take_wake_stats()["followup_quiet"] == 1


async def test_a_reply_far_quieter_than_the_owner_is_ignored() -> None:
    session, out, records, stt = wake_session()
    stt.peak_db, stt.noise_db = -12.0, -70.0  # the owner, close to the microphone
    await answered(session, stt)
    stt.text, stt.peak_db = "my neighbours wash their dishes, let's go on", -34.0  # across the room
    await session.hear_wake(SHORT, time.monotonic())
    assert len(records) == 1 and session.take_wake_stats()["followup_quiet"] == 1
    stt.text, stt.peak_db = "and the date?", -20.0  # the owner, a little further away
    await session.hear_wake(SHORT, time.monotonic())
    await finish(session)
    assert records[-1]["source"] == "followup" and records[-1]["transcript"] == "and the date?"


async def test_a_reply_said_unsurely_asks_to_say_it_again() -> None:
    session, out, records, stt = wake_session()
    await answered(session, stt)
    stt.text = "add it to friday"
    stt.probs = dict.fromkeys(stt.text.split(), 0.6)  # past wake.min_p (0.5), short of a reply's 0.7
    await session.hear_wake(SHORT, time.monotonic())
    await finish(session)
    assert records[-1]["status"] == "error" and records[-1]["error"] == "unclear_speech"
    assert out.last("error")["hint"] == "Try saying it again." and records[-1]["transcript_heard"] == "add it to friday"


async def test_a_long_stretch_of_talk_in_the_window_is_not_a_reply() -> None:
    session, out, records, stt = wake_session()
    await answered(session, stt)
    stt.text = "so anyway we drove all the way out there and it was closed"
    # Ten seconds of talk that ended now would have started before the window: make it start after.
    session._followup = (time.monotonic() - 20, time.monotonic() + 5)
    await session.hear_wake(np.zeros(9 * SAMPLE_RATE, dtype=np.int16), time.monotonic())
    assert len(records) == 1 and session.take_wake_stats()["followup_long"] == 1


def test_hesitations_and_the_name_dont_count_against_a_request() -> None:
    # 17:40:47, "Hey Crift, research about um Mozart": refused for "Crift" and "um".
    words = (Word("Hey", 0.3), Word("Crift,", 0.05), Word("research", 0.95), Word("about", 0.9), Word("um", 0.05),
             Word("Mozart.", 0.8))
    heard = Transcription("Hey Crift, research about um Mozart.", 300, 3.0, words=words)
    assert assess(heard) == "unclear"  # the name still counts on the whole...
    assert assess(heard.after(2)) == "clear"  # ...but not once it's set aside; "um" never counts
    assert heard.after(2).mean_p is not None and heard.after(2).mean_p > 0.85


async def test_the_hotkey_sets_a_misheard_name_aside() -> None:
    from test_voice import FakeRecorder

    out, records = Outbox(), []
    text = "Hey thrift, undo that."
    stt = FakeTranscriber(text=text, probs={"Hey": 0.9, "thrift,": 0.05, "undo": 0.95, "that.": 0.9})
    session = Session(out, EchoExecutor(), recorder=FakeRecorder(), transcriber=stt, on_finish=records.append, tail_s=0.0)
    await session.handle(Message("ptt", {"state": "down"}))
    await session.handle(Message("ptt", {"state": "up"}))
    assert session._task is not None
    await settled(session)
    assert records[0]["status"] != "error" and records[0]["transcript"] == text  # 17:59:06: refused


# ---- 2. a sign at once ---------------------------------------------------------------------------


async def test_the_hotkey_shows_and_sounds_heard_before_listening() -> None:
    session, out, records, stt = wake_session()
    await session.handle(Message("ptt", {"state": "down"}))
    await until(lambda: session.state == "listening")
    kinds = [m.type for m in out.messages]
    assert kinds.index("heard") < next(i for i, m in enumerate(out.messages) if m.type == "state")
    assert out.last("heard") == {"source": "ptt", "text": "Listening…"} and session.heard_sounds == ["ptt"]  # type: ignore[attr-defined]
    await session.handle(Message("ptt", {"state": "up"}))
    await finish(session)


async def test_the_wake_phrase_shows_heard_once_even_when_seen_early() -> None:
    session, out, records, stt = wake_session()
    stt.text = "Hey Swift, what"
    assert session.wants_peek()
    await session.peek_wake(AUDIO)  # the start of "hey Swift, what time is it", still being said
    assert out.last("heard")["source"] == "wake" and session.heard_sounds == ["wake"]  # type: ignore[attr-defined]
    await say(session, stt, "Hey Swift, what time is it?")
    await finish(session)
    assert [m.type for m in out.messages].count("heard") == 1 and session.heard_sounds == ["wake"]  # type: ignore[attr-defined]
    assert session.take_wake_stats()["peek_wake"] == 1


async def test_other_speech_never_shows_heard() -> None:
    session, out, records, stt = wake_session()
    stt.text = "I think swift is a nice"
    await session.peek_wake(AUDIO)
    await say(session, stt, "I think swift is a nice language")
    assert not [m for m in out.messages if m.type == "heard"] and session.heard_sounds == []  # type: ignore[attr-defined]


def test_the_listener_peeks_once_into_a_long_utterance_only_when_asked() -> None:
    peeks: list[int] = []
    allowed = [True]
    listener = WakeListener(lambda *a: None, on_peek=lambda a: peeks.append(len(a)), accept_peek=lambda: allowed[0])
    feed(listener, quiet=40)
    feed(listener, loud=80)  # 2.5 s
    feed(listener, quiet=40)
    assert len(peeks) == 1 and peeks[0] >= round(1.3 * SAMPLE_RATE / BLOCK) * BLOCK
    allowed[0] = False  # a run is going
    feed(listener, loud=80)
    feed(listener, quiet=40)
    assert len(peeks) == 1


def test_the_chime_is_short_and_soft() -> None:
    with wave.open(io.BytesIO(chime_wav())) as f:
        frames = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
        seconds = f.getnframes() / f.getframerate()
    assert 0.1 < seconds < 0.3
    assert np.abs(frames).max() <= VOLUME * 32767 + 1 and abs(int(frames[0])) < 50 and abs(int(frames[-1])) < 50


# ---- 3. a second request while the first is still being taken down -------------------------------


async def test_the_hotkey_while_the_last_request_is_transcribed_records_the_next() -> None:
    from test_voice import FakeRecorder

    out, records = Outbox(), []
    stt = FakeTranscriber(text="what time is it", delay=0.3)
    session = Session(out, EchoExecutor(), recorder=FakeRecorder(), transcriber=stt, on_finish=records.append, tail_s=0.0)
    await session.handle(Message("ptt", {"state": "down"}))
    await until(lambda: session.state == "listening")
    await session.handle(Message("ptt", {"state": "down"}))  # the key's own repeat: no second request
    assert len(session._runs) == 1
    await session.handle(Message("ptt", {"state": "up"}))
    await until(lambda: session.state == "transcribing")
    await session.handle(Message("ptt", {"state": "down"}))  # 17:22:44: "ptt ignored: busy"
    assert len(session._runs) == 2 and out.last("heard")["source"] == "queued"
    await until(lambda: session._runs[-1].state == "listening")
    await session.handle(Message("ptt", {"state": "up"}))
    await until(lambda: len(records) == 2, timeout=3)
    assert sorted(r.get("queued_behind", False) for r in records) == [False, True]
    assert all(r["status"] == "done" for r in records)


async def test_the_hotkey_during_a_hands_free_capture_holds_it_open() -> None:
    session, out, records, stt = wake_session()
    session.transcriber = FakeTranscriber(text="Hey Swift")
    await session.hear_wake(AUDIO, time.monotonic())
    await until(lambda: session.state == "listening")
    rec = session.recorder
    assert isinstance(rec, LeadRecorder) and rec.on_level is not None
    await session.handle(Message("ptt", {"state": "down"}))  # pressed while Swift listens after "hey Swift"
    rec.on_level(0.0)
    await asyncio.sleep(0.4)  # past start_timeout_s: without the key it would have ended
    rec.on_level(0.0)
    await asyncio.sleep(0.05)
    assert session.state == "listening" and rec.recording
    session.transcriber = FakeTranscriber(text="Hey Swift what time is it")
    await session.handle(Message("ptt", {"state": "up"}))
    await finish(session)
    assert records[-1]["transcript"] == "what time is it"


# ---- 4. brisk control phrases --------------------------------------------------------------------


def test_close_control_phrases() -> None:
    assert close_control("So me.") == "show me"
    assert close_control("Show be") == "show me"
    assert close_control("Stops.") == "stop"
    assert close_control("Go on") == "go on"
    assert close_control("So maybe") is None
    assert close_control("the game") is None
    assert close_control("show me the last five lines") is None  # only brisk clips


async def test_a_brisk_show_me_heard_as_so_me_shows_the_run() -> None:
    session, out, records, stt = make_hands_free("long", speed=0.2)
    await session.handle(Message("debug.run", {"scenario": "long"}))
    await until(lambda: session.state == "working")
    stt.text = "So me."
    await session.hear_wake(SHORT, time.monotonic(), True)
    assert out.last("view")["open"] is True
    stats = session.take_wake_stats()
    assert stats["short_close"] == 1 and stats["short_dropped"] == 0
    await session.cancel()


async def test_a_brisk_no_on_a_card_rejects_it_but_a_brisk_yes_never_approves() -> None:
    # 17:28: sixteen short clips on an open card, every one dropped.
    session, out, records, stt = make_hands_free()
    await until_confirm(session, out)
    for text in ("yes", "Swift, yes."):
        stt.text = text
        await session.hear_wake(SHORT, time.monotonic(), True)
    assert session.state == "confirm"
    stt.text = "No."
    await session.hear_wake(SHORT, time.monotonic(), True)
    await finish(session)
    assert records[0]["approvals"][0]["decision"] == "reject"


async def test_an_empty_short_clip_is_counted_apart() -> None:
    session, out, records, stt = make_hands_free()
    await until_confirm(session, out)
    stt.text = ""
    await session.hear_wake(SHORT, time.monotonic(), True)
    stats = session.take_wake_stats()
    assert stats["short_dropped"] == 1 and stats["short_empty"] == 1
    await session.cancel()


# ---- 5. naming a request that has just finished --------------------------------------------------


async def test_stop_the_research_one_after_it_finished_says_so() -> None:
    # Owner check 24 (17:39:02): sent to Claude Code, which offered to delete a calendar event.
    session, out, records, agent, stt = make_runs(wake_followup_s=8.0)
    research = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    await say_runs(session, stt, "Hey Swift, what time is it?")
    await until(lambda: out.last("result")["summary"].startswith("It's"))
    await say_runs(session, stt, "show me the research one")
    await until(lambda: out.last("runs")["focus"] == research)
    assert session._hands_free()  # listening for "stop the research one" now
    agent.runs[research]["go"].set()
    await until(lambda: out.last("result").get("run_id") == research)
    before = len(agent.requests)
    await say_runs(session, stt, "stop the research one")
    await until(lambda: "had already finished" in out.last("result")["summary"])
    assert len(agent.requests) == before
    await finish_all(session, agent)


async def say_runs(session: Session, stt: FakeTranscriber, text: str) -> None:
    stt.text = text
    await session.hear_wake(SHORT, time.monotonic())


async def test_stop_the_research_one_while_it_runs_in_front_after_show_me() -> None:
    session, out, records, agent, stt = make_runs(wake_followup_s=8.0)
    research = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    await say_runs(session, stt, "Hey Swift, what time is it?")
    await until(lambda: out.last("result")["summary"].startswith("It's"))
    await say_runs(session, stt, "show me the research one")
    await until(lambda: out.last("runs")["focus"] == research)
    await say_runs(session, stt, "stop the research one")
    await until(lambda: agent.cancelled == [research])
    await finish_all(session, agent)


# ---- 6. coming back ----------------------------------------------------------------------------


def test_coming_back_reopens_the_microphone_without_relisting_devices(fake_sd: Any, monkeypatch: Any) -> None:  # noqa: F811
    from swift.audio import recorder as rec_module
    from swift.audio.recorder import MicRecorder

    refreshed: list[int] = []
    monkeypatch.setattr(rec_module, "_refresh_devices", lambda: refreshed.append(1))
    r = MicRecorder(asyncio.new_event_loop(), keep_open=True)
    r._open_stream()
    r.pause()
    r.resume()
    assert refreshed == [] and FakeStream.instances[-1].active
    r.pause()
    fails = iter([True, False])
    real = rec_module.MicRecorder._open_stream

    def open_once_failing(self: Any) -> None:
        fake_sd.fail = next(fails)
        real(self)

    monkeypatch.setattr(rec_module.MicRecorder, "_open_stream", open_once_failing)
    r.resume()  # the old list no longer works (a headset unplugged while locked): list again, then open
    assert refreshed == [1] and FakeStream.instances[-1].active


def test_quiet_and_loud_blocks_still_cut_utterances() -> None:
    got: list[Any] = []
    listener = WakeListener(lambda a, t, *_: got.append(a))
    for _ in range(3):
        feed(listener, quiet=40)
        feed(listener, loud=30)
    feed(listener, quiet=40)
    assert len(got) == 3 and QUIET < LOUD
