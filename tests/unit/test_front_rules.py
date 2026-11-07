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
    await until(lambda: len(agent.requests) == 3)
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
    await until(lambda: len(agent.requests) == 3)
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


class SlowToStart(Agent):
    def __init__(self, tools: Any = None) -> None:
        super().__init__(tools)
        self.gate = asyncio.Event()

    async def start(self, request: str, **kw: Any) -> Any:
        self.requests.append(request)
        await self.gate.wait()
        return await super().start(request, **kw)


async def test_a_request_being_spoken_is_in_front_and_esc_abandons_it() -> None:
    session, out, _records, agent, stt = make(SlowToStart)
    await say(session, stt, TEA)
    await until(lambda: len(agent.requests) == 1)
    first = session._runs[0]
    await session.handle(Message("ptt", {"state": "down"}))  # the last one is still starting: this is the next
    await asyncio.sleep(0.1)
    speaking = session._runs[-1]
    assert speaking is not first and session._focus is speaking
    assert any(m.type == "state" and m.data["state"] == "listening" for m in out.messages)
    await session.handle(Message("cancel", {}))
    await asyncio.sleep(0.1)
    assert not speaking.alive and first.alive, "Esc went to the other request"
    agent.gate.set()
    await until(lambda: agent.runs)
    await finish_all(session, agent)


async def _hidden_while_recording(said: str) -> tuple[Any, Any, Any, Any, Any]:
    """Wake listening off: Swift records the answer itself. The question leaves the screen meanwhile."""
    session, out, agent, stt, control, _sched = _lane(30.0)
    session.wake_on = False
    session.test_release = release = asyncio.Event()
    real = session._capture_voice

    async def recording(capture: dict[str, Any], phase: Any = None, auto: Any = None) -> Any:
        if str(capture.get("id", "")).startswith("answer-"):
            await release.wait()
            return said
        return await real(capture, phase, auto=auto) if phase else await real(capture)

    session._capture_voice = recording
    research = await started(session, out, agent, stt, TEA)
    await asyncio.sleep(0.05)
    await say(session, stt, "Swift, turn off the wifi")
    await until(lambda: any(a.get("open") and a.get("question") == "Turn off Wi-Fi?" for a in asks(out)))
    await until(lambda: session._answer_task is not None)
    await session.handle(Message("focus", {"run_id": research}))
    await asyncio.sleep(0.05)
    assert not session._on_screen(session.dialogue.pending)
    return session, out, agent, control, research


async def test_a_recording_stops_when_its_question_leaves_the_screen_and_resumes_when_it_s_back() -> None:
    session, out, agent, control, _research = await _hidden_while_recording("Swift, yes")
    assert session._answer_task is None, "the microphone stayed open for a question nobody can see"
    session.test_release.set()
    await asyncio.sleep(0.1)
    assert control.radio_state["wifi"] is True, "the owner's 2026-11-05 incident: nothing asking on screen"
    q = session.dialogue.pending
    await session._bring(q.owner)
    await until(lambda: control.radio_state["wifi"] is False)  # back on screen: recorded, and answered
    await finish_all(session, agent)


async def test_no_recording_starts_for_a_hidden_question_until_it_s_back() -> None:
    session, _out, agent, _control, _research = await _hidden_while_recording("no")
    q = session.dialogue.pending
    session._answer_hidden = None
    await session._listen_for(q)
    assert session._answer_task is None and session._answer_hidden is q
    await session._bring(q.owner)
    await asyncio.sleep(0.05)
    assert session._answer_hidden is None
    await finish_all(session, agent)


async def test_a_click_on_a_hidden_question_s_own_button_still_answers_it() -> None:
    session, out, agent, stt, control, _sched = _lane(30.0)
    research = await _beside(session, out, agent, stt)
    await session.handle(Message("focus", {"run_id": research}))
    await asyncio.sleep(0.05)
    assert await session._take_answer("Yes", source="click") is True
    await until(lambda: control.radio_state["wifi"] is False)
    await finish_all(session, agent)


async def test_every_said_or_typed_answer_passes_the_gate_and_only_a_click_doesn_t() -> None:
    session, out, agent, stt, control, _sched = _lane(30.0)
    research = await _beside(session, out, agent, stt)
    await session.handle(Message("focus", {"run_id": research}))
    await asyncio.sleep(0.05)
    q = session.dialogue.pending
    for source in ("answer", "voice", "typed", "wake", "debug.ask"):
        assert await session._take_answer("Swift, yes", source=source, named=True) is False
    assert session.dialogue.pending is q and control.radio_state["wifi"] is True
    await finish_all(session, agent)


