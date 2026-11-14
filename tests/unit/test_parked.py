"""Resumable conversations (ADR-014 §5): a stopped or unanswered thread is parked and picked up later."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import numpy as np

from swift.executors.base import WorkerTask
from swift.audio.recorder import SAMPLE_RATE
from swift.parked import OFFER_TIMES, Parked, ParkedThreads, named_task
from swift.routing import route

from test_corrections import CalendarAgent, finish, make, start


class Later:
    """A clock some time after now: parked threads are old enough to offer."""

    def __init__(self, ahead: float = 120.0) -> None:
        self.ahead = ahead

    def __call__(self) -> float:
        return time.time() + self.ahead


def parked(thread: str = "t1", request: str = "Draft an email to Ada about the deadline", at: float | None = None,
           **kw: Any) -> Parked:
    return Parked(thread=thread, request=request, reason="stopped", at=time.time() if at is None else at, **kw)


# ---- the store -----------------------------------------------------------------------------------


def test_named_tasks() -> None:
    assert named_task("finish the email to Ada") == "email to Ada"
    assert named_task("ok, get back to my essay on tea.") == "essay on tea"
    assert named_task("draft an email to Ada") is None


def test_find_by_the_words_of_the_request() -> None:
    store = ParkedThreads(None)
    store.park(parked("t1", "Draft an email to Ada about the deadline"))
    store.park(parked("t2", "Set up a meeting with Professor Smith on Thursday"))
    assert store.find("finish the email to Ada").thread == "t1"  # type: ignore[union-attr]
    assert store.find("continue the meeting with Professor Smith").thread == "t2"  # type: ignore[union-attr]
    assert store.find("finish the report for Bob") is None
    assert store.find("what's the weather") is None


def test_kept_a_day_and_across_restarts(tmp_path: Path) -> None:
    path = tmp_path / "parked.json"
    store = ParkedThreads(path)
    store.park(parked("old", at=time.time() - 25 * 3600))
    store.park(parked("new", proposed="email to Ada <ada@example.com>"))
    again = ParkedThreads(path)
    assert [p.thread for p in again.all()] == ["new"]
    assert again.newest().proposed.startswith("email to Ada")  # type: ignore[union-attr]
    again.drop("new")
    assert ParkedThreads(path).all() == []


def test_offered_a_few_times_then_not() -> None:
    store = ParkedThreads(None, clock=Later())
    store.park(parked("t1"))
    shown = [store.offer() for _ in range(OFFER_TIMES + 1)]
    assert [p.thread if p else None for p in shown] == ["t1"] * OFFER_TIMES + [None]


def test_not_offered_right_after_parking_nor_after_not_now() -> None:
    store = ParkedThreads(None)
    store.park(parked("t1"))
    assert store.offer() is None  # just left: they know
    later = ParkedThreads(None, clock=Later())
    later.park(parked("t1"))
    later.dismiss("t1")
    assert later.offer() is None and later.newest() is not None  # still resumable


def test_an_unreadable_file_is_not_fatal(tmp_path: Path) -> None:
    path = tmp_path / "parked.json"
    path.write_text("{not json", encoding="utf-8")
    assert ParkedThreads(path).all() == []


def test_resume_phrases_route_locally() -> None:
    for text in ("continue", "Hey Swift, where were we?", "go on", "what was I doing", "let's carry on",
                 "pick up where we left off"):
        assert route(text).action == "resume", text
    assert route("not now").action == "not_now"
    assert route("continue the essay in Word").route == "agent"  # names a task: matched against parked ones


# ---- the session --------------------------------------------------------------------------------


class Recording(CalendarAgent):
    def __init__(self, tools: Any) -> None:
        super().__init__(tools)
        self.requests: list[str] = []

    async def start(self, task: WorkerTask, **kw: Any) -> str:
        request = task.prompt
        self.requests.append(request)
        return await super().start(task, **kw)


def make_parking(store: ParkedThreads) -> tuple[Any, ...]:
    session, out, records, calendar, agent, stt = make(parked=store)
    recording = Recording(agent.tools)
    session.executor = recording
    session.providers.executors[0] = recording  # type: ignore[attr-defined]
    return session, out, records, calendar, recording, stt


async def say(session: Any, stt: Any, text: str) -> None:
    stt.text = text
    await session.hear_wake(np.zeros(SAMPLE_RATE // 10, dtype=np.int16), time.monotonic())
    if session._task is not None:
        await finish(session)


async def test_stopped_then_continue_picks_it_up_in_the_same_thread() -> None:
    store = ParkedThreads(None)
    session, out, records, calendar, agent, stt = make_parking(store)
    await start(session, out, stt)
    await session.cancel()  # Esc on the card
    assert records[0]["status"] == "cancelled" and records[0]["parked"] == "stopped"
    kept = store.newest()
    assert kept is not None and "Thu 29 Oct" in kept.proposed and kept.thread == records[0]["thread"]

    stt.text = "Hey Swift, where were we?"
    await session.hear_wake(np.zeros(SAMPLE_RATE // 10, dtype=np.int16), time.monotonic())
    await asyncio.wait_for(out.confirm.wait(), 2)
    resumed = agent.requests[-1]
    assert resumed.startswith("[Context: an unfinished task") and "Professor Smith" in resumed
    assert "Thu 29 Oct" in resumed  # the draft it had shown
    assert out.last("confirm.request")["thread_id"] == kept.thread  # the overlay continues that card
    assert store.newest() is None  # picked up: no longer parked
    await session.cancel()
    assert records[1]["resumed"] == "stopped" and records[1]["thread"] == kept.thread


async def test_finish_the_named_task() -> None:
    store = ParkedThreads(None)
    store.park(parked("t-ada", "Draft an email to Ada about the deadline"))
    store.park(parked("t-tea", "Research the history of tea into Word"))
    session, out, records, calendar, agent, stt = make_parking(store)
    stt.text = "Hey Swift, finish the email to Ada"
    await session.hear_wake(np.zeros(SAMPLE_RATE // 10, dtype=np.int16), time.monotonic())
    await asyncio.wait_for(out.confirm.wait(), 2)
    assert "email to Ada about the deadline" in agent.requests[-1]
    assert records == [] and session._thread == "t-ada"
    await session.cancel()
    assert [p.thread for p in store.all()] == ["t-ada", "t-tea"]  # stopped again: parked again


async def test_nothing_to_continue() -> None:
    session, out, records, calendar, agent, stt = make_parking(ParkedThreads(None))
    await say(session, stt, "Hey Swift, continue")
    assert out.last("result")["summary"] == "There's nothing unfinished to pick up."
    assert agent.requests == []


async def test_the_next_answer_offers_it_and_not_now_stops_that() -> None:
    store = ParkedThreads(None, clock=Later())
    store.park(parked("t-ada"))
    session, out, records, calendar, agent, stt = make_parking(store)
    await say(session, stt, "Hey Swift, what time is it")
    assert out.last("resume.offer") == {"thread_id": "t-ada", "title": "Draft an email to Ada about the deadline"}
    await say(session, stt, "Hey Swift, not now")
    offers = [m for m in out.messages if m.type == "resume.offer"]
    await say(session, stt, "Hey Swift, what time is it")
    assert [m for m in out.messages if m.type == "resume.offer"] == offers  # not offered again
    assert store.newest() is not None  # but "continue" still works


async def test_forget_that_after_the_offer_lets_it_go() -> None:
    store = ParkedThreads(None, clock=Later())
    store.park(parked("t-ada"))
    session, out, records, calendar, agent, stt = make_parking(store)
    await say(session, stt, "Hey Swift, what time is it")
    await say(session, stt, "Hey Swift, forget that")
    assert store.newest() is None
    assert "let go of" in out.last("result")["summary"]


# ---- owner checks 15-16 (2026-10-27): the "Unfinished" line ---------------------------------------


def test_the_title_is_the_owners_words_not_the_workflow_wrapper() -> None:
    from swift.workflows.library import load_library

    match = load_library().match("add a calendar event for lunch with Ada on Friday at noon")
    assert match is not None
    wrapped = match.package.request(match.inputs, "add a calendar event for lunch with Ada on Friday at noon")
    assert wrapped.startswith("[Swift workflow:")
    assert parked(request=wrapped, said="add a calendar event for lunch with Ada").title == (
        "Add a calendar event for lunch with Ada"
    )
    # Parked before the owner's words were kept: taken from the wrapper's quote of them.
    assert parked(request=wrapped).title.startswith("Add a calendar event for lunch with Ada")
    assert "[" not in parked(request=wrapped).title


async def test_a_stopped_workflow_is_parked_under_the_owners_words() -> None:
    from swift.workflows.library import load_library

    store = ParkedThreads(None)
    session, out, records, calendar, agent, stt = make_parking(store)
    session.library = load_library()
    stt.text = "Hey Swift, add a calendar event for lunch with Ada on Friday at noon"
    await session.hear_wake(np.zeros(SAMPLE_RATE // 10, dtype=np.int16), time.monotonic())
    await asyncio.wait_for(out.confirm.wait(), 2)
    assert agent.requests[-1].startswith("[Swift workflow:")
    await session.cancel()
    kept = store.newest()
    assert kept is not None and records[0]["workflow"] == "calendar-event"
    assert kept.said == "add a calendar event for lunch with Ada on Friday at noon"
    assert kept.title == "Add a calendar event for lunch with Ada on Frid…"


async def test_continue_right_after_the_line_resumes_the_thread_it_showed() -> None:
    store = ParkedThreads(None, clock=Later())
    store.park(parked("t-shown", "Draft an email to Ada about the deadline", at=time.time() - 600))
    session, out, records, calendar, agent, stt = make_parking(store)
    await say(session, stt, "Hey Swift, what time is it")
    assert out.last("resume.offer")["thread_id"] == "t-shown"
    # Another thread parked after the line was shown, newer than the one it shows.
    store.park(parked("t-newer", "Set up a meeting with Professor Smith on Thursday"))
    stt.text = "Hey Swift, continue"
    await session.hear_wake(np.zeros(SAMPLE_RATE // 10, dtype=np.int16), time.monotonic())
    await asyncio.wait_for(out.confirm.wait(), 2)
    assert "email to Ada about the deadline" in agent.requests[-1]
    assert session._thread == "t-shown" and [p.thread for p in store.all()] == ["t-newer"]
    await session.cancel()


# ---- an answer that asks something (owner checks, 2026-10-27) -----------------------------------


def asking(question_s: float = 0.1, followup_s: float = 8.0) -> tuple[Any, ...]:
    from swift.executors.echo import EchoExecutor
    from swift.session import Session

    from test_session import Recorder as Outbox
    from test_voice import FakeTranscriber
    from test_wake import LeadRecorder

    out, records, stt, store = Outbox(), [], FakeTranscriber(text=""), ParkedThreads(None)
    session = Session(
        out, EchoExecutor(), recorder=LeadRecorder(), transcriber=stt, on_finish=records.append, tail_s=0.0,
        wake_followup_s=followup_s, wake_question_s=question_s, parked=store,
    )
    return session, out, records, stt, store


QUESTION = "Hey Swift, add lunch with Ada, which Tuesday and what time?"  # echoed back: ends with "?"


async def test_a_question_gets_a_longer_window_and_is_parked_if_unanswered() -> None:
    session, out, records, stt, store = asking(question_s=0.2)
    await say(session, stt, QUESTION)
    assert out.last("followup") == {"open": True, "seconds": 8.0, "question": True}  # 8 s here: question_s is shorter
    assert store.newest() is None  # not yet: Swift is listening for the answer
    await asyncio.sleep(0.3)
    kept = store.newest()
    assert kept is not None and kept.reason == "asked" and kept.thread == records[0]["thread"]
    assert kept.said == "add lunch with Ada, which Tuesday and what time?"
    assert "the answer hadn't come yet" in kept.as_context(time.time())

    session2, out2, _, stt2, _ = asking(question_s=25.0)
    await say(session2, stt2, QUESTION)
    assert out2.last("followup") == {"open": True, "seconds": 25.0, "question": True}
    session2._drop_question()


async def test_an_answer_in_the_window_parks_nothing() -> None:
    session, out, records, stt, store = asking(question_s=0.2)
    await say(session, stt, QUESTION)
    await say(session, stt, "next Tuesday at two")  # no wake phrase: a follow-up
    await asyncio.sleep(0.3)
    assert records[1]["source"] == "followup" and records[1]["thread"] == records[0]["thread"]
    assert store.newest() is None


async def test_answering_later_goes_on_in_the_parked_thread() -> None:
    session, out, records, stt, store = asking(question_s=0.05)
    await say(session, stt, QUESTION)
    await asyncio.sleep(0.15)
    assert store.newest() is not None
    await say(session, stt, "Hey Swift, next Tuesday at two")
    assert records[1]["thread"] == records[0]["thread"] and records[1]["answered_later"]
    assert records[1]["context"]["previous"] == records[0]["id"]
    assert store.newest() is None


async def test_continue_picks_up_an_unanswered_question() -> None:
    session, out, records, stt, store = asking(question_s=0.05)
    await say(session, stt, QUESTION)
    await asyncio.sleep(0.15)
    await say(session, stt, "Hey Swift, what time is it")  # something else first
    await say(session, stt, "Hey Swift, continue")
    assert records[2]["resumed"] == "asked" and records[2]["thread"] == records[0]["thread"]


async def test_a_plain_answer_keeps_the_short_window() -> None:
    session, out, records, stt, store = asking()
    await say(session, stt, "Hey Swift, add lunch with Ada on Tuesday at two")
    assert out.last("followup") == {"open": True, "seconds": 8.0, "question": False}
    await asyncio.sleep(0.2)
    assert store.newest() is None


async def test_quitting_while_a_question_waits_keeps_it() -> None:
    session, out, records, stt, store = asking(question_s=25.0)
    await say(session, stt, QUESTION)
    await session.close()
    kept = store.newest()
    assert kept is not None and kept.reason == "asked"


def test_a_workflow_request_picked_up_from_the_stack_gets_todays_date() -> None:
    # 2026-11-09: a calendar request parked at 22:59 kept "[Now] Monday ... 22:59"; resumed after midnight,
    # "tomorrow" would have been the wrong day. Its title was always the owner's words.
    from datetime import datetime

    from swift.parked import Parked
    from swift.workflows.library import refresh_now

    parked_at = "[Swift workflow: Calendar events]\nPlaybook...\n\n[Now]\nMonday 09 November 2026, 22:59 (UTC+03:00)\n\n" \
        "[The request, as the owner said it]\nAdd lunch with Sam tomorrow at one."
    later = refresh_now(parked_at, datetime(2026, 11, 10, 0, 30))  # local time
    assert "Tuesday 10 November 2026, 00:30" in later and "22:59" not in later
    assert later.endswith("Add lunch with Sam tomorrow at one.")
    assert Parked("t", parked_at, "asked", 0.0).title == "Add lunch with Sam tomorrow at one."
    assert refresh_now("research tea") == "research tea"  # not a workflow: unchanged
