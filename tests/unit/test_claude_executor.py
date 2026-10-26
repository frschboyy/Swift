"""ClaudeCodeExecutor (Agent SDK): message adapter, options, the permission bridge, cancel."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import psutil
import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
from claude_agent_sdk._internal.message_parser import parse_message
from test_session import Recorder

from swift.executors.base import ExecEvent, ExecutorUnavailable
from swift.executors.claude_code import _DONE, ClaudeCodeExecutor, _kill_tree, _Run, as_event
from swift.executors.claude_mapping import Outcome, confirm_card, outcome_for, steps_for
from swift.ipc.protocol import Message
from swift.session import Session

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def sdk_messages(name: str) -> list[Any]:
    """A recorded run parsed by the SDK itself (the scrubbed fixture lacks a few required fields)."""
    out = []
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        event.setdefault("session_id", "x")
        if event["type"] == "assistant":
            event["message"].setdefault("model", "x")
        if event["type"] == "result":
            event.setdefault("duration_api_ms", 0)
        message = parse_message(event)
        if message is not None:
            out.append(message)
    return out


def replay(name: str) -> tuple[list[str], Outcome | None]:
    steps, outcome = [], None
    for message in sdk_messages(name):
        event = as_event(message)
        if event is None:
            continue
        steps += [s.text for s in steps_for(event)]
        outcome = outcome_for(event) or outcome
    return steps, outcome


# ---- SDK messages -> overlay ----------------------------------------------------


def test_sdk_messages_map_like_the_raw_stream() -> None:
    steps, outcome = replay("claude_read_only.jsonl")
    assert steps[:5] == [
        "Finding files: src/swift/executors/**/*.py",
        "Reading __init__.py",
        "Reading base.py",
        "Reading mock.py",
        "Reading echo.py",
    ]
    assert outcome is not None and outcome.status == "done" and outcome.details["kind"] == "list"
    assert outcome.meta["turns"] == 6


def test_sdk_denial_maps_to_blocked_step_and_note() -> None:
    steps, outcome = replay("claude_denied_write.jsonl")
    assert "Blocked: Write isn't allowed" in steps
    assert outcome is not None and "(Blocked: Write.)" in outcome.summary


# ---- confirm card wording --------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "args", "title", "detail_part"),
    [
        ("Write", {"file_path": "C:\\p\\notes.md", "content": "# Next steps\n- a\n- b\n"}, "Create or overwrite notes.md", "3 lines into C:\\p\\notes.md"),
        ("Edit", {"file_path": "C:\\p\\a.py", "old_string": "x = 1", "new_string": "x = 2"}, "Edit a.py", "replace \u201cx = 1\u201d with \u201cx = 2\u201d"),
        ("Bash", {"command": "git commit -m 'wip'"}, "Run a command", "git commit -m 'wip'"),
        ("WebFetch", {"url": "https://example.com/x"}, "Fetch example.com", "https://example.com/x"),
    ],
)
def test_confirm_card(name: str, args: dict, title: str, detail_part: str) -> None:
    t, d = confirm_card(name, args)
    assert t == title and detail_part in d and len(d) <= 300


# ---- options sent to the CLI -------------------------------------------------------


def test_options_split_auto_and_confirm_tools_and_ignore_settings(tmp_path: Path) -> None:
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), confirm_tools=("Edit", "Write", "Bash", "Read"), claude="claude.exe")
    opts = ex.options(_Run(), "cc-1")
    escalate = "mcp__swift__request_stronger_model"
    assert opts.tools == ["Read", "Glob", "Grep", "Edit", "Write", "Bash", escalate]  # Read not duplicated
    assert opts.allowed_tools == ["Read", "Glob", "Grep", escalate]
    assert opts.permission_mode == "default" and opts.can_use_tool is not None
    assert opts.setting_sources == [] and opts.strict_mcp_config is True
    assert list(opts.mcp_servers) == ["swift"] and "request_stronger_model" in opts.system_prompt
    plain = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", escalation=False).options(_Run(), "cc-1")
    assert escalate not in plain.tools and plain.mcp_servers == {} and "transcribed" in plain.system_prompt
    assert opts.extra_args == {"no-session-persistence": None}
    assert opts.max_budget_usd == 1.0 and opts.cwd == str(tmp_path)


async def test_swift_tools_are_offered_without_a_claude_prompt(tmp_path: Path) -> None:
    """ADR-010 §3.5: Swift's tools are allowed outright; the gateway's card is the one approval."""
    from claude_agent_sdk import tool

    from swift.connectors.fake import FakeMailConnector
    from swift.workflows.tools import KnownContact, ToolHost

    host = ToolHost(FakeMailConnector(contacts=()), (KnownContact("Dr Ada Lovelace", "ada@example.edu", ("lecturer",)),))
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", tools=host)
    opts = ex.options(_Run(), "cc-1")
    swift_tools = ["mcp__swift__find_contact", "mcp__swift__draft_email", "mcp__swift__send_email", "mcp__swift__present"]
    for name in swift_tools:
        assert name in opts.allowed_tools and name in opts.tools
    assert "mcp__swift__request_stronger_model" in opts.allowed_tools
    assert "never type one yourself" in opts.system_prompt
    no_escalation = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", tools=host, escalation=False)
    assert list(no_escalation.options(_Run(), "cc-1").mcp_servers) == ["swift"]

    # The SDK tool runs the host's tool inside the session's run scope.
    published: list[Any] = []

    async def publish(artifact: Any) -> None:
        published.append(artifact)

    async def confirm(*_: Any) -> str:
        return "approve"

    host.open(publish, confirm)
    find = ex._sdk_tool(tool, host.tools["find_contact"])
    out = await find.handler({"query": "my lecturer"})
    assert out["is_error"] is False and "ada@example.edu" in out["content"][0]["text"]
    assert published[0].kind == "recipient"


def test_setup_problems_are_reported_before_anything_starts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ExecutorUnavailable, match="No working folder"):
        ClaudeCodeExecutor(cwd=None, claude="c").options(_Run(), "cc-1")
    with pytest.raises(ExecutorUnavailable, match="doesn't exist"):
        ClaudeCodeExecutor(cwd=str(tmp_path / "nope"), claude="c").options(_Run(), "cc-1")
    monkeypatch.setattr("swift.executors.claude_code.shutil.which", lambda _name: None)
    with pytest.raises(ExecutorUnavailable, match="isn't installed"):
        ClaudeCodeExecutor(cwd=str(tmp_path)).options(_Run(), "cc-1")


# ---- the permission bridge ----------------------------------------------------------


async def ask_and_answer(ex: ClaudeCodeExecutor, run: _Run, answer: bool | None, name: str = "Write") -> Any:
    args = {"file_path": "C:\\p\\hello.txt", "content": "hi"}
    task = asyncio.create_task(ex._ask(run, "cc-1", name, args))
    event: ExecEvent = await asyncio.wait_for(run.queue.get(), 2)
    assert event.type == "confirm" and event.tool == name and event.request_id == "cc-1:1"
    assert event.text == "Create or overwrite hello.txt"
    if answer is not None:
        await ex.reply(event.request_id, answer)
    return await asyncio.wait_for(task, 3)


async def test_approve_allows_with_the_same_input() -> None:
    ex, run = ClaudeCodeExecutor(cwd=None), _Run()
    ex._runs["cc-1"] = run
    result = await ask_and_answer(ex, run, True)
    assert isinstance(result, PermissionResultAllow) and result.updated_input["file_path"].endswith("hello.txt")
    assert run.stopped_by is None and run.pending == {}


async def test_reject_denies_and_stops_the_run() -> None:
    ex, run = ClaudeCodeExecutor(cwd=None), _Run()
    ex._runs["cc-1"] = run
    result = await ask_and_answer(ex, run, False)
    assert isinstance(result, PermissionResultDeny) and result.interrupt is True
    assert run.stopped_by == ("reject", "Create or overwrite hello.txt")
    final = ex._final(run, Outcome("done", "whatever"), None)
    assert final.status == "rejected" and final.summary.startswith("Rejected: Create or overwrite hello.txt")


async def test_no_answer_times_out_as_a_rejection() -> None:
    ex, run = ClaudeCodeExecutor(cwd=None, confirm_timeout_s=0.1), _Run()
    ex._runs["cc-1"] = run
    result = await ask_and_answer(ex, run, None)
    assert isinstance(result, PermissionResultDeny) and result.interrupt is True
    assert run.stopped_by[0] == "no_answer"
    assert ex._final(run, None, None).summary.startswith("No answer in time")


async def test_questions_are_denied_without_bothering_the_user() -> None:
    ex, run = ClaudeCodeExecutor(cwd=None), _Run()
    result = await ex._ask(run, "cc-1", "AskUserQuestion", {"questions": []})
    assert isinstance(result, PermissionResultDeny) and "assumption" in result.message
    assert run.queue.empty() and run.stopped_by is None


async def test_cancel_while_waiting_for_approval_resolves_it() -> None:
    ex, run = ClaudeCodeExecutor(cwd=None), _Run()
    ex._runs["cc-1"] = run
    run.task = asyncio.create_task(asyncio.sleep(30))
    ask = asyncio.create_task(ex._ask(run, "cc-1", "Bash", {"command": "rm -rf build"}))
    await asyncio.wait_for(run.queue.get(), 2)

    async def finish_when_cancelled() -> None:
        try:
            await run.task  # type: ignore[misc]
        except asyncio.CancelledError:
            run.result = ex._final(run, None, None)
            run.finished.set()

    asyncio.create_task(finish_when_cancelled())
    await asyncio.wait_for(ex.cancel("cc-1"), 3)
    assert isinstance(await asyncio.wait_for(ask, 2), PermissionResultDeny)
    assert (await ex.result("cc-1")).status == "cancelled"


async def test_stale_or_foreign_replies_are_ignored() -> None:
    ex = ClaudeCodeExecutor(cwd=None)
    await ex.reply("cc-9:1", True)
    await ex.reply("garbage", False)


# ---- overlay <-> bridge through a real Session ---------------------------------------


class ScriptedRun(ClaudeCodeExecutor):
    """Executor whose run is scripted: one step, one real permission request, then an answer."""

    def options(self, run: _Run, run_id: str) -> Any:
        return None

    async def _pump(self, run: _Run, request: str, options: Any, spare: Any = None) -> None:
        run_id = next(rid for rid, r in self._runs.items() if r is run)
        try:
            run.queue.put_nowait(ExecEvent("step", "Writing notes.md"))
            decision = await self._ask(run, run_id, "Write", {"file_path": "C:\\p\\notes.md", "content": "hi\n"})
            outcome = Outcome("done", "Wrote notes.md.") if isinstance(decision, PermissionResultAllow) else None
            run.result = self._final(run, outcome, None)
        finally:
            run.finished.set()
            run.queue.put_nowait(_DONE)


@pytest.mark.parametrize(("decision", "status"), [("approve", "done"), ("reject", "rejected")])
async def test_confirm_card_round_trip_through_the_session(decision: str, status: str) -> None:
    from swift.executors.mock import MockExecutor

    out = Recorder()
    records: list[dict[str, Any]] = []
    session = Session(out, ScriptedRun(cwd="unused"), debug_executor=MockExecutor(speed=0), on_finish=records.append)
    await session.handle(Message("debug.ask", {"text": "add hi to notes"}))
    await asyncio.wait_for(out.confirm.wait(), 3)
    request = out.last("confirm.request")
    assert request["title"] == "Create or overwrite notes.md" and request["tool"] == "Write"
    await session.handle(Message("confirm.reply", {"request_id": request["request_id"], "decision": decision}))
    await asyncio.wait_for(session._task, 3)  # type: ignore[arg-type]
    assert out.last("result")["status"] == status
    assert records[0]["approvals"][0]["decision"] == decision and records[0]["status"] == status


# ---- cancel kills the CLI's process tree ---------------------------------------------


async def test_kill_tree_also_kills_grandchildren(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pid_file = tmp_path / "child.pid"
    monkeypatch.setenv("FAKE_CLAUDE_CHILD_PID", str(pid_file))
    proc = subprocess.Popen([sys.executable, str(FIXTURES / "fake_claude.py")])
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text():
            break
        await asyncio.sleep(0.1)
    child = int(pid_file.read_text())
    await _kill_tree(proc.pid)
    proc.wait(10)
    await asyncio.sleep(0.3)
    assert not psutil.pid_exists(child), "the grandchild survived"


def test_card_paths_are_relative_inside_the_working_folder_only() -> None:
    _, inside = confirm_card("Write", {"file_path": r"C:\proj\docs\notes.md", "content": "hi"}, cwd=r"C:\proj")
    _, outside = confirm_card("Write", {"file_path": r"D:\elsewhere\a.txt", "content": "hi"}, cwd=r"C:\proj")
    assert r"into docs\notes.md" in inside
    assert r"D:\elsewhere\a.txt" in outside  # a write outside the project stays conspicuous


async def test_esc_on_the_confirm_card_logs_the_approval_as_cancelled() -> None:
    from swift.executors.mock import MockExecutor

    out = Recorder()
    records: list[dict[str, Any]] = []
    session = Session(out, ScriptedRun(cwd="unused"), debug_executor=MockExecutor(speed=0), on_finish=records.append)
    await session.handle(Message("debug.ask", {"text": "add hi to notes"}))
    await asyncio.wait_for(out.confirm.wait(), 3)
    await session.handle(Message("cancel", {}))
    assert out.last("result")["status"] == "cancelled"
    assert records[0]["approvals"][0]["decision"] == "cancelled"


async def test_web_and_own_tools_follow_the_workflow_grant(tmp_path: Path) -> None:
    """ADR-011 W1: web tools only in workflows that declare them; nothing undeclared, not even with a card."""
    from swift.workflows.scope import Grant
    from swift.workflows.tools import ToolHost

    host = ToolHost()
    ex, run = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", tools=host), _Run()
    ex._runs["cc-1"] = run
    opts = ex.options(run, "cc-1")
    assert "WebSearch" in opts.tools and "WebSearch" not in opts.allowed_tools  # decided per run in _ask

    async def nothing(*_: Any) -> Any:
        return None

    host.open(nothing, nothing)  # an ordinary request: no web
    denied = await ex._ask(run, "cc-1", "WebSearch", {"query": "tea"})
    assert isinstance(denied, PermissionResultDeny) and "isn't available" in denied.message

    research = Grant("research-into-word", frozenset({"desktop_write"}), frozenset({"web.search", "web.fetch"}))
    host.open(nothing, nothing, research)
    assert isinstance(await ex._ask(run, "cc-1", "WebFetch", {"url": "https://example.com"}), PermissionResultAllow)
    bash = await ex._ask(run, "cc-1", "Bash", {"command": "dir"})
    assert isinstance(bash, PermissionResultDeny) and "doesn't allow Bash" in bash.message
    assert run.queue.empty() and run.stopped_by is None  # no card, and the run goes on
    assert ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe").options(_Run(), "cc-1").tools.count("WebSearch") == 0
