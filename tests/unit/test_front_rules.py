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


class Fails(Agent):
    async def _work(self, run_id: str, run: dict[str, Any]) -> ExecResult:
        queue = run["queue"]
        try:
            queue.put_nowait(ExecEvent("step", "Reading", activity="reading"))
            await run["go"].wait()
            return ExecResult("error", "provider blew up")
        finally:
            queue.put_nowait(None)


async def test_an_error_from_behind_the_card_is_that_request_s_and_stays() -> None:
    session, out, _records, agent, stt = make(Fails)
    first = await started(session, out, agent, stt, TEA)
    second = await started(session, out, agent, stt, NOTES)
    await asyncio.sleep(0.02)
    agent.runs[second]["go"].set()
    await until(lambda: out.last("error"))
    await asyncio.sleep(0.05)
    screen = agree(session, out)
    assert screen["stage"] == "error" and screen["cardRun"] == second and screen["behind"] == [first]
    # The next news from the one behind doesn't wipe it.
    agent.runs[first]["queue"].put_nowait(ExecEvent("step", "Searching", activity="searching"))
    await until(lambda: any(r["activity"] == "searching" for r in runs(out)["rows"]))
    screen = agree(session, out)
    assert screen["stage"] == "error" and screen["cardRun"] == second
    await finish_all(session, agent)


async def test_an_answer_displaced_from_behind_stays_as_a_row_and_opens_again() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, TEA)
    second = await started(session, out, agent, stt, NOTES)
    agent.runs[first]["go"].set()
    await until(lambda: out.last("result").get("run_id") == first)
    agent.runs[second]["go"].set()
    await until(lambda: out.last("result").get("run_id") == second)
    assert runs(out)["focus"] == second
    assert [(r["run_id"], r["state"]) for r in runs(out)["rows"]] == [(first, "result")]
    assert session._next_focus is None
    agree(session, out)
    # Its answer is still there to read.
    await session.handle(Message("focus", {"run_id": first}))
    assert runs(out)["focus"] == first and out.last("result")["run_id"] == first
    await finish_all(session, agent)


async def test_a_follow_up_joins_the_conversation_on_the_card_not_the_one_behind() -> None:
    session, out, _records, agent, stt = make(wake_followup_s=5.0)
    first = await started(session, out, agent, stt, TEA)
    await started(session, out, agent, stt, NOTES)
    thread = session._runs[0].thread
    agent.runs[first]["go"].set()
    await until(lambda: out.last("result").get("run_id") == first)
    await until(lambda: out.last("followup")["open"] is True)
    await say(session, stt, "and who discovered it")
    await until(lambda: len(session._runs) >= 3)
    await asyncio.sleep(0.1)
    assert session._runs[-1].thread == thread
    await finish_all(session, agent)


async def test_a_typed_follow_up_joins_the_conversation_on_the_card_not_the_one_behind() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, TEA)
    await started(session, out, agent, stt, NOTES)
    thread = session._runs[0].thread
    agent.runs[first]["go"].set()
    await until(lambda: out.last("result").get("run_id") == first)
    await asyncio.sleep(0.05)
    await session.handle(Message("text", {"text": "and who discovered it", "thread_id": thread}))
    await asyncio.sleep(0.1)
    assert session._runs[-1].thread == thread
    await finish_all(session, agent)


async def test_push_to_talk_on_the_card_survives_another_request_s_answer() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, TEA)
    second = await started(session, out, agent, stt, NOTES)
    await session.handle(Message("ptt", {"state": "down"}))
    await asyncio.sleep(0.05)
    voice = session._confirm_voice
    assert voice is not None
    agent.runs[second]["go"].set()
    await asyncio.sleep(0.2)
    assert not voice.cancelled(), "the owner's words were thrown away"
    stt.text = "stop the research one"
    await session.handle(Message("ptt", {"state": "up"}))
    await until(lambda: agent.cancelled == [first])
    await finish_all(session, agent)


async def _answer_in_front(session: Any, out: Any, agent: Any, stt: Any) -> tuple[str, str]:
    first = await started(session, out, agent, stt, TEA)
    second = await started(session, out, agent, stt, NOTES)
    agent.runs[first]["go"].set()
    await until(lambda: out.last("result").get("run_id") == first)
    await asyncio.sleep(0.05)
    assert not session._front_busy()
    return first, second


async def test_stop_reaches_the_one_behind_an_answer() -> None:
    session, out, _records, agent, stt = make()
    _first, second = await _answer_in_front(session, out, agent, stt)
    await say(session, stt, "stop")
    await until(lambda: agent.cancelled == [second])
    assert "Stopped" in out.last("run.voice")["text"]
    await finish_all(session, agent)


async def test_naming_one_and_stop_everything_reach_those_behind_an_answer() -> None:
    session, out, _records, agent, stt = make()
    _first, second = await _answer_in_front(session, out, agent, stt)
    await say(session, stt, "stop the notes one")
    await until(lambda: agent.cancelled == [second])
    await finish_all(session, agent)
    session, out, _records, agent, stt = make()
    _first, second = await _answer_in_front(session, out, agent, stt)
    await say(session, stt, "stop everything")
    await until(lambda: agent.cancelled == [second])
    await finish_all(session, agent)


