"""Seams audit (2026-11-04), state machines and timers: failing tests that reproduce findings.
Reproduce open findings in docs/audit/2026-11-seams-audit.md; marked xfail(strict) until fixed."""

from __future__ import annotations

import pytest

import asyncio
import time

from test_dialogue import asker, asks
from test_runs import finish_all, say, started, until
from test_system_lane import lane

from swift.ipc.protocol import Message
from swift.parked import ParkedThreads


@pytest.mark.xfail(strict=True, reason="seams audit T-01: open finding; remove this marker with the fix")
async def test_s01_a_lane_question_behind_a_run_question_kills_the_run_questions_timer() -> None:
    """A run asks "Paris or Rome?"; the owner says "turn off the wifi" instead (a new request beside it).
    The lane asks "Turn off Wi-Fi?", queued behind the run's question, but ``_question_timer`` replaces the
    one shared ``_ask_timer``: the run's question then never times out, and its run never ends."""
    session, out, records, agent, stt = asker(parked=ParkedThreads(None), wake_question_s=0.3)
    session.system, _, _ = lane()
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    await say(session, stt, "turn off the wifi")
    await asyncio.sleep(0.2)
    # The run's question must still end by itself (0.3 s window): unanswered, into the stack.
    await until(lambda: run_id in agent.results, timeout=3)
    await finish_all(session, agent)


@pytest.mark.xfail(strict=True, reason="seams audit T-01: open finding; remove this marker with the fix")
async def test_s01b_the_lane_question_queued_behind_is_never_shown_nor_listened_for() -> None:
    """Same set-up: "Turn off Wi-Fi?" is said as a result line, but no Yes/No card opens for it and a
    "Swift, yes" goes to the run's "Paris or Rome?" question instead."""
    session, out, records, agent, stt = asker(parked=ParkedThreads(None), wake_question_s=5)
    session.system, control, _ = lane()
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    await say(session, stt, "turn off the wifi")
    await asyncio.sleep(0.2)
    shown = [a.get("question") for a in asks(out) if a.get("open")]
    pending = session.dialogue.pending
    waiting = [q.text for q in session.dialogue.waiting]
    try:
        assert "Turn off Wi-Fi?" in shown, (shown, pending and pending.text, waiting)
    finally:
        for q in [*session.dialogue.waiting, *([pending] if pending else [])]:
            session._question_done(q)
        agent.results.setdefault(run_id, None)
        await finish_all(session, agent)


@pytest.mark.xfail(strict=True, reason="seams audit T-02: open finding; remove this marker with the fix")
async def test_s02_an_answer_said_inside_the_window_but_transcribed_after_it_is_lost() -> None:
    """Trace of "a question timed out into the stack 2 s before the owner's answer": the window's timer
    (``_ask_timer``, a fixed call_later) fires while the owner's answer is being transcribed;
    ``_listening_for`` compares the window against the time the transcription *finished*, not when the
    owner started speaking. The answer said in time is dropped and the question goes to the stack."""
    session, out, records, agent, stt = asker(parked=ParkedThreads(None), wake_question_s=0.4)
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: asks(out) and asks(out)[-1]["open"])
    await asyncio.sleep(0.2)  # the owner answers 0.2 s into a 0.4 s window
    stt.delay = 0.35  # transcription of the answer takes 0.35 s (Whisper on the owner's PC: 1-3 s)
    await say(session, stt, "Rome")
    await until(lambda: run_id in agent.results, timeout=3)
    try:
        assert agent.results[run_id].data.get("answer") == "Rome", agent.results[run_id].data
    finally:
        await finish_all(session, agent)


