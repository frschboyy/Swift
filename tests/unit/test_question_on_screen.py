"""A plain "yes" counts only for a question the owner can see (owner, 2026-11-05; review scenarios F and G).
Fake agent and fake devices: nothing real is switched."""

from __future__ import annotations

import asyncio

from test_dialogue import asker, asks
from test_runs import finish_all, say, started, until
from test_system_lane import lane

from swift.ipc.protocol import Message
from swift.parked import ParkedThreads


def _session():  # type: ignore[no-untyped-def]
    session, out, _records, agent, stt = asker(parked=ParkedThreads(None), wake_question_s=5.0)
    session.system, control, _ = lane()
    return session, out, agent, stt, control


async def _card_up(session, out, agent, stt):  # type: ignore[no-untyped-def]
    rid = await started(session, out, agent, stt, "Hey Swift, research card tea")
    agent.runs[rid]["ask"].set()
    await until(lambda: out.last("confirm.request"))
    return rid


async def test_a_bare_yes_never_answers_a_question_hidden_by_a_card() -> None:
    session, out, agent, stt, control = _session()
    await _card_up(session, out, agent, stt)
    await say(session, stt, "Swift, turn off the wifi")
    await asyncio.sleep(0.15)
    assert not any(a.get("open") for a in asks(out)), "drawn or listening under the card"
    await say(session, stt, "yes")
    await asyncio.sleep(0.2)
    assert control.radio_state.get("wifi") is not False
    await finish_all(session, agent)


async def test_the_hidden_question_comes_on_screen_when_the_card_goes_then_yes_counts() -> None:
    session, out, agent, stt, control = _session()
    await _card_up(session, out, agent, stt)
    await say(session, stt, "Swift, turn off the wifi")
    await asyncio.sleep(0.15)
    await session.handle(Message("confirm.reply", {"request_id": out.last("confirm.request")["request_id"], "decision": "approve"}))
    await until(lambda: asks(out) and asks(out)[-1].get("open") and asks(out)[-1].get("question") == "Turn off Wi-Fi?")
    assert session.dialogue.pending is not None and session._on_screen(session.dialogue.pending)
    await until(lambda: session._listening_for() is not None)
    await say(session, stt, "yes")
    await until(lambda: control.radio_state.get("wifi") is False)
    await finish_all(session, agent)


async def test_a_bare_yes_never_answers_a_question_after_another_request_came_forward() -> None:
    session, out, agent, stt, control = _session()
    rid = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    await say(session, stt, "Hey Swift, turn off the wifi")
    await until(lambda: asks(out) and asks(out)[-1].get("open"))
    q = session.dialogue.pending
    assert q is not None and session._on_screen(q), "drawn beside the run"
    run = next(r for r in session._runs if r is not q.front and r.alive)
    await session._bring(run)
    assert not session._on_screen(q)
    await say(session, stt, "yes")
    await asyncio.sleep(0.2)
    assert control.radio_state.get("wifi") is not False, rid
    await finish_all(session, agent)


async def test_saying_swift_yes_to_a_hidden_question_shows_it_and_does_not_answer_it() -> None:
    session, out, agent, stt, control = _session()
    await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    await say(session, stt, "Hey Swift, turn off the wifi")
    await until(lambda: asks(out) and asks(out)[-1].get("open"))
    q = session.dialogue.pending
    await session._bring(next(r for r in session._runs if r is not q.front and r.alive))
    await finish_all(session, agent)  # that request's answer is on screen now, and nothing is running
    assert session.dialogue.pending is q and not session._on_screen(q)
    before = len(agent.runs)
    await say(session, stt, "Swift, yes")
    await asyncio.sleep(0.3)
    assert control.radio_state.get("wifi") is not False and len(agent.runs) == before
    assert session.dialogue.pending is q and session._on_screen(q), "it came back to be seen"
    await finish_all(session, agent)


async def test_a_yes_to_a_question_on_screen_still_works() -> None:
    session, out, agent, stt, control = _session()
    await say(session, stt, "Hey Swift, turn off the wifi")
    await until(lambda: session._listening_for() is not None)
    await say(session, stt, "yes")
    await until(lambda: control.radio_state.get("wifi") is False)
    await finish_all(session, agent)
