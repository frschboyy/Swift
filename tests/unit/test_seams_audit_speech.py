"""Seams audit 2026-11-04, speech and dialogue: reproductions of findings (expected to FAIL today).

Each test names the finding it reproduces (S-xx in the audit notes). Nothing here touches a real
microphone, voice or device: the fakes, the system lane's FakeSystem, and the session's own hooks.
"""

from __future__ import annotations

import asyncio
import sys
import time

import pytest

from swift.ipc.protocol import Message
from swift.session import Session
from swift.speech import FakeSpeaker, card_speech
from swift.system import intents as it

from test_hands_free import make as make_hands_free
from test_hands_free import say
from test_routing import ask
from test_system_lane import _session, lane


async def _until(check, tries: int = 100) -> bool:  # type: ignore[no-untyped-def]
    for _ in range(tries):
        if check():
            return True
        await asyncio.sleep(0.01)
    return False


async def _settle(session: Session) -> None:
    for _ in range(100):
        await asyncio.sleep(0)
        if session._task is not None and not session._task.done():
            try:
                await asyncio.wait_for(asyncio.shield(session._task), 2)
            except asyncio.CancelledError:
                pass
        if not session._live():
            return


def _wake_session(**kw):  # type: ignore[no-untyped-def]
    """Wake listening on (a reply window), with the system lane's fake devices."""
    session, out, records, stt = make_hands_free(wake_followup_s=8.0, **kw)
    session.system, control, _ = lane()
    return session, out, records, stt, control


async def _wifi_question(session: Session, out) -> dict:  # type: ignore[no-untyped-def]
    from swift.stt.transcriber import Transcription

    session._start_followup(Transcription("turn off the wifi", 300, 0.95))  # a spoken request
    await _settle(session)
    card = out.last("ask")
    assert card["question"] == "Turn off Wi-Fi?" and card["open"] is True
    return card


# ---- S-01: "turn the Wi-Fi back on" while offline is refused as "I'm offline" ---------------------


@pytest.mark.xfail(strict=True, reason="seams audit D-03: open finding; remove this marker with the fix")
async def test_s01_turn_the_wifi_back_on_while_offline_turns_it_on() -> None:
    session, rec, spy, records = await _session()
    session.system.control.radio_state["wifi"] = False  # type: ignore[union-attr]
    session.online = lambda: False  # Wi-Fi is off, so Windows says offline
    await ask("turn the wifi back on", session)
    # Today: the system grammar has no "back on", the agent route is swapped for the offline answer.
    assert records[-1]["action"] != "offline", "asked to turn Wi-Fi back on, told 'I'm offline'"
    assert session.system.control.radio_state["wifi"] is True  # type: ignore[union-attr]


# ---- S-02: any local answer in between overwrites the carry-over ("turn it back on" lost) -------


@pytest.mark.xfail(strict=True, reason="seams audit D-04: open finding; remove this marker with the fix")
async def test_s02_a_time_answer_in_between_doesnt_forget_the_switch() -> None:
    session, rec, spy, records = await _session()
    await ask("turn off the wifi", session)
    await ask("yes", session)
    assert session.system.control.radio_state["wifi"] is False  # type: ignore[union-attr]
    await ask("what time is it", session)  # a local answer: the single carry slot is replaced
    await ask("Turn it back on.", session)
    assert records[-1].get("action") == "system_carry", records[-1].get("route")
    assert session.system.control.radio_state["wifi"] is True  # type: ignore[union-attr]


# ---- S-03: "turn it back on" during a run (typed or "Swift, …") is not a request ----------------


@pytest.mark.xfail(strict=True, reason="seams audit D-05: open finding; remove this marker with the fix")
async def test_s03_turn_it_back_on_typed_during_a_run_is_carried_out() -> None:
    session, out, records, stt, control = _wake_session(speed=1.0, scenario="long")
    control.radio_state["wifi"] = False
    session.dialogue.remember(None, intents=(it.Intent("radio", {"kind": "wifi", "on": False}),))
    await session.handle(Message("debug.run", {"scenario": "long"}))
    assert await _until(lambda: session.state == "working", tries=600)
    await session.handle(Message("text", {"text": "turn it back on"}))
    await _until(lambda: control.radio_state["wifi"] is True, tries=50)
    hints = [m.data.get("text", "") for m in out.messages if m.type == "run.voice"]
    session._task.cancel()  # type: ignore[union-attr]
    assert control.radio_state["wifi"] is True, f"mid-run hint instead: {hints[-1:]}"


