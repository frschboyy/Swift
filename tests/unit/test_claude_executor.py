"""ClaudeCodeExecutor against a fake `claude` process (tests/fixtures/fake_claude.py)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from swift.executors.base import ExecutorUnavailable
from swift.executors.claude_code import ClaudeCodeExecutor

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class FakeClaudeExecutor(ClaudeCodeExecutor):
    """Same flags, but `claude` is replaced by the fake script."""

    def argv(self) -> list[str]:
        real = super().argv()
        return [sys.executable, str(FIXTURES / "fake_claude.py"), *real[1:]]


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def configure(mode: str, **env: str) -> FakeClaudeExecutor:
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
        monkeypatch.setenv("FAKE_CLAUDE_STDIN_OUT", str(tmp_path / "stdin.txt"))
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return FakeClaudeExecutor(cwd=str(tmp_path), claude="claude-not-used", max_budget_usd=0.5)

    return configure


async def collect(ex: ClaudeCodeExecutor, run_id: str) -> list[str]:
    return [e.text async for e in ex.events(run_id)]


async def test_replay_streams_steps_and_result(fake, tmp_path: Path) -> None:
    ex = fake("replay", FAKE_CLAUDE_FIXTURE=str(FIXTURES / "claude_read_only.jsonl"))
    run_id = await ex.start('-p "quoted" request with a leading dash')
    steps = await asyncio.wait_for(collect(ex, run_id), 20)
    result = await ex.result(run_id)

    assert steps[:3] == ["Starting Claude Code…", "Finding files: src/swift/executors/**/*.py", "Reading __init__.py"]
    assert result.status == "done" and result.details["kind"] == "list"
    assert result.meta["turns"] == 6 and result.meta["exit_code"] == 0

    sent, argv = (tmp_path / "stdin.txt").read_text(encoding="utf-8").split("\n--argv--\n")
    assert sent == '-p "quoted" request with a leading dash'  # on stdin, verbatim
    flags = json.loads(argv)
    assert "--permission-mode" in flags and flags[flags.index("--permission-mode") + 1] == "dontAsk"
    assert flags[flags.index("--tools") + 1] == "Read,Glob,Grep" == flags[flags.index("--allowedTools") + 1]
    assert "--max-budget-usd" in flags and "--dangerously-skip-permissions" not in flags
    assert '-p "quoted"' not in argv  # never on the command line


async def test_cancel_kills_the_whole_process_tree(fake, tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    ex = fake("hang", FAKE_CLAUDE_CHILD_PID=str(pid_file))
    run_id = await ex.start("run something long")
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text():
            break
        await asyncio.sleep(0.1)
    child_pid = int(pid_file.read_text())

    await asyncio.wait_for(ex.cancel(run_id), 15)
    result = await ex.result(run_id)
    assert result.status == "cancelled"

    alive = subprocess.run(["tasklist", "/FI", f"PID eq {child_pid}", "/NH"], capture_output=True, text=True).stdout
    assert str(child_pid) not in alive, "the grandchild process survived cancel"


async def test_crash_without_result_reports_stderr(fake) -> None:
    ex = fake("crash")
    run_id = await ex.start("x")
    await asyncio.wait_for(collect(ex, run_id), 20)
    result = await ex.result(run_id)
    assert result.status == "error"
    assert "something broke inside the CLI" in result.summary and result.meta["exit_code"] == 3


async def test_noise_and_huge_lines_are_tolerated(fake) -> None:
    ex = fake("garbage")
    run_id = await ex.start("x")
    await asyncio.wait_for(collect(ex, run_id), 20)
    result = await ex.result(run_id)
    assert result.status == "done" and result.summary == "Survived the noise."


async def test_missing_working_folder_and_cli_are_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ExecutorUnavailable, match="No working folder"):
        await ClaudeCodeExecutor(cwd=None).start("x")
    with pytest.raises(ExecutorUnavailable, match="doesn't exist"):
        await ClaudeCodeExecutor(cwd=str(tmp_path / "nope")).start("x")
    monkeypatch.setattr("swift.executors.claude_code.shutil.which", lambda _name: None)
    with pytest.raises(ExecutorUnavailable, match="isn't installed"):
        await ClaudeCodeExecutor(cwd=str(tmp_path)).start("x")
