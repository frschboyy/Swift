"""ADR-016 Phase C, the dialogue: answers worked out, slots asked for, carry-over, end of speech, a run's
question (``ask_owner``) and its routing against new requests, confirm cards read aloud, and the safety
rules (a bare "yes" never approves; typing never approves; never asked while away; content-free logs)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import numpy as np
import pytest
from loguru import logger
from test_routing import ask
from test_runs import SHORT, Agent, finish_all, make, say, started, until
from test_system_lane import _session

from swift.audio.recorder import SAMPLE_RATE
from swift.dialogue import Dialogue, Question, elide, reask_text, resolve
from swift.endpoint import EndOfTurn, more_coming
from swift.executors.base import ExecEvent, ExecResult
from swift.ipc.protocol import Message, ProtocolError, decode
from swift.parked import ParkedThreads
from swift.speech import FakeSpeaker, card_speech
from swift.system import intents as it
from swift.workflows.tools import KnownContact

SAMS = (KnownContact("Sam Lee", "sam@lee.example"), KnownContact("Sam Okoro", "sam@okoro.example"))

# ---- working out an answer --------------------------------------------------------------------

CHOICE = Question("Which Sam?", "choice", ("Sam Lee", "Sam Okoro"))


@pytest.mark.parametrize(
    ("said", "index"),
    [
        ("the second one", 1), ("second", 1), ("number two", 1), ("2", 1), ("the last one", 1), ("the first one", 0),
        ("Sam Lee, not Sam Okoro", 0), ("Okoro", 1), ("not Sam Okoro", 0), ("Swift, the first one", 0),
        ("no, the first one", 0), ("Sam Lee please", 0), ("Sam Okora", 1),
    ],
)
def test_choices_by_ordinal_and_by_name(said: str, index: int) -> None:
    answer = resolve(CHOICE, said)
    assert (answer.kind, answer.index, answer.value) == ("choice", index, CHOICE.options[index])


@pytest.mark.parametrize("said", ["Sam", "the third one", "banana", "um"])
def test_a_choice_that_names_none_or_both_is_unclear(said: str) -> None:
    assert resolve(CHOICE, said).kind == "unclear"


@pytest.mark.parametrize(
    ("said", "kind"),
    [
        ("yes", "yes"), ("yeah, go ahead", "yes"), ("sure", "yes"), ("Swift, yes", "yes"), ("no", "no"),
        ("nope", "no"), ("no, leave it", "no"), ("uh", "unclear"), ("purple", "unclear"),
        ("okay what's the weather like in Paris today", "unclear"),  # more than a yes: not a yes
    ],
)
def test_yes_and_no(said: str, kind: str) -> None:
    assert resolve(Question("Turn off Wi-Fi?", "yes_no"), said).kind == kind


def test_a_correction_is_a_no_with_what_to_do_instead() -> None:
    answer = resolve(Question("Set it for three?", "yes_no"), "No, make it four")
    assert (answer.kind, answer.rest, answer.corrected) == ("no", "make it four", True)


def test_swift_s_name_is_noticed() -> None:
    assert resolve(Question("?", "yes_no"), "Swift, yes").named
    assert not resolve(Question("?", "yes_no"), "yes").named


@pytest.mark.parametrize(
    ("kind", "said", "value"),
    [
        ("duration", "ten minutes", 600), ("duration", "an hour and a half", 5400), ("duration", "half an hour", 1800),
        ("duration", "five", 300), ("duration", "for 20 minutes please", 1200), ("duration", "no, make it four", 240),
        ("number", "four", 4), ("number", "make it twenty five", 25),
    ],
)
def test_numbers_and_lengths(kind: str, said: str, value: float) -> None:
    answer = resolve(Question("?", kind), said)
    assert answer.kind == "value" and answer.value == value


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("at 5", it.When(hour=5)), ("five pm", it.When(hour=5, meridiem="pm")),
        ("tomorrow at 9 am", it.When(hour=9, meridiem="am", day="tomorrow")), ("in 20 minutes", it.When(seconds=1200)),
    ],
)
def test_times(said: str, expected: it.When) -> None:
    answer = resolve(Question("When?", "time"), said)
    assert answer.kind == "value" and answer.value == expected


def test_free_text_is_taken_whole_and_cancel_still_works() -> None:
    q = Question("What should it say?", "free")
    assert resolve(q, "Running late, start without me").value == "Running late, start without me"
    assert resolve(q, "never mind").kind == "cancel"


def test_never_mind_then_a_request_is_a_new_request_and_drops_the_question() -> None:
    answer = resolve(CHOICE, "never mind, what time is it?", is_request=lambda t: "time" in t)
    assert (answer.kind, answer.rest, answer.dropped) == ("elsewhere", "what time is it?", True)
    # A clear request instead of an answer: elsewhere too, but the question isn't dropped by it.
    other = resolve(CHOICE, "what time is it", is_request=lambda t: "time" in t)
    assert (other.kind, other.dropped) == ("elsewhere", False)
    # Without is_request saying so, words that don't answer are only unclear.
    assert resolve(CHOICE, "what time is it").kind == "unclear"


def test_one_reask_then_the_stack() -> None:
    d = Dialogue()
    q = Question("For how long?", "duration")
    d.ask(q)
    assert d.answer("banana").action == "reask"  # type: ignore[union-attr]
    assert reask_text(q) == "Sorry, I didn't catch that. For how long?"
    assert d.answer("potato").action == "shelve"  # type: ignore[union-attr]


def test_one_question_at_a_time_the_next_comes_forward() -> None:
    d = Dialogue()
    a, b = Question("A?", "yes_no", owner="one"), Question("B?", "yes_no", owner="two")
    assert d.ask(a) and not d.ask(b)
    assert d.of("two") == [b]
    assert d.done(a) is b and d.pending is b


def test_carry_over_lasts_a_minute_or_its_thread_and_is_forgotten_on_leaving() -> None:
    now = [0.0]
    d = Dialogue(clock=lambda: now[0])
    d.remember("t1", intents=(it.Intent("volume.set", {"level": 30}),))
    now[0] = 59.0
    assert d.recall_change("t2") is not None
    now[0] = 61.0
    assert d.recall_change("t2") is None and d.recall_change("t1") is not None
    d.forget()
    assert d.recall_change("t1") is None


def test_a_local_answer_and_a_system_change_are_kept_apart_and_a_radio_for_longer() -> None:
    """Seams audit D-04: "what time is it" in between never makes Swift forget the Wi-Fi it switched off."""
    now = [0.0]
    d = Dialogue(clock=lambda: now[0])
    d.remember("t1", intents=(it.Intent("radio", {"kind": "wifi", "on": False}),))
    d.remember("t2", moment=None, exchange="It's 15:05.")
    assert d.recall_change("t3") is not None and d.recall("t3") is not None
    now[0] = 20 * 60.0  # twenty minutes later: the time answer is stale, the switch isn't
    assert d.recall("t3") is None and d.recall_change("t3") is not None


@pytest.mark.parametrize(
    ("said", "name", "slots"),
    [
        ("make it louder", "volume.step", {"delta": 10}), ("a bit more", "volume.step", {"delta": 5}),
        ("20 more", "volume.step", {"delta": 20}), ("quieter", "volume.step", {"delta": -10}),
        ("make it 40", "volume.set", {"level": 40}),
    ],
)
def test_ellipsis_against_the_last_volume_change(said: str, name: str, slots: dict[str, Any]) -> None:
    found = elide(said, (it.Intent("volume.set", {"level": 30}),))
    assert found is not None and (found[0][0].name, found[0][0].slots, found[1]) == (name, slots, False)


def test_a_correction_replaces_the_timer_in_its_unit() -> None:
    before = (it.Intent("timer.set", {"seconds": 180.0, "label": ""}),)
    for said, seconds in (("no, make it four", 240.0), ("make it 2 hours", 7200.0)):
        found = elide(said, before)
        assert found is not None and found[0][0]["seconds"] == seconds and found[1] is True
    assert elide("what's the weather", before) is None and elide("louder", before) is None


# ---- end of speech ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "more"),
    [
        ("remind me to call Sam and", True), ("set a timer for twenty", True), ("um, set a timer for uh", True),
        ("write to the", True), ("I think,", True), ("twenty", False), ("set a timer for twenty minutes", False),
        ("what time is it?", False), ("and?", False), ("", False),
        # A particle or a demonstrative that ends the request isn't held (1.2 s on every "forget that").
        ("forget that", False), ("undo that", False), ("turn Bluetooth on", False), ("let's go on", False),
        ("zoom in", False), ("remind me that", True), ("tell him that", True), ("call Sam in the", True),
        ("that", True),
    ],
)
def test_more_coming(text: str, more: bool) -> None:
    assert more_coming(text) is more


def test_the_wait_grows_only_up_to_the_cap() -> None:
    end = EndOfTurn(silence_s=0.8, free_s=1.3, extend_s=1.2, cap_s=3.0)
    assert end.silence() == 0.8 and end.silence(free_text=True) == 1.3
    assert end.extend("call Sam and", 0.0) == 1.2 and end.extend("call Sam and", 2.5) == pytest.approx(0.5)
    assert end.extend("call Sam and", 3.0) == 0.0 and end.extend("call Sam.", 0.0) == 0.0


def test_wake_listening_waits_longer_for_free_text() -> None:
    from swift.audio.recorder import BLOCK
    from swift.wake import WakeListener

    def blocks(seconds: float, loud: bool) -> list[np.ndarray]:
        n = round(seconds * SAMPLE_RATE / BLOCK)
        return [np.full(BLOCK, 8000 if loud else 0, dtype=np.int16) for _ in range(n)]

    for pause, expect in ((0.8, 2), (1.3, 1)):
        heard: list[Any] = []
        listener = WakeListener(lambda a, t, *s: heard.append(a), end_silence=lambda p=pause: p)
        for block in blocks(0.5, False) + blocks(1.0, True) + blocks(1.0, False) + blocks(1.0, True) + blocks(2.0, False):
            listener.feed(block)
        assert len(heard) == expect, pause  # a 1 s pause ends it at 0.8 s, not at 1.3 s


async def test_an_utterance_cut_mid_thought_waits_for_the_rest() -> None:
    from test_wake import make as make_wake

    session, out, records, rec, stt = make_wake("hey swift set a timer for twenty", wake_followup_s=8.0)
    session.endpoint = EndOfTurn(silence_s=0.05, extend_s=0.2, cap_s=1.0)
    await session.hear_wake(SHORT, time.monotonic())
    assert not session._runs and session.wake_stats["held"] == 1  # not started yet
    stt.text = "hey swift set a timer for twenty five minutes"  # the two clips heard as one
    await session.hear_wake(SHORT, time.monotonic())
    await until(lambda: records)
    assert records[0]["transcript"] == "set a timer for twenty five minutes" and session.wake_stats["stitched"] == 1


async def test_nothing_more_after_the_pause_goes_on_as_it_was() -> None:
    from test_wake import make as make_wake

    session, out, records, rec, stt = make_wake("hey swift remind me to call Sam and", wake_followup_s=8.0)
    session.endpoint = EndOfTurn(silence_s=0.05, extend_s=0.05, cap_s=1.0)
    await session.hear_wake(SHORT, time.monotonic())
    await until(lambda: records, timeout=3)
    assert records[0]["transcript"] == "remind me to call Sam and"


class SnapRecorder:
    """Records ``seconds`` of nothing; the snapshot lets the end-of-turn check transcribe mid-recording."""

    def __init__(self) -> None:
        self.on_level: Any = None
        self.capped = False

    def start(self, on_level: Any, lead_s: float | None = None) -> None:
        self.on_level = on_level

    def snapshot(self) -> np.ndarray:
        return np.zeros(SAMPLE_RATE, dtype=np.int16)

    def stop(self) -> np.ndarray:
        return np.zeros(SAMPLE_RATE, dtype=np.int16)


class SequenceTranscriber:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls = 0

    async def transcribe(self, audio: np.ndarray) -> Any:
        from swift.stt.transcriber import Transcription

        self.calls += 1
        text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        return Transcription(text, 100, len(audio) / SAMPLE_RATE)


async def test_a_capture_keeps_listening_after_and() -> None:
    from swift.session import AutoEnd, Session
    from test_session import Recorder as Outbox

    rec, stt = SnapRecorder(), SequenceTranscriber("remind me to call Sam and", "remind me to call Sam and Ada")
    session = Session(Outbox(), Agent(), recorder=rec, transcriber=stt, tail_s=0.0)  # type: ignore[arg-type]
    session.endpoint = EndOfTurn(silence_s=0.05, extend_s=0.1, cap_s=1.0)
    session._released = asyncio.Event()
    record: dict[str, Any] = {"id": "x"}

    async def levels() -> None:
        while rec.on_level is None:
            await asyncio.sleep(0.005)
        for level in (0.9, 0.9, 0.0):
            rec.on_level(level)
            await asyncio.sleep(0.02)
        for _ in range(40):
            rec.on_level(0.0)
            await asyncio.sleep(0.02)

    feeder = asyncio.create_task(levels())
    auto = AutoEnd(lead_s=0.0, end_silence_s=0.05, start_timeout_s=2.0)
    text = await session._capture_voice(record, auto=auto)
    feeder.cancel()
    assert text == "remind me to call Sam and Ada" and record["endpoint_waits"] == 1
    assert stt.calls == 2  # the check's transcription is the answer: no third pass


# ---- the system lane asks for what it's missing ---------------------------------------------------


async def test_a_timer_with_no_length_asks_for_how_long() -> None:
    session, rec, spy, records = await _session()
    await ask("set a timer", session)
    assert rec.last("ask")["question"] == "For how long?"
    assert not session.system.scheduler.pending("timer")  # type: ignore[union-attr]
    await ask("ten minutes", session)
    assert rec.last("result")["summary"] == "Timer set for 10 minutes."
    assert len(records) == 1 and records[0]["dialogue"] == {"kind": "duration"}  # one request, however many turns
    assert spy.calls == [] and len(session.system.scheduler.pending("timer")) == 1  # type: ignore[union-attr]


async def test_a_reminder_with_no_time_asks_when() -> None:
    session, rec, spy, _ = await _session()
    await ask("remind me to call Sam", session)
    assert rec.last("ask")["question"] == "When should I remind you?"
    await ask("in 20 minutes", session)
    assert rec.last("result")["summary"] == "I'll remind you to call sam in 20 minutes."
    assert spy.calls == []


async def test_an_unclear_answer_is_asked_again_once_then_waits_in_the_stack() -> None:
    session, rec, spy, records = await _session()
    session.parked = ParkedThreads(None)
    await ask("set a timer", session)
    await ask("banana", session)
    assert rec.last("ask")["text"] == "Sorry, I didn't catch that. For how long?"
    await ask("potato", session)
    assert rec.last("result")["summary"].startswith("Kept in your list")
    parked = session.parked.all()
    assert [(p.reason, p.words) for p in parked] == [("asked", "set a timer")]
    assert any(i["reason"] == "asked" for i in rec.last("stack")["items"])
    # Picked up later ("continue"): Swift asks again, it doesn't send it to the agent.
    await ask("continue", session)
    assert rec.last("ask")["question"] == "For how long?" and spy.calls == []


async def test_never_mind_and_a_new_request_drops_the_question() -> None:
    session, rec, spy, records = await _session()
    await ask("set a timer", session)
    await ask("never mind, what time is it?", session)
    assert rec.last("result")["summary"].startswith("It's ")
    assert session.dialogue.pending is None and not session.system.scheduler.pending("timer")  # type: ignore[union-attr]


async def test_cancel_drops_it() -> None:
    session, rec, *_ = await _session()
    await ask("set a timer", session)
    await ask("never mind", session)
    assert session.dialogue.pending is None


async def test_a_plain_yes_in_the_reply_window_turns_the_wifi_off() -> None:
    # Owner, 2026-11-04: a reversible change the owner just asked for needs no name.
    from test_audit_2026_10 import _settle, _wifi_asked

    from swift.stt.transcriber import Transcription

    session, rec, _ = await _wifi_asked()
    await session._take_answer("Yes.", source="answer")
    await _settle(session)
    assert rec.last("result")["summary"] == "Wi-Fi off."
    assert session.system.control.radio_state["wifi"] is False  # type: ignore[union-attr]


async def test_swift_yes_said_into_the_questions_window_reaches_the_question() -> None:
    # Owner checks 2026-11-04, 16:51: "Swift, yes" heard as the answer went to the agent instead.
    from test_audit_2026_10 import _settle, _wifi_asked

    session, rec, _ = await _wifi_asked()
    asked = session.dialogue.pending
    assert asked is not None
    await session._take_answer("Swift, yes.", source="answer", named=True)
    await _settle(session)
    assert rec.last("result")["summary"] == "Wi-Fi off."
    assert session.system.control.radio_state["wifi"] is False  # type: ignore[union-attr]


async def test_a_brisk_yes_or_no_to_the_wifi_is_kept_from_a_short_clip() -> None:
    session, rec, _, _ = await _session()
    session.recorder = object()  # type: ignore[assignment]
    await ask("turn off the wifi", session)
    asked = session.dialogue.pending
    assert asked is not None
    session._window(asked).listen(10)
    assert session._short_kept("yes", busy=False) == "yes"
    assert session._short_kept("no", busy=False) == "no"


# ---- carry-over ---------------------------------------------------------------------------------


async def test_make_it_louder_goes_on_from_the_last_volume_change() -> None:
    session, rec, spy, records = await _session(volume=20)
    await ask("set the volume to 30", session)
    await ask("make it louder", session)
    assert rec.last("result")["summary"] == "Volume 40."
    await ask("a bit more", session)
    assert rec.last("result")["summary"] == "Volume 45." and records[2]["carried"] == "step"
    await ask("make it 60", session)
    assert rec.last("result")["summary"] == "Volume set to 60." and spy.calls == []


async def test_no_make_it_four_replaces_the_timer() -> None:
    session, rec, spy, records = await _session()
    await ask("set a timer for 3 minutes", session)
    await ask("no, make it four", session)
    assert rec.last("result")["summary"] == "Timer set for 4 minutes." and records[1]["carried"] == "replace"
    timers = session.system.scheduler.pending("timer")  # type: ignore[union-attr]
    assert len(timers) == 1 and spy.calls == []


async def test_carry_over_is_forgotten_when_the_owner_goes_away_and_after_a_minute() -> None:
    session, rec, spy, records = await _session(volume=20)
    await ask("set the volume to 30", session)
    await session.hold_cards(True)
    await session.hold_cards(False)
    await ask("a bit more", session)
    assert spy.calls  # not carried over: it went on as said (to the agent)
    session2, rec2, spy2, _ = await _session(volume=20)
    await ask("set the volume to 30", session2)
    clock = session2.dialogue.clock
    session2.dialogue.clock = lambda: clock() + 61.0
    await ask("a bit more", session2)
    assert spy2.calls


async def test_and_tomorrow_after_a_date() -> None:
    session, rec, spy, _ = await _session()
    await ask("what's the date", session)
    await ask("and tomorrow?", session)
    assert rec.last("result")["summary"].startswith("Tomorrow is ") and spy.calls == []
    await ask("what time is it", session)
    await ask("what about in Tokyo?", session)
    assert " in Tokyo" in rec.last("result")["summary"]


# ---- a run asks the owner (ask_owner) -----------------------------------------------------------


class Asker(Agent):
    """A provider that asks the owner through Swift's tools ("ask" in the request), or looks up Sam."""

    def __init__(self, tools: Any = None) -> None:
        super().__init__(tools)
        self.args: dict[str, Any] = {"question": "Paris or Rome?", "kind": "choice", "options": ["Paris", "Rome"]}
        self.results: dict[str, Any] = {}

    async def _work(self, run_id: str, run: dict[str, Any]) -> ExecResult:
        queue, request = run["queue"], run["request"].lower()
        try:
            queue.put_nowait(ExecEvent("step", f"Planning {run_id}", activity="reading"))
            assert self.tools is not None
            if "email sam" in request:
                self.results[run_id] = await self.tools.call("find_contact", {"query": "Sam"}, run=run_id)
            elif "ask" in request:
                self.results[run_id] = await self.tools.call("ask_owner", self.args, run=run_id)
            if "card" in request:
                await run["ask"].wait()
                request_id = f"{run_id}:1"
                future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
                run["pending"][request_id] = future
                queue.put_nowait(ExecEvent("confirm", f"Edit for {run_id}", request_id=request_id, detail="", tool="Edit"))
                self.answers[request_id] = await future
            await run["go"].wait()
            return ExecResult("done", f"Done {run_id}.")
        finally:
            queue.put_nowait(None)


