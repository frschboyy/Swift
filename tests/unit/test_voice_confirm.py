"""Answering a confirm card by voice while the run waits (ADR-007 §8)."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from test_session import Recorder as Outbox
from test_voice import FakeRecorder, FakeTranscriber

from swift.executors.mock import MockExecutor
from swift.ipc.protocol import Message
from swift.session import Session


def make(**kw: Any) -> tuple[Session, Outbox, list[dict[str, Any]], FakeRecorder, FakeTranscriber]:
    out, records = Outbox(), []
    rec, stt = FakeRecorder(), FakeTranscriber("add a next steps section to my notes")
    session = Session(
        out, MockExecutor(speed=0, default_scenario="confirm"), recorder=rec, transcriber=stt, tail_s=0.0,
        on_finish=records.append, **kw,
    )
    return session, out, records, rec, stt


async def ptt(session: Session, state: str) -> None:
    await session.handle(Message("ptt", {"state": state}))
    await asyncio.sleep(0)


async def until_confirm(session: Session, out: Outbox) -> str:
    """Speak the request and wait for its confirm card."""
    await ptt(session, "down")
    await ptt(session, "up")
    await asyncio.wait_for(out.confirm.wait(), 2)
    assert session.state == "confirm"
    return out.last("confirm.request")["request_id"]


async def say(session: Session, stt: FakeTranscriber, text: str) -> None:
    """Hold push-to-talk on the open card and say ``text``."""
    stt.text = text
    await ptt(session, "down")
    await ptt(session, "up")
    assert session._confirm_voice is not None
    await asyncio.wait_for(asyncio.shield(session._confirm_voice), 2)


def phases(out: Outbox) -> list[str]:
    return [m.data["phase"] for m in out.messages if m.type == "confirm.voice"]


async def finish(session: Session) -> None:
    assert session._task is not None
    await asyncio.wait_for(session._task, 2)


async def test_saying_yes_approves_the_open_card() -> None:
    session, out, records, rec, _ = make()
    stt = session.transcriber
    assert isinstance(stt, FakeTranscriber)
    await until_confirm(session, out)
    await ptt(session, "down")
    assert rec.recording and session.state == "confirm"  # no "listening": the card stays up
    stt.text = "Yes, go ahead."
    await ptt(session, "up")
    await finish(session)

    assert out.states() == ["listening", "transcribing", "working", "confirm", "working", "result"]
    assert phases(out) == ["listening", "transcribing"]
    assert out.last("result")["status"] == "done"
    approval = records[0]["approvals"][0]
    assert approval["decision"] == "approve" and approval["source"] == "voice"
    assert approval["heard"] == ["Yes, go ahead."]
    assert records[0]["transcript"] == "add a next steps section to my notes"  # the request, not the answer


async def test_saying_no_rejects_it() -> None:
    session, out, records, _, stt = make()
    await until_confirm(session, out)
    await say(session, stt, "No, don't do that.")
    await finish(session)
    assert out.last("result")["status"] == "rejected"
    approval = records[0]["approvals"][0]
    assert (approval["tool"], approval["decision"], approval["source"]) == ("Edit", "reject", "voice")
    assert approval["heard"] == ["No, don't do that."] and approval["answered_ms"] is not None


async def test_saying_stop_cancels_the_run_like_escape() -> None:
    session, out, records, _, stt = make()
    await until_confirm(session, out)
    await say(session, stt, "never mind")
    with contextlib.suppress(asyncio.CancelledError):
        await finish(session)
    assert out.last("result")["status"] == "cancelled"
    assert records[0]["status"] == "cancelled"
    assert records[0]["approvals"][0]["decision"] == "cancelled" and records[0]["approvals"][0]["source"] == "voice"


async def test_anything_else_shows_a_hint_and_leaves_the_card_open() -> None:
    session, out, records, _, stt = make()
    request_id = await until_confirm(session, out)
    await say(session, stt, "what does that change exactly")
    assert session.state == "confirm" and not session._task.done()  # type: ignore[union-attr]
    hint = [m.data for m in out.messages if m.type == "confirm.voice"][-1]
    assert hint["phase"] == "hint" and hint["request_id"] == request_id
    assert "what does that change exactly" in hint["text"] and "approve" in hint["text"]

    await session.handle(Message("confirm.reply", {"request_id": request_id, "decision": "approve"}))
    await finish(session)
    approval = records[0]["approvals"][0]
    assert approval["source"] == "click" and approval["heard"] == ["what does that change exactly"]


async def test_a_click_while_transcribing_wins_over_the_voice_answer() -> None:
    session, out, records, _, stt = make()
    request_id = await until_confirm(session, out)
    stt.text, stt.delay = "reject", 0.2
    await ptt(session, "down")
    await ptt(session, "up")
    await session.handle(Message("confirm.reply", {"request_id": request_id, "decision": "approve"}))
    await finish(session)
    assert out.last("result")["status"] == "done"
    assert records[0]["approvals"][0]["source"] == "click"


async def test_escape_while_answering_stops_the_mic_and_the_run() -> None:
    session, out, records, rec, _ = make()
    await until_confirm(session, out)
    await ptt(session, "down")
    assert rec.recording
    await session.handle(Message("cancel", {}))
    assert not rec.recording
    assert out.last("result")["status"] == "cancelled" and records[0]["status"] == "cancelled"
    assert session._confirm_voice is None


async def test_a_quick_tap_on_the_card_does_nothing() -> None:
    session, out, _, rec, stt = make()
    await until_confirm(session, out)
    rec.seconds = 0.1
    await say(session, stt, "yes")
    assert phases(out) == ["listening", "idle"] and session.state == "confirm"
    assert stt.calls == 1  # only the request was transcribed


async def test_ptt_while_working_listens_for_midrun_commands_not_a_new_run() -> None:
    """ADR-010 §6: push-to-talk mid-run goes to the mid-run grammar (test_show_me.py); speech that is
    neither for the run nor a clear new request is a hint (a clear one starts beside it: test_runs.py)."""
    out = Outbox()
    session = Session(
        out, MockExecutor(speed=1, default_scenario="long"), recorder=FakeRecorder(),
        transcriber=FakeTranscriber(text="uh, hmm"),
        tail_s=0.0,
    )
    await ptt(session, "down")
    await ptt(session, "up")
    for _ in range(100):
        if session.state == "working":
            break
        await asyncio.sleep(0.01)
    first = session._task
    await ptt(session, "down")
    assert session._task is first and session._confirm_voice is not None
    await ptt(session, "up")
    await asyncio.wait_for(asyncio.shield(session._confirm_voice), 2)
    assert session._task is first and not first.done()  # still the same run
    assert out.last("run.voice")["phase"] == "hint"
    await session.cancel()


# ---- approving in noise (docs/stt-noise.md: "stop" heard as "sure" with a TV on) ------------


async def test_a_noisy_approve_waits_for_a_second_one() -> None:
    session, out, records, _, stt = make()
    await until_confirm(session, out)
    stt.noise_db = -38.0
    await say(session, stt, "Sure.")
    assert session.state == "confirm"  # not approved yet
    again = [m.data for m in out.messages if m.type == "confirm.voice"][-1]
    assert again["phase"] == "again" and "noisy" in again["text"]
    await say(session, stt, "Approve.")
    await finish(session)
    assert out.last("result")["status"] == "done"
    approval = records[0]["approvals"][0]
    assert approval["decision"] == "approve" and approval["held_for"] == "noise" and approval["confirmed_twice"]
    assert approval["heard"] == ["Sure.", "Approve."]


async def test_low_confidence_alone_does_not_hold_an_approve() -> None:
    # The owner's clean "Stop." scored 0.46: confidence can't tell a mishearing from a short word.
    session, out, _, _, stt = make()
    await until_confirm(session, out)
    stt.noise_db, stt.probs = -62.0, {"Approve.": 0.5}
    await say(session, stt, "Approve.")
    await finish(session)
    assert out.last("result")["status"] == "done" and "again" not in phases(out)


async def test_a_clear_approve_in_a_quiet_room_goes_through_at_once() -> None:
    session, out, records, _, stt = make()
    await until_confirm(session, out)
    stt.noise_db, stt.probs = -62.0, {}
    await say(session, stt, "Approve.")
    await finish(session)
    assert "again" not in phases(out) and "held_for" not in records[0]["approvals"][0]


async def test_rejecting_in_noise_is_never_held() -> None:
    session, out, records, _, stt = make()
    await until_confirm(session, out)
    stt.noise_db = -30.0
    await say(session, stt, "No.")
    await finish(session)
    assert out.last("result")["status"] == "rejected" and "again" not in phases(out)


async def test_a_held_approve_then_a_reject_rejects() -> None:
    session, out, records, _, stt = make()
    await until_confirm(session, out)
    stt.noise_db = -30.0
    await say(session, stt, "Yes.")
    await say(session, stt, "No.")
    await finish(session)
    assert out.last("result")["status"] == "rejected"


async def test_something_else_in_between_starts_over() -> None:
    session, out, _, _, stt = make()
    await until_confirm(session, out)
    stt.noise_db = -30.0
    await say(session, stt, "Yes.")
    await say(session, stt, "what was that")
    await say(session, stt, "Yes.")
    assert session.state == "confirm" and phases(out).count("again") == 2
    await session.cancel()


async def test_a_click_still_approves_a_held_card() -> None:
    session, out, _, _, stt = make()
    request_id = await until_confirm(session, out)
    stt.noise_db = -30.0
    await say(session, stt, "Yes.")
    await session.handle(Message("confirm.reply", {"request_id": request_id, "decision": "approve"}))
    await finish(session)
    assert out.last("result")["status"] == "done"


# ---- a change instead of approve / reject, whichever provider asked -------------------------


async def test_a_change_on_a_provider_card_without_native_support_becomes_the_next_request() -> None:
    """The demo agent can't revise: Swift rejects its card and asks again with the change."""
    session, out, records, _, stt = make()
    await until_confirm(session, out)
    out.confirm.clear()
    await say(session, stt, "No, put the section in the README instead.")
    await finish(session)
    assert records[0]["status"] == "rejected" and records[0]["approvals"][0]["change_chars"] > 0
    # Once the rejected run has finished, the change runs as the next request (here it reaches a
    # card again: the demo agent's script).
    await asyncio.wait_for(out.confirm.wait(), 2)
    assert out.last("transcript") == {"text": "No, put the section in the README instead.", "final": True, "typed": False}
    await session.cancel()
    assert records[1]["source"] == "correction"


