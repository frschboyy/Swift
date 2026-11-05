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


@pytest.mark.parametrize(("text", "p", "just_asked", "fragment"), [
    ("Ah.", 0.2, False, True), ("", None, False, True), ("um, hmm", 0.9, True, True),  # no words at all
    ("Kern", 0.57, False, True),  # one unsure word
    ("Kern", 0.57, True, False), ("Tuesday", 0.5, True, False),  # a reply to Swift's question
    ("Mozart", 0.95, False, False),  # one clear word is a request
    ("Kern", None, False, False),  # the model didn't say: taken at its word
    ("Kern Street", 0.3, False, False),  # more than one word: the clarity check's business
])
def test_what_counts_as_a_fragment(text: str, p: float | None, just_asked: bool, fragment: bool) -> None:
    assert intake.fragment(text, request_p=p, just_asked=just_asked) is fragment


def _heard(text: str, p: float):  # type: ignore[no-untyped-def]
    from swift.stt.transcriber import Transcription, Word

    return Transcription(text, 200, 0.9, words=tuple(Word(w, p) for w in text.split()))


@pytest.mark.parametrize(("heard", "p"), [("Kern", 0.57), ("Ah.", 0.2)])
async def test_a_spoken_fragment_never_starts_a_run(heard: str, p: float) -> None:
    """Owner checks 2026-11-05: "Kern" and "Ah." each started a run and a card of their own."""
    from test_followup import make

    session, out, executor, records = make()
    session._start_followup(_heard(heard, p))
    await asyncio.wait_for(session._task, 2)  # type: ignore[arg-type]
    assert executor.calls == [], "the agent got a fragment"
    assert records[-1].get("fragment") is True
    assert out.last("error")["title"] == "Say that again?"


@pytest.mark.parametrize("reply", ["Tuesday", "Both", "Second"])
async def test_one_word_replying_to_swifts_question_reaches_the_agent(reply: str) -> None:
    """The regression the reliability audit measured: "Which day?" "Tuesday." "Say that again?"."""
    from test_followup import Scripted, make

    session, _out, executor, records = make(Scripted(("done", "Which day suits you, Monday or Tuesday?")))
    await session.handle(Message("debug.ask", {"text": "Find a time for lunch with Ada next week."}))
    await asyncio.wait_for(session._task, 2)  # type: ignore[arg-type]
    session._start_followup(_heard(reply, 0.5))
    await asyncio.wait_for(session._task, 2)  # type: ignore[arg-type]
    assert len(executor.calls) == 2 and not records[-1].get("fragment")


@pytest.mark.parametrize(("said", "names"), [
    ("Turn the volume down. Write a haiku about tea.", ["volume.step"]),
    ("Turn on Bluetooth. Please turn on Bluetooth.", ["radio", "radio"]),
    ("Turn the volume down and write a haiku about tea", ["volume.step"]),
    ("Write a haiku about tea.", []),
])
def test_the_safety_check_reads_each_spoken_sentence(said: str, names: list[str]) -> None:
    """Speech recognition writes full stops; the check found nothing and the tool refused (2026-11-05)."""
    from swift.workflows.system_tools import owner_intents

    assert [i.name for i in owner_intents(said)] == names


@pytest.mark.parametrize(("text", "once"), [
    ("Turn on Bluetooth. Turn on Bluetooth.", "Turn on Bluetooth."),
    ("turn on bluetooth turn on bluetooth", "turn on bluetooth"),
    ("Turn on Bluetooth. Turn off Wi-Fi.", "Turn on Bluetooth. Turn off Wi-Fi."),
    ("no no", "no no"),
    ("Thanks. Thanks. Thanks.", "Thanks."),
])
def test_a_request_said_twice_is_taken_once(text: str, once: str) -> None:
    assert intake.collapse_repeats(text) == once


async def test_turn_on_bluetooth_said_twice_is_done_here() -> None:
    from test_system_lane import _session

    from swift.stt.transcriber import Transcription

    session, _rec, spy, records = await _session()
    session._start_followup(Transcription("Turn on Bluetooth. Turn on Bluetooth.", 200, 0.9))
    await asyncio.wait_for(session._task, 2)  # type: ignore[arg-type]
    assert spy.calls == [] and records[-1]["route"] == "local"


def test_a_brisk_hey_swift_on_its_own_is_kept_however_short() -> None:
    """2026-11-05: after a quiet while, each "Hey Swift" was a short clip, and short clips that
    weren't a control phrase were dropped, so it took several tries."""
    from test_hands_free import make

    session, *_ = make()
    assert session._short_kept("Hey Swift.", busy=False) == "Hey Swift."
    assert session._short_kept("Hey, Swift", busy=False) is not None
    assert session._short_kept("Kern", busy=False) is None