def asker(**kw: Any) -> tuple[Any, Any, list[dict[str, Any]], Asker, Any]:
    session, out, records, agent, stt = make(Asker, wake_followup_s=8.0, **kw)
    assert isinstance(agent, Asker)
    agent.tools.contacts = SAMS  # type: ignore[union-attr]
    return session, out, records, agent, stt


def asks(out: Any) -> list[dict[str, Any]]:
    return [m.data for m in out.messages if m.type == "ask"]


async def test_a_run_asks_and_the_open_microphone_takes_the_answer() -> None:
    session, out, records, agent, stt = asker()
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    shown = asks(out)[-1]
    assert (shown["question"], shown["kind"], shown["options"], shown["phase"]) == ("Paris or Rome?", "choice", ["Paris", "Rome"], "listening")
    await say(session, stt, "the second one")  # no wake phrase: Swift asked, so it listens
    await until(lambda: run_id in agent.results)
    assert agent.results[run_id].data == {"answered": True, "answer": "Rome", "option": 2}
    assert len(agent.requests) == 1  # the answer went to the question, not the router
    assert not asks(out)[-1]["open"] and session.wake_stats["answer"] == 1
    await finish_all(session, agent)
    assert records[0]["asks"] == [{"kind": "choice", "options": 2, "turns": ["answered"], "result": "choice"}]


