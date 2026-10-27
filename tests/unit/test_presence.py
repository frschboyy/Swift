"""Presence and lifecycle (ADR-014 L1): here / idle / away, lock and sleep, release and re-warm."""

from __future__ import annotations

import asyncio
import time
import types
from typing import Any

import numpy as np

from swift.audio.recorder import SAMPLE_RATE
from swift.ipc.protocol import Message
from swift.lifecycle import Lifecycle
from swift.presence import AWAY_S, IDLE_S, POLL_S, Change, PresenceMonitor
from swift.stt.transcriber import Transcription

from test_recorder_preroll import FakeStream, fake_sd  # noqa: F401 - the fake sounddevice fixture
from test_session import Recorder as Outbox
from test_wake import make as make_wake_session


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


class Probe:
    def __init__(self) -> None:
        self.is_locked = False
        self.idle = 0.0
        self.fail = False

    def locked(self) -> bool:
        if self.fail:
            raise OSError("no desktop")
        return self.is_locked

    def idle_s(self) -> float:
        return self.idle


def monitor() -> tuple[PresenceMonitor, Probe, Clock, list[Change]]:
    probe, clock, changes = Probe(), Clock(), []
    m = PresenceMonitor(probe, changes.append, clock=clock)
    m.poll()
    return m, probe, clock, changes


def step(m: PresenceMonitor, clock: Clock, seconds: float = POLL_S) -> None:
    clock.t += seconds
    m.poll()


# ---- the monitor --------------------------------------------------------------------------


def test_idle_then_away_then_back() -> None:
    m, probe, clock, changes = monitor()
    probe.idle = IDLE_S
    step(m, clock)
    probe.idle = AWAY_S
    step(m, clock)
    assert [(c.new, c.reason) for c in changes] == [("idle", "idle"), ("away", "idle")]
    assert m.listening_allowed  # away from the keyboard: hands-free stays on
    probe.idle = 1
    step(m, clock)
    assert (changes[-1].new, changes[-1].reason, changes[-1].returned) == ("here", "input", True)


def test_locked_turns_listening_off_and_unlock_is_a_return() -> None:
    m, probe, clock, changes = monitor()
    probe.is_locked = True
    step(m, clock)
    assert (m.state, m.reason, m.listening_allowed) == ("away", "locked", False)
    assert changes[-1].locked_or_asleep
    step(m, clock)  # still locked: no new change
    assert len(changes) == 1
    probe.is_locked, probe.idle = False, 0
    step(m, clock)
    assert (changes[-1].new, changes[-1].reason, changes[-1].returned) == ("here", "unlocked", True)
    assert m.listening_allowed


def test_sleep_is_noticed_from_a_late_poll() -> None:
    m, probe, clock, changes = monitor()
    probe.is_locked = True  # Windows usually locks on resume
    step(m, clock, 600)  # ten minutes between two polls: the machine was asleep
    assert [(c.new, c.reason) for c in changes] == [("away", "asleep"), ("away", "locked")]
    probe.is_locked = False
    step(m, clock)
    assert changes[-1].returned and changes[-1].reason == "unlocked"


def test_a_failed_probe_keeps_the_last_state() -> None:
    m, probe, clock, changes = monitor()
    probe.fail = True
    step(m, clock)
    assert m.state == "here" and changes == []


# ---- the lifecycle --------------------------------------------------------------------------


class FakeRecorder:
    def __init__(self) -> None:
        self.paused = False
        self.calls: list[str] = []

    def pause(self) -> None:
        self.paused = True
        self.calls.append("pause")

    def resume(self) -> None:
        self.paused = False
        self.calls.append("resume")


class FakeStt:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def start_loading(self) -> None:
        self.calls.append("load")

    def release(self) -> None:
        self.calls.append("release")


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def ensure_spare(self) -> None:
        self.calls.append("ensure")

    async def release_spare(self) -> None:
        self.calls.append("release")


