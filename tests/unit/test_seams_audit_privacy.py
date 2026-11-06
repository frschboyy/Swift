"""Seams audit 2026-11-04 (executors, gateway, contacts, logs): findings reproduced with fakes.

Tests marked ``xfail(strict=True)`` reproduce an open finding: they fail today and pass once it is
fixed (then strict xfail turns them red, so the marker must go). The others pin what holds.
Nothing here touches Google, Claude Code or the network.
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any

import pytest
from loguru import logger

from swift.backend.__main__ import _on_finish
from swift.connectors.base import Contact
from swift.connectors.fake import FakeMailConnector
from swift.executors.claude_mapping import outcome_for
from swift.logging_setup import make_patcher
from swift.runlog import LOCAL_ONLY_FIELDS, SUMMARY_FIELDS, InteractionLog, unclassified
from swift.security.gateway import Action, ActionGateway
from swift.security.journal import Journal
from swift.workflows.tools import ToolHost

CHIANU = Contact("Francis Chianu", "francis.chianu@example.com", "gmail")
MUTHONI = Contact("Muthoni, Francis (IITA)", "f.muthoni@iita.example", "gmail")
FRANCIS_OTHER = Contact("Francis", "francis@example.org", "gmail_emailed")
OKAFOR = Contact("Janet Okafor", "janet.okafor@uni.example", "gmail")


class AnyWordConnector(FakeMailConnector):
    """A directory that matches a contact when ANY word of the query starts one of its names, as a
    prefix search over several fields can (Google's People search is a prefix search; its multi-word
    behaviour is not documented). The worst case for "Francis Chianu" when Chianu isn't a contact."""

    async def directory(self, query: str) -> list[Contact]:
        words = query.lower().split()
        out = []
        for c in self.contacts:
            names = [w.strip(",()") for w in c.name.lower().split()] + [c.email.split("@")[0]]
            if any(n.startswith(w) for w in words for n in names):
                out.append(c)
        return out


async def _none(*_a: Any, **_k: Any) -> None:
    return None


def _host(said: str, contacts: tuple[Contact, ...], connector: type[FakeMailConnector] = FakeMailConnector) -> ToolHost:
    host = ToolHost(connector(contacts=contacts), (), ActionGateway(Journal(None)))
    scope = host.open(_none, _none)  # type: ignore[arg-type]
    scope.said = said
    return host


def _emails(found: Any) -> list[str]:
    return [c["email"] for c in found.data.get("candidates", [])]


# ---- contacts (#15) ----------------------------------------------------------------------------


async def test_exact_full_name_keeps_only_that_contact_even_with_an_any_word_directory() -> None:
    host = _host("Draft an email to Francis Chianu about lunch", (CHIANU, MUTHONI, FRANCIS_OTHER), AnyWordConnector)
    found = await host.call("find_contact", {"query": "Francis Chianu"})
    assert _emails(found) == [CHIANU.email]


async def test_surname_misheard_slightly_still_finds_the_one_contact() -> None:
    for heard in ("Francis Cianu", "Francis Chanu"):
        host = _host(f"Email {heard} about lunch", (CHIANU, MUTHONI, FRANCIS_OTHER))
        found = await host.call("find_contact", {"query": heard})
        assert _emails(found) == [CHIANU.email], heard
        assert "closest" in found.text  # guessed: the provider is told to ask first


async def test_a_first_name_shared_by_several_offers_them_all() -> None:
    host = _host("Email Francis about lunch", (CHIANU, MUTHONI, FRANCIS_OTHER))
    found = await host.call("find_contact", {"query": "Francis"})
    assert sorted(_emails(found)) == sorted(c.email for c in (CHIANU, MUTHONI, FRANCIS_OTHER))
    assert "Several contacts match" in found.text


async def test_nobody_by_that_name_is_no_match() -> None:
    host = _host("Email Ada Lovelace", (CHIANU, MUTHONI))
    found = await host.call("find_contact", {"query": "Ada Lovelace"})
    assert not found.ok and _emails(found) == []


@pytest.mark.xfail(strict=True, reason="seams audit X-01: one match is never narrowed (names.narrow needs two)")
async def test_the_whole_name_said_but_only_another_francis_is_a_contact() -> None:
    # The owner said "Francis Chianu"; the provider searched the first name only (or the directory
    # matched any word); the one contact found is Muthoni, Francis. Today: "Found Muthoni, Francis".
    host = _host("Draft an email to Francis Chianu about lunch", (MUTHONI,))
    found = await host.call("find_contact", {"query": "Francis"})
    assert not found.text.startswith("Found "), found.text


async def test_full_name_query_with_an_any_word_directory_and_one_wrong_match() -> None:
    host = _host("Draft an email to Francis Chianu about lunch", (MUTHONI, OKAFOR), AnyWordConnector)
    found = await host.call("find_contact", {"query": "Francis Chianu"})
    assert MUTHONI.email not in _emails(found) or "closest" in found.text, found.text