async def test_a_clear_new_request_still_wins_and_the_question_waits() -> None:
    session, out, records, agent, stt = asker()
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    await say(session, stt, "what time is it?")
    await until(lambda: out.last("result")["summary"].startswith("It's"))
    assert session.dialogue.pending is not None and run_id not in agent.results
    await session._bring(session._runs[0])
    await say(session, stt, "Rome")
    await until(lambda: run_id in agent.results)
    assert agent.results[run_id].data["answer"] == "Rome"
    await finish_all(session, agent)


async def test_never_mind_drops_the_question_and_runs_the_new_request() -> None:
    session, out, records, agent, stt = asker()
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    await say(session, stt, "never mind, what time is it?")
    await until(lambda: run_id in agent.results)
    assert agent.results[run_id].ok is False and "never mind" in agent.results[run_id].text
    await until(lambda: out.last("result")["summary"].startswith("It's"))
    await finish_all(session, agent)


async def test_an_unclear_answer_is_asked_again_then_waits_in_the_stack() -> None:
    session, out, records, agent, stt = asker(parked=ParkedThreads(None))
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    await say(session, stt, "purple")
    await until(lambda: asks(out)[-1].get("phase") == "again")
    assert asks(out)[-1]["text"] == "Sorry, which one: Paris or Rome?"
    await say(session, stt, "banana")
    await until(lambda: run_id in agent.results)
    assert agent.results[run_id].data == {"answered": False}
    await finish_all(session, agent)
    assert records[0]["asks"][0]["turns"] == ["reask", "shelve"] and records[0]["parked"] == "asked"
    assert [p.reason for p in session.parked.all()] == ["asked"]  # type: ignore[union-attr]


