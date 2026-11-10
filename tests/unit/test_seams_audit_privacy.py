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
from types import SimpleNamespace
from typing import Any

import pytest
from loguru import logger
from test_routing import Recorder, SpyExecutor, ask

from swift.backend.__main__ import _on_finish
from swift.connectors.base import ConnectorError, Contact
from swift.connectors.fake import FakeMailConnector
from swift.executors.claude_code import ClaudeCodeExecutor, model_unconfirmed
from swift.executors.claude_mapping import outcome_for
from swift.executors.mock import MockExecutor
from swift.failures import Failure, classify, clean_detail
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


# ---- X-07: Swift's own data is never read by the agent, card or not -----------------------------


def test_swift_s_data_folder_is_never_read(tmp_path: Path) -> None:
    from swift.executors.read_scope import ReadScope

    scope = ReadScope([str(tmp_path / "Documents")], home=str(tmp_path))
    data = tmp_path / "AppData" / "Local" / "Swift"
    for name in ("interactions.jsonl", "recordings/clip.wav", "logs/swift.log", "journal.jsonl"):
        assert scope.verdict(str(data / name)) == "never", name
    assert scope.verdict(str(tmp_path / "AppData" / "Local")) == "ask"  # a folder holding it: never a blanket read


def test_a_never_read_path_spelled_another_way_is_still_never_read(tmp_path: Path) -> None:
    from swift.executors.read_scope import ReadScope

    scope = ReadScope([], home=str(tmp_path))
    plain = str(tmp_path / "AppData" / "Local" / "Swift" / "journal.jsonl")
    drive, rest = plain[0], plain[2:]
    for spelled in (rf"\\localhost\{drive.lower()}$" + rest, rf"\\127.0.0.1\{drive}$" + rest, "\\\\?\\" + plain,
                    rf"\\?\UNC\localhost\{drive}$" + rest, plain.replace("\\", "/")):
        assert scope.verdict(spelled) == "never", spelled
    assert scope.verdict(str(tmp_path / ".ssh" / "id_rsa.pub").replace(drive + ":", rf"\\localhost\{drive}$", 1)) == "never"
    assert scope.verdict(r"\\fileserver\c$\notes.txt") == "ask"  # another PC's share is not this one's drive


def test_swift_s_data_is_never_read_wherever_the_settings_put_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from swift.backend.__main__ import _make_executor
    from swift.settings import Settings

    monkeypatch.setenv("SWIFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SWIFT_CONFIG_DIR", str(tmp_path / "config"))
    moved = tmp_path / "elsewhere"
    settings = Settings.model_validate({
        "executor": {"kind": "claude_code", "working_dirs": [str(tmp_path)], "read_dirs": [str(tmp_path)]},
        "logging": {"interactions": str(moved / "talk.jsonl"), "app_log_dir": str(moved / "logs"), "journal": str(moved / "j.jsonl")},
        "stt": {"audio_dir": str(moved / "audio"), "test_set_dir": str(moved / "testset"), "word_fixes_file": str(moved / "fixes.json")},
        "demand_classifier": {"examples_file": str(moved / "examples.jsonl")},
        "system": {"schedule_file": str(moved / "schedule.json")},
    })
    executor = _make_executor(settings, MockExecutor())
    assert isinstance(executor, ClaudeCodeExecutor)
    for path in ("data/recordings/clip.wav", "config/config.yaml", "elsewhere/talk.jsonl", "elsewhere/logs/swift.log",
                 "elsewhere/j.jsonl", "elsewhere/audio/clip.wav", "elsewhere/testset/clip.wav", "elsewhere/fixes.json",
                 "elsewhere/examples.jsonl", "elsewhere/schedule.json"):
        assert executor.reads.verdict(str(tmp_path / path)) == "never", path  # though inside a read folder
    assert executor.reads.verdict(str(tmp_path / "notes.txt")) == "read"


