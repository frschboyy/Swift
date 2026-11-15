"""OWN-04: Swift's question is on screen only once the overlay says it drew it in front (``screen``'s
``ask_id``), as a confirm card is. Before, the backend decided from its own state, so a "yes" answered a
question whose frame was still in flight, or one the overlay never drew because it was gone. Fake agent
and fake devices: nothing real is switched."""

from __future__ import annotations

import asyncio

import pytest
from test_dialogue import asks
from test_question_on_screen import _session
from test_runs import finish_all, say, until

from swift.ipc.protocol import Message

pytestmark = pytest.mark.drawn_by_test  # this file is the overlay


async def _drawn(session, ask_id: str) -> None:  # type: ignore[no-untyped-def]
    """The overlay's acknowledgement of the last frame, with ``ask_id`` drawn ("" for none)."""
    await session.handle(Message("screen", {"n": session._drawn.n, "stage": "working", "run_id": "", "confirm": "",
                                            "ask_id": ask_id}))


async def _asked(session, out, stt):  # type: ignore[no-untyped-def]
    await say(session, stt, "Hey Swift, turn off the wifi")
    await until(lambda: asks(out) and asks(out)[-1].get("open") and asks(out)[-1].get("question") == "Turn off Wi-Fi?")
    q = session.dialogue.pending
    assert q is not None
    return q


async def test_a_yes_before_the_overlay_drew_the_question_answers_nothing() -> None:
    session, out, agent, stt, control = _session()
    q = await _asked(session, out, stt)
    await say(session, stt, "yes")
    await asyncio.sleep(0.2)
    assert control.radio_state.get("wifi") is not False, "a yes to a question not drawn yet"
    assert not session._on_screen(q), "sent is not drawn"
    await _drawn(session, q.id)
    assert session._on_screen(q)
    await until(lambda: session._listening_for() is not None)
    await say(session, stt, "yes")
    await until(lambda: control.radio_state.get("wifi") is False)
    await finish_all(session, agent)


async def test_a_question_the_overlay_did_not_draw_takes_no_yes() -> None:
    session, out, agent, stt, control = _session()
    q = await _asked(session, out, stt)
    await _drawn(session, "")  # the frame came, the question isn't in front
    await say(session, stt, "yes")
    await asyncio.sleep(0.2)
    assert control.radio_state.get("wifi") is not False, "a yes to a question the overlay didn't draw"
    assert not session._on_screen(q)
    await finish_all(session, agent)


async def test_a_yes_after_the_overlay_went_answers_nothing() -> None:
    session, out, agent, stt, control = _session()
    q = await _asked(session, out, stt)
    await _drawn(session, q.id)
    session.overlay_gone()
    await say(session, stt, "yes")
    await asyncio.sleep(0.2)
    assert control.radio_state.get("wifi") is not False, "a yes with no overlay at all"
    assert not session._on_screen(q), "nothing is drawn once the overlay is gone"
    await finish_all(session, agent)
