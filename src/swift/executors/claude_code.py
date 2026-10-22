"""Runs Claude Code headless through the Python Agent SDK (PLAN.md §4, §7 option B).

- **Tools.** ``allowed_tools`` (read-only by default) run without asking.
  ``confirm_tools`` exist but each call goes to ``can_use_tool``, which shows the
  overlay's confirm card and waits for Approve / Reject. No other tool exists.
- **Settings files are ignored** (``setting_sources=[]``): an "allow" rule in the
  owner's Claude settings must not bypass the overlay. ``--strict-mcp-config``
  keeps project MCP servers out; sessions are not persisted.
- **Reject or no answer** within ``confirm_timeout`` denies the call with
  ``interrupt=True``: the run stops and reports ``rejected``.
- ``AskUserQuestion`` is denied (no way to answer it by voice yet).
- **Cancel** stops the SDK query and kills the CLI's process tree: ``claude``
  ignores CTRL_BREAK on Windows (measured), and nothing is persisted anyway.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import os
import shutil
import subprocess
import threading
import warnings
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any

import psutil
from loguru import logger

from swift.executors.base import ExecEvent, ExecResult, ExecutorUnavailable, UnknownRun
from swift.executors.claude_mapping import Outcome, confirm_card, outcome_for, steps_for

_DONE = object()

# Read-only tools are pre-approved on purpose, so can_use_tool never sees them. The SDK
# warns about that when the query starts; match by message so the SDK needn't be imported.
warnings.filterwarnings("ignore", message=r"can_use_tool will not be invoked")

REJECTED_MESSAGE = (
    "The user rejected this action in Swift's voice overlay. Stop here; don't retry it or try a workaround."
)
NO_QUESTIONS_MESSAGE = (
    "The user can't answer questions in this mode. Make a reasonable assumption, "
    "say what you assumed in your final answer, and continue."
)


@dataclass
class _Run:
    queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)
    task: asyncio.Task[None] | None = None
    result: ExecResult | None = None
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    cli_pid: int | None = None
    cancelled: bool = False
    # Set when the user rejects (or doesn't answer) a confirm request.
    stopped_by: tuple[str, str] | None = None  # (decision, title)
    pending: dict[str, asyncio.Future[bool]] = field(default_factory=dict)
    ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))


def as_event(message: Any) -> dict[str, Any] | None:
    """An SDK message as the stream-json dict the mapping understands (None: not needed)."""
    kind = type(message).__name__
    if kind == "SystemMessage":
        return {"type": "system", **message.data, "subtype": message.subtype}
    if kind == "AssistantMessage":
        content = []
        for block in message.content:
            block_kind = type(block).__name__
            if block_kind == "ToolUseBlock":
                content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
            elif block_kind == "TextBlock":
                content.append({"type": "text", "text": block.text})
        return {"type": "assistant", "parent_tool_use_id": message.parent_tool_use_id, "message": {"content": content}}
    if kind == "ResultMessage":
        data = asdict(message) if is_dataclass(message) else dict(vars(message))
        return {"type": "result", **data}
    return None


class ClaudeCodeExecutor:
    name = "claude_code"

    def __init__(
        self,
        cwd: str | None,
        allowed_tools: Sequence[str] = ("Read", "Glob", "Grep"),
        confirm_tools: Sequence[str] = ("Edit", "Write", "Bash"),
        max_budget_usd: float | None = 1.0,
        confirm_timeout_s: float = 120.0,
        claude: str | None = None,
    ) -> None:
        self.cwd = cwd
        self.allowed_tools = list(allowed_tools)
        self.confirm_tools = [t for t in confirm_tools if t not in self.allowed_tools]
        self.max_budget_usd = max_budget_usd
        self.confirm_timeout_s = confirm_timeout_s
        self._claude = claude
        self._runs: dict[str, _Run] = {}
        self._ids = itertools.count(1)

    def prepare(self) -> None:
        """Import the SDK in the background (about 3 s cold), so the first request doesn't pay for it."""
        threading.Thread(target=lambda: __import__("claude_agent_sdk"), name="sdk-import", daemon=True).start()

    # ---- setup checks --------------------------------------------------------

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

    def options(self, run: _Run, run_id: str) -> Any:
        from claude_agent_sdk import ClaudeAgentOptions

        async def can_use_tool(name: str, args: dict[str, Any], context: Any) -> Any:
            return await self._ask(run, run_id, name, args)

        return ClaudeAgentOptions(
            cwd=self._check_cwd(),
            cli_path=self._resolve_claude(),
            tools=[*self.allowed_tools, *self.confirm_tools],
            allowed_tools=list(self.allowed_tools),
            permission_mode="default",
            can_use_tool=can_use_tool,
            setting_sources=[],
            strict_mcp_config=True,
            max_budget_usd=self.max_budget_usd,
            extra_args={"no-session-persistence": None},
        )

    # ---- Executor interface ---------------------------------------------------

    async def start(self, request: str) -> str:
        run_id = f"cc-{next(self._ids)}"
        run = _Run()
        options = self.options(run, run_id)  # raises ExecutorUnavailable before anything starts
        self._runs[run_id] = run
        run.task = asyncio.create_task(self._pump(run, request, options))
        logger.info("claude started", run_id=run_id, cwd=self.cwd)
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
        for future in run.pending.values():
            if not future.done():
                future.set_result(False)
        if run.cli_pid is not None:
            await _kill_tree(run.cli_pid)
        if run.task is not None:
            run.task.cancel()
        await run.finished.wait()

    async def result(self, run_id: str) -> ExecResult:
        run = self._get(run_id)
        await run.finished.wait()
        assert run.result is not None
        return run.result

    async def reply(self, request_id: str, approve: bool) -> None:
        run_id = request_id.split(":", 1)[0]
        run = self._runs.get(run_id)
        future = run.pending.get(request_id) if run else None
        if future is not None and not future.done():
            future.set_result(approve)

    def _get(self, run_id: str) -> _Run:
        try:
            return self._runs[run_id]
        except KeyError:
            raise UnknownRun(run_id) from None

    # ---- permission bridge ----------------------------------------------------

    async def _ask(self, run: _Run, run_id: str, name: str, args: dict[str, Any]) -> Any:
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        if name == "AskUserQuestion":
            return PermissionResultDeny(message=NO_QUESTIONS_MESSAGE)
        title, detail = confirm_card(name, args, cwd=self.cwd)
        request_id = f"{run_id}:{next(run.ids)}"
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        run.pending[request_id] = future
        run.queue.put_nowait(ExecEvent("confirm", title, request_id=request_id, detail=detail, tool=name))
        try:
            approved = await asyncio.wait_for(future, self.confirm_timeout_s)
            decision = "approve" if approved else "reject"
        except TimeoutError:
            approved, decision = False, "no_answer"
        finally:
            run.pending.pop(request_id, None)
        if approved:
            return PermissionResultAllow(updated_input=args)
        if run.stopped_by is None and not run.cancelled:
            run.stopped_by = (decision, title)
        return PermissionResultDeny(message=REJECTED_MESSAGE, interrupt=True)

    # ---- the run --------------------------------------------------------------

    async def _pump(self, run: _Run, request: str, options: Any) -> None:
        from claude_agent_sdk import query

        outcome: Outcome | None = None
        known = _claude_children()
        try:
            async for message in query(prompt=request, options=options):
                if run.cli_pid is None:
                    run.cli_pid = next(iter(_claude_children() - known), None)
                event = as_event(message)
                if event is None:
                    continue
                for step in steps_for(event):
                    run.queue.put_nowait(ExecEvent("step", step.text))
                outcome = outcome_for(event) or outcome
            run.result = self._final(run, outcome, None)
        except asyncio.CancelledError:
            run.result = ExecResult("cancelled", "Cancelled.")
        except Exception as exc:  # noqa: BLE001 - any SDK/CLI failure ends the run with a card
            logger.warning("claude run failed", error=type(exc).__name__, detail=str(exc)[:300])
            run.result = self._final(run, outcome, exc)
        finally:
            if run.cli_pid is not None and psutil.pid_exists(run.cli_pid):
                with contextlib.suppress(Exception):
                    await _kill_tree(run.cli_pid)
            run.finished.set()
            run.queue.put_nowait(_DONE)

    @staticmethod
    def _final(run: _Run, outcome: Outcome | None, error: Exception | None) -> ExecResult:
        meta = outcome.meta if outcome else {}
        if run.cancelled:
            return ExecResult("cancelled", "Cancelled.", meta=meta)
        if run.stopped_by is not None:
            decision, title = run.stopped_by
            why = "No answer in time" if decision == "no_answer" else "Rejected"
            return ExecResult("rejected", f"{why}: {title}. Claude Code stopped there.", meta=meta | {"stopped_by": decision})
        if outcome is not None:
            status = "done" if outcome.status == "done" else "error"
            return ExecResult(status, outcome.summary, outcome.details, meta)
        detail = f" ({str(error).splitlines()[0][:160]})" if error else ""
        return ExecResult("error", f"Claude Code stopped without an answer{detail}.", meta=meta)


def _claude_children() -> set[int]:
    """PIDs of `claude` processes started by this process (the SDK spawns the CLI)."""
    try:
        return {p.pid for p in psutil.Process().children(recursive=True) if p.name().lower().startswith("claude")}
    except psutil.Error:
        return set()


async def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/T", "/F", "/PID", str(pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        await killer.wait()
    else:  # pragma: no cover - Swift targets Windows
        with contextlib.suppress(psutil.Error):
            psutil.Process(pid).kill()