async def test_the_whole_name_said_but_only_another_francis_is_a_contact() -> None:
    # The owner said "Francis Chianu"; the provider searched the first name only (or the directory
    # matched any word); the one contact found is Muthoni, Francis. Today: "Found Muthoni, Francis".
    host = _host("Draft an email to Francis Chianu about lunch", (MUTHONI,))
    found = await host.call("find_contact", {"query": "Francis"})
    assert not found.text.startswith("Found "), found.text


@pytest.mark.parametrize(("said", "contact"), [
    ("Email Francis that I'm running late", MUTHONI),  # nothing else named
    ("Email Francis about lunch", MUTHONI),
    ("Draft an email to Francis Muthoni about lunch", MUTHONI),  # the name said is this contact's
    ("Email Francis Cianu about lunch", CHIANU),  # heard a little wrong, still this contact
    ("Email Francis tomorrow morning", MUTHONI),
])
async def test_one_match_the_owner_named_is_found_without_asking(said: str, contact: Contact) -> None:
    host = _host(said, (contact,))
    found = await host.call("find_contact", {"query": "Francis"})
    assert found.text.startswith("Found "), found.text


def test_another_name_said_after_the_search_is_noticed() -> None:
    from swift.workflows.names import said_otherwise

    assert said_otherwise("Francis", "Draft an email to Francis Chianu about lunch", MUTHONI)
    assert said_otherwise("Francis", "email francis okafor", MUTHONI)
    assert not said_otherwise("Francis", "Draft an email to Francis Chianu", CHIANU)
    assert not said_otherwise("Francis", "Email my colleague", MUTHONI)  # the search isn't in the words said
    assert not said_otherwise("Francis Chianu", "Email Francis Chianu", CHIANU)  # nothing said after it
    # A correction: the name said again, with another surname.
    assert said_otherwise("Francis", "Email Francis, I mean Francis Chianu", MUTHONI)
    assert said_otherwise("Francis", "email Francis no wait Francis Chianu", MUTHONI)


@pytest.mark.parametrize("said", [
    "Email Francis Monday about the trip", "Email Francis these photos", "Send Francis our plan",
    "Email Francis your notes", "Email Francis thanking him", "Email Francis yesterday's slides",
    "Email Francis re the budget", "Email Francis's assistant", "Send Francis the file",
    "Email Francis Chi Anu about lunch",  # the surname heard in two pieces
    "email francis these photos",  # typed without capitals
])
def test_ordinary_words_after_the_name_don_t_make_it_a_guess(said: str) -> None:
    from swift.workflows.names import said_otherwise

    assert not said_otherwise("Francis", said, CHIANU), said


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


# ---- X-08: a few seconds to stop a send; after that it goes, and is journaled as it ends ----------


def _send(grace_s: float, sending_s: float = 0.0, tool: str = "send_email") -> tuple[Any, Any, Journal, list[tuple[str, dict[str, str]]], list[str]]:
    journal = Journal(None)
    gateway = ActionGateway(journal, send_grace_s=grace_s)
    scope = _scope_for(ToolHost(None, (), gateway))
    scope.resolved[CHIANU.email] = CHIANU
    shown: list[tuple[str, dict[str, str]]] = []
    sent: list[str] = []

    async def status(state: str, extra: dict[str, str]) -> None:
        shown.append((state, extra))

    async def perform() -> str:
        await asyncio.sleep(sending_s)  # the service is still busy when the stop comes
        sent.append("id-1")
        return "id-1"

    action = Action(tool, (CHIANU,), "Send", "", None, lambda: "d", perform, on_status=status)  # type: ignore[arg-type]
    return gateway.execute(scope, action), scope, journal, shown, sent


