"""Health audit 2026-11-12, group HEAR: repros for its findings (module-HEAR.yaml).

Each is a strict xfail: it passes once the finding is fixed. Fakes only: no microphone, no Wi-Fi.
"""

from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest
from test_audit_2026_10 import _settle, _wifi_asked
from test_dialogue import asker
from test_runs import until
from test_seam_replay import Detector, script
from test_voice_fixes_1700 import AUDIO, wake_session
from test_wake import make as make_wake
from test_wake_acoustic import FakeScorer, stream

from swift.parked import ParkedThreads
from swift.wake import match_wake_window
from swift.wake_acoustic import AcousticWake


@pytest.mark.xfail(strict=True, reason="HA-HEAR-01: typed 'Swift, yes' answers Swift's reversible question")
async def test_a_typed_swift_yes_doesnt_turn_the_wifi_off() -> None:
    # CLAUDE.md: typing never approves; the reversible exception is a spoken yes or a click.
    session, rec, _records = await _wifi_asked()
    await session._start_typed("Swift, yes")
    await _settle(session)
    assert session.system.control.radio_state["wifi"] is True  # type: ignore[union-attr]


async def test_a_wake_phrase_said_just_after_the_lock_isnt_chimed_by_the_peek() -> None:
    session, out, _records, _stt = wake_session()
    session.locked_now = lambda: True  # locked; the 2 s poll hasn't set listening_paused yet
    session.transcriber.text = "Hey Swift, what"
    await session.peek_wake(AUDIO)
    assert not [m for m in out.messages if m.type == "heard"]
    assert session.heard_sounds == []  # type: ignore[attr-defined]


async def test_a_lock_while_the_peek_is_transcribing_isnt_chimed() -> None:
    session, out, _records, _stt = wake_session()
    answers = iter([False])  # unlocked when the peek starts, locked once its transcript is back
    session.locked_now = lambda: next(answers, True)
    session.transcriber.text = "Hey Swift, what"
    await session.peek_wake(AUDIO)
    assert not [m for m in out.messages if m.type == "heard"]


class EarlyDetector(Detector):
    """Heard "Hey Swift" 0.5 s before the utterance ended."""

    def first_hit(self, t0: float, t1: float) -> float | None:
        return t1 - 0.5


@pytest.mark.xfail(strict=True, reason="HA-HEAR-03: after a bare second-way wake the request keeps the misheard name")
async def test_after_a_bare_hey_swift_only_the_detector_heard_the_request_is_only_what_followed() -> None:
    session, out, records, rec, stt = make_wake("")
    session.acoustic = EarlyDetector()
    # 1 s of speech ("Hey Swift", heard as "He's left."), then 0.5 s of quiet: a bare "Hey Swift".
    audio = np.concatenate([(np.random.default_rng(0).standard_normal(16000) * 8000).astype(np.int16),
                            np.zeros(8000, np.int16)])
    script(stt, "He's left.", "He swift.", "He's left. What time is it?")  # utterance, window, then the capture
    await session.hear_wake(audio, time.monotonic())
    await until(lambda: rec.recording)  # the capture opened, as for "Hey Swift"
    assert session.wake_stats["acoustic_wake"] == 1 and rec.lead is not None and rec.lead >= 1.5  # the whole utterance
    assert rec.on_level is not None
    rec.on_level(0.8)
    await asyncio.sleep(0.15)
    rec.on_level(0.0)
    await until(lambda: records)
    assert records[0]["transcript"] == "What time is it?"  # today: "He's left. What time is it?"


@pytest.mark.xfail(strict=True, reason="HA-HEAR-04: any presence change (here/idle) makes the detector forget its hits")
async def test_going_idle_doesnt_make_the_detector_forget_a_hey_swift() -> None:
    session, _out, _records, _agent, _stt = asker(parked=ParkedThreads(None))
    session.acoustic = wake = AcousticWake(FakeScorer(hot=[10]))
    try:
        start = time.monotonic()
        end = stream(wake, 2.0, start=start)
        assert wake.first_hit(start, end) is not None
        session.listening_changed()  # Lifecycle.handle calls it on every change, "here" -> "idle" too
        assert wake.first_hit(start, end) is not None
    finally:
        wake.close()


@pytest.mark.xfail(strict=True, reason="HA-HEAR-05: the window check takes any word before 'swift'")
@pytest.mark.parametrize("text", ["Taylor Swift.", "Swift, Swift.", "The swift fox"])
def test_the_window_check_turns_down_a_name_or_a_word_before_swift(text: str) -> None:
    assert not match_wake_window(text)