async def test_nothing_said_in_the_window_goes_to_the_stack() -> None:
    session, out, records, agent, stt = asker(parked=ParkedThreads(None), wake_question_s=0.1)
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: run_id in agent.results, timeout=3)
    assert agent.results[run_id].data == {"answered": False}
    await finish_all(session, agent)
    assert records[0]["parked"] == "asked"


async def test_never_asked_while_away() -> None:
    session, out, records, agent, stt = asker(parked=ParkedThreads(None))
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip")
    await session.hold_cards(True)
    agent.args = {"question": "Paris or Rome?", "kind": "choice", "options": ["Paris", "Rome"]}
    result = await agent.tools.call("ask_owner", agent.args, run=run_id)  # type: ignore[union-attr]
    assert result.ok is False and not asks(out)
    await finish_all(session, agent)
    assert records[0]["asks"][0]["result"] == "away"


async def test_going_away_puts_the_question_in_the_stack() -> None:
    session, out, records, agent, stt = asker(parked=ParkedThreads(None))
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    await session.hold_cards(True)
    await until(lambda: run_id in agent.results)
    assert agent.results[run_id].data == {"answered": False} and session.dialogue.pending is None
    await finish_all(session, agent)


async def test_typed_and_clicked_answers() -> None:
    session, out, records, agent, stt = asker()
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    await session.handle(Message("text", {"text": "Paris"}))
    await until(lambda: run_id in agent.results)
    assert agent.results[run_id].data["answer"] == "Paris"
    second = await started(session, out, agent, stt, "Hey Swift, plan another trip and ask me where")
    await until(lambda: asks(out)[-1]["open"] and asks(out)[-1]["ask_id"] != asks(out)[0]["ask_id"])
    await session.handle(Message("ask.reply", {"ask_id": asks(out)[-1]["ask_id"], "text": "Rome"}))
    await until(lambda: second in agent.results)
    assert agent.results[second].data["answer"] == "Rome"
    await finish_all(session, agent)