async def test_a_typed_answer_can_t_reach_a_hidden_question_with_an_answer_on_the_card() -> None:
    session, out, _records, agent, stt = asker()
    await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    q = session.dialogue.pending
    second = await started(session, out, agent, stt, NOTES)
    agent.runs[second]["go"].set()
    await until(lambda: out.last("result").get("run_id") == second)
    await asyncio.sleep(0.05)
    assert not session._on_screen(q)
    await session.handle(Message("text", {"text": "the second one", "thread_id": None}))
    await asyncio.sleep(0.1)
    assert session.dialogue.pending is q
    await finish_all(session, agent)


async def test_a_stop_with_the_question_hidden_still_asks_which() -> None:
    session, out, _records, agent, stt = asker()
    first = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    second = await started(session, out, agent, stt, NOTES)
    await session.handle(Message("focus", {"run_id": second}))
    await started(session, out, agent, stt, "Hey Swift, compare three e-readers")
    await asyncio.sleep(0.05)
    assert not session._on_screen(session.dialogue.pending)
    await say(session, stt, "stop")
    await until(lambda: "Which one?" in out.last("run.voice")["text"])
    assert agent.cancelled == [] and first != second
    await finish_all(session, agent)


async def test_a_question_on_screen_settles_a_stop_with_one_unseen_behind() -> None:
    session, out, agent, stt, _control, _sched = _lane(30.0)
    await started(session, out, agent, stt, TEA)
    behind = await started(session, out, agent, stt, NOTES)
    await session.handle(Message("focus", {"run_id": behind}))
    await session.handle(Message("focus", {"run_id": "a-1"}))
    third = await started(session, out, agent, stt, "Hey Swift, compare three e-readers")
    session._next_focus = next(r for r in session._runs if r.ui_id == third)
    await say(session, stt, "Swift, turn off the wifi")
    await until(lambda: any(a.get("open") and a.get("question") == "Turn off Wi-Fi?" for a in asks(out)))
    await asyncio.sleep(0.05)
    session._next_focus = next(r for r in session._runs if r.ui_id == third)
    assert session._on_screen(session.dialogue.pending) and not session._which_is_unclear()
    await finish_all(session, agent)


async def _answer_asks_with_one_behind(session: Any, out: Any, agent: Any, stt: Any) -> str:
    first, second = await _answer_in_front(session, out, agent, stt)
    assert first != second
    return second


async def test_words_for_the_answer_on_the_card_don_t_stop_the_one_behind() -> None:
    for said in ("never mind", "forget it", "enough", "quiet", "cancel"):
        session, out, _records, agent, stt = make()
        await _answer_asks_with_one_behind(session, out, agent, stt)
        await say(session, stt, said)
        await asyncio.sleep(0.1)
        assert agent.cancelled == [], f"{said!r} stopped a request nobody named"
        await finish_all(session, agent)


async def test_a_brisk_stop_gets_through_with_an_answer_on_the_card() -> None:
    session, out, _records, agent, stt = make()
    second = await _answer_asks_with_one_behind(session, out, agent, stt)
    assert session.wants_short(), "the listener would drop a brisk stop as too short"
    await say(session, stt, "stop it.")
    await until(lambda: agent.cancelled == [second])
    await finish_all(session, agent)


async def test_with_nothing_behind_short_clips_stay_dropped_as_before() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, TEA)
    agent.runs[first]["go"].set()
    await until(lambda: out.last("result").get("run_id") == first)
    await asyncio.sleep(0.05)
    assert not session._live() and not session.wants_short()
    await finish_all(session, agent)


async def _hotkey_held_then_the_other_answers() -> tuple[Any, Any, Any, Any, str, Any]:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, TEA)
    second = await started(session, out, agent, stt, NOTES)
    await session.handle(Message("ptt", {"state": "down"}))
    await asyncio.sleep(0.05)
    voice = session._confirm_voice
    agent.runs[second]["go"].set()
    await until(lambda: out.last("result").get("run_id") == second)
    await asyncio.sleep(0.05)
    return session, out, agent, stt, first, voice


