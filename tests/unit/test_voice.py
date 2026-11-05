"""Push-to-talk pipeline with a fake recorder and transcriber (no mic, no model)."""

from __future__ import annotations

from settling import settled

import asyncio
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from swift.audio.recorder import SAMPLE_RATE, MicError, level_from_block
from swift.executors.echo import EchoExecutor
from swift.ipc.protocol import Message
from swift.session import Session
from swift.stt.transcriber import (
    SILENCE_DB,
    SttUnavailable,
    Transcription,
    WhisperTranscriber,
    Word,
    loudest_db,
)

from test_session import Recorder as Outbox


class FakeRecorder:
    def __init__(self, seconds: float = 1.5, fail: MicError | None = None) -> None:
        self.seconds = seconds
        self.fail = fail
        self.recording = False
        self.capped = False
        self.on_level: Callable[[float], None] | None = None

    def start(self, on_level: Callable[[float], None]) -> None:
        if self.fail:
            raise self.fail
        self.recording = True
        self.on_level = on_level
        on_level(0.4)
        on_level(0.7)

    def stop(self) -> np.ndarray:
        self.recording = False
        return np.zeros(int(self.seconds * SAMPLE_RATE), dtype=np.int16)


class FakeTranscriber:
    def __init__(
        self,
        text: str = "open my project",
        delay: float = 0.0,
        fail: SttUnavailable | None = None,
        probs: dict[str, float] | None = None,
        noise_db: float | None = None,
        peak_db: float | None = None,
    ) -> None:
        self.text = text
        # How loud the loudest moment was (None: not measured).
        self.peak_db = peak_db
        # How loud the room was between words (None: not measured).
        self.noise_db = noise_db
        # Word -> probability for words the model was unsure of; the rest are 0.99.
        self.probs = probs
        self.delay = delay
        self.fail = fail
        self.calls = 0

    async def transcribe(self, audio: np.ndarray) -> Transcription:
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.fail:
            raise self.fail
        words = None
        if self.probs is not None:
            words = tuple(Word(w, self.probs.get(w, 0.99)) for w in self.text.split())
        return Transcription(
            self.text, 420, len(audio) / SAMPLE_RATE, peak_db=self.peak_db, words=words, noise_db=self.noise_db
        )


def make(
    recorder: FakeRecorder | None = None, transcriber: FakeTranscriber | None = None, **kw: Any
) -> tuple[Session, Outbox, list[dict[str, Any]], FakeRecorder, FakeTranscriber]:
    out = Outbox()
    records: list[dict[str, Any]] = []
    rec = recorder or FakeRecorder()
    stt = transcriber or FakeTranscriber()
    kw.setdefault("tail_s", 0.0)
    session = Session(
        out, EchoExecutor(), recorder=rec, transcriber=stt, ptt_label="Ctrl+Shift+Space", on_finish=records.append, **kw
    )
    return session, out, records, rec, stt


async def down(session: Session) -> None:
    await session.handle(Message("ptt", {"state": "down"}))
    await asyncio.sleep(0)  # let the interaction reach "listening"


async def up_and_wait(session: Session) -> None:
    await session.handle(Message("ptt", {"state": "up"}))
    assert session._task is not None
    await settled(session)


async def test_hold_and_release_transcribes_and_shows_result() -> None:
    session, out, records, rec, stt = make()
    await down(session)
    assert rec.recording and session.state == "listening"
    await asyncio.sleep(0.01)
    await up_and_wait(session)

    assert out.states() == ["listening", "transcribing", "working", "result"]
    assert [m.data["rms"] for m in out.messages if m.type == "level"] == [0.4, 0.7]
    assert out.last("transcript") == {"text": "open my project", "final": True, "typed": False}
    assert "open my project" in out.last("result")["summary"]
    assert not rec.recording
    assert records[0]["status"] == "done" and records[0]["stt_ms"] == 420 and records[0]["audio_s"] == 1.5
    assert records[0]["transcript"] == "open my project" and records[0]["executor"] == "echo"