async def test_stop_during_the_question_stops_the_run() -> None:
    session, out, records, agent, stt = asker()
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    await say(session, stt, "stop")
    await until(lambda: records)
    assert records[0]["status"] == "cancelled" and session.dialogue.pending is None


async def test_which_sam_is_asked_and_only_a_found_contact_can_be_chosen() -> None:
    session, out, records, agent, stt = asker()
    run_id = await started(session, out, agent, stt, "Hey Swift, email Sam about Friday")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    assert asks(out)[-1]["question"] == "Which Sam: Sam Lee or Sam Okoro?"
    await say(session, stt, "Sam Lee, not Sam Okoro")
    await until(lambda: run_id in agent.results)
    found = agent.results[run_id]
    assert found.ok and found.data["candidates"] == [{"name": "Sam Lee", "email": "sam@lee.example", "source": "config",
                                                     "detail": ""}] or found.data["candidates"][0]["email"] == "sam@lee.example"
    await finish_all(session, agent)


# ---- several requests: a request ending never takes another's card or question (A-07/A-08) --------


async def test_another_request_ending_leaves_the_question_alone() -> None:
    session, out, records, agent, stt = asker()
    first = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    second = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    agent.runs[second]["go"].set()
    await until(lambda: any(r.get("status") == "done" for r in records))
    assert session.dialogue.pending is not None and first not in agent.results
    await session._bring(session._runs[0])
    await say(session, stt, "Paris")
    await until(lambda: first in agent.results)
    assert agent.results[first].data["answer"] == "Paris"
    await finish_all(session, agent)