def lifecycle(wake: bool = True) -> tuple[Lifecycle, PresenceMonitor, Probe, Clock, Any]:
    out = Outbox()
    session = types.SimpleNamespace(listening_paused=False)
    probe, clock = Probe(), Clock()
    life = Lifecycle(session, out, recorder=FakeRecorder(), transcriber=FakeStt(), executor=FakeExecutor(),
                     wake_enabled=wake, clock=clock, spare_after_speech_s=0.0)
    m = PresenceMonitor(probe, lambda c: None, clock=clock)
    life.attach(m)
    return life, m, probe, clock, out


async def change(life: Lifecycle, m: PresenceMonitor, clock: Clock, seconds: float = POLL_S) -> None:
    clock.t += seconds
    c = m.poll()
    if c is not None:
        await life.handle(c)


async def test_locking_pauses_listening_and_coming_back_warms_up() -> None:
    life, m, probe, clock, out = lifecycle()
    probe.is_locked = True
    await change(life, m, clock)
    assert life.session.listening_paused and life.recorder.calls == ["pause"]
    assert out.last("presence") == {"state": "away", "reason": "locked", "listening": False, "wake": True}
    probe.is_locked = False
    await change(life, m, clock)
    assert not life.session.listening_paused and life.recorder.calls == ["pause", "resume"]
    assert life.transcriber.calls == ["load"]
    assert life._warming is not None
    await life._warming  # the warm Claude Code follows the speech model
    assert life.executor.calls == ["ensure"]
    assert out.last("presence")["listening"] is True


async def test_long_away_releases_memory_but_keeps_what_listening_needs() -> None:
    # Away only from the keyboard: hands-free still listens, so the speech model stays.
    life, m, probe, clock, out = lifecycle()
    probe.idle = AWAY_S
    await change(life, m, clock)
    clock.t += 31 * 60
    await life.tick()
    assert life.executor.calls == ["release"] and life.transcriber.calls == []
    await life.tick()  # once only
    assert life.executor.calls == ["release"]

    # Locked: nothing listens, so the speech model goes too.
    life, m, probe, clock, out = lifecycle()
    probe.is_locked = True
    await change(life, m, clock)
    clock.t += 31 * 60
    await life.tick()
    assert life.executor.calls == ["release"] and life.transcriber.calls == ["release"]


async def test_a_dead_warm_claude_is_replaced_while_here() -> None:
    life, m, probe, clock, out = lifecycle()
    await life.tick()
    assert life.executor.calls == []  # not yet due
    clock.t += 5 * 60
    await life.tick()
    assert life.executor.calls == ["ensure"]


async def test_without_wake_listening_the_microphone_is_left_alone() -> None:
    life, m, probe, clock, out = lifecycle(wake=False)
    probe.is_locked = True
    await change(life, m, clock)
    assert life.recorder.calls == [] and not life.session.listening_paused
    assert out.last("presence")["listening"] is False and out.last("presence")["wake"] is False


async def test_the_overlay_hears_presence_when_it_connects() -> None:
    life, m, probe, clock, out = lifecycle()
    session, sout, *_ = make_wake_session("")
    session.on_ready = life.announce
    await session.handle(Message("ready", {"startup_ms": 1}))
    assert out.last("presence")["state"] == "here"


