"""Follow-up context: the previous exchange rides along with the next request (ADR-007 §9)."""

from __future__ import annotations

from settling import settled

import asyncio
from typing import Any

from test_routing import SpyExecutor
from test_session import Recorder

from swift.executors.base import ExecResult
from swift.executors.mock import MockExecutor
from swift.ipc.protocol import Message
from swift.routing import route
from swift.session import Session


class Scripted(SpyExecutor):
    """A spy whose answers come from a list (status, summary)."""

    def __init__(self, *answers: tuple[str, str]) -> None:
        super().__init__()
        self.answers = list(answers)

    async def result(self, run_id: str) -> ExecResult:
        status, summary = self.answers.pop(0) if self.answers else ("done", f"answer {run_id}")
        return ExecResult(status, summary)  # type: ignore[arg-type]


def make(executor: Any = None, **kw: Any) -> tuple[Session, Recorder, Any, list[dict[str, Any]]]:
    out, records = Recorder(), []
    executor = executor or Scripted()
    session = Session(out, executor, debug_executor=MockExecutor(speed=0), on_finish=records.append, **kw)
    return session, out, executor, records


async def ask(session: Session, text: str) -> None:
    await session.handle(Message("debug.ask", {"text": text}))
    await settled(session)


async def test_a_follow_up_carries_the_previous_request_and_answer() -> None:
    session, _, spy, records = make(Scripted(("done", "Added a Next steps section to notes.md.")))
    await ask(session, "Add a next steps section to my notes.")
    await ask(session, "Now commit it.")

    first, second = spy.calls[0][0], spy.calls[1][0]
    assert first == "Add a next steps section to my notes."
    assert "Previous request: Add a next steps section to my notes." in second
    assert "Previous answer: Added a Next steps section to notes.md." in second
    assert second.endswith("[Current request]\nNow commit it.")
    assert spy.calls[1][1]["demand"] == "standard"  # the demand comes from the words, not the context
    assert records[1]["transcript"] == "Now commit it."
    assert records[1]["context"] == {"previous": records[0]["id"], "age_s": 0}
    assert "context" not in records[0]


async def test_only_the_last_exchange_is_kept() -> None:
    session, _, spy, _ = make()
    await ask(session, "List the docs folder.")
    await ask(session, "Read the first file.")
    await ask(session, "Summarize it.")
    third = spy.calls[2][0]
    assert "Read the first file." in third and "List the docs folder." not in third
    assert third.count("[Current request]") == 1


async def test_an_old_exchange_is_not_sent(monkeypatch: Any) -> None:
    session, _, spy, _ = make(followup_s=60)
    await ask(session, "List the docs folder.")
    last = session._last_exchange
    assert last is not None
    monkeypatch.setattr(session, "_last_exchange", type(last)(last.id, last.request, last.answer, (), last.at - 61))
    await ask(session, "Read the first file.")
    assert spy.calls[1][0] == "Read the first file."


async def test_zero_turns_it_off() -> None:
    session, _, spy, _ = make(followup_s=0)
    await ask(session, "List the docs folder.")
    await ask(session, "Read the first file.")
    assert spy.calls[1][0] == "Read the first file."


async def test_new_topic_clears_it_and_says_so() -> None:
    session, out, spy, records = make()
    await ask(session, "List the docs folder.")
    await ask(session, "New topic.")
    assert records[1]["action"] == "new_topic" and "starting fresh" in out.last("result")["summary"]
    await ask(session, "Read the first file.")
    assert spy.calls[1][0] == "Read the first file."


async def test_an_error_clears_it() -> None:
    session, _, spy, _ = make(Scripted(("done", "ok"), ("error", "Claude Code stopped without an answer.")))
    await ask(session, "List the docs folder.")
    await ask(session, "Read the first file.")
    await ask(session, "Try again.")
    assert spy.calls[2][0] == "Try again."


async def test_local_answers_in_between_keep_it() -> None:
    session, _, spy, _ = make()
    await ask(session, "List the docs folder.")
    await ask(session, "What time is it?")
    await ask(session, "Read the first file in it.")
    assert "Previous request: List the docs folder." in spy.calls[1][0]


class RecordingMock(MockExecutor):
    def __init__(self) -> None:
        super().__init__(speed=0, default_scenario="confirm")
        self.requests: list[str] = []

    async def start(self, request: str, scenario: str | None = None, **kw: Any) -> str:
        self.requests.append(request)
        return await super().start(request, scenario, **kw)


async def test_approved_actions_are_part_of_the_context() -> None:
    mock = RecordingMock()
    session, out, _, _ = make(mock)
    await session.handle(Message("debug.ask", {"text": "Add a next steps section to my notes."}))
    await asyncio.wait_for(out.confirm.wait(), 2)
    request_id = out.last("confirm.request")["request_id"]
    await session.handle(Message("confirm.reply", {"request_id": request_id, "decision": "approve"}))
    await settled(session)

    out.confirm.clear()
    await session.handle(Message("debug.ask", {"text": "Undo that."}))
    await asyncio.wait_for(out.confirm.wait(), 2)
    assert "Actions the user approved: Edit notes.md" in mock.requests[1]
    await session.cancel()


async def test_a_rejected_run_is_still_context() -> None:
    session, _, spy, _ = make(Scripted(("rejected", "Rejected: Edit notes.md. Claude Code stopped there.")))
    await ask(session, "Add a next steps section to my notes.")
    await ask(session, "Do it in a new file instead.")
    assert "Previous answer: Rejected: Edit notes.md." in spy.calls[1][0]


def test_new_topic_is_a_whole_utterance_command() -> None:
    for text in ("New topic.", "Let's start over", "Hey Swift, fresh start"):
        assert (route(text).route, route(text).action) == ("control", "new_topic")
    assert route("Start over the migration with the new schema.").route == "agent"


def test_context_is_clipped() -> None:
    from swift.session import Exchange

    text = Exchange("x", "r" * 1000, "a " * 2000, tuple(f"Edit f{i}.py" for i in range(9)), 0.0).as_context(12.0)
    assert len(text) < 1600 and "12 s ago" in text
    assert "Edit f8.py" in text and "Edit f3.py" not in text