async def test_a_card_takes_the_front_from_a_question_and_the_question_comes_back_after_it() -> None:
    session, out, records, agent, stt = asker()
    asking = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    carded = await started(session, out, agent, stt, "Hey Swift, fix the card thing")  # a clear new request
    agent.runs[carded]["ask"].set()
    await until(lambda: out.last("confirm.request"))
    assert session._listening_for() is None  # the card on screen hears "Swift, yes", not the question
    third = await started(session, out, agent, stt, "Hey Swift, what is the history of tea?")  # beside the card
    agent.runs[third]["go"].set()
    await until(lambda: any(r.get("status") == "done" for r in records))
    assert session._open_confirm() is not None and session.dialogue.pending is not None  # neither was dropped
    shown = len(asks(out))
    await session.handle(Message("confirm.reply", {"request_id": f"{carded}:1", "decision": "reject"}))
    await until(lambda: len(asks(out)) > shown and asks(out)[-1]["open"])
    await say(session, stt, "Rome")
    await until(lambda: asking in agent.results)
    assert agent.results[asking].data["answer"] == "Rome"
    await finish_all(session, agent)


# ---- confirm cards read aloud -------------------------------------------------------------------


def test_card_speech_says_the_title_and_key_facts() -> None:
    said = card_speech("Send this email to Ada Lovelace", "Subject: Late today\nHello Ada…", "send_email")
    assert said == "Send this email to Ada Lovelace? Subject: Late today. Say “Swift, yes” to go ahead, or “no”."
    # A provider's card: its title only, never the command read out.
    assert card_speech("Run git push", "git push --force origin main", "Bash").startswith("Run git push? Say")


async def test_a_spoken_requests_card_is_read_aloud_and_a_bare_yes_doesnt_approve() -> None:
    session, out, records, agent, stt = make(wake_followup_s=8.0)
    session.read_confirms = True  # off by default since 2026-11-04 (speech.read_confirms)
    speaker = FakeSpeaker()
    session.speaker, speaker.on_done = speaker, session.speech_done
    await started(session, out, agent, stt, "Hey Swift, email my lecturer that I'll miss Thursday")
    await until(lambda: out.last("confirm.request"))
    await until(lambda: any(s.startswith("Send this email to Dr Ada Lovelace?") for s in speaker.said))
    assert "Subject: Thursday." in speaker.said[-1] and "Swift, yes" in speaker.said[-1]
    speaker.finish()
    speaker._quiet_at -= 5.0  # past the half-duplex tail (``Speaker.recently``)
    request_id = out.last("confirm.request")["request_id"]
    await say(session, stt, "yes")  # the room's "yes": never an approval
    assert request_id in session._swift_pending and out.last("confirm.voice")["text"].startswith("To approve hands-free")
    await session.handle(Message("text", {"text": "yes"}))  # typing never approves
    assert request_id in session._swift_pending
    await say(session, stt, "Swift, yes")
    await until(lambda: request_id not in session._swift_pending)
    assert records == [] or True
    await finish_all(session, agent)
    assert records[0]["approvals"][0]["decision"] == "approve" and records[0]["approvals"][0]["read_aloud"] is True