# ---- S-04: an empty transcription in the question window spends the re-ask -----------------------


@pytest.mark.xfail(strict=True, reason="seams audit D-06: open finding; remove this marker with the fix")
async def test_s04_an_empty_transcription_is_not_an_answer() -> None:
    session, out, records, stt, control = _wake_session()
    await _wifi_question(session, out)
    await say(session, stt, "")  # a cough or a door: the model returns no words
    await _settle(session)
    turns = [r.get("dialogue", {}).get("turn") for r in records]
    assert "reask" not in turns, "an utterance with no words was taken as an unclear answer (log 17:43:39)"


# ---- S-05: after a lane's re-ask, the answer window is the old one --------------------------------


# Fixed by S3 (swift/answer_window.py, 2026-11-05); the docstring is the bug as found.
async def test_s05_after_a_lane_reask_the_microphone_listens_for_a_whole_window() -> None:
    session, out, records, stt, control = _wake_session()
    speaker = FakeSpeaker()
    session.speaker, speaker.on_done = speaker, session.speech_done
    session.wake_question_s = 2.0
    await _wifi_question(session, out)
    first = session._answer_window
    assert first is not None
    await asyncio.sleep(0.5)
    await say(session, stt, "Purple.")  # unclear: asked once more, said aloud
    assert await _until(lambda: speaker.speaking)  # "Sorry, was that a yes or a no? Turn off Wi-Fi?"
    await asyncio.sleep(0.5)
    speaker.finish()  # Swift has finished saying it: the window should start now
    await asyncio.sleep(0.05)
    window = session._answer_window
    assert window is not None and window is not first, "the answer window wasn't reopened after the re-ask"
    assert window[1] >= time.monotonic() + session.wake_question_s - 0.2


# ---- S-06: the question times out while the owner is still saying the answer --------------------


# Fixed by S3 (swift/answer_window.py, 2026-11-05); the docstring is the bug as found.
async def test_s06_the_question_waits_while_an_answer_is_being_said() -> None:
    session, out, records, stt, control = _wake_session()
    session.wake_question_s = 0.1
    session.in_speech = lambda: True  # the open microphone is collecting an utterance right now
    await _wifi_question(session, out)
    await asyncio.sleep(0.3)
    assert session.dialogue.pending is not None, "timed out into the stack mid-answer"


# ---- S-07: a "no" over Swift's voice is dropped whenever Swift's sentence contains "no" ----------


@pytest.mark.xfail(strict=True, reason="seams audit V-02: open finding; remove this marker with the fix")
def test_s07_no_over_the_card_hint_is_the_owner() -> None:
    session, *_ = make_hands_free()
    session._said_aloud = card_speech("Send this email to Ada?", "Subject: Late", "send_email")
    # The hint itself ends with “no”, so the owner's "No." is taken for Swift's own voice.
    assert session._said_over_speech("No.")


@pytest.mark.xfail(strict=True, reason="seams audit V-02: open finding; remove this marker with the fix")
def test_s07b_no_over_the_reask_is_the_owner() -> None:
    from swift.dialogue import Question, reask_text

    session, *_ = make_hands_free()
    session._said_aloud = reask_text(Question("Turn off Wi-Fi?", "yes_no"))
    assert session._said_over_speech("No.")


# ---- S-08: a brisk "no" under 0.4 s never reaches the session while Swift talks -----------------


@pytest.mark.xfail(strict=True, reason="seams audit V-02: open finding; remove this marker with the fix")
async def test_s08_a_brisk_clip_is_wanted_while_a_card_waits_and_swift_talks() -> None:
    session, out, records, stt, control = _wake_session()
    await _wifi_question(session, out)
    speaker = FakeSpeaker()
    session.speaker = speaker
    speaker.speak("Turn off Wi-Fi?")
    assert session.wants_short(), "WakeListener drops a 0.15-0.4 s 'no' as too short while Swift talks"


# ---- S-09: "No" said over the question being read aloud is lost ----------------------------------


@pytest.mark.xfail(strict=True, reason="seams audit V-02: open finding; remove this marker with the fix")
async def test_s09_no_said_over_the_question_answers_it() -> None:
    session, out, records, stt, control = _wake_session()
    speaker = FakeSpeaker()
    session.speaker, speaker.on_done = speaker, session.speech_done
    session.read_confirms = True  # the question is said aloud; the mic opens when it ends
    from swift.stt.transcriber import Transcription

    session._start_followup(Transcription("turn off the wifi", 300, 0.95))
    await _settle(session)
    assert speaker.speaking
    await say(session, stt, "No.")
    await _settle(session)
    assert session.dialogue.pending is None, "the refusal stopped Swift's voice but never reached the question"