async def test_the_hotkey_s_repeat_doesn_t_start_a_second_recording() -> None:
    session, _out, agent, stt, _first, voice = await _hotkey_held_then_the_other_answers()
    before = len(session._runs)
    released = session._released
    await session.handle(Message("ptt", {"state": "down"}))  # it repeats about a second in
    await asyncio.sleep(0.05)
    assert len(session._runs) == before and session._released is released and not voice.done()
    stt.text = "stop the research one"
    await session.handle(Message("ptt", {"state": "up"}))
    await until(lambda: voice.done())
    await finish_all(session, agent)


async def test_the_owner_s_words_survive_their_card_ending_behind_another() -> None:
    session, _out, agent, stt, first, voice = await _hotkey_held_then_the_other_answers()
    agent.runs[first]["go"].set()
    await asyncio.sleep(0.15)
    assert not voice.cancelled(), "their words were thrown away"
    stt.text = "what time is it"
    await session.handle(Message("ptt", {"state": "up"}))
    await until(lambda: voice.done())
    await finish_all(session, agent)


async def test_a_stop_heard_with_the_hotkey_held_waits_for_the_hotkey() -> None:
    session, _out, agent, stt, _first, _voice = await _hotkey_held_then_the_other_answers()
    await say(session, stt, "stop")
    await asyncio.sleep(0.1)
    assert agent.cancelled == []
    stt.text = "what time is it"
    await session.handle(Message("ptt", {"state": "up"}))
    await asyncio.sleep(0.1)
    await finish_all(session, agent)


async def test_naming_a_tie_means_what_s_running_not_a_finished_card() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, TEA)
    second = await started(session, out, agent, stt, "Hey Swift, research the history of coffee")
    agent.runs[first]["go"].set()
    await until(lambda: out.last("result").get("run_id") == first)
    await asyncio.sleep(0.05)
    await say(session, stt, "stop the research one")
    await until(lambda: agent.cancelled == [second])
    await finish_all(session, agent)


async def test_a_displaced_answer_s_row_ages_out(monkeypatch: Any) -> None:
    monkeypatch.setattr("swift.session.FINISHED_ROW_S", 0.05)
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, TEA)
    second = await started(session, out, agent, stt, NOTES)
    agent.runs[first]["go"].set()
    await until(lambda: out.last("result").get("run_id") == first)
    agent.runs[second]["go"].set()
    await until(lambda: out.last("result").get("run_id") == second)
    await asyncio.sleep(0.15)
    assert [r.ui_id for r in session._runs] == [second]
    await finish_all(session, agent)


async def test_words_said_with_the_hotkey_held_are_taken_once_not_from_the_open_mic_too() -> None:
    session, out, agent, stt, _first, voice = await _hotkey_held_then_the_other_answers()
    before = len(session._runs)
    released = session._released
    answers = len([m for m in out.messages if m.type == "result"])
    for said in ("Hey Swift, what time is it", "Hey Swift", "and who discovered it"):
        await say(session, stt, said)
        await asyncio.sleep(0.1)
    assert len(session._runs) == before and session._released is released
    assert len([m for m in out.messages if m.type == "result"]) == answers
    stt.text = "what time is it"
    await session.handle(Message("ptt", {"state": "up"}))
    await until(lambda: voice.done())
    await finish_all(session, agent)


async def test_stop_with_filler_words_reaches_the_one_behind_too() -> None:
    session, out, _records, agent, stt = make()
    second = await _answer_asks_with_one_behind(session, out, agent, stt)
    await say(session, stt, "please stop")
    await until(lambda: agent.cancelled == [second])
    await finish_all(session, agent)


async def test_pause_listening_closes_the_answer_recording_and_resume_reopens_it() -> None:
    session, _out, agent, _control, _research = await _hidden_while_recording("no")
    q = session.dialogue.pending
    # Paused from the tray, wake listening off: only hands_free_blocked is set.
    session.hands_free_blocked = True
    session.listening_changed()
    await session._bring(q.owner)
    await asyncio.sleep(0.05)
    assert session._answer_task is None, "the microphone opened during Pause listening"
    session.hands_free_blocked = False
    session.listening_changed()
    assert session._answer_task is not None
    # And a recording going when it's paused stops.
    session.hands_free_blocked = True
    session.listening_changed()
    assert session._answer_task is None
    session.hands_free_blocked = False
    await finish_all(session, agent)


