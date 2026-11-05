"""One owner of what is on screen (seams audit 2026-11, S1): the backend tells every new overlay what is
on screen, a card counts down only while an overlay draws it, one card per request is sent, and a due
card leaves the schedule only once drawn."""

from __future__ import annotations

import asyncio

from test_runs import finish_all
from test_seams_audit_ipc import _one_card
from test_seams_audit_speech import _wake_session, _wifi_question

from swift.ipc.protocol import Message
from swift.session import Run


async def test_when_the_overlay_goes_the_card_stops_counting_down() -> None:
    session, _out, attention, agent, request_id = await _one_card()
    assert attention._runs(request_id)
    session.overlay_gone()
    try:
        assert not attention._runs(request_id)
        await session.handle(Message("card.seen", {"request_id": request_id, "visible": True}))  # the next draws it
        assert attention._runs(request_id)
    finally:
        await finish_all(session, agent)


async def test_a_new_overlay_gets_the_card_with_the_time_it_has_left() -> None:
    session, out, _attention, agent, request_id = await _one_card()
    before = len(out.messages)
    await session.handle(Message("ready", {"startup_ms": 1}))
    sent = out.messages[before:]
    try:
        types = [m.type for m in sent]
        assert "confirm.request" in types and "confirm.hold" in types
        hold = next(m.data for m in sent if m.type == "confirm.hold")
        assert hold["request_id"] == request_id and hold["held"] is False and hold["timeout_s"] > 0
    finally:
        await finish_all(session, agent)


async def test_a_new_overlay_gets_a_lane_question_card_with_its_countdown() -> None:
    session, out, _records, _stt, _control = _wake_session()
    card = await _wifi_question(session, out)
    await asyncio.sleep(0.05)
    before = len(out.messages)
    await session.handle(Message("ready", {"startup_ms": 1}))
    again = [m.data for m in out.messages[before:] if m.type == "ask" and m.data.get("ask_id") == card["ask_id"]]
    assert again and again[-1]["open"] and 0 < again[-1]["seconds"] <= session.wake_question_s
    assert any(m.type == "state" and m.data.get("run_id") == card["run_id"] for m in out.messages[before:])


def test_a_request_with_two_cards_replays_the_one_on_screen() -> None:
    from swift.ipc.protocol import outbound

    run = Run(thread="t")
    for n in (1, 2):
        run.remember(outbound("state", state="confirm", run_id="a-1"))
        run.remember(outbound("confirm.request", request_id=f"a-1:{n}", run_id="a-1", title=f"Edit {n}", detail="",
                              tool="Edit"))
    assert [m.data["request_id"] for m in run.replay("a-1:1") if m.type == "confirm.request"] == ["a-1:1"]
    assert [m.data["request_id"] for m in run.replay() if m.type == "confirm.request"] == ["a-1:2"]


async def test_a_due_card_sent_as_the_overlay_goes_is_shown_to_the_next_one() -> None:
    from test_hardening_2026_10 import _settle
    from test_system_lane import _session

    session, rec, _, _ = await _session()
    assert session.system is not None
    sched = session.system.scheduler
    tea = sched.add("timer", sched.clock(), "tea")
    sched.items[-1].fired = True
    await session.notify_due(tea, False)
    await _settle()
    sent = [m.data["run_id"] for m in rec.messages if m.type == "result" and m.data["run_id"].startswith("due-")]
    assert len(sent) == 1 and [i.id for i in sched.items] == [tea.id]  # sent, not yet drawn: still in the file
    session.overlay_gone()  # it went before drawing it
    assert [i.id for i, _, _ in session._due] == [tea.id] and [i.id for i in sched.items] == [tea.id]
    await session._kick_due()
    await _settle()
    again = [m.data["run_id"] for m in rec.messages if m.type == "result" and m.data["run_id"].startswith("due-")]
    assert len(again) == 2
    session._due_drawn(again[-1])
    assert sched.items == []  # drawn: off the schedule, once


# ---- owner checks 2026-11-05 ----------------------------------------------------------------------


async def test_a_lane_question_put_into_the_stack_ends_its_own_card() -> None:
    """Two unsure answers to "Turn off Wi-Fi?" put it in the stack. Before, its card stayed "working"
    in the overlay for ever, so it was both on screen and in the stack, and a timer's card behind it
    was refused again and again (2026-11-05)."""
    from swift.stt.transcriber import Transcription

    session, out, _records, _stt, _control = _wake_session()
    card = await _wifi_question(session, out)
    q = session.dialogue.pending
    assert q is not None
    q.reasked = 99  # the last unsure answer it gets
    await session._take_answer("", source="answer", unsure=True)
    await asyncio.sleep(0.05)
    ends = [m.data for m in out.messages if m.type == "result" and m.data.get("run_id") == card["run_id"]]
    assert ends and "later" in ends[-1]["summary"], "the lane card was left on screen"
    assert any(m.type == "ask" and m.data.get("ask_id") == card["ask_id"] and not m.data["open"] for m in out.messages)


async def test_a_due_item_is_said_once_when_it_comes_due_even_if_its_card_waits() -> None:
    from test_hardening_2026_10 import _settle
    from test_system_lane import _session

    session, _rec, _, _ = await _session()
    assert session.system is not None
    said: list[str] = []
    session._speak = lambda text, *a, **k: said.append(text)  # type: ignore[method-assign]
    session.speech_replies = "auto"
    session._open_confirm = lambda: "req-1"  # type: ignore[method-assign]  # a card is in the way
    sched = session.system.scheduler
    tea = sched.add("timer", sched.clock(), "tea")
    sched.items[-1].fired = True
    await session.notify_due(tea, False)
    await session.notify_due(tea, False)
    await _settle()
    assert len(said) == 1, said
    session._open_confirm = lambda: None  # type: ignore[method-assign]
    await session._kick_due()
    await _settle()
    assert len(said) == 1, said
