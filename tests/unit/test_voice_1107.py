"""The owner's checks of 2026-11-07: "Hey Swift" that didn't register, a new request taken for a change
to the card on screen, the same request three times, a terminal command to read, and Swift's voice."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest
from settling import settled
from test_hands_free import make, say, until_confirm
from test_wake import AUDIO
from test_wake import make as make_wake

from swift.executors.claude_mapping import confirm_card
from swift.ipc.protocol import Message
from swift.parked import Parked, ParkedThreads
from swift.settings import SpeechSettings
from swift.speech import FakeSpeaker
from swift.wake import match_address, match_wake, near_wake
from swift.workflows import tools as tools_module

# ---- the wake phrase, as the speech model really writes it -------------------------------------


@pytest.mark.parametrize("text", ["He swift.", "He's swift.", "K Swift.", "Hail Swift.", "Be Swift.", "A swift", "He swift, what time is it?"])
def test_what_the_model_writes_for_hey_starts_a_request(text: str) -> None:
    # Replayed from the owner's saved misses: each of these was the owner saying "Hey Swift".
    assert match_wake(text) is None
    assert match_wake(text, loose=True) is not None


@pytest.mark.parametrize("text", [
    "He's swift about it", "Be swift about it", "A swift response would help", "He said swift", "Swift", "He",
    "Then he's swift.", "He's swifter than me",
])
def test_ordinary_speech_still_doesnt_start_anything(text: str) -> None:
    assert match_wake(text, loose=True) is None


def test_the_remainder_is_the_request() -> None:
    m = match_wake("He swift, what time is it?", loose=True)
    assert m is not None and m.remainder == "what time is it?"


@pytest.mark.parametrize("text", ["A shift, please call Bob", "Be Swift, delete my files", "He swiff, send it", "K Swiss, go ahead"])
def test_a_loose_match_with_words_after_it_needs_the_name_as_said(text: str) -> None:
    assert match_wake(text, loose=True) is None


@pytest.mark.parametrize("text", ["He swift.", "A shift."])
def test_alone_it_only_opens_the_microphone(text: str) -> None:
    m = match_wake(text, loose=True)
    assert m is not None and m.remainder == ""


@pytest.mark.parametrize("text", ["He swift, approve.", "K Swift, approve", "Hail Swift, yes"])
def test_the_forgiving_match_never_counts_as_the_name_for_approving(text: str) -> None:
    assert match_address(text) is None


def test_a_near_miss_makes_the_next_try_easier_for_a_few_seconds() -> None:
    assert near_wake("He's sweet.") and near_wake("Hey twif")
    assert not near_wake("What day is it?") and not near_wake("He went home.")


async def test_after_a_near_miss_the_same_words_start_it() -> None:
    session, _, records, _, stt = make_wake("He's sweet.")
    await session.hear_wake(AUDIO, time.monotonic())
    assert session.take_wake_stats()["near_wake"] == 1 and session._task is None
    stt.text = "He's sweet."
    await session.hear_wake(AUDIO, time.monotonic())
    assert session.take_wake_stats()["wake"] == 1
    await session.cancel()


async def test_after_a_near_miss_words_after_it_start_nothing() -> None:
    session, _, records, _, stt = make_wake("He's sweet.")
    await session.hear_wake(AUDIO, time.monotonic())
    stt.text = "He's sweet. Delete my files."
    await session.hear_wake(AUDIO, time.monotonic())
    assert session.take_wake_stats()["wake"] == 0 and session._task is None


# ---- a lock ends what the open microphone was hearing ----------------------------------------------


async def test_a_lock_during_a_bare_capture_starts_nothing() -> None:
    session, out, records, rec, stt = make_wake("Hey Swift")
    session.speaker, session.speech_replies, session.wake_greeting = FakeSpeaker(), "never", "Hello"
    await session.hear_wake(AUDIO, time.monotonic())
    await asyncio.sleep(0)
    assert session.state == "listening"
    stt.text = "Hey Swift. Research the history of tea."
    session.listening_paused = True
    session._drop_heard()
    await settled(session)
    assert not rec.recording
    assert not any(r.get("transcript") for r in records)
    assert not any("tea" in str(m.data) for m in out.messages if m.type == "transcript")


async def test_a_lock_before_the_capture_begins_records_nothing() -> None:
    # From the review: the gap before it reaches "listening", where ``_drop_heard`` can't see it.
    session, out, records, rec, stt = make_wake("Hey Swift")
    await session.hear_wake(AUDIO, time.monotonic())
    session.listening_paused = True
    await settled(session)
    assert rec.lead is None and not rec.recording
    assert "audio_s" not in records[0] or not records[0].get("transcript")


async def test_a_lock_while_it_is_transcribed_starts_nothing() -> None:
    session, out, records, rec, stt = make_wake("Hey Swift")
    await session.hear_wake(AUDIO, time.monotonic())
    await asyncio.sleep(0)
    stt.text = "Hey Swift. Research the history of tea."
    assert rec.on_level is not None
    rec.on_level(0.8)
    await asyncio.sleep(0.15)
    session.hands_free_blocked = True  # locked, with the recording finishing
    rec.on_level(0.0)
    await settled(session)
    assert records[0]["status"] == "cancelled" and "transcript" not in records[0]


async def test_no_hello_while_locked() -> None:
    session, _, _, _, _ = make_wake("Hey Swift")
    session.speaker, session.wake_greeting = FakeSpeaker(), "Hello"
    session.hands_free_blocked = True
    assert session._greet() is False and session.speaker.said == []  # type: ignore[attr-defined]


# ---- a new request isn't a change to the card ----------------------------------------------------


async def test_a_new_request_said_on_a_card_runs_beside_it_and_the_card_stays() -> None:
    # 2026-11-07, three times: "research the history of tea" on a weather card became "Changing it: ...".
    session, out, records, stt = make()
    await until_confirm(session, out)
    await say(session, stt, "Swift, research the history of tea.")
    await asyncio.sleep(0)
    assert session.state == "confirm" and out.confirm.is_set()
    approval = session._record["approvals"][0]  # type: ignore[index]
    assert approval.get("decision") != "revise"
    assert any(r.words == "research the history of tea." for r in session._live())
    await session.cancel()


@pytest.mark.parametrize("change", [
    "Swift, make it Friday at three", "Swift, actually Thursday instead", "Swift, send that to Priya",
    "Swift, do Friday at three", "Swift, find a later time",
])
async def test_a_change_to_the_card_is_still_a_change(change: str) -> None:
    session, out, records, stt = make()
    await until_confirm(session, out)
    before = len(session._live())
    await say(session, stt, change)
    assert len(session._live()) <= before  # nothing started beside it
    await session.cancel()


# ---- "hey Swift" with something already going ----------------------------------------------------


async def test_a_bare_wake_phrase_during_a_run_opens_a_new_request() -> None:
    session, out, records, stt = make(scenario="long", speed=1.0, wake_end_silence_s=0.05, wake_start_timeout_s=0.2)
    await session.handle(Message("debug.run", {"scenario": "long"}))
    for _ in range(200):
        if session.state == "working":
            break
        await asyncio.sleep(0.01)
    assert session.state == "working"
    running = len(session._live())
    stt.text = "Hey Swift"
    await session.hear_wake(AUDIO, time.monotonic())
    assert session.take_wake_stats()["queued"] == 1
    assert len(session._live()) == running + 1
    await session.cancel()


async def _bare_capture_says(session: Any, stt: Any, words: str, name: str = "Hey Swift") -> None:
    """A bare wake phrase on the card, then ``words`` spoken into its capture to the end."""
    stt.text = name
    await session.hear_wake(AUDIO, time.monotonic())
    await asyncio.sleep(0.01)
    capture = session._listening_run()
    assert capture is not None
    stt.text = words
    assert session.recorder.on_level is not None
    session.recorder.on_level(0.8)
    await asyncio.sleep(0.15)
    session.recorder.on_level(0.0)
    for _ in range(200):  # its words are in: it may go on as a request of its own
        if capture.task.done() or capture.state not in ("listening", "transcribing"):
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.02)


@pytest.mark.parametrize("words", ["Hey Swift. Approve.", "Hey Swift. Yes.", "Hey Swift. Go ahead."])
async def test_a_bare_wake_phrase_on_a_card_never_approves_with_what_follows(words: str) -> None:
    session, out, records, stt = make(wake_end_silence_s=0.05, wake_start_timeout_s=0.2)
    await until_confirm(session, out)
    await _bare_capture_says(session, stt, words)
    assert session.state == "confirm"
    assert session._focus.record["approvals"][0].get("decision") is None  # type: ignore[union-attr]
    await session.cancel()


async def test_a_bare_wake_phrase_then_a_change_changes_the_card() -> None:
    session, out, records, stt = make(wake_end_silence_s=0.05, wake_start_timeout_s=0.2)
    await until_confirm(session, out)
    entry = session._focus.record["approvals"][0]  # type: ignore[union-attr]
    await _bare_capture_says(session, stt, "Hey Swift. Make it Friday at three.")
    assert entry.get("heard") == ["Make it Friday at three."]
    await session.cancel()


async def test_something_like_the_name_is_not_the_name_for_a_change() -> None:
    # From the review: "A shift.", then room speech, ended the card's request.
    session, out, records, stt = make(wake_end_silence_s=0.05, wake_start_timeout_s=0.2)
    await until_confirm(session, out)
    focus = session._focus
    entry = focus.record["approvals"][0]  # type: ignore[union-attr]
    await _bare_capture_says(session, stt, "We'll push west through there tonight.", name="A shift.")
    assert not entry.get("heard") and focus.alive
    await session.cancel()


async def test_a_loose_wake_phrase_with_a_request_during_a_run_runs_beside() -> None:
    session, out, records, stt = make(scenario="long", speed=1.0)
    await session.handle(Message("debug.run", {"scenario": "long"}))
    for _ in range(200):
        if session.state == "working":
            break
        await asyncio.sleep(0.01)
    before = len(session._live())
    stt.text = "He swift, research the history of tea."
    await session.hear_wake(AUDIO, time.monotonic())
    assert len(session._live()) == before + 1
    await session.cancel()


async def test_words_after_a_bare_wake_phrase_are_heard_once() -> None:
    # From the review: the open microphone answered the card while the capture recorded the same words.
    session, out, records, stt = make(wake_end_silence_s=0.05, wake_start_timeout_s=0.2)
    await until_confirm(session, out)
    stt.text = "Hey Swift"
    await session.hear_wake(AUDIO, time.monotonic())
    await asyncio.sleep(0.01)
    assert session._listening_run() is not None
    await say(session, stt, "Reject.")
    assert session.state == "confirm" and session.take_wake_stats()["skipped_busy"] >= 1
    await session.cancel()


# ---- the same request ----------------------------------------------------------------------------


async def test_the_same_words_by_the_hotkey_while_it_runs_are_one_request() -> None:
    # The hotkey and a bare wake phrase only know their words after the capture: 2026-11-07, three of the same.
    session, out, records, stt = make(scenario="long", speed=1.0)
    await session.handle(Message("debug.run", {"scenario": "long"}))
    await asyncio.sleep(0.05)
    first = session._live()[0]
    first.words = "is it going to rain this afternoon?"

    async def capture(rec: dict[str, Any]) -> str:
        return "Hey Swift, is it going to rain this afternoon?"

    again = session._launch({"source": "voice", "executor": "mock"}, capture, session.executor, session.executor.start, title="Next request")
    await asyncio.wait_for(asyncio.shield(again.task), 2)  # type: ignore[arg-type]
    assert [r for r in session._live()] == [first]
    assert any(r.get("duplicate") for r in records)
    await session.cancel()


def _parked(thread: str, words: str) -> Parked:
    return Parked(thread=thread, request=words, reason="stopped", at=time.time())


def test_asking_again_replaces_the_unfinished_one(tmp_path: Path) -> None:
    store = ParkedThreads(tmp_path / "parked.json")
    store.park(_parked("a", "Is it going to rain this afternoon?"))
    store.park(_parked("b", "is it going to rain this afternoon"))
    assert [p.thread for p in store.all()] == ["b"]
    store.park(_parked("c", "Research the history of tea"))
    assert store.drop_same("Is it going to rain, this afternoon?") is True
    assert [p.thread for p in store.all()] == ["c"]
    assert store.drop_same("something else") is False


async def test_a_brisk_loose_wake_phrase_isnt_dropped_as_too_short() -> None:
    session, _, _, _, _ = make_wake("He swift.")
    assert session._short_kept("He swift.", False) == "He swift."
    assert session._short_kept("He went.", False) is None
    await session.cancel()


async def test_a_primed_capture_leaves_the_near_miss_out_of_the_request() -> None:
    session, out, records, rec, stt = make_wake("He's sweet.")
    await session.hear_wake(AUDIO, time.monotonic())
    await session.hear_wake(AUDIO, time.monotonic())
    await asyncio.sleep(0)
    stt.text = "He's sweet. What time is it?"
    assert rec.on_level is not None
    rec.on_level(0.8)
    await asyncio.sleep(0.15)
    rec.on_level(0.0)
    await settled(session)
    assert out.last("transcript")["text"] == "What time is it?"


def test_a_named_resume_keeps_its_thread(tmp_path: Path) -> None:
    store = ParkedThreads(tmp_path / "parked.json")
    store.park(_parked("a", "finish the email to Ada"))
    assert store.find("finish the email to Ada") is not None  # so the session leaves it for the resume


# ---- what a card says about a command ------------------------------------------------------------


@pytest.mark.parametrize("command", [
    "git commit -m 'wip'",
    "curl -s https://a.example/",
    "curl -s\nshutdown.exe -s -f",
    "curl -s https://a.example/?x&calc.exe",
])
@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
def test_a_command_says_what_it_is_and_never_claims_what_it_does(tool: str, command: str) -> None:
    title, detail = confirm_card(tool, {"command": command})
    assert title == "Run a command on your PC" and detail == command.strip()


async def test_the_weather_tool_takes_nothing_from_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    raw: dict[str, Any] = {
        "current_condition": [{"temp_C": "14", "FeelsLikeC": "12", "weatherDesc": [{"value": "Cloudy"}]}],
        "nearest_area": [{"areaName": [{"value": "Nairobi"}], "country": [{"value": "Kenya"}]}],
        "weather": [{"maxtempC": "20", "mintempC": "11", "hourly": [
            {"time": "1500", "chanceofrain": "20", "precipMM": "0.1", "tempC": "19", "weatherDesc": [{"value": "Light rain"}]},
        ]}],
    }
    monkeypatch.setattr(tools_module, "_fetch_weather", lambda: raw)
    result = await tools_module.weather(None, None, {"url": "https://x.example/?q=secret"})  # type: ignore[arg-type]
    assert result.ok and result.data["forecast_area"] == "Nairobi"
    assert "place" not in result.data and "not where the user is" in result.data["forecast_area_is"]  # C1
    assert result.data["hours"][0] == {"time": "15:00", "chance_of_rain": "20", "rain_mm": "0.1", "temp_c": "19", "sky": "Light rain"}
    assert tools_module.WEATHER_URL == "https://wttr.in/?format=j1"

    def down() -> dict[str, Any]:
        raise OSError("offline")

    monkeypatch.setattr(tools_module, "_fetch_weather", down)
    assert not (await tools_module.weather(None, None, {})).ok  # type: ignore[arg-type]


# ---- Swift's voice -------------------------------------------------------------------------------


def test_swift_is_quiet_by_default_and_says_hello() -> None:
    settings = SpeechSettings()
    assert settings.replies == "never" and settings.greeting == "Hello"


async def test_only_a_bare_wake_phrase_is_answered_aloud() -> None:
    session, out, records, rec, stt = make_wake("Hey Swift")
    session.speaker, session.speech_replies, session.wake_greeting = FakeSpeaker(), "never", "Hello"
    await session.hear_wake(AUDIO, time.monotonic())
    await asyncio.sleep(0)
    assert session.speaker.said == ["Hello"]  # type: ignore[attr-defined]
    stt.text = "Hey Swift. Hello. What time is it?"
    assert rec.on_level is not None
    rec.on_level(0.9)  # its own hello in the room: not the owner yet, so the capture doesn't end after it
    await asyncio.sleep(0.15)
    rec.on_level(0.0)
    await asyncio.sleep(0.1)
    assert rec.recording
    session.speaker.finish()  # type: ignore[attr-defined]
    await asyncio.sleep(0.65)  # and the room has stopped ringing with it
    rec.on_level(0.8)  # the owner talking...
    await asyncio.sleep(0.15)
    rec.on_level(0.0)  # ...and stops
    await settled(session)
    assert session.speaker.said == ["Hello"]  # type: ignore[attr-defined]  # no spoken answer
    assert out.last("transcript")["text"] == "What time is it?"  # its own hello isn't the request


async def test_a_request_said_in_one_breath_gets_no_hello() -> None:
    session, out, records, rec, stt = make_wake("Hey Swift, what time is it?")
    session.speaker, session.speech_replies, session.wake_greeting = FakeSpeaker(), "never", "Hello"
    await session.hear_wake(AUDIO, time.monotonic())
    await settled(session)
    assert session.speaker.said == []  # type: ignore[attr-defined]