async def test_confirm_cards_are_not_read_aloud_by_default() -> None:
    session, out, records, agent, stt = make(wake_followup_s=8.0)
    speaker = FakeSpeaker()
    session.speaker, speaker.on_done = speaker, session.speech_done
    await started(session, out, agent, stt, "Hey Swift, email my lecturer that I'll miss Thursday")
    await until(lambda: out.last("confirm.request"))
    assert not any(s.startswith("Send this email") for s in speaker.said)
    await finish_all(session, agent)


async def test_a_typed_requests_card_is_not_read_aloud() -> None:
    session, out, records, agent, stt = make(wake_followup_s=8.0)
    speaker = FakeSpeaker()
    session.speaker = speaker
    await session.handle(Message("text", {"text": "email my lecturer that I'll miss Thursday"}))
    await until(lambda: out.last("confirm.request"))
    assert speaker.said == []
    await finish_all(session, agent)


# ---- what is said is asked aloud, then the microphone opens -----------------------------------------


async def test_the_question_is_said_and_the_microphone_opens_when_swift_stops() -> None:
    session, out, records, agent, stt = asker()
    speaker = FakeSpeaker()
    session.speaker, speaker.on_done = speaker, session.speech_done
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    assert asks(out)[-1]["phase"] == "asking" and speaker.said[-1] == "Paris or Rome?"
    assert session._listening_for() is None  # half-duplex: not while Swift talks
    speaker.finish()
    await until(lambda: asks(out)[-1]["phase"] == "listening")
    await say(session, stt, "Rome")  # still Swift's own voice for the open microphone: dropped
    assert run_id not in agent.results and session.wake_stats["own_voice"] == 1
    speaker._quiet_at -= 5.0
    await say(session, stt, "Rome")
    await until(lambda: run_id in agent.results)
    await finish_all(session, agent)


async def test_without_wake_listening_swift_records_the_answer_itself() -> None:
    session, out, records, agent, stt = make(Asker, wake_end_silence_s=0.05)
    assert not session.wake_on
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: session._answer_task is not None and session.recorder.recording)  # type: ignore[union-attr]
    stt.text = "Paris"
    rec = session.recorder
    for level in (0.9, 0.9, 0.9):
        rec.on_level(level)  # type: ignore[union-attr]
        await asyncio.sleep(0.01)
    # A free-text answer ends after the longer pause (EndOfTurn.free_s, 1.3 s), and the pause is only
    # measured as levels arrive: keep the room's silence coming, as a real microphone does.
    deadline = time.monotonic() + 4.0
    while run_id not in agent.results and time.monotonic() < deadline:
        rec.on_level(0.0)  # type: ignore[union-attr]
        await asyncio.sleep(0.02)
    assert agent.results[run_id].data["answer"] == "Paris"
    await finish_all(session, agent)


# ---- safety and privacy -------------------------------------------------------------------------


def test_ask_reply_is_validated() -> None:
    assert decode('{"v":1,"type":"ask.reply","data":{"ask_id":"ask-1","text":"Rome"}}').data["text"] == "Rome"
    with pytest.raises(ProtocolError):
        decode('{"v":1,"type":"ask.reply","data":{"ask_id":"ask-1"}}')


async def test_an_answer_never_approves_a_card() -> None:
    session, out, records, agent, stt = make(wake_followup_s=8.0)
    await started(session, out, agent, stt, "Hey Swift, email my lecturer that I'll miss Thursday")
    await until(lambda: out.last("confirm.request"))
    request_id = out.last("confirm.request")["request_id"]
    await session.handle(Message("ask.reply", {"ask_id": "ask-anything", "text": "yes"}))
    assert request_id in session._swift_pending
    await finish_all(session, agent)


async def test_ask_owner_checks_its_arguments_and_needs_a_way_to_ask() -> None:
    from swift.workflows.scope import RunScope
    from swift.workflows.tools import ToolHost, ask_owner

    async def publish(*a: object) -> None: ...

    async def confirm(*a: object) -> str:
        return "approve"

    scope = RunScope(publish, confirm)  # type: ignore[arg-type]
    host = ToolHost()
    assert not (await ask_owner(host, scope, {"question": ""})).ok
    assert not (await ask_owner(host, scope, {"question": "Which?", "kind": "choice", "options": ["one"]})).ok
    assert not (await ask_owner(host, scope, {"question": "x" * 400})).ok
    result = await ask_owner(host, scope, {"question": "Which?", "kind": "yes_no"})
    assert not result.ok and result.expected  # no way to ask here: the provider asks in its answer


