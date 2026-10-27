"""The email workflow end to end through the session, and "show me" during a run (ADR-010).

The demo agent calls Swift's real tools, gateway and confirm card; the connector is the
fake one, so nothing is ever sent.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from test_session import Recorder as Outbox
from test_voice import FakeRecorder, FakeTranscriber

from swift.connectors.fake import FakeMailConnector
from swift.executors.mock import MockExecutor
from swift.ipc.protocol import Message
from swift.routing.rules import route_midrun
from swift.session import Session
from swift.workflows.tools import KnownContact, ToolHost

LECTURER = KnownContact("Dr Ada Lovelace", "ada.lovelace@example.edu", ("lecturer",))


class Pausing(MockExecutor):
    """The email scenario, stopping before ``send_email`` until the test lets it go on."""

    def __init__(self, tools: ToolHost) -> None:
        super().__init__(speed=0, default_scenario="email", tools=tools)
        self.drafted = asyncio.Event()
        self.go_on = asyncio.Event()
        self.go_on.set()

    async def _sleep(self, seconds: float) -> None:
        if seconds == 3.0:  # the "Reading the draft over" pause
            self.drafted.set()
            await self.go_on.wait()
        await asyncio.sleep(0)


def make(**kw: Any) -> tuple[Session, Outbox, list[dict[str, Any]], FakeMailConnector, Pausing, FakeTranscriber]:
    out, records = Outbox(), []
    mail = FakeMailConnector(contacts=())
    tools = ToolHost(mail, (LECTURER,))
    mock = Pausing(tools)
    stt = FakeTranscriber("send an email to my lecturer")
    session = Session(
        out, mock, debug_executor=mock, demo_speed=0, tools=tools, recorder=FakeRecorder(), transcriber=stt,
        tail_s=0.0, on_finish=records.append, router=None, **kw,
    )
    return session, out, records, mail, mock, stt


async def start(session: Session) -> None:
    await session.handle(Message("debug.run", {"scenario": "email"}))


async def finish(session: Session) -> None:
    assert session._task is not None
    await asyncio.wait_for(session._task, 2)


def of(out: Outbox, kind: str) -> list[dict[str, Any]]:
    return [m.data for m in out.messages if m.type == kind]


async def approve(session: Session, out: Outbox) -> dict[str, Any]:
    await asyncio.wait_for(out.confirm.wait(), 2)
    card = out.last("confirm.request")
    await session.handle(Message("confirm.reply", {"request_id": card["request_id"], "decision": "approve"}))
    return card


async def test_draft_show_me_confirm_sent() -> None:
    session, out, records, mail, mock, _ = make()
    mock.go_on.clear()
    await start(session)
    await asyncio.wait_for(mock.drafted.wait(), 2)

    # "show me" while drafting opens the draft.
    await session.handle(Message("debug.say", {"text": "show me"}))
    view = out.last("view")
    assert view["open"] is True and view["artifact_id"] == "draft-1"
    draft = [a for a in of(out, "artifact") if a["id"] == "draft-1"][-1]
    assert draft["kind"] == "email_draft" and draft["phase"] == "drafting"
    assert draft["data"]["to"] == [{"name": "Dr Ada Lovelace", "email": "ada.lovelace@example.edu"}]
    assert "Thursday" in draft["data"]["body"]
    assert view["run_id"] == draft["run_id"] == out.last("state")["run_id"]
    assert session.state == "working"  # no new run, no state change

    mock.go_on.set()
    card = await approve(session, out)
    # Swift's own card: no provider asking, and it shows the draft.
    assert card["request_id"].startswith("swift:") and card["agent"] is None
    assert card["artifact_id"] == "draft-1" and card["tool"] == "send_email"
    await finish(session)

    assert out.states() == ["listening", "transcribing", "working", "confirm", "working", "result"]
    assert out.last("result")["status"] == "done"
    assert len(mail.sent) == 1
    status = [a for a in of(out, "artifact") if a["kind"] == "send_status"]
    assert [s["data"]["state"] for s in status] == ["waiting_approval", "sending", "sent"]
    assert [s["version"] for s in status] == [1, 2, 3]
    record = records[0]
    assert record["approvals"][0]["by"] == "swift" and record["approvals"][0]["decision"] == "approve"
    assert [a["kind"] for a in record["artifacts"]][:2] == ["recipient", "email_draft"]
    assert "body" not in str(record["artifacts"])  # kinds and versions only

    # The result card is up: "show me" (the Show button) still has the send status.
    await session.handle(Message("view", {"action": "show"}))
    assert out.last("view")["artifact_id"] == "send-draft-1"


async def test_rejecting_the_send_card_ends_not_approved() -> None:
    session, out, records, mail, _, _ = make()
    await start(session)
    await asyncio.wait_for(out.confirm.wait(), 2)
    card = out.last("confirm.request")
    await session.handle(Message("confirm.reply", {"request_id": card["request_id"], "decision": "reject"}))
    await finish(session)
    assert mail.sent == []
    assert out.last("result")["status"] == "rejected"
    assert records[0]["approvals"][0]["decision"] == "reject"


async def test_swift_card_times_out_without_sending() -> None:
    session, out, _, mail, _, _ = make(confirm_timeout_s=0.05)
    await start(session)
    await finish(session)
    assert mail.sent == [] and out.last("result")["status"] == "rejected"
    assert out.last("confirm.request")["timeout_s"] == 0.05


async def test_escape_on_the_send_card_sends_nothing() -> None:
    session, out, records, mail, _, _ = make()
    await start(session)
    await asyncio.wait_for(out.confirm.wait(), 2)
    await session.handle(Message("cancel", {}))
    assert mail.sent == [] and out.last("result")["status"] == "cancelled"
    assert records[0]["approvals"][0]["decision"] == "cancelled"
    assert session.tools is not None and session.tools.scope is None


async def test_show_me_on_the_confirm_card_and_hide() -> None:
    session, out, _, mail, _, _ = make()
    await start(session)
    await asyncio.wait_for(out.confirm.wait(), 2)
    await session.handle(Message("debug.say", {"text": "show me the draft"}))
    assert out.last("view")["artifact_id"] == "draft-1" and session.state == "confirm"
    await session.handle(Message("debug.say", {"text": "hide that"}))
    assert out.last("view")["open"] is False
    await approve(session, out)
    await finish(session)
    assert len(mail.sent) == 1


async def test_ptt_while_working_takes_the_midrun_grammar() -> None:
    session, out, records, mail, mock, stt = make()
    mock.go_on.clear()
    await start(session)
    await asyncio.wait_for(mock.drafted.wait(), 2)

    stt.text = "show me the recipient"
    await session.handle(Message("ptt", {"state": "down"}))
    await asyncio.sleep(0)
    await session.handle(Message("ptt", {"state": "up"}))
    assert session._confirm_voice is not None
    await asyncio.wait_for(asyncio.shield(session._confirm_voice), 2)
    assert [v["phase"] for v in of(out, "run.voice")] == ["listening", "transcribing", "idle"]
    assert out.last("view")["artifact_id"] == "recipient"

    # Anything that is neither for the run nor a clear new request is a hint (test_runs.py: new ones).
    stt.text = "um, the"
    await session.handle(Message("ptt", {"state": "down"}))
    await asyncio.sleep(0)
    await session.handle(Message("ptt", {"state": "up"}))
    await asyncio.wait_for(asyncio.shield(session._confirm_voice), 2)
    assert of(out, "run.voice")[-1]["phase"] == "hint" and "show me" in of(out, "run.voice")[-1]["text"]

    # "stop" cancels like Esc.
    await session.handle(Message("debug.say", {"text": "stop"}))
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(asyncio.shield(session._task), 2)  # type: ignore[arg-type]
    assert out.last("result")["status"] == "cancelled" and mail.sent == []
    assert records[0]["midrun"] == ["show", None, "stop"]


async def test_show_with_no_artifacts_opens_the_steps() -> None:
    out, mock = Outbox(), MockExecutor(speed=0)
    session = Session(out, mock, debug_executor=mock, demo_speed=0, tools=ToolHost())
    await session.handle(Message("debug.run", {"scenario": "confirm"}))
    await asyncio.wait_for(out.confirm.wait(), 2)
    await session.handle(Message("view", {"action": "show"}))
    assert out.last("view") == {"run_id": "mock-1", "artifact_id": None, "open": True}


def test_midrun_grammar() -> None:
    def action(text: str) -> tuple[str | None, str | None] | None:
        r = route_midrun(text)
        return (r.action, r.target) if r else None

    assert action("Show me.") == ("show", None)
    assert action("Hey Swift, show me the draft") == ("show", "email_draft")
    assert action("show the email") == ("show", "email_draft")
    assert action("can you show me what you're doing") == ("show", None)
    assert action("show me the steps") == ("show", "steps")
    assert action("let me see it") == ("show", None)
    assert action("hide that") == ("hide", None)
    assert action("go back") == ("hide", None)
    assert action("stop") == ("stop", None)
    assert action("never mind") == ("cancel", None)
    assert action("show me the weather in Paris") is None
    assert action("send it to Bob instead") is None
    assert action("show me how to fix the test") is None