async def test_a_question_on_a_card_is_not_a_change() -> None:
    session, out, records, _, stt = make()
    await until_confirm(session, out)
    await say(session, stt, "Is that the notes file?")
    assert session.state == "confirm"
    assert [m.data for m in out.messages if m.type == "confirm.voice"][-1]["phase"] == "hint"
    await session.cancel()


class RevisingMock(MockExecutor):
    """A provider that takes changes itself (like Claude Code): it records them and carries on."""

    def __init__(self) -> None:
        super().__init__(speed=0, default_scenario="confirm")
        self.changes: list[str] = []

    async def change(self, request_id: str, text: str) -> bool:
        self.changes.append(text)
        await self.reply(request_id, True)  # revised and done, for the test
        return True


async def test_a_provider_that_revises_takes_the_change_in_the_same_run() -> None:
    out, records, rec, stt = Outbox(), [], FakeRecorder(), FakeTranscriber("add a next steps section to my notes")
    mock = RevisingMock()
    session = Session(out, mock, recorder=rec, transcriber=stt, tail_s=0.0, on_finish=records.append)
    await until_confirm(session, out)
    await say(session, stt, "Call it Next actions instead.")
    await finish(session)
    assert mock.changes == ["Call it Next actions instead."]
    assert records[0]["approvals"][0]["decision"] == "revise" and len(records) == 1
    assert any("Changing it" in m.data.get("text", "") for m in out.messages if m.type == "step")