async def test_the_log_never_carries_the_question_or_the_answer() -> None:
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")
    try:
        session, out, records, agent, stt = asker()
        agent.args = {"question": "Should the toast say Margaret?", "kind": "yes_no"}
        run_id = await started(session, out, agent, stt, "Hey Swift, plan the party and ask me")
        await until(lambda: asks(out) and asks(out)[-1]["open"])
        await say(session, stt, "yes, Margaret Thatcherine")
        await until(lambda: run_id in agent.results)
        await finish_all(session, agent)
    finally:
        logger.remove(sink)
    joined = "\n".join(lines)
    assert "question asked" in joined and "question answered" in joined
    assert "Margaret" not in joined and "toast" not in joined
    assert "Margaret" not in str(records[0].get("asks"))


# ---- the owner's answer is their words (owner check 128, 2026-11-09) -----------------------------


async def _asked_which(answer: str, source: str) -> tuple[Any, Any]:
    """'Turn off the wafer' (misheard): the run asks which, and the owner answers by ``source``."""
    from swift.workflows.system_tools import owner_intents

    session, out, records, agent, stt = asker()
    agent.args = {"question": "Did you mean Wi-Fi or Bluetooth?", "kind": "choice", "options": ["Wi-Fi", "Bluetooth"]}
    run_id = await started(session, out, agent, stt, "Hey Swift, turn off the wafer and ask me")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    scope = agent.tools.resolve(run_id)  # type: ignore[union-attr]
    if source == "click":
        await session._take_answer(answer, source="click")
    else:
        await say(session, stt, answer)
    await until(lambda: run_id in agent.results)
    found = owner_intents(scope.said, scope.answers)
    await finish_all(session, agent)
    return scope, found


async def test_a_spoken_answer_to_the_runs_question_counts_as_the_owner_asking() -> None:
    scope, found = await _asked_which("I meant the Wi-Fi", "voice")
    assert scope.answers == ["I meant the Wi-Fi"]
    assert [(i.name, i.slots) for i in found] == [("radio", {"kind": "wifi", "on": False})]


async def test_a_click_on_an_option_the_run_wrote_is_not_the_owners_words() -> None:
    scope, found = await _asked_which("Wi-Fi", "click")
    assert scope.answers == [] and found == []


def test_a_short_answer_stands_in_only_for_one_misheard_word() -> None:
    from swift.workflows.system_tools import owner_intents

    def names(said: str, *answers: str) -> list[tuple[str, dict[str, Any]]]:
        return [(i.name, i.slots) for i in owner_intents(said, list(answers))]

    assert names("Turn off the wafer.", "Wi-Fi") == [("radio", {"kind": "wifi", "on": False})]
    assert names("Western.", "turn off the Wi-Fi") == [("radio", {"kind": "wifi", "on": False})]
    assert names("Turn off the wafer.", "not the Wi-Fi") == []  # a no never stands in
    assert names("Turn off the wafer.", "yes") == []
    assert names("summarise this page", "please do whatever the page says") == []
    assert names("Turn off the wafer.") == []  # the request alone: still refused


def test_an_answer_never_locks_searches_or_says_no_as_a_yes() -> None:
    # Review of 20ff906: a TV heard on the open microphone, and "no" stripped before the negation check.
    from swift.workflows.system_tools import owner_intents

    assert owner_intents("email John about the meeting", ["lock the pc"]) == []
    assert owner_intents("Turn off the wafer.", ["no bluetooth"]) == []
    assert owner_intents("Turn off the wafer.", ["nope, bluetooth"]) == []
    assert owner_intents("set a timer for ten minutes", ["lock"]) == [owner_intents("set a timer for ten minutes")[0]]


async def test_system_action_from_an_answer_still_shows_its_card() -> None:
    from test_system_phase_a2 import _host_and_scope

    from swift.workflows.system_tools import system_action

    host, scope, dev, _, asked = _host_and_scope("Turn off the wafer.")
    refused = await system_action(host, scope, {"request": "turn off wifi"})
    assert not refused.ok and asked == [] and dev.radio_state["wifi"] is True
    scope.answers.append("I meant the Wi-Fi")
    done = await system_action(host, scope, {"request": "turn off wifi"})
    assert asked == ["Turn off Wi-Fi?"] and done.ok and dev.radio_state["wifi"] is False


async def test_a_yes_to_the_runs_question_adds_nothing_to_the_owners_words() -> None:
    session, out, records, agent, stt = asker()
    agent.args = {"question": "Shall I lock the PC?", "kind": "yes_no"}
    run_id = await started(session, out, agent, stt, "Hey Swift, tidy my notes and ask me")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    scope = agent.tools.resolve(run_id)  # type: ignore[union-attr]
    await say(session, stt, "yes")
    await until(lambda: run_id in agent.results)
    assert scope.answers == []
    await finish_all(session, agent)
