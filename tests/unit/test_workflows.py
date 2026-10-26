"""Swift's workflow tools, the gateway and the journal (ADR-010 §3-§4). No real email is sent."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from swift.connectors.base import Contact
from swift.connectors.fake import FakeMailConnector
from swift.security.gateway import ActionGateway
from swift.security.journal import Journal
from swift.workflows.artifacts import Artifact, ArtifactStore
from swift.workflows.tools import KnownContact, ToolHost

LECTURER = KnownContact("Dr Ada Lovelace", "ada.lovelace@example.edu", ("lecturer", "my lecturer"))


class Owner:
    """Stands in for the session: collects artifacts and answers confirm cards."""

    def __init__(self, decision: str = "approve") -> None:
        self.decision = decision
        self.artifacts: list[Artifact] = []
        self.asked: list[tuple[str, str, str, str | None]] = []
        self.on_ask: Any = None

    async def publish(self, artifact: Artifact) -> None:
        self.artifacts.append(artifact)

    async def confirm(self, title: str, detail: str, tool: str, artifact_id: str | None) -> str:
        self.asked.append((title, detail, tool, artifact_id))
        if self.on_ask is not None:
            await self.on_ask()
        return self.decision

    def kinds(self) -> list[tuple[str, str]]:
        return [(a.kind, a.phase) for a in self.artifacts]


def make(decision: str = "approve", journal: Journal | None = None, **fake: Any) -> tuple[ToolHost, FakeMailConnector, Owner]:
    mail = FakeMailConnector(contacts=(), **fake)
    host = ToolHost(mail, (LECTURER,), ActionGateway(journal or Journal(None)))
    owner = Owner(decision)
    host.open(owner.publish, owner.confirm)
    return host, mail, owner


async def drafted(host: ToolHost) -> str:
    found = await host.call("find_contact", {"query": "my lecturer"})
    address = found.data["candidates"][0]["email"]
    draft = await host.call("draft_email", {"to": [address], "subject": "Missing Thursday", "body": "Dear Dr Lovelace, ..."})
    assert draft.ok, draft.text
    return draft.data["draft_id"]


async def test_email_workflow_end_to_end() -> None:
    host, mail, owner = make()
    draft_id = await drafted(host)
    sent = await host.call("send_email", {"draft_id": draft_id})
    assert sent.ok and sent.data["message_id"] == "fake-1"
    assert [e.to[0].email for e in mail.sent] == ["ada.lovelace@example.edu"]
    # The confirm card shows the draft itself.
    assert owner.asked == [("Send this email to Dr Ada Lovelace", "Subject: Missing Thursday", "send_email", draft_id)]
    assert owner.kinds() == [
        ("recipient", "resolving"), ("email_draft", "drafting"), ("send_status", "confirming"),
        ("send_status", "sending"), ("send_status", "done"),
    ]
    assert owner.artifacts[-1].data["state"] == "sent" and owner.artifacts[-1].version == 3


async def test_reject_sends_nothing_and_says_so() -> None:
    host, mail, owner = make("reject")
    result = await host.call("send_email", {"draft_id": await drafted(host)})
    assert not result.ok and "NOT sent" in result.text
    assert mail.sent == [] and owner.artifacts[-1].data["state"] == "rejected"


async def test_no_answer_sends_nothing() -> None:
    host, mail, _ = make("no_answer")
    result = await host.call("send_email", {"draft_id": await drafted(host)})
    assert "didn't answer in time" in result.text and mail.sent == []


async def test_an_address_from_the_model_is_never_used() -> None:
    host, mail, _ = make()
    result = await host.call("draft_email", {"to": ["x@evil.example"], "subject": "Hi", "body": "Hello"})
    assert not result.ok and "find_contact" in result.text
    assert mail.sent == []


async def test_gateway_rechecks_the_recipient_at_send() -> None:
    host, mail, owner = make()
    draft_id = await drafted(host)
    assert host.scope is not None
    host.scope.resolved.clear()  # e.g. a draft that outlived the lookup
    result = await host.call("send_email", {"draft_id": draft_id})
    assert "isn't one of the owner's contacts" in result.text
    assert mail.sent == [] and owner.asked == []


async def test_a_draft_changed_after_approval_is_not_sent() -> None:
    host, mail, owner = make()
    draft_id = await drafted(host)

    async def revise() -> None:  # the provider edits the draft while the card is up
        address = "ada.lovelace@example.edu"
        await host.call("draft_email", {"to": [address], "subject": "Changed", "body": "Other", "draft_id": draft_id})

    owner.on_ask = revise
    result = await host.call("send_email", {"draft_id": draft_id})
    assert "changed after the owner approved" in result.text
    assert mail.sent == []


async def test_an_approval_is_used_once() -> None:
    host, mail, _ = make()
    draft_id = await drafted(host)
    assert (await host.call("send_email", {"draft_id": draft_id})).ok
    again = await host.call("send_email", {"draft_id": draft_id})
    assert not again.ok and "already done" in again.text
    assert len(mail.sent) == 1


async def test_no_message_id_is_a_failure_not_sent() -> None:
    journal = Journal(None)
    host, mail, owner = make(journal=journal, no_id=True)
    result = await host.call("send_email", {"draft_id": await drafted(host)})
    assert not result.ok and "didn't confirm" in result.text
    assert owner.artifacts[-1].data["state"] == "failed"
    assert [e["state"] for e in journal.entries] == ["PENDING", "FAILED"]


async def test_connector_failure_is_journalled(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.jsonl")
    host, _, owner = make(journal=journal, fail="Gmail refused the request")
    result = await host.call("send_email", {"draft_id": await drafted(host)})
    assert "Sending failed: Gmail refused" in result.text
    lines = [json.loads(line) for line in (tmp_path / "journal.jsonl").read_text().splitlines()]
    assert [e["state"] for e in lines] == ["PENDING", "FAILED"]
    assert lines[0]["domains"] == ["example.edu"]
    # Metadata only: no body, subject or full address in the journal (T8).
    text = (tmp_path / "journal.jsonl").read_text()
    assert "Dear" not in text and "Missing Thursday" not in text and "ada.lovelace" not in text


def test_pending_actions_are_reported_not_resumed(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    Journal(path).write("a1", "PENDING", tool="send_email")
    Journal(path).write("a2", "PENDING", tool="send_email")
    Journal(path).write("a2", "DONE", receipt="m")
    assert [e["action"] for e in Journal(path).unfinished()] == ["a1"]


async def test_tools_need_an_open_run() -> None:
    host, mail, owner = make()
    assert host.scope is not None
    host.close(host.scope)
    result = await host.call("find_contact", {"query": "lecturer"})
    assert not result.ok and "No Swift run is active" in result.text
    assert owner.artifacts == []


async def test_closing_the_run_mid_confirm_voids_the_send() -> None:
    host, mail, owner = make()
    draft_id = await drafted(host)
    scope = host.scope
    assert scope is not None

    async def end_run() -> None:  # Esc while the card is up
        host.close(scope)

    owner.on_ask = end_run
    result = await host.call("send_email", {"draft_id": draft_id})
    assert not result.ok and "ended" in result.text
    assert mail.sent == []


async def test_find_contact_uses_config_and_connector() -> None:
    host, mail, owner = make()
    mail.contacts = (Contact("Ada Byron", "ada.byron@example.com", "fake"),)
    found = await host.call("find_contact", {"query": "Ada"})
    emails = [c["email"] for c in found.data["candidates"]]
    assert emails == ["ada.lovelace@example.edu", "ada.byron@example.com"]
    assert "Several contacts match" in found.text
    assert owner.artifacts[-1].data["chosen"] is None
    nobody = await host.call("find_contact", {"query": "my dentist"})
    assert not nobody.ok and "Don't guess" in nobody.text


async def test_unknown_tool_and_bad_present() -> None:
    host, _, _ = make()
    assert not (await host.call("delete_everything", {})).ok
    assert not (await host.call("present", {"kind": "video", "title": "x", "data": {}})).ok
    shown = await host.call("present", {"kind": "list", "title": "Results", "data": {"items": ["a", "b"]}})
    assert shown.ok


def test_mcp_shape() -> None:
    from swift.workflows.tools import ToolResult

    out = ToolResult(False, "No.", {"a": 1}).as_mcp()
    assert out["is_error"] is True and out["content"][0]["text"] == 'No.\n{"a": 1}'


def test_show_me_picks_by_phase() -> None:
    store = ArtifactStore()
    assert store.pick() is None
    store.put("recipient", "recipient", "resolving", "", {})
    assert store.pick().kind == "recipient"  # type: ignore[union-attr]
    store.put("draft-1", "email_draft", "drafting", "", {})
    assert store.pick().kind == "email_draft"  # type: ignore[union-attr]
    store.put("send-draft-1", "send_status", "confirming", "", {})
    assert store.pick().kind == "email_draft"  # type: ignore[union-attr]  # the card is about the draft
    store.put("send-draft-1", "send_status", "sending", "", {})
    assert store.pick().kind == "send_status"  # type: ignore[union-attr]
    assert store.pick("recipient").id == "recipient"  # type: ignore[union-attr]
    assert store.pick("table") is None
