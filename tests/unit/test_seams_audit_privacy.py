"""Seams audit 2026-11-04 (executors, gateway, contacts, logs): findings reproduced with fakes.

Tests marked ``xfail(strict=True)`` reproduce an open finding: they fail today and pass once it is
fixed (then strict xfail turns them red, so the marker must go). The others pin what holds.
Nothing here touches Google, Claude Code or the network.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
from pathlib import Path
from typing import Any

import pytest
from loguru import logger
from test_routing import Recorder, SpyExecutor, ask

from swift.backend.__main__ import _on_finish
from swift.connectors.base import ConnectorError, Contact
from swift.connectors.fake import FakeMailConnector
from swift.executors.claude_mapping import outcome_for
from swift.executors.mock import MockExecutor
from swift.failures import Failure
from swift.logging_setup import make_patcher
from swift.routing import route
from swift.routing.local import OpenTarget
from swift.runlog import LOCAL_ONLY_FIELDS, SUMMARY_FIELDS, InteractionLog, unclassified
from swift.security.gateway import Action, ActionGateway
from swift.security.journal import Journal
from swift.session import Session
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


def _captured(*, exceptions: bool = False) -> io.StringIO:
    sink = io.StringIO()
    logger.remove()
    logger.configure(patcher=make_patcher(False), extra={"_extra": "", "_exc": ""})
    tail = "{extra[_exc]}\n" if exceptions else ""
    logger.add(sink, format="{message}{extra[_extra]}" + tail, level="INFO", backtrace=False, diagnose=False)
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


# ---- swift.log: what went wrong, without the words (X-05) ------------------------------------------


class _RefusingOpener:
    def launch(self, target: OpenTarget) -> None:
        raise OSError(2, "cannot open", target.path)


async def test_a_failed_open_keeps_the_file_out_of_swift_log() -> None:
    target = OpenTarget("file", "visa interview notes.docx", "C:/Users/owner/Documents/visa interview notes.docx")
    rec, record = Recorder(), {"source": "voice"}
    session = Session(rec, SpyExecutor(), opener=_RefusingOpener())  # type: ignore[arg-type]
    sink = _captured()
    try:
        await session._handle_here(route("open my downloads folder"), record, target)
    finally:
        logger.remove()
    out = sink.getvalue()
    assert "visa interview" not in out, out
    assert "open failed" in out and "FileNotFoundError" in out and "failure shown" in out and "open_failed" in out
    assert "visa interview" in record["error_detail"] and "visa interview" in rec.last("error")["detail"]


async def test_a_model_s_error_text_stays_out_of_swift_log() -> None:
    outcome = outcome_for({"type": "result", "subtype": "success", "is_error": True,
                           "result": "Rate limit reached while writing the letter about the visa interview"})
    assert outcome is not None and outcome.failure is not None and "visa interview" in str(outcome.failure.detail)
    record: dict[str, Any] = {"source": "voice"}
    session = Session(Recorder(), SpyExecutor())
    sink = _captured()
    try:
        await session._send_failure(outcome.failure, record)
    finally:
        logger.remove()
    out = sink.getvalue()
    assert "visa interview" not in out and outcome.failure.code in out, out
    assert "visa interview" in record["error_detail"]


async def test_a_failure_s_text_is_masked_in_the_local_log_too() -> None:
    record: dict[str, Any] = {"source": "voice"}
    await Session(Recorder(), SpyExecutor())._send_failure(
        Failure("rate_limited", "t", "m", "h", detail="rate limit about tea, Authorization: Bearer abcdef123456"), record)
    assert "about tea" in record["error_detail"] and "abcdef123456" not in record["error_detail"]


class _Unprintable(Exception):
    def __str__(self) -> str:
        raise RuntimeError("str failed")


async def test_an_exception_that_can_t_be_printed_still_gets_its_card() -> None:
    class Broken(SpyExecutor):
        async def start(self, *_a: Any, **_k: Any) -> str:
            raise _Unprintable

    rec, spy, records = Recorder(), Broken(), []
    session = Session(rec, spy, debug_executor=MockExecutor(speed=0), on_finish=records.append)
    session._test = (rec, spy, records)  # type: ignore[attr-defined]
    await ask("write a poem about the sea", session)
    assert rec.last("error")["code"] == "internal"
    assert records[0]["status"] == "error" and records[0]["error_detail"].startswith("_Unprintable")


@pytest.mark.parametrize(("failure", "code"), [
    (ConnectorError("Google couldn't do that: GET /people:search?query=visa+interview returned 400"), "connector_failed"),
    (ValueError("bad value: visa+interview"), "ValueError"),
])
async def test_a_failed_action_s_text_stays_out_of_swift_log_and_the_journal(failure: Exception, code: str) -> None:
    journal = Journal(None)
    gateway = ActionGateway(journal)
    scope = _scope_for(ToolHost(None, (), gateway))
    scope.resolved[CHIANU.email] = CHIANU

    async def perform() -> str:
        raise failure

    sink = _captured(exceptions=True)
    try:
        out = await gateway.execute(scope, Action("send_email", (CHIANU,), "Send", "", None, lambda: "d", perform))
    finally:
        logger.remove()
    assert out.status == "failed" and "visa+interview" in out.reason  # what the owner is told is unchanged
    assert "visa+interview" not in sink.getvalue(), sink.getvalue()
    assert journal.entries[-1]["state"] == "FAILED" and journal.entries[-1]["reason"] == code


async def test_an_outcome_nobody_can_confirm_keeps_its_text_out_of_the_journal() -> None:
    journal = Journal(None)
    gateway = ActionGateway(journal)
    scope = _scope_for(ToolHost(None, (), gateway))
    scope.resolved[CHIANU.email] = CHIANU

    async def perform() -> str:
        raise ConnectorError("Lost the connection during /send?subject=visa+interview", code="unknown")

    out = await gateway.execute(scope, Action("send_email", (CHIANU,), "Send", "", None, lambda: "d", perform))
    assert out.status == "unknown" and "visa+interview" in out.reason
    assert journal.entries[-1]["state"] == "UNKNOWN" and journal.entries[-1]["reason"] == "unknown"


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


def test_every_field_written_in_the_source_is_classified() -> None:
    """Beside conftest's check of real records, which can't see a branch no test reaches."""
    root = Path(__file__).resolve().parents[2] / "src" / "swift"
    records = "\n".join((root / name).read_text(encoding="utf-8") for name in ("session.py", "backend/__main__.py"))
    written = {a or b for a, b in re.findall(r'\b(?:record|rec)\["(\w+)"\]\s*(?:=|\+=|,)|\b(?:record|rec)\.setdefault\("(\w+)"', records)}
    meta = "\n".join(path.read_text(encoding="utf-8") for path in (root / "executors").glob("*.py"))
    written |= set(re.findall(r'\bmeta\["(\w+)"\]\s*=', meta))
    for block in re.findall(r'\bmeta(?:\s*\|?=\s*|=)\{(.*?)\}', meta, re.DOTALL):
        written |= set(re.findall(r'"(\w+)":', block))
    assert {"status", "transcript_raw", "asks", "fix", "cost_usd", "start_model", "escalations", "improve"} <= written, (
        "the scan no longer finds what it should")
    assert unclassified(written) == set()
