"""The overlay <-> backend contract (seams audit 2026-11, layer A; O-06): tests/protocol_contract.py."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest
from protocol_contract import TS_EXAMPLES, Dialogue, check_frame, load, render_ts

from swift.executors.mock import MockExecutor
from swift.ipc.protocol import _INBOUND, OUTBOUND_TYPES, Message, decode, encode, outbound
from swift.session import Session

FRAMES = load()


def test_every_backend_message_type_has_an_example_and_each_is_one_outbound_accepts() -> None:
    assert {f["type"] for f in FRAMES["to_overlay"]} == OUTBOUND_TYPES
    for f in FRAMES["to_overlay"]:
        outbound(f["type"], **f["data"])


def test_every_overlay_message_type_has_an_example_and_each_decodes() -> None:
    assert {f["type"] for f in FRAMES["to_backend"]} == set(_INBOUND)
    for f in FRAMES["to_backend"]:
        assert decode(encode(Message(f["type"], f["data"], 1))).type == f["type"]


def test_the_typescript_examples_are_up_to_date() -> None:
    """tsc checks overlay/src/protocol.examples.ts against protocol.ts; it must be these examples."""
    assert TS_EXAMPLES.read_text(encoding="utf-8") == render_ts(), (
        "frames.json changed: run `uv run python tests/protocol_contract.py`, then tsc in overlay/"
    )


def test_the_examples_fit_themselves() -> None:
    for direction in ("to_overlay", "to_backend"):
        for f in FRAMES[direction]:
            assert check_frame(f["type"], f["data"], direction) == [], f


@pytest.mark.parametrize(("msg_type", "data", "problem"), [
    ("level", {"rms": 0.1, "words": "hi"}, "level.words: not in any example"),
    ("level", {}, "level.rms: missing"),
    ("confirm.hold", {"request_id": "r", "held": "yes"}, "confirm.hold.held: a str"),
    ("runs", {"focus": None, "rows": [{"run_id": "a", "colour": "red"}], "waiting": 0}, "runs.rows[].colour"),
    ("nonsense", {}, "no example of this type"),
])
def test_a_frame_that_does_not_fit_is_named(msg_type: str, data: dict[str, Any], problem: str) -> None:
    assert any(problem in p for p in check_frame(msg_type, data)), check_frame(msg_type, data)


def test_the_open_parts_are_not_checked_inside() -> None:
    frame = {"run_id": "a", "id": "x", "kind": "table", "phase": "done", "version": 1, "title": "",
             "data": {"kind": "table", "columns": ["a"], "rows": [["1"]]}}
    assert check_frame("artifact", frame) == []


# ---- the dialogue invariants -------------------------------------------------------------------


def test_the_dialogue_names_two_cards_for_one_request_and_a_question_left_open() -> None:
    d = Dialogue()
    d.sent("confirm.request", {"run_id": "a", "request_id": "a:1"})
    d.sent("confirm.request", {"run_id": "a", "request_id": "a:2"})
    d.sent("ask", {"ask_id": "q", "run_id": "a", "open": True})
    assert d.finished() == ["two cards open for a: a:1 and a:2", "question q (request a) still open on the overlay"]
    ok = Dialogue()
    ok.sent("confirm.request", {"run_id": "a", "request_id": "a:1"})
    ok.received("confirm.reply", {"request_id": "a:1"})
    ok.sent("confirm.request", {"run_id": "a", "request_id": "a:2"})
    ok.sent("state", {"state": "working", "run_id": "a"})
    ok.sent("confirm.request", {"run_id": "a", "request_id": "a:3"})
    ok.sent("ask", {"ask_id": "q", "run_id": "a", "open": True})
    ok.sent("ask", {"ask_id": "q", "run_id": "a", "open": False})
    assert ok.finished() == []


class _Wire:
    """A session's frames both ways, through the dialogue invariants."""

    def __init__(self) -> None:
        self.dialogue = Dialogue()
        self.messages: list[Message] = []

    async def __call__(self, msg: Message) -> None:
        self.messages.append(msg)
        self.dialogue.sent(msg.type, msg.data)

    def last(self, kind: str) -> dict[str, Any]:
        return [m for m in self.messages if m.type == kind][-1].data


async def _reply(session: Session, wire: _Wire, msg_type: str, data: dict[str, Any]) -> None:
    wire.dialogue.received(msg_type, data)
    await session.handle(Message(msg_type, data))


@pytest.mark.parametrize("scenario", ["happy", "confirm", "error", "long", "email"])
async def test_each_debug_scenario_keeps_the_dialogue_invariants(scenario: str) -> None:
    wire = _Wire()
    mock = MockExecutor(speed=0)
    session = Session(wire, mock, debug_executor=mock, demo_speed=0)
    await session.handle(Message("debug.run", {"scenario": scenario}))
    for _ in range(200):
        await asyncio.sleep(0.01)
        pending = [m for m in wire.messages if m.type == "confirm.request"]
        if pending and session.state == "confirm":
            await _reply(session, wire, "confirm.reply", {"request_id": pending[-1].data["request_id"],
                                                          "decision": "approve"})
        if session._task is None or session._task.done():
            break
    if session._task is not None:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(session._task), 3)
    assert wire.dialogue.finished() == []
    assert any(m.type in ("result", "error") for m in wire.messages)


async def test_a_question_asked_and_answered_by_a_click_is_closed() -> None:
    from test_dialogue import asker, asks
    from test_runs import finish_all, started, until

    session, out, records, agent, stt = asker(wake_question_s=5)
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    ask_id = asks(out)[-1]["ask_id"]
    await session.handle(Message("ask.reply", {"ask_id": ask_id, "text": "Paris"}))
    await until(lambda: run_id in agent.results, timeout=3)
    await finish_all(session, agent)
    d = Dialogue()
    for m in out.messages:
        d.sent(m.type, m.data)
    assert d.finished() == []
