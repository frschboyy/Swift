"""Event mapping against real (scrubbed) Claude Code stream-json runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swift.executors.claude_mapping import describe_tool, outcome_for, split_answer, steps_for

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def replay(name: str) -> tuple[list[str], object]:
    steps, outcome = [], None
    for event in load(name):
        steps += [s.text for s in steps_for(event)]
        outcome = outcome_for(event) or outcome
    return steps, outcome


def test_read_only_run_maps_to_readable_steps_and_a_list_result() -> None:
    steps, outcome = replay("claude_read_only.jsonl")
    assert steps[0] == "Starting Claude Code…"
    assert steps[1] == "Finding files: src/swift/executors/**/*.py"
    assert steps[2:6] == ["Reading __init__.py", "Reading base.py", "Reading mock.py", "Reading echo.py"]
    assert all(len(s) <= 80 for s in steps)
    assert outcome.status == "done"
    assert outcome.summary.startswith("The src/swift/executors package")  # markdown backticks removed
    assert outcome.details["kind"] == "list" and len(outcome.details["items"]) == 4
    assert outcome.meta["turns"] == 6 and outcome.meta["cost_usd"] > 0


def test_denied_write_shows_blocked_step_and_note() -> None:
    steps, outcome = replay("claude_denied_write.jsonl")
    assert "Writing hello.txt" in steps
    assert "Blocked: Write isn't allowed" in steps
    assert outcome.status == "done"
    assert "(Blocked: Write.)" in outcome.summary
    assert outcome.meta["denied"] == ["Write"]


def test_unknown_and_noise_events_are_ignored() -> None:
    for event in (
        {"type": "rate_limit_event"},
        {"type": "system", "subtype": "task_summary", "detail": "x"},
        {"type": "system", "subtype": "thinking_tokens"},
        {"type": "stream_event"},
        {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
        {"type": "brand_new_event_2027"},
    ):
        assert steps_for(event) == [] and outcome_for(event) is None


@pytest.mark.parametrize(
    ("name", "args", "text"),
    [
        ("Read", {"file_path": "C:\\a\\b\\notes.md"}, "Reading notes.md"),
        ("Grep", {"pattern": "TODO"}, "Searching for 'TODO'"),
        ("Bash", {"command": "git status"}, "Running `git status`"),
        ("Edit", {"file_path": "C:\\x\\y.py"}, "Editing y.py"),
        ("WebFetch", {"url": "https://example.com/a?b=c"}, "Fetching example.com"),
        ("Task", {"description": "scan tests"}, "Starting a helper: scan tests"),
        ("mcp__github__list_issues", {}, "Using github: list_issues"),
    ],
)
def test_describe_tool(name: str, args: dict, text: str) -> None:
    assert describe_tool(name, args) == text


def test_long_commands_and_text_are_truncated() -> None:
    step = steps_for({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "x" * 500}}]}})
    assert len(step[0].text) <= 80 and step[0].text.endswith("…`")


def test_helper_steps_are_prefixed_and_helper_text_skipped() -> None:
    event = {
        "type": "assistant",
        "parent_tool_use_id": "toolu_parent",
        "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "a.py"}}, {"type": "text", "text": "thinking aloud"}]},
    }
    assert [s.text for s in steps_for(event)] == ["Helper: Reading a.py"]


@pytest.mark.parametrize(
    ("event", "message"),
    [
        ({"type": "result", "subtype": "error_max_budget_usd", "is_error": True}, "spending limit"),
        ({"type": "result", "subtype": "error_max_turns", "is_error": True}, "turn limit"),
        ({"type": "result", "subtype": "success", "is_error": True, "result": "Invalid API key · Please run /login"}, "Invalid API key"),
    ],
)
def test_failed_results(event: dict, message: str) -> None:
    outcome = outcome_for(event)
    assert outcome is not None and outcome.status == "error" and message in outcome.summary


def test_split_answer_paragraphs_and_numbered_lists() -> None:
    summary, details = split_answer("**Tests pass.**\n\n1. protocol: 18\n2. session: 16")
    assert summary == "Tests pass." and details == {"kind": "list", "items": ["protocol: 18", "session: 16"]}
    summary, details = split_answer("Short answer.\n\nMore context here.")
    assert summary == "Short answer." and details == {"kind": "text", "text": "More context here."}
    summary, details = split_answer("\n".join(f"- item {i}" for i in range(9)))
    assert details["items"][-1] == "…and 3 more" and len(details["items"]) == 7