@pytest.mark.xfail(strict=True, reason="seams audit T-03: open finding; remove this marker with the fix")
async def test_s03_after_a_spoken_reask_of_swifts_own_question_the_microphone_stops_listening_for_it() -> None:
    """Log 2026-11-04 17:43:39 (reask) -> 17:44:04.84 (unanswered, exactly 25 s after the reask began, while the
    card's 25 s countdown restarted when Swift finished saying it, 17:43:45). ``_lane_turn`` restarts the timer
    before the reask is spoken and leaves the old ``_answer_window``; ``speech_done`` only reopens listening when
    ``_answer_window is None``, so after the reask nothing listens for the answer and the timer runs from the
    reask's start."""
    from swift.speech import FakeSpeaker

    session, out, records, agent, stt = asker(parked=ParkedThreads(None), wake_question_s=1.0)
    session.system, _, _ = lane()
    speaker = FakeSpeaker()
    session.speaker = speaker
    await say(session, stt, "Hey Swift, turn off the wifi")
    await until(lambda: asks(out) and asks(out)[-1]["open"] and asks(out)[-1]["question"] == "Turn off Wi-Fi?")
    await asyncio.sleep(0.05)
    await say(session, stt, "purple")  # unclear: asked again, aloud
    await until(lambda: speaker.speaking)
    await asyncio.sleep(0.7)  # Swift says the reask for 0.7 s
    speaker.finish()
    session.speech_done()
    await asyncio.sleep(0.35)  # 0.35 s into the 1 s the owner should now have
    try:
        assert session.dialogue.pending is not None, "timed out: the timer ran from the reask's start"
        assert session._listening_for() is not None, "nothing listens for the answer after the reask"
    finally:
        await asyncio.sleep(1.0)
        await finish_all(session, agent)


class _TwoCards:
    """A run that asks two confirm cards at once (Claude Code's parallel tool calls each reach
    ``can_use_tool``; Swift's own gateway card can come beside a provider's)."""

    def __init__(self) -> None:
        from test_runs import Agent

        class Two(Agent):
            async def _work(self, run_id, run):  # type: ignore[no-untyped-def]
                from swift.executors.base import ExecEvent, ExecResult

                queue = run["queue"]
                try:
                    futures = {}
                    for n in (1, 2):
                        request_id = f"{run_id}:{n}"
                        futures[request_id] = run["pending"][request_id] = asyncio.get_running_loop().create_future()
                        queue.put_nowait(ExecEvent("confirm", f"Edit {n}", request_id=request_id, detail="", tool="Edit"))
                    for request_id, future in futures.items():
                        self.answers[request_id] = await future
                    return ExecResult("done", "Done.")
                finally:
                    queue.put_nowait(None)

        self.cls = Two


@pytest.mark.xfail(strict=True, reason="seams audit O-07: open finding; remove this marker with the fix")
async def test_s04_the_overlay_and_the_backend_disagree_on_which_card_is_on_screen() -> None:
    """Backend: ``_cards[0]`` (card 1) is on screen, card 2 waits behind it, its countdown not started. But
    ``_send`` forwards card 2's ``confirm.request`` (same run, in front), and the overlay's ``onConfirm``
    makes it ``pendingConfirm``: card 1 disappears from the screen while the backend counts it as shown."""
    from test_runs import make

    session, out, records, agent, stt = make(_TwoCards().cls, wake_followup_s=8.0)
    await say(session, stt, "Hey Swift, edit the two files")
    await until(lambda: len(session._cards) == 2)
    on_screen_backend = session._cards[0][1]
    last_card_sent = [m.data["request_id"] for m in out.messages if m.type == "confirm.request"][-1]
    try:
        assert last_card_sent == on_screen_backend, (on_screen_backend, last_card_sent)
    finally:
        for rid, fut in agent.runs["a-1"]["pending"].items():
            if not fut.done():
                fut.set_result(False)
        await finish_all(session, agent)


@pytest.mark.xfail(strict=True, reason="seams audit T-04: open finding; remove this marker with the fix")
async def test_s05_an_answer_that_asks_is_put_in_the_stack_while_its_reply_window_is_still_open() -> None:
    """Swift's answer asks something ("Which Tuesday, and what time?"). ``_expect_answer`` starts the park timer
    (``wake_question_s``) when the answer is sent, but the reply window (``_followup``, and the overlay's
    countdown from the ``followup`` message) restarts when Swift *finishes saying it* (``speech_done``). The
    question goes into the stack while the card still says it's listening: two timers for one window."""
    from test_runs import Agent, make

    from swift.executors.base import ExecEvent, ExecResult
    from swift.speech import FakeSpeaker

    class Asks(Agent):
        async def _work(self, run_id, run):  # type: ignore[no-untyped-def]
            try:
                run["queue"].put_nowait(ExecEvent("step", "Looking", activity="reading"))
                return ExecResult("done", "I found two Tuesdays. Which Tuesday, and what time?")
            finally:
                run["queue"].put_nowait(None)

    session, out, records, agent, stt = make(Asks, wake_followup_s=8.0, wake_question_s=0.4,
                                             parked=ParkedThreads(None))
    speaker = FakeSpeaker()
    session.speaker = speaker
    await say(session, stt, "Hey Swift, when is the meeting")
    await until(lambda: speaker.speaking and session._question is not None)
    await asyncio.sleep(0.3)  # Swift says the answer for 0.3 s
    speaker.finish()
    session.speech_done()
    await asyncio.sleep(0.25)  # 0.25 s into the reply window the card shows (0.55 s after the answer)
    try:
        assert session._followup is not None and time.monotonic() <= session._followup[1]
        assert session.parked.all() == [], "parked while its reply window is still open"  # type: ignore[union-attr]
    finally:
        await finish_all(session, agent)


