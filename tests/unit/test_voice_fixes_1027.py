"""The five voice problems from the owner checks of 2026-10-27, 12:50.

1. "show me" and "stop" lost during a run: short clips, the confidence bar, and hands-free
   before the provider has started.
2. "show me" during a run that writes in an app brings that app to the front.
3. Unlocking: a pause handled late never closes the microphone, the speech model is warmed
   before the microphone reopens, and the time until Swift listens again is logged.
4. A question from a request that ended behind another comes to the front and waits for the answer.
5. The fast lane answers a follow-up about its last answer's moment ("and the date?").
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import types
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from loguru import logger

from swift.executors.base import WorkerTask
from swift.audio.recorder import SAMPLE_RATE
from swift.desktop.base import WriteReceipt
from swift.desktop.fake import FakeApp, FakeDesktop
from swift.executors.base import ExecResult
from swift.executors.echo import EchoExecutor
from swift.ipc.protocol import Message
from swift.lifecycle import Lifecycle
from swift.presence import AWAY_POLL_S, POLL_S, PresenceMonitor
from swift.routing import fast
from swift.routing.rules import route_midrun
from swift.session import PAUSED_HINT, Session
from swift.wake import WakeListener
from swift.workflows.tools import ToolHost

from test_hands_free import finish, make as make_hands_free, say, until_confirm
from test_presence import Clock, FakeExecutor, FakeRecorder, Probe
from test_recorder_preroll import FakeStream, fake_sd  # noqa: F401 - the fake sounddevice fixture
from test_runs import Agent, make as make_runs, started, until
from test_session import Recorder as Outbox
from test_voice import FakeTranscriber
from test_wake import LOUD, QUIET, LeadRecorder, feed

SHORT = np.zeros(SAMPLE_RATE // 10, dtype=np.int16)


# ---- 1. short control phrases during a run ----------------------------------------------------


def test_a_brisk_stop_is_handed_on_only_when_the_session_wants_it() -> None:
    got: list[tuple[Any, ...]] = []
    wanted = [False]
    listener = WakeListener(lambda *a: got.append(a), accept_short=lambda: wanted[0])
    feed(listener, quiet=40)
    feed(listener, loud=8)  # ~0.26 s of speech: under min_s (0.4 s)
    feed(listener, quiet=40)
    assert got == [] and listener.stats["too_short"] == 1
    wanted[0] = True  # a run is going
    feed(listener, loud=8)
    feed(listener, quiet=40)
    assert len(got) == 1 and got[0][2] is True and listener.stats["short"] == 1
    feed(listener, loud=2)  # a click is still a click
    feed(listener, quiet=40)
    assert len(got) == 1 and listener.stats["too_short"] == 2


def test_without_accept_short_the_callback_keeps_two_arguments() -> None:
    got: list[tuple[Any, ...]] = []
    listener = WakeListener(lambda a, t: got.append((a, t)))
    feed(listener, quiet=40)
    feed(listener, loud=30)
    feed(listener, quiet=40)
    assert len(got) == 1


async def test_a_short_stop_during_a_run_stops_it() -> None:
    session, out, records, stt = make_hands_free()
    await until_confirm(session, out)
    assert session.wants_short()
    stt.text = "stop"
    await session.hear_wake(SHORT, time.monotonic(), True)
    await finish(session)
    assert out.last("result")["status"] == "cancelled"
    assert session.take_wake_stats()["short_heard"] == 1


async def test_a_short_clip_that_isnt_a_control_phrase_is_dropped() -> None:
    session, out, records, stt = make_hands_free()
    await until_confirm(session, out)
    before = len(out.messages)
    for text in ("yes", "Swift, approve.", "the game"):  # never an approval from a short clip
        stt.text = text
        await session.hear_wake(SHORT, time.monotonic(), True)
    assert session.state == "confirm" and len(out.messages) == before
    assert session.take_wake_stats()["short_dropped"] == 3
    await session.cancel()


async def test_short_clips_are_not_wanted_at_rest() -> None:
    session, out, records, stt = make_hands_free()
    assert not session.wants_short()


async def test_an_unsure_stop_during_a_run_still_stops_it() -> None:
    # A clean "Stop." scored 0.46, under wake.min_p (0.5): mid-run it gets the lower bar.
    session, out, records, stt = make_hands_free(wake_min_p=0.5, wake_phrase_min_p=0.2)
    await until_confirm(session, out)
    stt.probs = {"Stop.": 0.46}
    await say(session, stt, "Stop.")
    await finish(session)
    assert out.last("result")["status"] == "cancelled"
    assert session.take_wake_stats()["unsure_midrun"] == 1


async def test_an_unsure_approve_during_a_run_keeps_the_bar() -> None:
    session, out, records, stt = make_hands_free(wake_min_p=0.5, wake_phrase_min_p=0.2)
    await until_confirm(session, out)
    stt.probs = {"Swift,": 0.46, "approve.": 0.46}
    await say(session, stt, "Swift, approve.")
    assert session.state == "confirm" and session.take_wake_stats()["unsure"] == 1
    await session.cancel()


async def test_stop_works_before_the_provider_has_started() -> None:
    # Hands-free no longer waits for the provider's run id: "stop" works as soon as the card says working.
    session, out, records, stt = make_hands_free()
    gate = asyncio.Event()
    real_start = session.executor.start

    async def slow_start(*args: Any, **kw: Any) -> str:
        await gate.wait()
        return await real_start(*args, **kw)

    session.executor.start = slow_start  # type: ignore[method-assign]
    await say(session, stt, "Hey Swift, research the history of tea")
    deadline = time.monotonic() + 2
    while session._record is None or "transcript" not in session._record:
        assert time.monotonic() < deadline
        await asyncio.sleep(0.005)
    await asyncio.sleep(0.05)  # waiting on the provider's start
    assert session._active is None and session._hands_free(), session.state
    await say(session, stt, "stop")
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(asyncio.shield(session._task), 2)  # type: ignore[arg-type]
    assert records[-1]["status"] == "cancelled"


def test_pause_and_go_on_in_the_midrun_grammar() -> None:
    assert route_midrun("Pause.").action == "pause"  # type: ignore[union-attr]
    assert route_midrun("pause it").action == "pause"  # type: ignore[union-attr]
    assert route_midrun("Go on.").action == "resume"  # type: ignore[union-attr]
    assert route_midrun("carry on please").action == "resume"  # type: ignore[union-attr]
    assert route_midrun("pause the music in the other room") is None


async def test_pause_stops_and_keeps_it_then_go_on_needs_no_wake_phrase() -> None:
    session, out, records, stt = make_hands_free(wake_followup_s=8.0)
    await until_confirm(session, out)
    await say(session, stt, "pause")
    await finish(session)
    assert out.last("result") == {**out.last("result"), "status": "cancelled", "summary": PAUSED_HINT}
    assert records[0]["paused"]
    assert out.last("followup")["open"] is True  # "go on" next needs no "hey Swift"
    assert session.wants_short()  # and may be said briskly


async def test_go_on_during_a_run_just_says_it_is_going() -> None:
    session, out, records, stt = make_hands_free(scenario="happy", speed=0.5)
    await session.handle(Message("debug.run", {"scenario": "happy"}))
    deadline = time.monotonic() + 8
    while session.state != "working":
        assert time.monotonic() < deadline
        await asyncio.sleep(0.005)
    await say(session, stt, "go on")
    assert out.last("run.voice")["text"] == "It's still going." and session.state == "working"
    await session.cancel()


# ---- 2. "show me" during a run brings the app it writes in -------------------------------------


async def test_show_me_while_writing_brings_the_app_to_the_front() -> None:
    from swift.executors.mock import MockExecutor

    desktop = FakeDesktop(front=FakeApp("notepad.exe"))
    tools = ToolHost(desktop=desktop)
    out, mock = Outbox(), MockExecutor(speed=0)
    session = Session(out, mock, debug_executor=mock, demo_speed=0, tools=tools, desktop=desktop)
    await session.handle(Message("debug.run", {"scenario": "confirm"}))
    await asyncio.wait_for(out.confirm.wait(), 2)
    scope = session._scope
    assert scope is not None
    writer = await desktop.writer("word", "insert")
    tools.live_write = (scope, writer.live())  # what desktop_write sets while it writes
    views = sum(1 for m in out.messages if m.type == "view")
    await session.handle(Message("view", {"action": "show"}))
    assert desktop.front is desktop.word and len(desktop.shown) == 1
    assert out.last("run.voice")["text"] == "Here it is in Word."
    assert sum(1 for m in out.messages if m.type == "view") == views  # no empty steps view
    # Another request's write is not this one's work: the steps view, as before.
    other = types.SimpleNamespace()
    tools.live_write = (other, writer.live())  # type: ignore[assignment]
    await session.handle(Message("view", {"action": "show"}))
    assert out.last("view") == {"run_id": "mock-1", "artifact_id": None, "open": True}
    await session.cancel()


async def test_desktop_write_publishes_the_live_receipt_while_it_writes() -> None:
    from swift.security.gateway import ActionGateway
    from swift.security.journal import Journal
    from swift.workflows.desktop_tools import desktop_write
    from swift.workflows.scope import RunScope

    desktop = FakeDesktop(front=FakeApp("notepad.exe"))
    tools = ToolHost(gateway=ActionGateway(Journal(None)), desktop=desktop)
    seen: list[Any] = []

    async def on_write(n: int) -> None:
        seen.append(tools.live_write)

    desktop.on_write = on_write

    async def publish(*a: Any) -> None:
        return None

    async def confirm(*a: Any) -> str:
        return "approve"

    scope = RunScope(publish, confirm, said="write it in Word")
    result = await desktop_write(tools, scope, {"text": "one\n\ntwo", "where": "word"})
    assert result.ok
    assert seen and all(s is not None and s[0] is scope and s[1].app == "Word" for s in seen)
    assert tools.live_write is None and tools.last_write_scope is scope and tools.last_write is not None


# ---- 3. unlocking ---------------------------------------------------------------------------------


def test_a_pause_overtaken_by_a_resume_never_closes_the_microphone(fake_sd: Any) -> None:  # noqa: F811
    from swift.audio.recorder import MicRecorder

    r = MicRecorder(asyncio.new_event_loop(), keep_open=True)
    r.prepare().result()
    first = FakeStream.instances[0]
    # Locked, then unlocked, while the audio thread was busy: both queued, the resume newest.
    stale = r._want()
    newest = r._want()
    r._pause(stale)
    assert not first.closed and not r.paused  # skipped: resumed since
    r._resume(newest)
    assert not first.closed and len(FakeStream.instances) == 1  # still delivering: not reopened
    # In order, a pause still pauses and a resume reopens.
    r.pause()
    assert first.closed and r.paused
    r.resume()
    assert len(FakeStream.instances) == 2 and FakeStream.instances[1].active and r.opened_at > 0


class OrderedStt:
    """Records when the speech model is warmed relative to the microphone."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def start_loading(self) -> None:
        self.calls.append("speech")

    async def wait_loaded(self) -> None:
        return None

    def prime(self) -> None:
        self.calls.append("primed")