async def test_the_open_microphone_is_ignored_while_locked() -> None:
    session, out, records, rec, stt = make_wake_session("Hey Swift, what time is it?")
    session.listening_paused = True
    await session.hear_wake(np.zeros(SAMPLE_RATE // 10, dtype=np.int16), time.monotonic())
    assert stt.calls == 0 and records == [] and session.wake_stats["heard"] == 0


# ---- the parts that release and warm up -----------------------------------------------------


def test_recorder_pause_and_resume(fake_sd: Any) -> None:  # noqa: F811
    from swift.audio.recorder import MicRecorder

    r = MicRecorder(asyncio.new_event_loop(), keep_open=True)
    reopened: list[str] = []
    r.on_reopen = lambda: reopened.append("reset")
    r.prepare().result()
    first = FakeStream.instances[0]
    r.pause()
    assert first.closed and r.paused
    r._last_block -= 60
    assert r.check_stream() is False and len(FakeStream.instances) == 1  # the watchdog leaves it closed
    r.resume()
    assert len(FakeStream.instances) == 2 and FakeStream.instances[1].active and reopened == ["reset"]


async def test_speech_model_release_and_reload_on_use() -> None:
    from swift.stt.transcriber import LocalTranscriber

    class Tiny(LocalTranscriber):
        loads = 0

        def _load_model(self) -> Any:
            Tiny.loads += 1
            return object()

    stt = Tiny(models_dir=None)  # type: ignore[arg-type]
    stt.start_loading()
    await stt.wait_loaded()
    assert stt.loaded and Tiny.loads == 1
    stt.release()
    assert not stt.loaded
    await asyncio.wait_for(stt.wait_loaded(), 5)  # the next use loads it again
    assert stt.loaded and Tiny.loads == 2


async def test_claude_replaces_a_spare_that_exited() -> None:
    from swift.executors.claude_code import ClaudeCodeExecutor, _Spare

    ex = ClaudeCodeExecutor(cwd=None, prewarm=True)
    connects: list[str] = []

    async def fake_connect() -> Any:
        connects.append("connect")
        return None

    ex._connect_spare = fake_connect  # type: ignore[method-assign]

    async def dead() -> _Spare:
        return _Spare(client=None, pid=2_000_000_000)  # no such process

    ex._spare = asyncio.create_task(dead())
    await asyncio.sleep(0)
    await ex.ensure_spare()
    await asyncio.sleep(0)
    assert connects == ["connect"]
    await ex.release_spare()
    assert ex._spare is None


# ---- coming back: the speech model first (owner checks, 2026-10-27) --------------------------


class SlowStt:
    """Loads in ``load_s``; a transcription is slow (9 s, as logged) while a Claude Code is starting."""

    def __init__(self, executor: SlowSpare, load_s: float = 0.05) -> None:
        self.executor = executor
        self.load_s = load_s
        self.loaded = asyncio.Event()
        self.order: list[str] = executor.order
        self.busy = False

    def start_loading(self) -> None:
        asyncio.get_running_loop().call_later(self.load_s, self.loaded.set)

    async def wait_loaded(self) -> None:
        await self.loaded.wait()
        self.order.append("speech loaded")

    def prime(self) -> None:
        self.order.append("speech primed")

    async def transcribe(self, audio: Any) -> Transcription:
        await self.wait_loaded()
        return Transcription("Hey Swift, what time is it?", 8938 if self.executor.starting else 300, len(audio) / SAMPLE_RATE)


class SlowSpare:
    """A warm Claude Code that takes a while to start, and competes for the CPU meanwhile."""

    def __init__(self) -> None:
        self.order: list[str] = []
        self.starting = False

    async def ensure_spare(self) -> None:
        # Like the real one: returns at once, the CLI starts in the background.
        self.order.append("spare")
        self.starting = True
        asyncio.get_running_loop().call_later(0.5, setattr, self, "starting", False)


async def test_coming_back_readies_the_speech_model_before_the_warm_claude() -> None:
    spare = SlowSpare()
    stt = SlowStt(spare)
    session, out, records, rec, _ = make_wake_session("")
    session.transcriber = stt
    life = Lifecycle(session, Outbox(), transcriber=stt, executor=spare, spare_after_speech_s=0.2)
    await life.warm_up()  # returns at once
    assert spare.order == []
    # "Hey Swift, ..." right after unlocking, while the speech model is still loading.
    await session.hear_wake(np.zeros(SAMPLE_RATE, dtype=np.int16), time.monotonic())
    assert "spare" not in spare.order  # no Claude Code started yet
    assert session._task is not None
    await asyncio.wait_for(session._task, 2)
    assert records[0]["source"] == "wake" and records[0]["stt_ms"] == 300  # not 9 s
    assert life._warming is not None
    await life._warming
    assert spare.order[-1] == "spare"
