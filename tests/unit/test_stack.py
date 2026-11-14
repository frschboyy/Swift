"""The waiting stack and typing to Swift (ADR-015 §9, §10; owner checks of 2026-10-27).

The stack lists what waits for the owner: cards in line or set aside ("Later"), held cards, and
unfinished conversations, including a question pushed off the screen by a card. Each can be
opened, skipped or ended. A typed request goes through the same router as speech, as source
``typed``, but never approves a card. A request started beside another shows its words at once.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from test_runs import Agent, finish_all, make, runs, sent_for, started, until

from swift.attention import Attention
from swift.executors.base import ExecResult
from swift.ipc.protocol import Message, ProtocolError, decode, encode
from swift.parked import Parked, ParkedThreads
from swift.session import TYPED_APPROVE_HINT
from swift.stack import StackItem, order, split_id


def stack(out: Any) -> list[dict[str, Any]]:
    return out.last("stack")["items"]


def kinds(out: Any) -> list[tuple[str, str]]:
    return [(i["kind"], i["id"]) for i in stack(out)]


# ---- pure ------------------------------------------------------------------------------------


def test_order_cards_first_then_conversations_newest_first_skipped_last() -> None:
    a = StackItem("card:1", "waiting", "A", "waiting", 100)
    b = StackItem("card:2", "later", "B", "later", 50)
    old = StackItem("parked:x", "parked", "Old", "stopped", 10)
    new = StackItem("parked:y", "parked", "New", "asked", 20)
    held = StackItem("card:3", "held", "H", "held", 300)
    assert [i.id for i in order([old, a, new, b, held], {})] == ["card:3", "card:2", "card:1", "parked:y", "parked:x"]
    assert [i.id for i in order([old, a, new], {"card:1": 2.0, "parked:y": 1.0})] == ["parked:x", "parked:y", "card:1"]


def test_ids() -> None:
    assert split_id("card:swift:1") == ("card", "swift:1")
    assert split_id("parked:abc") == ("parked", "abc")
    assert split_id("nope") is None and split_id("run:1") is None and split_id("card:") is None


def test_inbound_messages_are_validated() -> None:
    msg = decode(encode(Message("stack.action", {"id": "card:swift:1", "action": "skip"})))
    assert msg.data["action"] == "skip"
    with pytest.raises(ProtocolError):
        decode(encode(Message("stack.action", {"id": "card:swift:1", "action": "approve"})))
    assert decode(encode(Message("text", {"text": "what time is it", "thread_id": "t1"}))).data["thread_id"] == "t1"
    with pytest.raises(ProtocolError):
        decode(encode(Message("text", {})))


# ---- cards ----------------------------------------------------------------------------------


async def two_cards() -> tuple[Any, Any, Attention, Agent, str, str]:
    attention = Attention()
    session, out, _records, agent, stt = make(attention=attention, parked=ParkedThreads(None))
    agent.attention = attention
    first = await started(session, out, agent, stt, "Hey Swift, tidy the readme with a card")
    second = await started(session, out, agent, stt, "Hey Swift, rename the notes file with a card")
    agent.runs[first]["ask"].set()
    await until(lambda: sent_for(out, first, "confirm.request"))
    agent.runs[second]["ask"].set()
    await until(lambda: runs(out)["waiting"] == 1)
    return session, out, attention, agent, first, second


async def test_a_card_waiting_behind_another_is_in_the_stack_and_opens_from_it() -> None:
    session, out, attention, agent, first, second = await two_cards()
    assert kinds(out) == [("waiting", f"card:{second}:1")]
    assert stack(out)[0]["title"] == "Edit for " + second
    await session.handle(Message("stack.action", {"id": f"card:{second}:1", "action": "open"}))
    await until(lambda: sent_for(out, second, "confirm.request"))
    assert session._open_confirm() == f"{second}:1" and runs(out)["focus"] == second
    # The one that was on screen now waits, its countdown paused.
    assert kinds(out) == [("waiting", f"card:{first}:1")]
    assert attention._waits[f"{first}:1"].deadline is None
    await finish_all(session, agent)


async def test_later_sets_the_card_on_screen_aside_and_open_brings_it_back() -> None:
    session, out, attention, agent, first, second = await two_cards()
    await session.handle(Message("stack.action", {"id": f"card:{first}:1", "action": "skip"}))
    hold = out.last("confirm.hold")
    assert hold["request_id"] == f"{first}:1" and hold["held"] is True
    # The next card comes forward; the skipped one is "later", off screen and paused.
    await until(lambda: sent_for(out, second, "confirm.request"))
    assert session._open_confirm() == f"{second}:1"
    assert kinds(out) == [("later", f"card:{first}:1")]
    assert attention._waits[f"{first}:1"].deadline is None
    await session.handle(Message("stack.action", {"id": f"card:{first}:1", "action": "open"}))
    assert session._open_confirm() == f"{first}:1"
    assert out.last("confirm.hold") == {"request_id": f"{first}:1", "held": False}
    await asyncio.sleep(0.01)
    assert out.last("countdown") == {"request_id": f"{first}:1", "left_s": 120.0, "running": True}
    await session.handle(Message("confirm.reply", {"request_id": f"{first}:1", "decision": "reject"}))
    await until(lambda: agent.answers.get(f"{first}:1") is False)
    await finish_all(session, agent)


async def test_a_lone_card_skipped_stays_in_the_stack_until_answered() -> None:
    attention = Attention()
    session, out, _records, agent, stt = make(attention=attention, parked=ParkedThreads(None))
    agent.attention = attention
    only = await started(session, out, agent, stt, "Hey Swift, tidy the readme with a card")
    agent.runs[only]["ask"].set()
    await until(lambda: sent_for(out, only, "confirm.request"))
    await session.handle(Message("stack.action", {"id": f"card:{only}:1", "action": "skip"}))
    assert session._open_confirm() is None and kinds(out) == [("later", f"card:{only}:1")]
    await session.handle(Message("stack.action", {"id": f"card:{only}:1", "action": "open"}))
    assert session._open_confirm() == f"{only}:1"
    await session.handle(Message("confirm.reply", {"request_id": f"{only}:1", "decision": "approve"}))
    await finish_all(session, agent)
    assert stack(out) == []


async def test_end_stops_the_request_and_does_not_keep_it() -> None:
    session, out, _attention, agent, first, second = await two_cards()
    await session.handle(Message("stack.action", {"id": f"card:{second}:1", "action": "end"}))
    assert agent.cancelled == [second]
    assert session.parked is not None and session.parked.all() == []  # gone, not "unfinished"
    assert stack(out) == []
    await finish_all(session, agent)


# ---- conversations --------------------------------------------------------------------------


async def test_an_unfinished_conversation_opens_from_the_stack() -> None:
    parked = ParkedThreads(None)
    parked.park(Parked(thread="t-lunch", request="add lunch with Test Me on Friday", reason="stopped", at=time.time(),
                       said="add lunch with Test Me on Friday"))
    session, out, records, agent, _stt = make(parked=parked)
    await session.handle(Message("ready", {"startup_ms": 1}))
    assert [(i["kind"], i["reason"], i["title"]) for i in stack(out)] == [("parked", "stopped", "Add lunch with Test Me on Friday")]
    await session.handle(Message("stack.action", {"id": "parked:t-lunch", "action": "open"}))
    await until(lambda: agent.requests)
    assert "add lunch with Test Me on Friday" in agent.requests[0] and "unfinished task" in agent.requests[0]
    await until(lambda: stack(out) == [])
    await finish_all(session, agent)
    assert records[0]["thread"] == "t-lunch" and records[0]["source"] == "stack"


async def test_ending_a_conversation_drops_it() -> None:
    parked = ParkedThreads(None)
    parked.park(Parked(thread="t1", request="research tea", reason="asked", at=time.time()))
    session, out, _records, _agent, _stt = make(parked=parked)
    await session.handle(Message("ready", {"startup_ms": 1}))
    assert len(stack(out)) == 1
    await session.handle(Message("stack.action", {"id": "parked:t1", "action": "end"}))
    assert parked.all() == [] and stack(out) == []


class Asks(Agent):
    """Requests with "lunch" in them end with a question."""

    async def result(self, run_id: str) -> ExecResult:
        result = await super().result(run_id)
        if "lunch" in self.runs[run_id]["request"].lower():
            return ExecResult("done", "Which day, and what time?")
        return result


async def test_a_question_pushed_off_screen_by_a_card_waits_in_the_stack() -> None:
    attention = Attention()
    session, out, _records, agent, stt = make(Asks, attention=attention, parked=ParkedThreads(None))
    agent.attention = attention
    card = await started(session, out, agent, stt, "Hey Swift, tidy the readme with a card")
    asks = await started(session, out, agent, stt, "Hey Swift, add lunch with Test Me to my calendar")
    agent.runs[asks]["go"].set()
    await until(lambda: out.last("result").get("summary") == "Which day, and what time?")
    assert session._question is not None
    agent.runs[card]["ask"].set()  # a card takes the front from the question
    await until(lambda: sent_for(out, card, "confirm.request"))
    assert session._question is None
    assert [(i["kind"], i["reason"]) for i in stack(out)] == [("parked", "asked")]
    await finish_all(session, agent)


# ---- a chip at once (bug 4) ----------------------------------------------------------------


async def test_a_request_beside_another_shows_its_words_at_once() -> None:
    session, out, _records, agent, stt = make()
    await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    before = len(out.messages)
    session._start_beside("summarise my notes from Monday and the week before")
    await asyncio.sleep(0)  # the chip goes out before the request has done anything
    await asyncio.sleep(0)
    rows = [r for m in out.messages[before:] if m.type == "runs" for r in m.data["rows"]]
    assert any(r["words"] == "summarise my notes from Monday and the week before" for r in rows)
    await finish_all(session, agent)


async def test_the_overlay_asking_for_a_request_it_should_not_know_gets_the_rows_again() -> None:
    session, out, _records, agent, stt = make()
    await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    await session.handle(Message("focus", {"run_id": "local-99"}))
    assert out.messages[-1].type == "runs"
    await finish_all(session, agent)


# ---- typing ---------------------------------------------------------------------------------


async def test_a_typed_request_runs_like_a_spoken_one() -> None:
    session, out, records, agent, _stt = make()
    await session.handle(Message("text", {"text": "  what time is it  "}))
    await until(lambda: out.last("result")["summary"].startswith("It's"))
    await session.handle(Message("text", {"text": "research green tea"}))
    await until(lambda: agent.requests)
    assert agent.requests[-1].endswith("research green tea")
    await finish_all(session, agent)
    assert [r["source"] for r in records] == ["typed", "typed"]
    assert records[0]["route"] == "local" and records[1]["route"] == "agent"


async def test_a_typed_follow_up_continues_the_conversation_on_screen() -> None:
    session, out, records, agent, _stt = make()
    await session.handle(Message("text", {"text": "what time is it"}))
    await until(lambda: records)
    thread = records[0]["thread"]
    await session.handle(Message("text", {"text": "and the date?", "thread_id": thread}))
    await until(lambda: len(records) == 2)
    await session.handle(Message("text", {"text": "what day is it", "thread_id": "someone-else"}))
    await until(lambda: len(records) == 3)
    assert records[1]["thread"] == thread and records[2]["thread"] != thread
    await finish_all(session, agent)


async def test_typing_never_approves_a_card() -> None:
    session, out, records, agent, stt = make()
    run = await started(session, out, agent, stt, "Hey Swift, tidy the readme with a card")
    agent.runs[run]["ask"].set()
    await until(lambda: sent_for(out, run, "confirm.request"))
    for text in ("approve", "yes", "Swift, approve"):
        await session.handle(Message("text", {"text": text}))
        assert out.last("confirm.voice") == {"request_id": f"{run}:1", "phase": "hint", "text": TYPED_APPROVE_HINT}
    assert f"{run}:1" not in agent.answers and session._open_confirm() == f"{run}:1"
    await session.handle(Message("text", {"text": "reject"}))  # rejecting is fine
    await until(lambda: agent.answers.get(f"{run}:1") is False)
    await finish_all(session, agent)