class OrderedRecorder(FakeRecorder):
    def __init__(self, calls: list[str]) -> None:
        super().__init__()
        self.calls = calls

    def resume(self) -> None:
        self.paused = False
        self.calls.append("mic")

    def pause(self) -> None:
        self.paused = True
        self.calls.append("pause")


async def test_unlocking_warms_the_speech_model_before_the_microphone_and_logs_when_listening() -> None:
    calls: list[str] = []
    marks: list[str] = []
    session = types.SimpleNamespace(listening_paused=False, mark_return=marks.append)
    probe, clock = Probe(), Clock()
    life = Lifecycle(session, Outbox(), recorder=OrderedRecorder(calls), transcriber=OrderedStt(calls),
                     executor=FakeExecutor(), wake_enabled=True, clock=clock, spare_after_speech_s=0.0)
    m = PresenceMonitor(probe, lambda c: None, clock=clock)
    life.attach(m)
    lines: list[str] = []
    sink = logger.add(lambda msg: lines.append(str(msg)), format="{message} {extra}")
    try:
        probe.is_locked = True
        clock.t += POLL_S
        await life.handle(m.poll())  # type: ignore[arg-type]
        probe.is_locked = False
        clock.t += POLL_S
        await life.handle(m.poll())  # type: ignore[arg-type]
        assert life._warming is not None
        await life._warming
    finally:
        logger.remove(sink)
    assert calls[:3] == ["pause", "speech", "mic"]  # the speech model is started before the mic reopens
    assert marks == ["unlocked"]
    ready = [line for line in lines if line.startswith("listening again")]
    assert len(ready) == 1 and "'reason': 'unlocked'" in ready[0] and "'mic_ms'" in ready[0]


