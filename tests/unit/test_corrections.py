"""Corrections (owner, 2026-10-26): a change said on Swift's own confirm card revises it within
the same run, and a correction after a rejection keeps the rest of what was shown. Also the
intent triggers that run a clear request directly instead of offering the workflow.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import time
from collections.abc import AsyncIterator
from typing import Any

import numpy as np

from swift.executors.base import WorkerTask
from swift.audio.recorder import SAMPLE_RATE
from swift.connectors.fake import FakeCalendarConnector
from swift.executors.base import ExecEvent, ExecResult
from swift.ipc.protocol import Message
from swift.security.gateway import ActionGateway
from swift.security.journal import Journal
from swift.session import Exchange, Session
from swift.workflows.library import load_library
from swift.workflows.toolset import ALL_TOOLS
from swift.workflows.tools import ToolHost

from test_session import Recorder as Outbox
from test_voice import FakeTranscriber
from test_wake import LeadRecorder

WRONG = {"title": "Meeting with Prof. Smith", "start": "2026-10-29T15:00"}
RIGHT = {"title": "Meeting with Prof. Smith", "start": "2026-10-30T15:00"}


class CalendarAgent:
    """Stands in for Claude Code: proposes WRONG, and RIGHT if the owner asks for a change."""

    name = "agent"

    def __init__(self, tools: ToolHost) -> None:
        self.tools = tools
        self.told: list[str] = []
        self._ids = itertools.count(1)
        self._runs: dict[str, tuple[asyncio.Queue[Any], asyncio.Task[ExecResult]]] = {}

    async def start(self, task: WorkerTask) -> str:
        request = task.prompt
        run_id = f"agent-{next(self._ids)}"
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._runs[run_id] = (queue, asyncio.create_task(self._work(queue)))
        return run_id

    async def _work(self, queue: asyncio.Queue[Any]) -> ExecResult:
        try:
            queue.put_nowait(ExecEvent("step", "Adding the event", activity="editing"))
            result = await self.tools.call("create_calendar_event", WRONG)
            self.told.append(result.text)
            if not result.ok and "wants a change" in result.text:
                result = await self.tools.call("create_calendar_event", RIGHT)
                self.told.append(result.text)
            return ExecResult("done" if result.ok else "done", result.text)
        finally:
            queue.put_nowait(None)

    async def events(self, run_id: str) -> AsyncIterator[ExecEvent]:
        queue = self._runs[run_id][0]
        while (item := await queue.get()) is not None:
            yield item

    async def result(self, run_id: str) -> ExecResult:
        return await self._runs[run_id][1]

    async def cancel(self, run_id: str) -> None:
        self._runs[run_id][1].cancel()

    async def reply(self, request_id: str, approve: bool) -> None:
        pass


def make(**kw: Any) -> tuple[Session, Outbox, list[dict[str, Any]], FakeCalendarConnector, CalendarAgent, FakeTranscriber]:
    calendar = FakeCalendarConnector()
    tools = ToolHost(gateway=ActionGateway(Journal(None)), tools=ALL_TOOLS, calendar=calendar)
    agent = CalendarAgent(tools)
    out, records, stt = Outbox(), [], FakeTranscriber(text="")
    session = Session(
        out, agent, debug_executor=None, tools=tools, recorder=LeadRecorder(), transcriber=stt,
        on_finish=records.append, tail_s=0.0, **kw,
    )
    return session, out, records, calendar, agent, stt


async def start(session: Session, out: Outbox, stt: FakeTranscriber) -> None:
    stt.text = "Hey Swift, set up a meeting with Professor Smith on Thursday at three"
    await session.hear_wake(np.zeros(SAMPLE_RATE // 10, dtype=np.int16), time.monotonic())
    await asyncio.wait_for(out.confirm.wait(), 2)
    out.confirm.clear()


async def finish(session: Session) -> None:
    assert session._task is not None
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(asyncio.shield(session._task), 2)


async def press_and_say(session: Session, stt: FakeTranscriber, text: str) -> None:
    """Push-to-talk on the open card."""
    stt.text = text
    await session.handle(Message("ptt", {"state": "down"}))
    await asyncio.sleep(0)
    await session.handle(Message("ptt", {"state": "up"}))
    assert session._confirm_voice is not None
    await asyncio.wait_for(asyncio.shield(session._confirm_voice), 2)


async def test_a_change_on_the_card_revises_it_in_the_same_run() -> None:
    session, out, records, calendar, agent, stt = make()
    await start(session, out, stt)
    first_card = out.last("confirm.request")
    await press_and_say(session, stt, "No, make it Friday at three instead")
    await asyncio.wait_for(out.confirm.wait(), 2)  # a new card, with the corrected event
    second_card = out.last("confirm.request")
    assert second_card["request_id"] != first_card["request_id"]
    assert "Fri 30 Oct" in second_card["detail"] and "Thu 29 Oct" in first_card["detail"]
    assert calendar.created == []  # nothing added from the first card
    assert "wants a change" in agent.told[0] and "make it Friday at three instead" in agent.told[0]
    assert any("Changing it" in m.data.get("text", "") for m in out.messages if m.type == "step")
    await session.handle(Message("confirm.reply", {"request_id": second_card["request_id"], "decision": "approve"}))
    await finish(session)
    assert [e.start.day for e in calendar.created] == [30]
    assert out.last("result")["status"] == "done"
    decisions = [a["decision"] for a in records[0]["approvals"]]
    assert decisions == ["revise", "approve"]
    assert records[0]["approvals"][0]["change_chars"] > 0


async def test_hands_free_a_change_needs_swifts_name() -> None:
    session, out, records, calendar, agent, stt = make()
    await start(session, out, stt)
    stt.text = "make it Friday at three"  # overheard, or not addressed: ignored
    await session.hear_wake(np.zeros(SAMPLE_RATE // 10, dtype=np.int16), time.monotonic())
    assert agent.told == [] and session.state == "confirm"
    stt.text = "Swift, make it Friday at three"
    await session.hear_wake(np.zeros(SAMPLE_RATE // 10, dtype=np.int16), time.monotonic())
    await asyncio.wait_for(out.confirm.wait(), 2)
    assert "Fri 30 Oct" in out.last("confirm.request")["detail"]
    await session.cancel()
    assert calendar.created == []


async def test_reject_still_rejects() -> None:
    session, out, records, calendar, agent, stt = make()
    await start(session, out, stt)
    await press_and_say(session, stt, "reject")
    await finish(session)
    assert calendar.created == [] and out.last("result")["status"] == "rejected"
    assert records[0]["approvals"][0]["decision"] == "reject"


async def test_after_a_rejection_the_context_carries_what_was_shown() -> None:
    session, out, records, calendar, agent, stt = make()
    await start(session, out, stt)
    await press_and_say(session, stt, "reject")
    await finish(session)
    exchange = session._last_exchange
    assert exchange is not None and "Thu 29 Oct" in exchange.proposed and not exchange.proposed_done
    context = exchange.as_context(time.monotonic())
    assert "did NOT approve" in context and "corrected values win" in context


def test_context_without_a_proposal_is_unchanged() -> None:
    context = Exchange("id", "what's in the folder", "Three files.", (), time.monotonic()).as_context(time.monotonic())
    assert "What Swift last showed" not in context


# ---- intent triggers: clear requests run directly -------------------------------------------


def test_clear_requests_run_and_questions_do_not() -> None:
    library = load_library(None)
    cases = {
        "set up a meeting on my google calendar with a professor": ("calendar-event", "run"),
        "schedule office hours with Dr Smith on Friday at 3": ("calendar-event", "run"),
        "can you book lunch with Ada next Tuesday": ("calendar-event", "run"),
        "add lunch with Ada to my calendar tomorrow at noon": ("calendar-event", "run"),
        "write my lecturer an email about the deadline": ("email-draft", "run"),
        "research the history of tea and write it up in a word document": ("research-into-word", "run"),
        "I have a meeting later": None,
        "what time is it": None,
        # The calendar's whole lifecycle runs there too (looking, moving, cancelling, Meet links).
        "move my meeting with Ada to Friday at 3": ("calendar-event", "run"),
        "cancel my dentist appointment tomorrow": ("calendar-event", "run"),
        "add a google meet link to my meeting with Ada": ("calendar-event", "run"),
        "show me my calendar for this week": ("calendar-event", "run"),
        # Questions about the owner's own calendar run it on purpose: it answers them by looking
        # (list_calendar_events, read-only), so is_question doesn't block them.
        "what's on my calendar tomorrow": ("calendar-event", "run"),
        "when is my next meeting?": ("calendar-event", "run"),
        "Hey Swift, do I have anything on my calendar this week": ("calendar-event", "run"),
        "am I free on Friday afternoon": ("calendar-event", "run"),
        # ... but not questions about meetings in general, nor coding requests.
        "what is a meeting": None,
        "how do I schedule a meeting in Teams?": None,
        "remove the event listener in main.ts": None,
        "update the function call in session.py": None,
    }
    for text, expected in cases.items():
        m = library.match(text)
        assert ((m.package.name, m.kind) if m else None) == expected, text
    # A question that isn't about the owner's calendar never runs a workflow that does something.
    m = library.match("did I add the meeting")
    assert m is None