async def test_with_two_behind_an_answer_stop_asks_which() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, TEA)
    await started(session, out, agent, stt, NOTES)
    await started(session, out, agent, stt, "Hey Swift, compare three e-readers")
    agent.runs[first]["go"].set()
    await until(lambda: out.last("result").get("run_id") == first)
    await asyncio.sleep(0.05)
    await say(session, stt, "stop")
    await until(lambda: "Which one?" in out.last("run.voice")["text"])
    assert agent.cancelled == []
    await finish_all(session, agent)


async def test_a_reply_to_the_answer_is_still_a_reply_with_requests_behind_it() -> None:
    session, out, _records, agent, stt = make(wake_followup_s=5.0)
    await _answer_in_front(session, out, agent, stt)
    await until(lambda: out.last("followup")["open"] is True)
    await say(session, stt, "and who discovered it")
    await until(lambda: len(session._runs) >= 3)
    assert agent.cancelled == []
    await finish_all(session, agent)


async def test_a_new_request_on_the_card_isn_t_displaced_by_an_older_one_behind() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, TEA)
    second = await started(session, out, agent, stt, NOTES)
    agent.runs[first]["go"].set()
    await until(lambda: out.last("result").get("run_id") == first)
    await asyncio.sleep(0.05)
    third = await started(session, out, agent, stt, "Hey Swift, compare three e-readers")
    await asyncio.sleep(0.05)
    assert runs(out)["focus"] == third
    agent.runs[second]["go"].set()
    await asyncio.sleep(0.1)
    assert runs(out)["focus"] == third, "an older answer took the card from the request just said"
    # And a plain "stop" is the one on the card: it was just said, and nothing newer is behind it.
    await say(session, stt, "stop")
    await until(lambda: agent.cancelled == [third])
    await finish_all(session, agent)


async def test_a_request_stopped_by_name_says_stopped_not_ready_to_read() -> None:
    session, out, _records, agent, stt = make()
    await started(session, out, agent, stt, TEA)
    second = await started(session, out, agent, stt, NOTES)
    await say(session, stt, "stop the notes one")
    await until(lambda: agent.cancelled == [second])
    await until(lambda: runs(out)["rows"] and runs(out)["rows"][0]["state"] == "done")
    assert runs(out)["rows"][0]["summary"] == ""
    await finish_all(session, agent)


async def test_naming_a_tie_means_the_card_on_screen() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, TEA)
    await started(session, out, agent, stt, "Hey Swift, research the history of coffee")
    await say(session, stt, "stop the research one")
    await until(lambda: agent.cancelled == [first])
    await finish_all(session, agent)


async def test_said_over_a_confirm_card_it_stays_behind_until_the_card_is_answered() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, "Hey Swift, research card tea")
    agent.runs[first]["ask"].set()
    await until(lambda: out.last("confirm.request"))
    second = await started(session, out, agent, stt, "Swift, what's the history of coffee?")
    await asyncio.sleep(0.05)
    # A card on screen settles what a "stop" means, and nothing takes the front from it.
    assert not session._which_is_unclear()
    agent.runs[second]["go"].set()
    await until(lambda: sent_for(out, second, "result") == [] and runs(out)["rows"][0]["state"] == "result")
    assert runs(out)["focus"] == first and session._open_confirm() is not None
    await finish_all(session, agent)


async def test_said_over_a_confirm_card_its_answer_comes_forward_once_the_card_is_gone() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, "Hey Swift, research card tea")
    agent.runs[first]["ask"].set()
    await until(lambda: out.last("confirm.request"))
    second = await started(session, out, agent, stt, "Swift, what's the history of coffee?")
    await session.handle(Message("confirm.reply", {"request_id": out.last("confirm.request")["request_id"], "decision": "reject"}))
    await asyncio.sleep(0.1)
    agent.runs[second]["go"].set()
    await until(lambda: out.last("result").get("run_id") == second)
    assert runs(out)["focus"] == second
    await finish_all(session, agent)


async def test_what_settles_which_a_stop_means_and_what_clears_it() -> None:
    session, out, agent, stt, _control, _sched = _lane(30.0)
    research = await started(session, out, agent, stt, TEA)
    await started(session, out, agent, stt, NOTES)
    assert session._which_is_unclear()
    await say(session, stt, "Swift, turn off the wifi")
    await until(lambda: any(a.get("open") and a.get("question") == "Turn off Wi-Fi?" for a in asks(out)))
    await asyncio.sleep(0.05)
    assert not session._which_is_unclear(), "a question on screen says what's going on"
    await finish_all(session, agent)
    session, out, _records, agent, stt = make()
    research = await started(session, out, agent, stt, TEA)
    second = await started(session, out, agent, stt, "Hey Swift, research card tea")
    assert session._which_is_unclear()
    agent.runs[second]["ask"].set()
    await until(lambda: out.last("confirm.request"))
    assert session._next_focus is None and runs(out)["focus"] == second and not session._which_is_unclear()
    assert research != second
    await finish_all(session, agent)
