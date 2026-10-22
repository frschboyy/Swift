"""Runs Claude Code headless and streams its progress (PLAN.md §4).

Per request::

    claude -p --output-format stream-json --verbose
           --tools <allowed> --allowedTools <allowed>
           --permission-mode dontAsk --permission-prompts none
           --strict-mcp-config --no-session-persistence [--max-budget-usd N]

- The request goes in on **stdin**, never argv: no Windows quoting issues, and a
  transcript starting with "-" can't be read as a flag. (With no stdin the CLI
  also waits 3 s for one.)
- ``--tools`` limits which tools exist and ``--allowedTools`` pre-approves them;
  in ``dontAsk`` mode anything else is denied instead of prompting. Milestone 5
  replaces this with real approvals on the overlay.
- Cancel kills the process tree (``taskkill /T /F``): ``claude`` ignores
  CTRL_BREAK on Windows (measured), and nothing is persisted per session anyway.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import shutil
import subprocess
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from swift.executors.base import ExecEvent, ExecResult, ExecutorUnavailable, UnknownRun
from swift.executors.claude_mapping import Outcome, outcome_for, steps_for

LINE_LIMIT = 16 * 1024 * 1024  # tool results can carry whole files on one line
_DONE = object()


@dataclass
class _Run:
    proc: asyncio.subprocess.Process
    queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)
    task: asyncio.Task[None] | None = None
    result: ExecResult | None = None
    cancelled: bool = False
    finished: asyncio.Event = field(default_factory=asyncio.Event)


class ClaudeCodeExecutor:
    name = "claude_code"

    def __init__(
        self,
        cwd: str | None,
        allowed_tools: Sequence[str] = ("Read", "Glob", "Grep"),
        max_budget_usd: float | None = 1.0,
        claude: str | None = None,
        extra_args: Sequence[str] = (),
    ) -> None:
        self.cwd = cwd
        self.allowed_tools = list(allowed_tools)
        self.max_budget_usd = max_budget_usd
        self._claude = claude
        self.extra_args = list(extra_args)
        self._runs: dict[str, _Run] = {}
        self._ids = itertools.count(1)

    def argv(self) -> list[str]:
        tools = ",".join(self.allowed_tools)
        args = [
            self._resolve_claude(),
            "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--tools", tools,
            "--allowedTools", tools,
            "--permission-mode", "dontAsk",
            "--permission-prompts", "none",
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        if self.max_budget_usd is not None:
            args += ["--max-budget-usd", f"{self.max_budget_usd:g}"]
        return args + self.extra_args

    def _resolve_claude(self) -> str:
        path = self._claude or shutil.which("claude")
        if not path:
            raise ExecutorUnavailable(
                "Claude Code isn't installed, or isn't on PATH.",
                "Install Claude Code and run `claude` once in a terminal to sign in, then restart Swift.",
            )
        return path

    def _check_cwd(self) -> str:
        if not self.cwd:
            raise ExecutorUnavailable(
                "No working folder is set for Claude Code.",
                "Add a folder you trust to executor.working_dirs in config.yaml, then restart Swift.",
            )
        if not Path(self.cwd).is_dir():
            raise ExecutorUnavailable(
                f"The working folder doesn't exist: {self.cwd}",
                "Fix executor.working_dirs in config.yaml, then restart Swift.",
            )
        return self.cwd

    async def start(self, request: str) -> str:
        cwd = self._check_cwd()
        argv = self.argv()
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=LINE_LIMIT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        assert proc.stdin is not None
        proc.stdin.write(request.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()

        run_id = f"cc-{next(self._ids)}"
        run = _Run(proc)
        self._runs[run_id] = run
        run.task = asyncio.create_task(self._pump(run))
        logger.info("claude started", run_id=run_id, pid=proc.pid, cwd=cwd)
        return run_id

    async def events(self, run_id: str) -> AsyncIterator[ExecEvent]:
        run = self._get(run_id)
        while True:
            item = await run.queue.get()
            if item is _DONE:
                return
            yield item

    async def cancel(self, run_id: str) -> None:
        run = self._get(run_id)
        if run.finished.is_set():
            return
        run.cancelled = True
        await _kill_tree(run.proc)
        await run.finished.wait()

    async def result(self, run_id: str) -> ExecResult:
        run = self._get(run_id)
        await run.finished.wait()
        assert run.result is not None
        return run.result

    async def reply(self, request_id: str, approve: bool) -> None:
        # No approvals in dontAsk mode; Milestone 5 routes them to the overlay.
        return None

    def _get(self, run_id: str) -> _Run:
        try:
            return self._runs[run_id]
        except KeyError:
            raise UnknownRun(run_id) from None

    async def _pump(self, run: _Run) -> None:
        proc = run.proc
        assert proc.stdout is not None and proc.stderr is not None
        stderr_task = asyncio.create_task(proc.stderr.read())
        outcome: Outcome | None = None
        try:
            while line := await proc.stdout.readline():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                for step in steps_for(event):
                    run.queue.put_nowait(ExecEvent("step", step.text))
                outcome = outcome_for(event) or outcome
            code = await proc.wait()
            stderr = (await stderr_task).decode("utf-8", "replace").strip()
            run.result = self._final(run, outcome, code, stderr)
        except Exception as exc:  # noqa: BLE001 - surface any reader failure as a failed run
            logger.exception("claude output reader failed")
            await _kill_tree(proc)
            run.result = ExecResult("error", f"Swift couldn't read Claude Code's output ({type(exc).__name__}).")
        finally:
            if not stderr_task.done():
                stderr_task.cancel()
            run.finished.set()
            run.queue.put_nowait(_DONE)

    @staticmethod
    def _final(run: _Run, outcome: Outcome | None, code: int, stderr: str) -> ExecResult:
        if run.cancelled:
            return ExecResult("cancelled", "Cancelled.")
        if outcome is not None:
            status = "done" if outcome.status == "done" else "error"
            return ExecResult(status, outcome.summary, outcome.details, outcome.meta | {"exit_code": code})
        last = stderr.splitlines()[-1] if stderr else f"exit code {code}"
        logger.warning("claude ended without a result", exit_code=code)
        return ExecResult("error", f"Claude Code stopped without an answer ({last[:160]}).", meta={"exit_code": code})


async def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/T", "/F", "/PID", str(proc.pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        await killer.wait()
    else:  # pragma: no cover - Swift targets Windows
        proc.kill()
    try:
        await asyncio.wait_for(proc.wait(), 5)
    except TimeoutError:
        proc.kill()