async def test_presence_polls_faster_while_locked() -> None:
    probe, clock = Probe(), Clock()
    m = PresenceMonitor(probe, lambda c: None, clock=clock)
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError
        await real_sleep(0)

    probe.is_locked = True
    import swift.presence as presence

    presence.asyncio.sleep = fake_sleep  # type: ignore[assignment]
    try:
        with contextlib.suppress(asyncio.CancelledError):
            await m.run()
    finally:
        presence.asyncio.sleep = real_sleep  # type: ignore[assignment]
    assert sleeps[0] == AWAY_POLL_S < POLL_S


async def test_the_first_wake_after_coming_back_says_how_long_it_was() -> None:
    from test_wake import make as make_wake

    session, out, records, rec, stt = make_wake("Hey Swift, what time is it?")
    session.mark_return("unlocked")
    session._returned = ("unlocked", time.monotonic() - 2.0)
    await session.hear_wake(SHORT, time.monotonic())
    await asyncio.wait_for(asyncio.shield(session._task), 2)  # type: ignore[arg-type]
    assert records[0]["back"] == "unlocked" and 1900 <= records[0]["since_back_ms"] <= 3000
    assert session._returned is None  # only the first one


# ---- 4. a question waits for the answer ---------------------------------------------------------


class AskingAgent(Agent):
    async def result(self, run_id: str) -> ExecResult:
        await super().result(run_id)
        return ExecResult("done", "Which day, and what time?")


