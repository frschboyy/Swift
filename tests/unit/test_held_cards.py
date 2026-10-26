"""Held cards (ADR-014 §4): a confirm card waits while the owner is away instead of timing out."""

from __future__ import annotations

import asyncio
import types

import pytest

from swift.attention import Attention, wait_answer
from swift.ipc.protocol import Message
from swift.lifecycle import Lifecycle
from swift.parked import ParkedThreads
from swift.presence import AWAY_S, PresenceMonitor

from test_corrections import finish, make, start
from test_presence import Clock, Probe

# ---- the wait --------------------------------------------------------------------------------


async def test_the_countdown_runs_while_here() -> None:
    attention = Attention()
    with pytest.raises(TimeoutError):
        await attention.wait("c1", asyncio.get_running_loop().create_future(), 0.05)
    assert attention.left("c1") is None  # forgotten once it's over


async def test_away_stops_the_countdown_and_back_gives_time_to_read_again() -> None:
    attention = Attention(return_s=0.1)
    future = asyncio.get_running_loop().create_future()
    waiting = asyncio.create_task(attention.wait("c1", future, 0.05))
    await asyncio.sleep(0)
    assert attention.set_held(True) == ["c1"]
    await asyncio.sleep(0.2)  # well past the 0.05 s countdown
    assert not waiting.done() and attention.left("c1") == pytest.approx(0.05, abs=0.04)
    attention.set_held(False)
    assert attention.left("c1") == pytest.approx(0.1, abs=0.02)  # at least return_s again
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(waiting, 1)


async def test_an_answer_while_held_still_counts() -> None:
    attention = Attention()
    attention.set_held(True)
    future = asyncio.get_running_loop().create_future()
    waiting = asyncio.create_task(attention.wait("c1", future, 0.05))
    await asyncio.sleep(0.1)
    future.set_result(True)
    assert await asyncio.wait_for(waiting, 1) is True


async def test_held_too_long_gives_up() -> None:
    clock = Clock()
    attention = Attention(hold_s=12 * 3600, clock=clock)
    attention.set_held(True)
    waiting = asyncio.create_task(attention.wait("c1", asyncio.get_running_loop().create_future(), 120))
    await asyncio.sleep(0)
    clock.t += 12 * 3600 + 1
    attention.check()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(waiting, 1)


async def test_without_attention_it_is_the_plain_timeout() -> None:
    with pytest.raises(TimeoutError):
        await wait_answer(None, "c1", asyncio.get_running_loop().create_future(), 0.01)


# ---- presence: talking to Swift is being here ----------------------------------------------------


def test_talking_to_swift_counts_as_being_here() -> None:
    probe, clock, changes = Probe(), Clock(), []
    m = PresenceMonitor(probe, changes.append, clock=clock)
    probe.idle = AWAY_S
    m.poll()
    assert m.state == "away"
    m.touch()  # "hey Swift" from across the room
    assert (changes[-1].new, changes[-1].reason, changes[-1].returned) == ("here", "swift", True)
    clock.t += 2
    m.poll()  # the keyboard is still idle, but they just spoke
    assert m.state == "here"


def test_touch_does_not_unlock() -> None:
    probe, clock, changes = Probe(), Clock(), []
    m = PresenceMonitor(probe, changes.append, clock=clock)
    probe.is_locked = True
    m.poll()
    assert m.touch() is None and m.state == "away"


async def test_the_lifecycle_holds_cards_while_away() -> None:
    held: list[bool] = []

    async def hold_cards(h: bool) -> None:
        held.append(h)

    session = types.SimpleNamespace(listening_paused=False, hold_cards=hold_cards)

    async def send(msg: Message) -> None:
        pass

    probe, clock = Probe(), Clock()
    life = Lifecycle(session, send, clock=clock)
    m = PresenceMonitor(probe, lambda c: None, clock=clock)
    life.attach(m)
    probe.is_locked = True
    clock.t += 2
    await life.handle(m.poll())  # type: ignore[arg-type]
    probe.is_locked = False
    clock.t += 2
    await life.handle(m.poll())  # type: ignore[arg-type]
    assert held == [True, False]


# ---- the session: a real card, held and shown again -------------------------------------------------


async def test_a_card_left_while_away_waits_and_comes_back() -> None:
    session, out, records, calendar, agent, stt = make(attention=Attention(), parked=ParkedThreads(None))
    await start(session, out, stt)
    card = out.last("confirm.request")
    await session.hold_cards(True)
    hold = out.last("confirm.hold")
    assert hold == {"request_id": card["request_id"], "held": True, "timeout_s": pytest.approx(120, abs=1)}
    await session.hold_cards(False)
    assert out.last("confirm.hold")["held"] is False and out.last("confirm.hold")["timeout_s"] >= 60
    await session.handle(Message("confirm.reply", {"request_id": card["request_id"], "decision": "approve"}))
    await finish(session)
    assert len(calendar.created) == 1 and out.last("result")["status"] == "done"
    assert records[0]["approvals"][0]["held_away"] == 1 and "parked" not in records[0]


async def test_a_held_card_does_not_time_out_and_unanswered_after_return_is_parked() -> None:
    parked = ParkedThreads(None)
    session, out, records, calendar, agent, stt = make(
        attention=Attention(return_s=0.1), parked=parked, confirm_timeout_s=0.1,
    )
    await start(session, out, stt)
    await session.hold_cards(True)
    await asyncio.sleep(0.3)  # three times the countdown
    assert session.state == "confirm" and records == []
    await session.hold_cards(False)
    await finish(session)
    assert calendar.created == [] and records[0]["approvals"][0]["decision"] == "no_answer"
    assert records[0]["parked"] == "unanswered"
    kept = parked.newest()
    assert kept is not None and kept.thread == records[0]["thread"] and "Professor Smith" in kept.request
    assert "Thu 29 Oct" in kept.proposed


async def test_no_card_no_hold_message() -> None:
    # A hold for a card that isn't open sends nothing.
    session, out, *_rest = make(attention=Attention())
    await session.hold_cards(True)
    assert [m for m in out.messages if m.type == "confirm.hold"] == []