@pytest.mark.xfail(strict=True, reason="seams audit T-06: open finding; remove this marker with the fix")
async def test_s06_an_unsure_answer_to_an_open_question_is_dropped_without_a_word() -> None:
    """While Swift's question card is up the session is busy (state "working"), so ``_hear_transcribed``'s
    ``wake_min_p`` bar runs *before* the ``_listening_for`` check: an answer the model was unsure of is counted
    as "unsure" and dropped, with no reask and nothing on the card, and the timer goes on to the stack. (Older
    builds turned it into a "Try saying it again" error card over the question: log 16:52:35 -> 16:52:54.)"""
    session, out, records, agent, stt = asker(parked=ParkedThreads(None), wake_question_s=1.0)
    session.system, _, _ = lane()
    await say(session, stt, "Hey Swift, turn off the wifi")
    await until(lambda: asks(out) and asks(out)[-1]["open"] and asks(out)[-1]["question"] == "Turn off Wi-Fi?")
    sent = len(out.messages)
    stt.probs = {"uh": 0.2, "maybe": 0.2, "do": 0.2, "it": 0.2}
    await say(session, stt, "uh maybe do it")
    await asyncio.sleep(0.2)
    stt.probs = None
    try:
        assert session.wake_stats["unsure"] == 0 or len(out.messages) > sent, (
            "an answer heard during the question's window got no reaction at all")
    finally:
        await asyncio.sleep(1.2)
        await finish_all(session, agent)



@pytest.mark.xfail(strict=True, reason="seams audit O-01: open finding; remove this marker with the fix")
async def test_s07_a_new_overlay_is_not_shown_the_card_the_backend_thinks_is_on_screen() -> None:
    """The overlay reloads or reconnects (webview reload, Tauri window recreated) while a confirm card waits.
    ``ready`` resends the stack and due items only: not the run in front, its card, its question or the rows.
    The backend still counts the card as on screen (``_cards[0]``) and as seen: the old overlay's
    ``card.seen`` is never cleared on disconnect, so it counts down unseen and expires into the stack."""
    from test_card_timing import finish, make as make_card, start

    from swift.attention import Attention

    session, out, records, calendar, agent, stt = make_card(attention=Attention(require_seen=True),
                                                            parked=ParkedThreads(None))
    await start(session, out, stt)
    card = out.last("confirm.request")
    await session.handle(Message("card.seen", {"request_id": card["request_id"], "visible": True}))
    before = len(out.messages)
    await session.handle(Message("ready", {"startup_ms": 100}))
    resent = [m.type for m in out.messages[before:]]
    try:
        assert "confirm.request" in resent, resent
    finally:
        await session.handle(Message("confirm.reply", {"request_id": card["request_id"], "decision": "reject"}))
        await finish(session)


async def test_s08_an_utterance_held_mid_thought_does_not_start_a_request_after_the_screen_locks() -> None:
    """Fixed (T-07): "Hey Swift, remind me to call Sam and" (held: more is coming), then Win+L. The lock
    drops the held utterance, and ``_flush_held`` / ``_hear_transcribed`` check ``_deaf()`` where heard
    speech acts, so no request starts while locked (threat model T7)."""
    from test_dialogue import until as until_d
    from test_wake import make as make_wake

    from swift.endpoint import EndOfTurn
    from test_runs import SHORT

    session, out, records, rec, stt = make_wake("hey swift remind me to call Sam and", wake_followup_s=8.0)
    session.endpoint = EndOfTurn(silence_s=0.05, extend_s=0.2, cap_s=1.0)
    await session.hear_wake(SHORT, time.monotonic())
    assert session.wake_stats["held"] == 1
    session.listening_paused = True  # Lifecycle.handle on the lock
    await session.hold_cards(True)
    await asyncio.sleep(0.5)
    assert records == [] and not session._runs, "a request started while the screen was locked"
