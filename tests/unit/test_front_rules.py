"""What takes the front, and what "stop" reaches, with requests behind the card (ADR-018 §4.1). These
are the independent review's reproductions of 2026-11-07, kept. Nothing real is switched."""

from __future__ import annotations

import asyncio
from typing import Any

from test_dialogue import asker, asks
from test_runs import Agent, finish_all, make, runs, say, sent_for, started, until
from test_seam_replay import _beside, _lane, agree

from swift.executors.base import ExecEvent, ExecResult
from swift.ipc.protocol import Message

TEA = "Hey Swift, research the history of tea"
NOTES = "Hey Swift, summarise my notes from Monday"


async def test_a_hidden_question_can_t_be_answered_by_saying_more_with_the_name() -> None:
    session, out, agent, stt, control, _sched = _lane(30.0)
    research = await _beside(session, out, agent, stt)
    await session.handle(Message("focus", {"run_id": research}))
    await asyncio.sleep(0.05)
    assert not session._on_screen(session.dialogue.pending)
    for said in ("yes", "Swift, yes", "Swift, yes turn it off", "Swift, yes please turn it off now"):
        await say(session, stt, said)
        await asyncio.sleep(0.1)
        assert control.radio_state["wifi"] is True, f"{said!r} answered a question not on screen"
    await finish_all(session, agent)


async def test_a_hidden_choice_can_t_be_answered_by_voice_or_typing() -> None:
    session, out, _records, agent, stt = asker()
    first = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    second = await started(session, out, agent, stt, NOTES)
    await session.handle(Message("focus", {"run_id": second}))
    await asyncio.sleep(0.05)
    q = session.dialogue.pending
    assert q is not None and not session._on_screen(q)
    await say(session, stt, "Swift, the second one")
    await asyncio.sleep(0.1)
    assert session.dialogue.pending is q, "said to a card that wasn't asking"
    await session.handle(Message("text", {"text": "the second one", "thread_id": None}))
    await asyncio.sleep(0.1)
    assert session.dialogue.pending is q, "typed to a card that wasn't asking"
    # On screen again, it answers as ever.
    await session.handle(Message("focus", {"run_id": first}))
    await asyncio.sleep(0.05)
    assert session._on_screen(q)
    await say(session, stt, "Swift, the second one")
    await until(lambda: session.dialogue.pending is not q)
    await finish_all(session, agent)