# ---- S-10: with SAPI unavailable, Swift is 'speaking' forever and wake listening goes deaf --------


@pytest.mark.skipif(sys.platform != "win32", reason="WindowsSpeaker")
async def test_s10_no_voice_never_leaves_swift_speaking(monkeypatch: pytest.MonkeyPatch) -> None:
    win32 = pytest.importorskip("win32com.client")
    from swift.speech import WindowsSpeaker

    def broken(*_a, **_k):  # type: ignore[no-untyped-def]
        raise OSError("no SAPI here")

    monkeypatch.setattr(win32, "Dispatch", broken)
    speaker = WindowsSpeaker(loop=asyncio.get_running_loop())
    speaker.ready.wait(2)
    assert speaker.error
    speaker.speak("Wi-Fi off.")
    await asyncio.sleep(0.3)
    assert not speaker.speaking, "speaking stays True: hear_wake drops everything as own_voice"
    speaker.close()


# ---- S-12: a yes with more than four words after it drops the question and goes to the agent ------


@pytest.mark.xfail(strict=True, reason="seams audit D-02: open finding; remove this marker with the fix")
async def test_s12_a_wordy_yes_answers_the_question() -> None:
    session, rec, spy, records = await _session()
    await ask("turn off the wifi", session)
    await ask("Yeah, turn it off for now, please, thanks.", session)
    assert spy.calls == [], "the answer became a new request for the agent"
    assert session.system.control.radio_state["wifi"] is False  # type: ignore[union-attr]


@pytest.mark.xfail(strict=True, reason="seams audit D-02: open finding; remove this marker with the fix")
async def test_s12b_hold_on_doesnt_drop_the_question() -> None:
    session, rec, spy, records = await _session()
    await ask("turn off the wifi", session)
    await ask("Hold on a second.", session)
    assert session.dialogue.pending is not None, "'hold on a second' was taken as a new request"


# ---- S-13: an answer said for longer than the reply window leaves no reply window after it --------


@pytest.mark.xfail(strict=True, reason="seams audit T-05: open finding; remove this marker with the fix")
async def test_s13_the_reply_window_opens_after_a_long_spoken_answer() -> None:
    from swift.stt.transcriber import Transcription

    session, out, records, stt, control = _wake_session()
    session.wake_followup_s = 0.2  # stands for 8 s against a 10-15 s spoken answer
    speaker = FakeSpeaker()
    session.speaker, speaker.on_done = speaker, session.speech_done
    session._start_followup(Transcription("what time is it", 300, 0.95))
    await _settle(session)
    assert speaker.speaking
    await asyncio.sleep(0.3)  # Swift is still talking when the window would have ended
    speaker.finish()
    await asyncio.sleep(0.05)
    window = session._followup
    assert window is not None and time.monotonic() <= window[1], "no reply window after Swift finished talking"


# ---- S-14: one timer slot for every question: a lane question asked behind a run's cancels its timer


# Fixed by S3 (swift/answer_window.py, 2026-11-05). Each question has its own window: the lane's question
# is asked first and the run's waits behind it, its window stopped; it comes back with a whole window and
# times out by itself. Before, the lane's 25 s timer replaced the run's and the run's never fired.
async def test_s14_a_question_behind_doesnt_cancel_the_timer_of_the_one_on_screen() -> None:
    from swift.dialogue import Question

    session, rec, spy, records = await _session()
    session.wake_question_s = 0.1
    on_screen = Question("Which Sam: Sam Lee or Sam Okoro?", "choice", ("Sam Lee", "Sam Okoro"), source="run",
                         future=asyncio.get_running_loop().create_future())
    assert session.dialogue.ask(on_screen)
    session._question_timer(on_screen, 0.1)
    # "hey Swift, set a timer" meanwhile: "For how long?" is asked now, the run's question waits behind it.
    lane_q = session._ask_lane("For how long?", "duration", "seconds", (), {"thread": "t2", "transcript": "set a timer"})
    assert session.dialogue.pending is lane_q and session.dialogue.waiting == [on_screen]
    assert on_screen.window.timer is None  # stopped while it waits: one deadline at a time
    session._question_timer(lane_q, 0.1)
    await asyncio.sleep(0.4)
    assert lane_q.window.state == "closed"
    # ...then the run's question was on screen again with its own window, and ran out by itself.
    assert on_screen.future.done(), "the question on screen lost its timer: it never times out"
