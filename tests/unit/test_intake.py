"""One set of steps for every input (swift/intake.py; seams audit S2). The same words through every door
give the same decision, or a declared difference (typing never approves; hands-free needs the name)."""

from __future__ import annotations

import asyncio

import pytest

from swift import intake
from swift.ipc.protocol import Message


@pytest.mark.parametrize(("source", "named", "card", "reversible"), [
    ("click", False, True, True),
    ("voice", False, True, True),
    ("debug.ask", False, True, True),  # stands for the hotkey
    ("wake", False, False, True),
    ("wake", True, True, True),
    ("answer", False, False, True),
    ("followup", True, True, True),
    ("typed", False, False, False),
    ("typed", True, False, True),  # typing never approves a card, even with the name
    ("over_speech", True, False, False),
    ("something new", True, False, False),  # a door the table doesn't know: the strict rule
])
def test_who_may_approve_what(source: str, named: bool, card: bool, reversible: bool) -> None:
    assert intake.approves(source, named=named, target="card").allowed is card
    assert intake.approves(source, named=named, target="reversible").allowed is reversible


def test_no_words_is_nothing_and_a_mid_run_control_is_never_an_answer_during_a_run() -> None:
    assert not intake.has_words("") and not intake.has_words(" ... ") and intake.has_words("no")
    assert not intake.for_question("stop", run_working=True)
    assert intake.for_question("stop", run_working=False)  # at rest, "stop" may answer "Turn off Wi-Fi?"
    assert intake.for_question(None, run_working=True)


async def _card() -> tuple:  # type: ignore[type-arg]
    from test_hands_free import make, until_confirm

    session, out, records, stt = make()
    await until_confirm(session, out)
    return session, out, records, stt, out.last("confirm.request")["request_id"]


async def _decided(session, records, rid: str) -> str | None:  # type: ignore[no-untyped-def]
    from test_hands_free import finish

    await asyncio.sleep(0.1)
    if session.state == "confirm":
        await session.handle(Message("confirm.reply", {"request_id": rid, "decision": "reject"}))
        await finish(session)
        return records[0]["approvals"][0]["decision"] if records else None  # rejected by the test: not approved
    await finish(session)
    return records[0]["approvals"][0]["decision"]


@pytest.mark.parametrize(("how", "approved"), [
    ("typed approve", False),
    ("typed Swift, approve", False),
    ("said approve", False),
    ("said Swift, approve", True),
    ("click", True),
])
async def test_the_same_approve_through_every_door(how: str, approved: bool) -> None:
    from test_hands_free import say

    session, out, records, stt, rid = await _card()
    if how.startswith("typed "):
        await session.handle(Message("text", {"text": how.removeprefix("typed ")}))
    elif how.startswith("said "):
        await say(session, stt, how.removeprefix("said ") + ".")
    else:
        await session.handle(Message("confirm.reply", {"request_id": rid, "decision": "approve"}))
    decision = await _decided(session, records, rid)
    assert (decision == "approve") is approved, (how, decision)


async def test_a_click_on_a_lane_question_answers_it_not_the_card_open_beside_it() -> None:
    """D-07: before, the click went through the text box, where the open card took it first."""
    from test_hands_free import finish

    session, out, records, stt, rid = await _card()
    q = session._ask_lane("Turn off Wi-Fi?", "yes_no", None, (), {"thread": "t9", "transcript": "turn off the wifi"})
    q.run_id = "local-9"
    await session.handle(Message("ask.reply", {"ask_id": q.id, "text": "No"}))
    await asyncio.sleep(0.2)
    assert session.state == "confirm" and session._open_confirm() == rid, "the click answered the card"
    await session.handle(Message("confirm.reply", {"request_id": rid, "decision": "reject"}))
    await finish(session)