async def test_a_stop_in_the_first_seconds_keeps_the_email() -> None:
    execute, _scope, journal, shown, sent = _send(grace_s=1.0)
    task = asyncio.create_task(execute)
    await asyncio.sleep(0.2)
    assert shown[-1][0] == "sending" and "Say “stop”" in shown[-1][1]["reason"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(1.2)
    assert sent == [] and journal.entries[-1]["state"] == "CANCELLED"
    assert shown[-1] == ("failed", {"reason": "You stopped it in time: it wasn't sent."})


async def test_a_stop_once_it_is_sending_lets_it_finish_and_journals_it_done() -> None:
    execute, scope, journal, shown, sent = _send(grace_s=0.2, sending_s=0.5)
    task = asyncio.create_task(execute)
    await asyncio.sleep(0.4)  # past the grace: the service has it
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sent == ["id-1"] and journal.entries[-1]["state"] == "DONE"
    assert shown[-1][0] == "sent" and scope.done  # shown as sent, and a later change of mind knows it went


async def test_a_service_that_hangs_after_a_stop_doesn_t_keep_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from swift.security import gateway as gateway_module

    monkeypatch.setattr(gateway_module, "LATE_STOP_WAIT_S", 0.3)
    execute, _scope, journal, shown, sent = _send(grace_s=0.1, sending_s=60.0)
    task = asyncio.create_task(execute)
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 3)
    assert sent == [] and journal.entries[-1] == {**journal.entries[-1], "state": "UNKNOWN", "reason": "stopped_while_sending"}
    assert shown[-1] == ("failed", {"reason": "It may have been sent: look in your Sent folder."})


async def test_nobody_stops_it_and_it_goes_after_the_grace() -> None:
    execute, _scope, journal, shown, sent = _send(grace_s=0.2)
    outcome = await execute
    assert outcome.status == "done" and sent == ["id-1"]
    assert [s for s, _ in shown] == ["waiting_approval", "sending", "sending", "sent"]
    assert "reason" not in shown[2][1]  # once it's going, the "say stop" line goes


async def test_only_a_send_that_can_t_be_called_back_waits() -> None:
    execute, *_rest, shown, sent = _send(grace_s=30.0, tool="create_calendar_event")
    outcome = await asyncio.wait_for(execute, 2)
    assert outcome.status == "done" and [s for s, _ in shown] == ["waiting_approval", "sending", "sent"]


def test_the_app_gives_sends_five_seconds(tmp_path: Path) -> None:
    from swift.backend.__main__ import _make_tools
    from swift.settings import Settings

    settings = Settings.model_validate({"debug": True, "logging": {"journal": str(tmp_path / "j.jsonl")}})
    assert _make_tools(settings, None, None).gateway.send_grace_s == 5.0  # type: ignore[arg-type]


async def _stopped_the_sdk_s_way(execute: Any, after_s: float) -> None:
    """A stop as it reaches a tool call: the SDK's anyio cancel scope, which cancels again at every await."""
    import anyio

    scopes: list[Any] = []

    async def call() -> None:
        with anyio.CancelScope() as cancel_scope:
            scopes.append(cancel_scope)
            await execute

    task = asyncio.create_task(call())
    await asyncio.sleep(after_s)
    scopes[0].cancel()
    await asyncio.wait_for(task, 3)


def _yielding(shown: list[tuple[str, dict[str, str]]]) -> Any:
    async def status(state: str, extra: dict[str, str]) -> None:
        await asyncio.sleep(0)  # the real one sends a frame: it yields, so a re-cancel can land here
        shown.append((state, extra))
    return status


def _sdk_send(grace_s: float, sending_s: float = 0.0) -> tuple[Any, Journal, list[tuple[str, dict[str, str]]], list[str]]:
    journal = Journal(None)
    gateway = ActionGateway(journal, send_grace_s=grace_s)
    scope = _scope_for(ToolHost(None, (), gateway))
    scope.resolved[CHIANU.email] = CHIANU
    shown: list[tuple[str, dict[str, str]]] = []
    sent: list[str] = []

    async def perform() -> str:
        await asyncio.sleep(sending_s)
        sent.append("id-1")
        return "id-1"

    action = Action("send_email", (CHIANU,), "Send", "", None, lambda: "d", perform, on_status=_yielding(shown))  # type: ignore[arg-type]
    return gateway.execute(scope, action), journal, shown, sent


