"""A card counts down only while the owner can answer it (ADR-015 §4.2).

On screen (not waiting in line), drawn by the overlay (``card.seen``), and the owner around.
Owner checks 18 and 19 of 2026-10-27: a held card wasn't redrawn after "back", and cards
waiting behind another ran out unseen.
"""

from __future__ import annotations

import asyncio

import pytest

from swift.attention import Attention
from swift.ipc.protocol import Message, ProtocolError, decode, encode
from swift.parked import ParkedThreads

from test_corrections import finish, make, start

# ---- the wait --------------------------------------------------------------------------------


async def test_unseen_card_does_not_count_down() -> None:
    attention = Attention(require_seen=True)
    future = asyncio.get_running_loop().create_future()
    waiting = asyncio.ensure_future(attention.wait("c1", future, 0.05))
    await asyncio.sleep(0.2)  # four times the countdown, never drawn
    assert not waiting.done() and attention.left("c1") == pytest.approx(0.05)
    attention.set_seen("c1", True)
    with pytest.raises(TimeoutError):
        await waiting


async def test_hidden_again_pauses_and_seen_again_goes_on() -> None:
    attention = Attention(require_seen=True)
    future = asyncio.get_running_loop().create_future()
    attention.set_seen("c1", True)  # the overlay's word can come before the wait starts
    waiting = asyncio.ensure_future(attention.wait("c1", future, 0.2))
    await asyncio.sleep(0.05)
    attention.set_seen("c1", False)
    left = attention.left("c1")
    await asyncio.sleep(0.3)
    assert not waiting.done() and attention.left("c1") == left
    attention.set_seen("c1", True)
    future.set_result(True)
    assert await waiting is True


async def test_back_after_away_waits_for_the_overlay_too() -> None:
    attention = Attention(require_seen=True, return_s=0.05)
    future = asyncio.get_running_loop().create_future()
    attention.set_seen("c1", True)
    waiting = asyncio.ensure_future(attention.wait("c1", future, 0.05))
    attention.set_held(True)
    attention.set_seen("c1", False)  # the session does this when it hides a held card
    attention.set_held(False)
    await asyncio.sleep(0.2)
    assert not waiting.done()  # back, but not drawn yet
    attention.set_seen("c1", True)
    with pytest.raises(TimeoutError):
        await waiting


async def test_without_require_seen_it_is_as_before() -> None:
    attention = Attention()
    with pytest.raises(TimeoutError):
        await attention.wait("c1", asyncio.get_running_loop().create_future(), 0.05)


def test_card_seen_is_a_valid_inbound_message() -> None:
    msg = decode(encode(Message("card.seen", {"request_id": "swift:1", "visible": True})))
    assert msg.type == "card.seen" and msg.data["visible"] is True
    with pytest.raises(ProtocolError):
        decode(encode(Message("card.seen", {"request_id": "swift:1", "visible": "yes"})))


# ---- the session --------------------------------------------------------------------------


async def test_a_card_never_drawn_does_not_run_out() -> None:
    session, out, records, calendar, agent, stt = make(
        attention=Attention(require_seen=True), parked=ParkedThreads(None), confirm_timeout_s=0.05,
    )
    await start(session, out, stt)
    await asyncio.sleep(0.3)
    assert session.state == "confirm" and records == []  # still waiting, not "no answer"
    card = out.last("confirm.request")
    await session.handle(Message("card.seen", {"request_id": card["request_id"], "visible": True}))
    await finish(session)
    assert records[0]["approvals"][0]["decision"] == "no_answer"


async def test_back_redraws_the_held_card_then_gives_its_time() -> None:
    session, out, records, calendar, agent, stt = make(attention=Attention(require_seen=True), parked=ParkedThreads(None))
    await start(session, out, stt)
    card = out.last("confirm.request")
    await session.handle(Message("card.seen", {"request_id": card["request_id"], "visible": True}))
    await session.hold_cards(True)
    before = len(out.messages)
    await session.hold_cards(False)
    back = [m.type for m in out.messages[before:]]
    # The card is drawn again first (whatever the overlay remembered), then "back" with its time.
    assert "confirm.request" in back and back[-1] == "confirm.hold"
    assert back.index("confirm.request") < back.index("confirm.hold")
    assert out.last("confirm.request")["request_id"] == card["request_id"]
    await session.handle(Message("confirm.reply", {"request_id": card["request_id"], "decision": "reject"}))
    await finish(session)
    assert records[0]["approvals"][0]["decision"] == "reject"
