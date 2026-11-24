"""Listening from a card (owner items 4 and 15, 2026-11-18): the hotkey on a card reopened from the stack."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from swift import intake
from swift.attention import Attention
from swift.ipc.protocol import Message
from swift.parked import ParkedThreads

from test_card_timing import seen
from test_seam_replay import _screen
from virtual_clock import VIRTUAL, event_loop_policy, one_clock, wall_ms  # noqa: F401 (fixtures)

pytestmark = VIRTUAL
from test_corrections import make, start
from settling import settled
from test_runs import until
from test_wake import AUDIO
from test_wake import make as wake_make


async def test_the_hotkey_on_a_confirm_card_reopened_from_the_stack_records_its_answer() -> None:
    session, out, _records, _calendar, _agent, stt = make(
        attention=Attention(require_seen=True), parked=ParkedThreads(None), confirm_timeout_s=0.2,
    )
    await start(session, out, stt)
    card = out.last("confirm.request")
    await session.handle(seen(card["request_id"]))
    await asyncio.sleep(0.4)  # expired into the stack
    item = out.last("stack")["items"][0]
    await session.handle(Message("stack.action", {"id": item["id"], "action": "open"}))
    await session.handle(seen(card["request_id"]))
    screen = _screen(out)
    assert (screen["stage"], screen["confirm"]) == ("confirm", card["request_id"]), screen
    n = len(out.messages)
    await session.handle(Message("ptt", {"state": "down"}))
    await asyncio.sleep(0.05)
    sent = [(m.type, m.data) for m in out.messages[n:]]
    assert ("confirm.voice", {"request_id": card["request_id"], "phase": "listening", "text": ""}) in sent, sent
    await session.handle(Message("ptt", {"state": "up"}))


# ---- the card's mic button (card_mic.py) -------------------------------------------------------------------


async def _talk(rec: Any) -> None:
    """The owner says something, then stops: the capture ends by itself (no key to release)."""
    await until(lambda: rec.on_level is not None and rec.recording)
    rec.on_level(0.8)
    await asyncio.sleep(0.1)
    rec.on_level(0.0)
    await asyncio.sleep(0.1)
    rec.on_level(0.0)


async def test_the_mic_button_listens_once_in_the_cards_conversation_then_stops_by_itself() -> None:
    session, out, records, rec, stt = wake_make("Hey Swift, what time is it?")
    await session.hear_wake(AUDIO, time.monotonic())
    await settled(session)
    stt.text = "and in Tokyo?"
    await session.handle(Message("listen.card", {}))
    await _talk(rec)
    assert out.last("heard")["source"] == "ptt" and rec.lead == 0.0  # nothing from before the click
    await until(lambda: len(records) == 2)
    assert records[1]["source"] == "followup" and records[1]["card_mic"] is True
    assert records[1]["thread"] == records[0]["thread"]  # the card's conversation
    assert not rec.recording and out.states()[-1] in ("result", "error")


async def test_on_a_card_reopened_from_the_stack_it_follows_that_card_not_the_last_request() -> None:
    # Item 15: the follow-up window closed long ago, and the hotkey starts a new conversation; the button follows the card.
    session, out, records, rec, stt = wake_make("Hey Swift, what time is it?")
    await session.hear_wake(AUDIO, time.monotonic())
    await settled(session)
    first = next(r for r in session._runs if r.thread == records[0]["thread"])
    stt.text = "Hey Swift, what's the date?"
    await session.hear_wake(AUDIO, time.monotonic())
    await until(lambda: len(records) == 2)
    assert records[1]["thread"] != records[0]["thread"]
    await session._bring(first)  # "Open" on it in the stack (recent.open_)
    stt.text = "and in Tokyo?"
    await session.handle(Message("listen.card", {}))
    await _talk(rec)
    await until(lambda: len(records) == 3)
    assert records[2]["thread"] == records[0]["thread"]


async def test_its_words_are_a_hands_free_reply_never_a_gesture() -> None:
    # Product rule (CLAUDE.md, foundation decision 3): only speech with the hotkey held is a gesture.
    assert intake.channel("followup", named=False) == "plain_voice"
    assert not intake.approves("followup", named=False, level=intake.CARD).allowed


async def test_the_mic_button_starts_nothing_while_a_card_waits_for_an_answer() -> None:
    session, out, _records, _calendar, _agent, stt = make()
    await start(session, out, stt)  # a confirm card is open: the hotkey answers it, not this
    n = len(out.messages)
    await session.handle(Message("listen.card", {}))
    await asyncio.sleep(0.05)
    assert not [m for m in out.messages[n:] if m.type in ("heard", "state", "confirm.voice")]


async def test_the_mic_button_starts_nothing_while_listening_is_paused() -> None:
    session, out, records, rec, _stt = wake_make("Hey Swift, what time is it?")
    session.listening_paused = True
    await session.handle(Message("listen.card", {}))
    await asyncio.sleep(0.05)
    assert not rec.recording and records == [] and not [m for m in out.messages if m.type == "heard"]