async def test_the_wrong_francis_offered_can_be_drafted_to_because_resolved_means_found() -> None:
    # Design: every candidate find_contact returned is "resolved", so the gateway's T1 check passes
    # for the one the owner didn't mean; only the card's recipient line stands between them.
    host = _host("Email Francis about lunch", (CHIANU, MUTHONI))
    await host.call("find_contact", {"query": "Francis"})
    draft = await host.call("draft_email", {"to": [MUTHONI.email], "subject": "Lunch", "message": "Lunch at one?"})
    assert draft.ok


# ---- the gateway ------------------------------------------------------------------------------


async def _approve(*_a: Any, **_k: Any) -> str:
    return "approve"


def _scope_for(gateway_host: ToolHost) -> Any:
    scope = gateway_host.open(_none, _approve)  # type: ignore[arg-type]
    return scope


@pytest.mark.xfail(strict=True, reason="seams audit X-08: a stop while sending journals FAILED, though it may have gone")
async def test_a_stop_while_the_service_is_sending_is_unknown_not_failed() -> None:
    journal = Journal(None)
    gateway = ActionGateway(journal)
    host = ToolHost(None, (), gateway)
    scope = _scope_for(host)
    scope.resolved[CHIANU.email] = CHIANU
    started = asyncio.Event()

    async def perform() -> str:  # the connector's thread keeps going after the await is cancelled
        started.set()
        await asyncio.sleep(10)
        return "id-1"

    action = Action("send_email", (CHIANU,), "Send", "", None, lambda: "d", perform)
    task = asyncio.create_task(gateway.execute(scope, action))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert journal.entries[-1]["state"] == "UNKNOWN", journal.entries[-1]


def _captured() -> io.StringIO:
    sink = io.StringIO()
    logger.remove()
    logger.configure(patcher=make_patcher(False), extra={"_extra": "", "_exc": ""})
    logger.add(sink, format="{message}{extra[_extra]}", level="INFO")
    return sink


@pytest.mark.xfail(strict=True, reason="seams audit X-04 (B-07 still open): a denied action's reason names the address in swift.log")
async def test_a_denied_address_does_not_reach_the_log() -> None:
    sink = _captured()
    try:
        gateway = ActionGateway(Journal(None))
        scope = _scope_for(ToolHost(None, (), gateway))
        stranger = Contact("X", "someone@evil.example")
        out = await gateway.execute(scope, Action("send_email", (stranger,), "Send", "", None, lambda: "d", _none))  # type: ignore[arg-type]
        assert out.status == "denied"
    finally:
        logger.remove()
    assert "someone@evil.example" not in sink.getvalue()


# ---- swift.log: the interaction summary is an allow-list (X-03) ----------------------------------


def _finish_through_the_real_path(record: dict[str, Any], tmp_path: Path) -> tuple[str, dict[str, Any]]:
    """What swift.log and the local interaction log each get, from the backend's own ``finish``."""
    local = tmp_path / "interactions.jsonl"
    sink = _captured()
    try:
        _on_finish(InteractionLog(local))(record)
    finally:
        logger.remove()
    return sink.getvalue(), json.loads(local.read_text(encoding="utf-8"))


def test_the_interaction_summary_keeps_words_out_of_swift_log(tmp_path: Path) -> None:
    out, kept = _finish_through_the_real_path({
        "source": "voice", "status": "done", "steps": [{"t_ms": 0, "text": "visa interview step"}],
        "transcript": "email francis about the visa interview",
        "transcript_raw": "email francis chanu about the visa interview",
        "target": "visa interview notes.docx",
        "addressed_as": "visa interview",
        "escalations": [{"to": "claude-opus-5-5", "by": "model", "reason": "visa interview letter", "t_ms": 1}],
    }, tmp_path)
    assert "visa interview" not in out, out
    assert "status='done'" in out and "steps=1" in out and "claude-opus-5-5" in out, out
    assert "visa interview" in kept["transcript_raw"] and "visa interview" in kept["escalations"][0]["reason"]


def test_a_field_nobody_has_classified_stays_out_of_swift_log(tmp_path: Path) -> None:
    out, kept = _finish_through_the_real_path({"status": "done", "a_field_added_next_year": "visa interview"}, tmp_path)
    assert "visa interview" not in out and "a_field_added_next_year" not in out, out
    assert kept["a_field_added_next_year"] == "visa interview"


def test_a_field_is_decided_one_way_only() -> None:
    assert SUMMARY_FIELDS.isdisjoint(LOCAL_ONLY_FIELDS)
    assert unclassified(["status", "transcript_raw", "escalations", "a_field_added_next_year"]) == {"a_field_added_next_year"}


def test_a_real_run_s_result_fields_are_classified() -> None:
    """Fakes write the records the session tests see, so conftest's check never meets these."""
    outcome = outcome_for({"type": "result", "subtype": "success", "result": "Done."})
    assert outcome is not None and outcome.meta
    assert unclassified([*outcome.meta, "start_model", "models", "escalations"]) == set()
