"""Seams audit 2026-11 (overlay and IPC): failing tests that reproduce findings. Reproduce open findings in docs/audit/2026-11-seams-audit.md; marked xfail(strict) until fixed.

OI-01: an overlay that reloads (or reconnects) while a confirm card is open gets the stack, but
not the card on screen; and the card keeps counting down as "seen" although nothing draws it.
"""

from __future__ import annotations

import pytest

from test_runs import Agent, finish_all, make, sent_for, started, until

from swift.attention import Attention
from swift.ipc.protocol import Message


async def _one_card() -> tuple[object, object, Attention, Agent, str]:
    attention = Attention(require_seen=True)
    session, out, _records, agent, stt = make(attention=attention)
    agent.attention = attention
    first = await started(session, out, agent, stt, "Hey Swift, tidy the readme with a card")
    agent.runs[first]["ask"].set()
    await until(lambda: sent_for(out, first, "confirm.request"))
    request_id = sent_for(out, first, "confirm.request")[-1]["request_id"]
    await session.handle(Message("card.seen", {"request_id": request_id, "visible": True}))
    return session, out, attention, agent, request_id


@pytest.mark.xfail(strict=True, reason="seams audit O-01: open finding; remove this marker with the fix")
async def test_a_reloaded_overlay_gets_the_open_card_again() -> None:
    session, out, _attention, agent, request_id = await _one_card()
    before = len(out.messages)
    await session.handle(Message("ready", {"startup_ms": 1}))  # the webview reloaded
    again = [m for m in out.messages[before:] if m.type == "confirm.request" and m.data["request_id"] == request_id]
    try:
        assert again, "the card on screen is not drawn again for a new overlay"
    finally:
        await finish_all(session, agent)


@pytest.mark.xfail(strict=True, reason="seams audit O-01: open finding; remove this marker with the fix")
async def test_a_reloaded_overlay_stops_the_cards_countdown_until_it_draws_it() -> None:
    session, _out, attention, agent, request_id = await _one_card()
    await session.handle(Message("ready", {"startup_ms": 1}))  # nothing drawn yet in the new overlay
    try:
        assert not attention._runs(request_id), "the countdown runs for a card no overlay shows"
    finally:
        await finish_all(session, agent)
