"""Swift's own escalation leaves card revisions and email/calendar runs alone (owner check 5, 2026-10-27).

At 12:55:35 a "use the same contact name" change on a calendar card moved the run to Opus:
the owner's change and rejection came back as tool errors and counted as "tool calls kept failing".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from swift.executors.claude_code import ClaudeCodeExecutor, _Run
from swift.workflows.tools import ToolHost, ToolResult, ToolSpec, _obj


class ToolResultBlock:
    def __init__(self, is_error: bool) -> None:
        self.is_error = is_error


class ToolUseBlock:
    pass


class UserMessage:
    def __init__(self, *errors: bool) -> None:
        self.content = [ToolResultBlock(e) for e in errors]


class AssistantMessage:
    def __init__(self) -> None:
        self.content = [ToolUseBlock()]


class Client:
    def __init__(self) -> None:
        self.models: list[str] = []

    async def set_model(self, model: str) -> None:
        self.models.append(model)


def make(tmp_path: Path, level: str = "standard", **kw: Any) -> tuple[ClaudeCodeExecutor, _Run]:
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", **kw)
    run = _Run(level=level, client=Client())
    ex._runs["cc-1"] = run
    return ex, run


async def test_the_owner_changing_and_rejecting_cards_is_not_failing(tmp_path: Path) -> None:
    ex, run = make(tmp_path)
    run.swift_tools, run.expected = True, 2  # a revise, then a rejection, from Swift's tools
    await ex._watch(run, UserMessage(True))
    await ex._watch(run, UserMessage(True))
    assert run.escalations == [] and run.level == "standard" and run.failures == 0


async def test_tool_calls_that_really_keep_failing_still_move_up(tmp_path: Path) -> None:
    ex, run = make(tmp_path)
    run.swift_tools = True
    await ex._watch(run, UserMessage(True))
    await ex._watch(run, UserMessage(True))
    assert [e["to"] for e in run.escalations] == ["claude-opus-5-5"]
    assert run.escalations[0]["reason"] == "tool calls kept failing"


async def test_a_run_with_swift_tools_isnt_moved_to_opus_for_its_steps(tmp_path: Path) -> None:
    ex, run = make(tmp_path, turn_limits={"light": 2, "standard": 2})
    run.swift_tools = True
    for _ in range(5):
        await ex._watch(run, AssistantMessage())
    assert run.escalations == []


async def test_other_runs_still_move_up_for_their_steps(tmp_path: Path) -> None:
    ex, run = make(tmp_path, turn_limits={"light": 2, "standard": 2})
    for _ in range(3):
        await ex._watch(run, AssistantMessage())
    assert [e["to"] for e in run.escalations] == ["claude-opus-5-5"]


async def test_light_runs_with_swift_tools_can_still_move_to_standard(tmp_path: Path) -> None:
    ex, run = make(tmp_path, level="light", turn_limits={"light": 2, "standard": 2})
    run.swift_tools = True
    for _ in range(6):
        await ex._watch(run, AssistantMessage())
    assert [e["to"] for e in run.escalations] == ["claude-sonnet-5-5"]


async def test_the_tool_bridge_counts_expected_results(tmp_path: Path) -> None:
    async def says_no(host: ToolHost, scope: Any, args: dict[str, Any]) -> ToolResult:
        return ToolResult(False, "The owner rejected it", expected=True)

    host = ToolHost(tools=(ToolSpec("say_no", "", _obj([]), "none", says_no),))

    async def publish(_: Any) -> None:
        return None

    async def confirm(*_: Any) -> str:
        return "approve"

    host.open(publish, confirm)
    ex, run = make(tmp_path, tools=host)
    call = ex._sdk_tool(lambda *_: (lambda fn: fn), host.tools["say_no"], lambda: (run, "cc-1"))
    answer = await call({})
    assert answer["is_error"] and run.expected == 1 and run.swift_tools