async def test_a_question_from_behind_comes_to_the_front_and_listens_for_the_answer() -> None:
    session, out, records, agent, stt = make_runs(AskingAgent, wake_followup_s=8.0, wake_question_s=25.0)
    first = await started(session, out, agent, stt, "Hey Swift, add lunch with Test Me to my calendar")
    await say(session, stt, "Hey Swift, what time is it?")  # beside it, and in front
    await until(lambda: out.last("result")["summary"].startswith("It's"))
    assert out.last("runs")["focus"].startswith("local-")
    agent.runs[first]["go"].set()
    await until(lambda: out.last("followup").get("question") is True)
    assert out.last("followup") == {"open": True, "seconds": 25.0, "question": True}
    assert out.last("runs")["focus"] == first and out.last("result")["summary"] == "Which day, and what time?"
    session._drop_question()


# ---- 5. the fast lane remembers its last answer -------------------------------------------------

NOW = datetime(2026, 10, 27, 13, 27, tzinfo=timezone.utc)


def test_and_the_date_is_about_the_day_just_answered() -> None:
    said, moment = fast.reply("What day will it be one week from today?", NOW)  # type: ignore[misc]
    assert "Tuesday" in said and moment is not None
    for follow in ("And the date?", "and what date is that", "what date is that", "And what's the date?"):
        assert fast.reply(follow, NOW, moment) == ("That's Tuesday, 3 November 2026.", moment), follow
    assert fast.reply("what day is that", NOW, moment)[0] == "That's a Tuesday."  # type: ignore[index]
    # Said fresh, "what's the date" is still today.
    assert fast.reply("what's the date", NOW, moment)[0] == "It's Tuesday, 27 October 2026."  # type: ignore[index]