async def test_quick_tap_is_ignored_without_transcribing() -> None:
    session, out, records, _, stt = make(recorder=FakeRecorder(seconds=0.1))
    await down(session)
    await up_and_wait(session)
    assert out.states() == ["listening", "idle"]
    assert stt.calls == 0
    assert records[0]["status"] == "cancelled" and records[0]["reason"] == "too_short"


async def test_silence_shows_didnt_catch_that_with_hotkey_hint() -> None:
    session, out, records, _, _ = make(transcriber=FakeTranscriber(text=""))
    await down(session)
    await up_and_wait(session)
    assert out.states()[-1] == "error"
    err = out.last("error")
    assert err["code"] == "no_speech" and "Ctrl+Shift+Space" in err["hint"]
    assert records[0]["status"] == "error" and records[0]["error"] == "no_speech"


async def test_mostly_unclear_speech_is_not_acted_on() -> None:
    stt = FakeTranscriber(text="Thank you.", probs={"Thank": 0.2, "you.": 0.3})
    session, out, records, _, _ = make(transcriber=stt)
    await down(session)
    await up_and_wait(session)
    assert out.states()[-1] == "error"
    err = out.last("error")
    assert err["code"] == "unclear_speech" and "Thank you." in err["message"]
    assert not [m for m in out.messages if m.type == "result"]
    assert records[0]["error"] == "unclear_speech" and records[0]["unclear"] == ["Thank", "you."]
    assert records[0]["stt_confidence"] == 0.2


async def test_a_few_unclear_words_are_named_to_the_agent() -> None:
    stt = FakeTranscriber(text="explain the tori config file", probs={"tori": 0.3})
    session, out, records, _, _ = make(transcriber=stt)
    await down(session)
    await up_and_wait(session)
    summary = out.last("result")["summary"]
    assert "explain the tori config file" in summary and "“tori”" in summary
    assert records[0]["status"] == "done" and records[0]["unclear"] == ["tori"]


async def test_unclear_check_can_be_turned_off() -> None:
    stt = FakeTranscriber(text="Thank you.", probs={"Thank": 0.2, "you.": 0.3})
    session, out, records, _, _ = make(transcriber=stt, unclear_p=0.0, reject_p=0.0)
    await down(session)
    await up_and_wait(session)
    assert records[0]["status"] == "done" and "unclear" not in records[0]


async def test_blocked_mic_shows_privacy_hint() -> None:
    blocked = MicError("Windows blocked access to the microphone.", "Open Settings > Privacy & security > Microphone")
    session, out, _, _, _ = make(recorder=FakeRecorder(fail=blocked))
    await session.handle(Message("ptt", {"state": "down"}))
    await settled(session)
    err = out.last("error")
    assert err["code"] == "mic_unavailable" and "Privacy" in err["hint"]


async def test_missing_model_shows_error() -> None:
    missing = SttUnavailable("The speech model 'base.en' couldn't be loaded.", "Download it, then restart Swift.")
    session, out, _, _, _ = make(transcriber=FakeTranscriber(fail=missing))
    await down(session)
    await up_and_wait(session)
    assert out.last("error")["code"] == "stt_unavailable"


async def test_escape_while_listening_stops_mic_and_returns_to_idle() -> None:
    session, out, records, rec, stt = make()
    await down(session)
    await session.handle(Message("cancel", {}))
    assert out.states()[-1] == "idle"
    assert not rec.recording and stt.calls == 0
    assert records[0]["status"] == "cancelled"


async def test_escape_while_transcribing_discards_result() -> None:
    session, out, records, _, _ = make(transcriber=FakeTranscriber(delay=0.5))
    await down(session)
    await session.handle(Message("ptt", {"state": "up"}))
    for _ in range(50):
        if session.state == "transcribing":
            break
        await asyncio.sleep(0.01)
    await session.handle(Message("cancel", {}))
    assert out.states()[-1] == "idle"
    assert not any(m.type == "result" for m in out.messages)
    assert records[0]["status"] == "cancelled"


