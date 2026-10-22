from __future__ import annotations

import asyncio
from typing import Any

from swift.executors.mock import MockExecutor
from swift.ipc.protocol import Message
from swift.session import Session


class Recorder:
    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.confirm = asyncio.Event()

    async def __call__(self, msg: Message) -> None:
        self.messages.append(msg)
        if msg.type == "confirm.request":
            self.confirm.set()

    def states(self) -> list[str]:
        out: list[str] = []
        for m in self.messages:
            if m.type == "state" and (not out or out[-1] != m.data["state"]):
                out.append(m.data["state"])
        return out

    def last(self, kind: str) -> dict[str, Any]:
        return [m for m in self.messages if m.type == kind][-1].data


def make(speed: float = 0) -> tuple[Session, Recorder, list[dict[str, Any]]]:
    rec = Recorder()
    records: list[dict[str, Any]] = []
    mock = MockExecutor(speed=speed)
    session = Session(rec, mock, debug_executor=mock, demo_speed=speed, on_finish=records.append)
    return session, rec, records


async def run_demo(session: Session, scenario: str) -> None:
    await session.handle(Message("debug.run", {"scenario": scenario}))
    assert session._task is not None
    await asyncio.wait_for(session._task, 2)


async def test_happy_path_walks_the_states() -> None:
    session, rec, records = make()
    await run_demo(session, "happy")
    assert rec.states() == ["listening", "transcribing", "working", "result"]
    assert rec.last("result")["status"] == "done"
    assert any(m.type == "level" for m in rec.messages)
    assert rec.last("transcript")["final"] is True
    assert records[0]["status"] == "done" and records[0]["steps"]


async def test_error_scenario_ends_in_error_state_with_hint() -> None:
    session, rec, records = make()
    await run_demo(session, "error")
    assert rec.states()[-1] == "error"
    err = rec.last("error")
    assert err["message"] and err["hint"]
    assert records[0]["status"] == "error"


async def answer_confirm(session: Session, rec: Recorder, decision: str) -> None:
    await asyncio.wait_for(rec.confirm.wait(), 2)
    request_id = rec.last("confirm.request")["request_id"]
    await session.handle(Message("confirm.reply", {"request_id": request_id, "decision": decision}))


async def test_confirm_approve() -> None:
    session, rec, records = make()
    await session.handle(Message("debug.run", {"scenario": "confirm"}))
    await answer_confirm(session, rec, "approve")
    await asyncio.wait_for(session._task, 2)  # type: ignore[arg-type]
    assert rec.states() == ["listening", "transcribing", "working", "confirm", "working", "result"]
    assert records[0]["approvals"][0]["decision"] == "approve"


async def test_confirm_reject() -> None:
    session, rec, records = make()
    await session.handle(Message("debug.run", {"scenario": "confirm"}))
    await answer_confirm(session, rec, "reject")
    await asyncio.wait_for(session._task, 2)  # type: ignore[arg-type]
    assert rec.states()[-1] == "result"
    assert rec.last("result")["status"] == "rejected"
    assert records[0]["status"] == "rejected"
    assert records[0]["approvals"][0]["decision"] == "reject"


async def test_unknown_confirm_reply_is_ignored() -> None:
    session, rec, _ = make()
    await session.handle(Message("confirm.reply", {"request_id": "forged", "decision": "approve"}))
    assert rec.messages == []


async def test_cancel_while_working_reports_cancelled() -> None:
    session, rec, records = make(speed=0.05)
    await session.handle(Message("debug.run", {"scenario": "long"}))
    for _ in range(200):
        if session.state == "working":
            break
        await asyncio.sleep(0.01)
    await session.handle(Message("cancel", {}))
    assert rec.states()[-1] == "result"
    assert rec.last("result")["status"] == "cancelled"
    assert records[0]["status"] == "cancelled"


async def test_cancel_while_listening_returns_to_idle() -> None:
    session, rec, records = make(speed=0.5)
    await session.handle(Message("debug.run", {"scenario": "happy"}))
    await asyncio.sleep(0.05)
    assert session.state == "listening"
    await session.handle(Message("cancel", {}))
    assert rec.states()[-1] == "idle"
    assert records[0]["status"] == "cancelled"


async def test_busy_session_ignores_second_demo() -> None:
    session, rec, _ = make(speed=0.05)
    await session.handle(Message("debug.run", {"scenario": "long"}))
    first = session._task
    await session.handle(Message("debug.run", {"scenario": "happy"}))
    assert session._task is first
    await session.cancel()


async def test_new_interaction_allowed_from_result() -> None:
    session, rec, records = make()
    await run_demo(session, "happy")
    await run_demo(session, "error")
    assert len(records) == 2


async def test_executor_crash_shows_error_instead_of_hanging() -> None:
    session, rec, records = make()

    async def boom(request: str, scenario: str | None = None) -> str:
        raise RuntimeError("executor exploded")

    session.debug_executor.start = boom  # type: ignore[union-attr,method-assign]
    await run_demo(session, "happy")
    assert rec.states()[-1] == "error"
    assert rec.last("error")["code"] == "internal"
    assert records[0]["status"] == "error"


async def test_debug_ask_runs_the_real_executor_on_typed_text() -> None:
    from swift.executors.echo import EchoExecutor

    rec = Recorder()
    records: list[dict[str, Any]] = []
    session = Session(rec, EchoExecutor(), debug_executor=MockExecutor(speed=0), on_finish=records.append)
    await session.handle(Message("debug.ask", {"text": "  what is in this folder?  "}))
    await asyncio.wait_for(session._task, 2)  # type: ignore[arg-type]
    assert rec.states() == ["working", "result"]
    assert "what is in this folder?" in rec.last("result")["summary"]
    assert records[0]["source"] == "debug.ask" and records[0]["executor"] == "echo"


async def test_debug_ask_is_ignored_outside_debug_mode() -> None:
    from swift.executors.echo import EchoExecutor

    rec = Recorder()
    session = Session(rec, EchoExecutor())
    await session.handle(Message("debug.ask", {"text": "hello"}))
    assert session._task is None and rec.messages == []


async def test_unavailable_executor_shows_its_hint() -> None:
    from swift.executors.claude_code import ClaudeCodeExecutor

    rec = Recorder()
    session = Session(rec, ClaudeCodeExecutor(cwd=None), debug_executor=MockExecutor(speed=0))
    await session.handle(Message("debug.ask", {"text": "hello"}))
    await asyncio.wait_for(session._task, 2)  # type: ignore[arg-type]
    err = rec.last("error")
    assert err["code"] == "executor_unavailable" and "working_dirs" in err["hint"]


async def test_debug_run_ignored_without_debug_executor() -> None:
    rec = Recorder()
    session = Session(rec, MockExecutor(speed=0))
    await session.handle(Message("debug.run", {"scenario": "happy"}))
    assert session._task is None and rec.messages == []