def test_time_follow_ups_and_other_cities() -> None:
    _, later = fast.reply("what time will it be in 3 hours", NOW)  # type: ignore[misc]
    assert fast.reply("and in Tokyo?", NOW, later)[0] == "That's 01:27 in Tokyo, Wednesday."  # type: ignore[index]
    assert fast.reply("what time is that in Tokyo", NOW, later)[0] == "That's 01:27 in Tokyo, Wednesday."  # type: ignore[index]
    assert fast.reply("what time is that there", NOW, later) is None  # no place yet: the agent asks
    _, tokyo = fast.reply("what time is it in Tokyo", NOW)  # type: ignore[misc]
    assert fast.reply("what time is that there", NOW, tokyo)[0] == "That's 22:27 in Tokyo."  # type: ignore[index]
    # A day with no time of day: "and the time?" is not "now".
    _, day = fast.reply("What day will it be one week from today?", NOW)  # type: ignore[misc]
    assert fast.reply("and the time?", NOW, day) is None
    assert fast.answer("and the time?", NOW) == "It's 13:27."  # with nothing before it, it is now


class Spy(EchoExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[str] = []

    async def start(self, task: WorkerTask, **kw: Any) -> str:
        request = task.prompt
        self.requests.append(request)
        return await super().start(task, **kw)


def follow_session() -> tuple[Session, Outbox, list[dict[str, Any]], FakeTranscriber, Spy]:
    out, records, stt, spy = Outbox(), [], FakeTranscriber(text=""), Spy()
    session = Session(out, spy, recorder=LeadRecorder(), transcriber=stt, on_finish=records.append, tail_s=0.0,
                      wake_followup_s=8.0)
    return session, out, records, stt, spy


async def settle(session: Session) -> None:
    for run in list(session._runs):
        if run.task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(run.task), 2)


async def test_in_a_thread_and_the_date_follows_the_last_local_answer() -> None:
    session, out, records, stt, spy = follow_session()
    await say(session, stt, "Hey Swift, what day will it be one week from today?")
    await settle(session)
    first = out.last("result")["summary"]
    assert "a " in first and records[0]["action"] == "answer"
    await say(session, stt, "And the date?")  # in the reply window: same thread
    await settle(session)
    assert records[1]["thread"] == records[0]["thread"] and records[1]["source"] == "followup"
    in_a_week = datetime.now().astimezone() + timedelta(days=7)
    assert out.last("result")["summary"] == f"That's {in_a_week.strftime('%A')}, {in_a_week.day} {in_a_week.strftime('%B %Y')}."
    assert spy.requests == []


async def test_a_follow_up_the_fast_lane_cant_answer_goes_to_the_agent_with_the_answer() -> None:
    session, out, records, stt, spy = follow_session()
    await say(session, stt, "Hey Swift, what time will it be in 3 hours?")
    await settle(session)
    await say(session, stt, "What time is that there?")  # "there" with no place: the agent, with context
    await settle(session)
    assert records[1]["route"] == "agent" and records[1]["follows_local"]
    assert len(spy.requests) == 1 and "Previous answer: It'll be" in spy.requests[0]
    assert spy.requests[0].rstrip().endswith("What time is that there?")