async def test_a_stop_in_time_from_the_sdk_still_says_so() -> None:
    execute, journal, shown, sent = _sdk_send(grace_s=1.0)
    await _stopped_the_sdk_s_way(execute, 0.3)
    await asyncio.sleep(1.2)
    assert sent == [] and journal.entries[-1]["state"] == "CANCELLED"
    assert shown[-1] == ("failed", {"reason": "You stopped it in time: it wasn't sent."})


async def test_a_late_stop_from_the_sdk_waits_for_the_send_without_spinning(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from swift.security import gateway as gateway_module

    monkeypatch.setattr(gateway_module, "LATE_STOP_WAIT_S", 0.5)
    execute, journal, shown, _sent = _sdk_send(grace_s=0.1, sending_s=60.0)
    started = time.process_time()
    await _stopped_the_sdk_s_way(execute, 0.3)
    assert time.process_time() - started < 0.4  # waiting, not looping
    assert journal.entries[-1]["state"] == "UNKNOWN"
    assert shown[-1] == ("failed", {"reason": "It may have been sent: look in your Sent folder."})


async def test_a_late_stop_from_the_sdk_lets_a_quick_send_finish() -> None:
    execute, journal, shown, sent = _sdk_send(grace_s=0.1, sending_s=0.4)
    await _stopped_the_sdk_s_way(execute, 0.3)
    assert sent == ["id-1"] and journal.entries[-1]["state"] == "DONE" and shown[-1][0] == "sent"


def _captured(*, exceptions: bool = False) -> io.StringIO:
    sink = io.StringIO()
    logger.remove()
    logger.configure(patcher=make_patcher(False), extra={"_extra": "", "_exc": ""})
    tail = "{extra[_exc]}\n" if exceptions else ""
    logger.add(sink, format="{message}{extra[_extra]}" + tail, level="INFO", backtrace=False, diagnose=False)
    return sink


async def test_a_recipient_s_domain_stays_out_of_swift_log_and_in_the_journal() -> None:
    person = Contact("Ada", "ada@adas-own-domain.example", "gmail")
    journal = Journal(None)
    gateway = ActionGateway(journal)
    scope = _scope_for(ToolHost(None, (), gateway))
    scope.resolved[person.email] = person

    async def perform() -> str:
        return "receipt-1"

    sink = _captured()
    try:
        out = await gateway.execute(scope, Action("send_email", (person,), "Send", "", None, lambda: "d", perform))
    finally:
        logger.remove()
    assert out.status == "done"
    assert "adas-own-domain" not in sink.getvalue() and "action done" in sink.getvalue(), sink.getvalue()
    assert journal.entries[0]["domains"] == ["adas-own-domain.example"]


@pytest.mark.parametrize(("kw", "code"), [
    ({}, "not_a_contact"),  # the address isn't one the owner's contacts gave
    ({"validate": lambda: "Not an email address: someone@evil.example"}, "invalid"),  # the action's own check
])
async def test_a_denied_address_does_not_reach_the_log(kw: dict[str, Any], code: str) -> None:
    sink = _captured()
    try:
        gateway = ActionGateway(Journal(None))
        scope = _scope_for(ToolHost(None, (), gateway))
        stranger = Contact("X", "someone@evil.example")
        out = await gateway.execute(scope, Action("send_email", (stranger,), "Send", "", None, lambda: "d", _none, **kw))  # type: ignore[arg-type]
    finally:
        logger.remove()
    assert out.status == "denied" and "someone@evil.example" in out.reason  # the agent still needs to hear why
    assert "someone@evil.example" not in sink.getvalue(), sink.getvalue()
    assert f"code='{code}'" in sink.getvalue() and "tool='send_email'" in sink.getvalue(), sink.getvalue()


@pytest.mark.parametrize(("kw", "closed", "sent", "code"), [
    ({}, True, False, "run_ended"),
    ({}, False, True, "already_done"),
    ({"tool": "no_such_tool"}, False, False, "no_policy"),
])
async def test_every_other_denial_logs_a_code(kw: dict[str, Any], closed: bool, sent: bool, code: str) -> None:
    gateway = ActionGateway(Journal(None))
    scope = _scope_for(ToolHost(None, (), gateway))
    scope.resolved[CHIANU.email] = CHIANU
    scope.closed = closed
    if sent:
        scope.sent.add("d")
    action = Action(kw.get("tool", "send_email"), (CHIANU,), "Send", "", None, lambda: "d", _none)  # type: ignore[arg-type]
    sink = _captured()
    try:
        out = await gateway.execute(scope, action)
    finally:
        logger.remove()
    assert out.status == "denied" and out.reason
    assert f"code='{code}'" in sink.getvalue() and "reason=" not in sink.getvalue(), sink.getvalue()


async def test_a_denial_with_no_recipient_logs_a_code() -> None:
    gateway = ActionGateway(Journal(None))
    scope = _scope_for(ToolHost(None, (), gateway))
    sink = _captured()
    try:
        out = await gateway.execute(scope, Action("send_email", (), "Send", "", None, lambda: "d", _none))  # type: ignore[arg-type]
    finally:
        logger.remove()
    assert out.status == "denied" and "code='no_recipient'" in sink.getvalue(), sink.getvalue()
    assert "reason=" not in sink.getvalue(), sink.getvalue()


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


def _ended(*, stopped_by: tuple[str, str] | None = None) -> Any:
    return SimpleNamespace(models=[], escalations=[], cancelled=False, stopped_by=stopped_by)


@pytest.mark.parametrize(("error", "name"), [(ValueError(), "ValueError"), (TimeoutError(), "TimeoutError"),
                                             (_Unprintable(), "_Unprintable")])
def test_a_run_s_end_is_classified_whatever_its_exception_can_say(error: Exception, name: str) -> None:
    result = ClaudeCodeExecutor._final(_ended(), None, error)
    assert result.status == "error" and result.failure is not None
    assert result.meta["error_detail"].startswith(name)
    assert not model_unconfirmed(error)


def test_a_rejected_run_keeps_its_exception_s_text() -> None:
    result = ClaudeCodeExecutor._final(_ended(stopped_by=("reject", "Edit")), None, ValueError("about tea"))
    assert result.status == "rejected" and "about tea" in result.meta["error_detail"]


@pytest.mark.parametrize(("text", "code"), [
    ("Bearer token expired", "auth"),
    ("Basic authentication failed", "auth"),
    ("x-api-key: invalid api key", "auth"),
    ("credentials: not logged in", "auth"),
    ("auth: unauthorized", "auth"),
    ("access_token: 403", "auth"),
    ("auth: rate_limit_error", "rate_limited"),
    ("token: 529", "overloaded"),
    ("auth: timeout", "timeout"),
    ("basic network error", "offline"),
])
def test_masking_never_hides_what_a_failure_is(text: str, code: str) -> None:
    assert classify(text, "Claude Code").code == code
    assert ClaudeCodeExecutor._final(_ended(), None, ValueError(text)).failure.code == code  # type: ignore[union-attr]


def test_a_recognised_failure_s_detail_is_still_masked() -> None:
    failure = classify("401 unauthorized, Authorization: Bearer abcdef123456", "Claude Code")
    assert failure.code == "auth" and failure.detail is not None and "abcdef123456" not in failure.detail
    result = ClaudeCodeExecutor._final(_ended(), None, ValueError("no route to host, Bearer abcdef123456"))
    assert "abcdef123456" not in str(result.failure.detail) and "abcdef123456" not in result.meta["error_detail"]  # type: ignore[union-attr]


def test_a_long_secret_is_masked_before_a_detail_is_clipped() -> None:
    token = "eyJ" + "a" * 150 + "." + "b" * 150 + "." + "c" * 150
    detail = clean_detail(f"failed: {token}")
    assert detail is not None and "aaaa" not in detail and "bbbb" not in detail


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