async def test_no_answer_recording_opens_while_the_hotkey_holds_one() -> None:
    session, _out, agent, _control, _research = await _hidden_while_recording("no")
    q = session.dialogue.pending
    stt = session.transcriber
    await session.handle(Message("ptt", {"state": "down"}))
    await asyncio.sleep(0.05)
    voice, released = session._confirm_voice, session._released
    assert voice is not None and not voice.done()
    await session._bring(q.owner)
    await asyncio.sleep(0.05)
    assert session._answer_task is None and session._released is released, "two recordings on one microphone"
    stt.text = "show me"  # nothing that takes the card from the question
    await session.handle(Message("ptt", {"state": "up"}))
    await until(lambda: voice.done())
    await until(lambda: session._answer_task is not None)  # its turn now
    await finish_all(session, agent)


async def test_no_answer_recording_opens_over_swift_s_own_voice() -> None:
    session, _out, agent, _control, _research = await _hidden_while_recording("no")
    q = session.dialogue.pending

    class Talking(type(session.speaker)):
        speaking = True

    session.speaker.__class__ = Talking
    await session._bring(q.owner)
    await asyncio.sleep(0.05)
    assert session._answer_task is None, "the microphone recorded Swift"
    Talking.speaking = False
    session.speech_done()
    await until(lambda: session._answer_task is not None)
    await finish_all(session, agent)


async def test_a_hung_transcription_doesn_t_leave_swift_deaf(monkeypatch: Any) -> None:
    monkeypatch.setattr("swift.session.CAPTURE_STT_TIMEOUT_S", 0.05)
    session, _out, agent, stt, first, voice = await _hotkey_held_then_the_other_answers()
    agent.runs[first]["go"].set()
    await asyncio.sleep(0.05)
    real = stt.transcribe

    async def hung(_audio: Any) -> Any:
        await asyncio.Event().wait()

    stt.transcribe = hung
    await session.handle(Message("ptt", {"state": "up"}))
    await until(lambda: voice.done())
    stt.transcribe = real
    await started(session, _out, agent, stt, "Hey Swift, compare three e-readers")
    await finish_all(session, agent)


async def _agent_question_recording() -> tuple[Any, Any, Any, Any]:
    session, out, _records, agent, stt = asker()
    session.wake_on = False
    real = session._capture_voice

    async def recording(capture: dict[str, Any], phase: Any = None, auto: Any = None) -> Any:
        if str(capture.get("id", "")).startswith("answer-"):
            await asyncio.Event().wait()
        return await real(capture, phase, auto=auto) if phase else await real(capture)

    session._capture_voice = recording
    await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    await until(lambda: session._answer_task is not None)
    return session, agent, stt, session._answer_task


async def test_the_hotkey_takes_over_from_an_answer_recording() -> None:
    session, agent, stt, recording = await _agent_question_recording()
    await session.handle(Message("ptt", {"state": "down"}))
    await asyncio.sleep(0.05)
    voice = session._confirm_voice
    assert voice is not None and not voice.done() and recording.done(), "two recordings on one microphone"
    stt.text = "show me"
    await session.handle(Message("ptt", {"state": "up"}))
    await until(lambda: voice.done())
    await until(lambda: session._answer_task is not None)  # the question still waits: it records again
    await finish_all(session, agent)


async def test_an_answer_recording_stops_when_swift_starts_talking_and_resumes_after() -> None:
    session, agent, _stt, recording = await _agent_question_recording()

    class Talking(type(session.speaker)):
        speaking = True

    session.speaker.__class__ = Talking
    session._speech_news(True)
    await asyncio.sleep(0.05)
    assert recording.done() and session._answer_task is None, "the microphone recorded Swift"
    Talking.speaking = False
    session.speech_done()
    await until(lambda: session._answer_task is not None)
    await finish_all(session, agent)


async def test_waiting_for_the_speech_model_isn_t_a_transcription_that_hung(monkeypatch: Any) -> None:
    monkeypatch.setattr("swift.session.CAPTURE_STT_TIMEOUT_S", 0.05)
    session, out, agent, stt, first, voice = await _hotkey_held_then_the_other_answers()
    assert first

    async def loading() -> None:
        await asyncio.sleep(0.2)

    stt.wait_loaded = loading
    stt.text = "show me"
    await session.handle(Message("ptt", {"state": "up"}))
    await until(lambda: voice.done())
    assert not any("too long" in str(m.data.get("text")) for m in out.messages if m.type == "run.voice")
    await finish_all(session, agent)
