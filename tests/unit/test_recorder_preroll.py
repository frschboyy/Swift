"""MicRecorder pre-roll with a fake sounddevice (no real microphone)."""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import numpy as np
import pytest

from swift.audio import recorder as rec
from swift.audio.recorder import BLOCK, SAMPLE_RATE, MicRecorder, MicError


class FakeStream:
    instances: list[FakeStream] = []

    def __init__(self, callback: Any, **_: Any) -> None:
        self.callback = callback
        self.active = False
        self.closed = False
        FakeStream.instances.append(self)

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False

    def close(self) -> None:
        self.closed = True

    def feed(self, value: int) -> None:
        self.callback(np.full((BLOCK, 1), value, dtype=np.int16), BLOCK, None, None)


class FakePortAudioError(Exception):
    pass


@pytest.fixture
def fake_sd(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    FakeStream.instances = []
    state = types.SimpleNamespace(fail=False)

    def input_stream(**kw: Any) -> FakeStream:
        if state.fail:
            raise FakePortAudioError("-9999 Unanticipated host error")
        return FakeStream(**kw)

    mod = types.SimpleNamespace(
        InputStream=lambda **kw: input_stream(callback=kw.pop("callback"), **kw),
        PortAudioError=FakePortAudioError,
        query_devices=lambda: [],
        query_hostapis=lambda: [],
    )
    monkeypatch.setitem(sys.modules, "sounddevice", mod)
    return state


def make(preroll_s: float) -> MicRecorder:
    return MicRecorder(asyncio.new_event_loop(), preroll_s=preroll_s)


def test_without_preroll_opens_on_start_and_closes_on_stop(fake_sd: Any) -> None:
    r = make(0.0)
    r.prepare().result()
    assert FakeStream.instances == []
    r.start(lambda _: None)
    s = FakeStream.instances[0]
    s.feed(1)
    audio = r.stop()
    assert len(audio) == BLOCK and r.preroll_ms == 0 and r.first_audio_ms is not None
    assert s.closed


def test_preroll_stream_opens_in_prepare_and_stays_open(fake_sd: Any) -> None:
    r = make(0.5)
    r.prepare().result()
    s = FakeStream.instances[0]
    assert s.active
    r.start(lambda _: None)
    r.stop()
    assert s.active and not s.closed and len(FakeStream.instances) == 1


def test_start_prepends_buffered_audio_up_to_preroll(fake_sd: Any) -> None:
    r = make(0.5)  # 0.5 s = 15.625 -> 16 blocks
    r.prepare().result()
    s = FakeStream.instances[0]
    for i in range(1, 41):  # 40 idle blocks, only the last 16 are kept
        s.feed(i)
    r.start(lambda _: None)
    s.feed(99)
    audio = r.stop()
    assert len(audio) == 17 * BLOCK
    assert audio[0] == 25 and audio[16 * BLOCK - 1] == 40 and audio[-1] == 99
    assert r.preroll_ms == int(16 * BLOCK * 1000 / SAMPLE_RATE)


def test_first_audio_ms_counts_live_blocks_only(fake_sd: Any) -> None:
    r = make(0.5)
    r.prepare().result()
    s = FakeStream.instances[0]
    s.feed(1)
    r.start(lambda _: None)
    assert r.first_audio_ms is None
    s.feed(2)
    assert r.first_audio_ms is not None and r.first_audio_ms < 1000
    r.stop()


def test_idle_audio_is_not_kept_between_requests(fake_sd: Any) -> None:
    r = make(0.1)  # 4 blocks
    r.prepare().result()
    s = FakeStream.instances[0]
    for _ in range(4):
        s.feed(5)
    r.start(lambda _: None)
    r.stop()
    r.start(lambda _: None)  # ring was consumed: nothing from the previous request leaks in
    assert len(r.stop()) == 0 and r.preroll_ms == 0


def test_dead_preroll_stream_is_reopened_on_start(fake_sd: Any) -> None:
    r = make(0.5)
    r.prepare().result()
    first = FakeStream.instances[0]
    first.active = False  # device unplugged
    r.start(lambda _: None)
    assert first.closed and len(FakeStream.instances) == 2
    FakeStream.instances[1].feed(7)
    assert len(r.stop()) == BLOCK and r.preroll_ms == 0


def test_failed_preroll_open_falls_back_to_open_on_demand(fake_sd: Any) -> None:
    fake_sd.fail = True
    r = make(0.5)
    r.prepare().result()  # logs, does not raise
    assert FakeStream.instances == []
    fake_sd.fail = False
    r.start(lambda _: None)
    assert len(FakeStream.instances) == 1
    r.stop()


def test_start_error_is_a_mic_error(fake_sd: Any) -> None:
    fake_sd.fail = True
    r = make(0.5)
    with pytest.raises(MicError):
        r.start(lambda _: None)
    assert rec.MicRecorder  # recorder stays usable
    fake_sd.fail = False
    r.start(lambda _: None)
    r.stop()


# ---- the always-open stream recovers by itself (wake listening) ------------------------------


def test_a_stream_that_went_quiet_is_reopened(fake_sd: Any) -> None:
    r = MicRecorder(asyncio.new_event_loop(), keep_open=True)
    r.prepare().result()
    first = FakeStream.instances[0]
    first.feed(1)
    assert r.check_stream() is False  # blocks are arriving
    r._last_block -= 10  # ...then nothing for 10 s (sleep, a headset switch)
    assert r.check_stream() is True
    assert first.closed and len(FakeStream.instances) == 2 and FakeStream.instances[1].active


def test_a_stopped_stream_is_reopened_and_a_failure_retried_later(fake_sd: Any) -> None:
    r = MicRecorder(asyncio.new_event_loop(), keep_open=True)
    r.prepare().result()
    FakeStream.instances[0].active = False  # the device went away
    fake_sd.fail = True
    assert r.check_stream() is False  # can't reopen yet: logged, tried again next time
    fake_sd.fail = False
    assert r.check_stream() is True and FakeStream.instances[-1].active


def test_nothing_is_reopened_during_a_recording_or_without_keep_open(fake_sd: Any) -> None:
    r = MicRecorder(asyncio.new_event_loop(), keep_open=True)
    r.prepare().result()
    r.start(lambda _: None)
    r._last_block -= 10
    assert r.check_stream() is False and len(FakeStream.instances) == 1
    r.stop()
    plain = make(0.0)
    plain.prepare().result()
    assert plain.check_stream() is False


def test_a_reopen_tells_the_listener_to_start_over(fake_sd: Any) -> None:
    r = MicRecorder(asyncio.new_event_loop(), keep_open=True)
    calls: list[str] = []
    r.on_reopen = lambda: calls.append("reset")
    r.prepare().result()
    r._last_block -= 10
    assert r.check_stream() is True and calls == ["reset"]