async def test_recording_stops_itself_at_the_cap() -> None:
    session, out, _, rec, _ = make(max_record_s=0.05)
    await down(session)
    await settled(session)
    assert not rec.recording
    assert out.states()[-1] == "result"


async def test_ptt_while_busy_is_ignored_and_stray_release_is_harmless() -> None:
    session, out, _, _, _ = make(transcriber=FakeTranscriber(delay=0.2))
    await session.handle(Message("ptt", {"state": "up"}))  # release with nothing held
    assert out.messages == []
    await down(session)
    first = session._task
    await session.handle(Message("ptt", {"state": "up"}))
    await asyncio.sleep(0.01)
    await session.handle(Message("ptt", {"state": "down"}))  # while transcribing
    assert session._task is first
    await asyncio.wait_for(first, 2)  # type: ignore[arg-type]


async def test_ptt_without_audio_components_is_ignored() -> None:
    out = Outbox()
    session = Session(out, EchoExecutor())
    await session.handle(Message("ptt", {"state": "down"}))
    assert session._task is None and out.messages == []


@pytest.mark.parametrize(
    ("amplitude", "expected"),
    [(0, 0.0), (32767, 1.0), (int(32768 * 10 ** (-36 / 20) * 2**0.5), 0.5)],
)
def test_level_mapping(amplitude: int, expected: float) -> None:
    t = np.arange(1600)
    block = (amplitude * np.sin(2 * np.pi * 440 * t / SAMPLE_RATE)).astype(np.int16)
    assert level_from_block(block) == pytest.approx(expected, abs=0.02)


async def test_echo_executor_contract() -> None:
    ex = EchoExecutor()
    run_id = await ex.start("hello there")
    assert [e async for e in ex.events(run_id)] == []
    result = await ex.result(run_id)
    assert result.status == "done" and "hello there" in result.summary
    assert result.details and "nothing was sent" in result.details["text"]


async def test_mic_stays_open_briefly_after_release() -> None:
    session, _, _, rec, _ = make(tail_s=0.1)
    await down(session)
    await session.handle(Message("ptt", {"state": "up"}))
    await asyncio.sleep(0.03)
    assert rec.recording  # still catching the last word
    assert session._task is not None
    await settled(session)
    assert not rec.recording


async def test_save_audio_writes_a_wav_per_interaction(tmp_path: Path) -> None:
    session, _, records, _, _ = make(audio_dir=tmp_path)
    await down(session)
    await up_and_wait(session)
    path = Path(records[0]["audio_file"])
    assert path.parent == tmp_path and path.stem == records[0]["id"]
    with wave.open(str(path)) as f:
        assert f.getframerate() == SAMPLE_RATE and f.getnchannels() == 1
        assert f.getnframes() == int(1.5 * SAMPLE_RATE)


async def test_audio_is_not_saved_by_default() -> None:
    session, _, records, _, _ = make()
    await down(session)
    await up_and_wait(session)
    assert "audio_file" not in records[0]


def test_loudest_db_finds_the_loudest_block() -> None:
    samples = np.zeros(SAMPLE_RATE, dtype=np.float32)
    samples[8192:8704] = 0.1  # one 32 ms block at -20 dBFS
    assert loudest_db(samples) == pytest.approx(-20.0, abs=0.1)
    assert loudest_db(np.zeros(100, dtype=np.float32)) == -120.0


def test_silence_never_reaches_whisper(tmp_path: Path) -> None:
    stt = WhisperTranscriber("small.en", tmp_path)
    stt._model = object()  # would fail if Whisper were called
    noise = (np.random.default_rng(0).normal(0, 10, SAMPLE_RATE * 2)).astype(np.int16)  # about -70 dBFS
    result = stt._transcribe_sync(noise)
    assert result.text == "" and result.audio_s == 2.0
    assert result.peak_db is not None and result.peak_db < SILENCE_DB
