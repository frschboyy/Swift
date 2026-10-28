"""Runs Claude Code headless through the Python Agent SDK (PLAN.md §4, §7 option B).

- **Tools.** ``allowed_tools`` (read-only by default) run without asking.
  ``confirm_tools`` exist but each call goes to ``can_use_tool``, which shows the
  overlay's confirm card and waits for Approve / Reject. No other tool exists.
- **Settings files are ignored** (``setting_sources=[]``): an "allow" rule in the
  owner's Claude settings must not bypass the overlay. ``--strict-mcp-config``
  keeps project MCP servers out; sessions are not persisted.
- **Reject or no answer** within ``confirm_timeout`` denies the call with
  ``interrupt=True``: the run stops and reports ``rejected``. With ``attention`` set, the
  countdown stops while the owner is away (ADR-014 §4, swift/attention.py).
- ``AskUserQuestion`` is denied (no way to answer it by voice yet).
- **Cancel** stops the SDK query and kills the CLI's process tree: ``claude``
  ignores CTRL_BREAK on Windows (measured), and nothing is persisted anyway.
- **Pre-warming.** Starting ``claude`` takes 5-13 s on the development laptop
  (spikes/latency/claude_startup.py) before the model is even called. With
  ``prewarm`` on, one CLI is connected ahead of time and waits; a request is sent
  to it, and a fresh one is connected after every run, so requests stay as
  independent as before. If the spare isn't usable, the run starts cold.
- **Models (ADR-007).** A run starts on the model for its demand (light: Haiku,
  standard: Sonnet, or an explicit override) and can move up mid-run, keeping
  its context: Claude calls ``request_stronger_model``, or Swift notices it
  struggling (too many steps on one model, tool calls failing). Haiku -> Sonnet
  -> Opus, never down. A Swift tool result that is ``expected`` (the owner rejected a card or
  asked for a change, nobody matched) isn't a failure. A run that uses Swift's tools (email,
  calendar, cards) is short work: Swift moves it to Opus only when its tool calls really keep
  failing, never for its number of steps.
- **Swift's tools (ADR-010).** With a ``ToolHost``, Swift's workflow tools
  (``find_contact``, ``draft_email``, ``send_email``, ``present``) join the in-process
  ``swift`` MCP server and ``allowed_tools``: Claude Code doesn't ask about them,
  because anything with a side effect goes through Swift's gateway and its confirm card.
- **Workflows (ADR-011 W1).** Swift picks the workflow and puts its playbook in the request;
  Claude Code never loads skills itself (``setting_sources=[]``). In a workflow run the tool
  host refuses Swift tools the manifest doesn't declare, and ``can_use_tool`` refuses Claude
  Code's own tools that go through it (Edit, Write, Bash) without a card. Web search and
  fetch are allowed without a card in runs whose workflow declares ``web.search`` /
  ``web.fetch``, and in ordinary requests (no workflow) when ``web`` is on: they only read.
  A workflow that doesn't declare them never gets them.
- **Several runs at once (ADR-013 phase B).** Each run has its own CLI; Swift's tools are
  called with the run's id, so the tool host uses that run's scope.
- **Changing course (ADR-014 §7).** ``redirect`` hands the owner's "actually, …" to a running
  run: an open card takes it as a change; otherwise the current turn is interrupted and the
  change goes in as the next turn of the same session, so what was read so far is kept.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import os
import re
import shutil
import subprocess
import threading
import time
import warnings
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from pathlib import Path
from typing import Any

import psutil
from loguru import logger

from swift.attention import Attention, wait_answer
from swift.executors.base import ExecEvent, ExecResult, ExecutorUnavailable, UnknownRun
from swift.executors.claude_mapping import Outcome, confirm_card, outcome_for, steps_for
from swift.executors.providers import CLAUDE_CODE
from swift.executors.web_scope import DENIED_MESSAGE as NOT_GIVEN_URL_MESSAGE
from swift.executors.web_scope import WebScope, result_text
from swift.failures import classify, clean_detail
from swift.workflows.tools import ToolHost, ToolSpec

_DONE = object()

# Read-only tools are pre-approved on purpose, so can_use_tool never sees them. The SDK
# warns about that when the query starts; match by message so the SDK needn't be imported.
warnings.filterwarnings("ignore", message=r"can_use_tool will not be invoked")

LEVELS = ("light", "standard", "strong")
DEFAULT_MODELS = {"light": "claude-haiku-5-5", "standard": "claude-sonnet-5-5", "strong": "claude-opus-5-5"}
OVERRIDE_LEVEL = {"haiku": "light", "sonnet": "standard", "opus": "strong"}
# Steps (assistant messages that use a tool) on one model before Swift moves the run up.
DEFAULT_TURN_LIMITS = {"light": 8, "standard": 25}
ESCALATE_TOOL = "mcp__swift__request_stronger_model"
WORKFLOW_PROMPT = (
    " Swift has its own tools for the user's accounts and apps (mcp__swift__*). For email, use only them: "
    "find_contact to get an address (never type one yourself), draft_email to write it, then send_email; "
    "Swift shows the user the draft and sends only if they approve. To work in the app the user is in "
    "(write here, open this), use the desktop_* tools. For a timer, reminder, volume, music, dark mode, "
    "Wi-Fi or other PC action the user asked for, use system_action with their words. If a Swift tool says something wasn't "
    "done, don't try another way: say so in your answer."
)
# Claude Code's own tools a workflow can declare: tool -> capability (ADR-011 §7.1).
PROVIDER_TOOLS = {"WebSearch": "web.search", "WebFetch": "web.fetch"}
NOT_IN_WORKFLOW_MESSAGE = (
    "This workflow doesn't allow {tool}, so Swift refused it. Continue with the workflow's own tools."
)
NO_WEB_MESSAGE = "Web access isn't available for this request. Answer without it."
SYSTEM_PROMPT = (
    "You are working for Swift, the user's voice assistant: the user talks to Swift, Swift handed you this "
    "request, and Swift shows your final answer to the user. Answer the request directly; don't introduce "
    "yourself or sign the answer. "
    "The user spoke this request and it was transcribed, so it may contain "
    "recognition errors: read it for what was meant. Keep the final answer short; it is shown on a small card."
)
ESCALATE_PROMPT = (
    " If the request needs more capability than you have (multi-step changes, debugging, design or "
    "judgment calls), call request_stronger_model before attempting it, with a reason of a few words."
)

CHANGE_MESSAGE = (
    "The user didn't approve this as it is, and asked for a change instead: “{text}”. "
    "Apply the change and try again; Swift will ask the user again before it runs."
)
REDIRECT_MESSAGE = (
    "The user changed their mind while you were working: “{text}”. Go on from where you are with this "
    "change: keep what is still useful, drop what no longer fits, and don't repeat what's already done."
)
REJECTED_MESSAGE = (
    "The user rejected this action in Swift's voice overlay. Stop here; don't retry it or try a workaround."
)
NO_QUESTIONS_MESSAGE = (
    "The user can't answer questions in this mode. Make a reasonable assumption, "
    "say what you assumed in your final answer, and continue."
)


@dataclass
class _Spare:
    """A ``claude`` CLI connected ahead of time, waiting for its one request."""

    client: Any
    pid: int | None
    # Filled in when the spare is handed a run, so can_use_tool reaches the right one.
    binding: list[tuple[_Run, str]] = field(default_factory=list)


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
    pending: dict[str, asyncio.Future[bool | str]] = field(default_factory=dict)
    ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))
    # Model state (ADR-007): current level, the connected client, and what happened.
    level: str = "standard"
    client: Any = None
    started: float = field(default_factory=time.monotonic)
    models: list[str] = field(default_factory=list)
    escalations: list[dict[str, Any]] = field(default_factory=list)
    steps_at_level: int = 0
    failures: int = 0
    # Swift tool results not yet seen in the stream that are ``expected``, not failures; and
    # whether the run has called Swift's tools at all.
    expected: int = 0
    swift_tools: bool = False
    # Changes of mind waiting for the next turn (``redirect``).
    redirects: list[str] = field(default_factory=list)
    # The web addresses this run was given: the only ones it may fetch (audit 2026-10, A-03).
    web: WebScope = field(default_factory=WebScope)


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
    provider = CLAUDE_CODE

    def __init__(
        self,
        cwd: str | None,
        allowed_tools: Sequence[str] = ("Read", "Glob", "Grep"),
        confirm_tools: Sequence[str] = ("Edit", "Write", "Bash"),
        max_budget_usd: float | None = 1.0,
        confirm_timeout_s: float = 120.0,
        claude: str | None = None,
        prewarm: bool = True,
        client_factory: Any = None,
        models: dict[str, str] | None = None,
        escalation: bool = True,
        confirm_strong: bool = False,
        turn_limits: dict[str, int] | None = None,
        tools: ToolHost | None = None,
        web: bool = False,
    ) -> None:
        self.cwd = cwd
        # Web search and fetch for ordinary requests ("research the history of tea"): read-only,
        # so no card; workflows still get them only by declaring them (owner checks 2026-10-28).
        self.web = web
        self.allowed_tools = list(allowed_tools)
        self.confirm_tools = [t for t in confirm_tools if t not in self.allowed_tools]
        self.max_budget_usd = max_budget_usd
        self.confirm_timeout_s = confirm_timeout_s
        self._claude = claude
        self._runs: dict[str, _Run] = {}
        self._ids = itertools.count(1)
        self.prewarm = prewarm
        self._client_factory = client_factory
        self.models = DEFAULT_MODELS | (models or {})
        self.escalation = escalation
        self.confirm_strong = confirm_strong
        self.turn_limits = DEFAULT_TURN_LIMITS | (turn_limits or {})
        self.tools = tools
        # Holds confirm cards while the owner is away (set by the backend); None: plain timeout.
        self.attention: Attention | None = None
        self._spare: asyncio.Task[_Spare | None] | None = None
        self._closed = False

    def prepare(self) -> None:
        """Import the SDK in the background (about 3 s cold), then connect a spare CLI.

        Call from the event loop. Neither blocks it.
        """
        if not self.prewarm:
            threading.Thread(target=lambda: __import__("claude_agent_sdk"), name="sdk-import", daemon=True).start()
            return
        self._refill()

    async def close(self) -> None:
        """Disconnect the spare CLI (quitting Swift)."""
        self._closed = True
        spare = await self._take_spare(wait=False)
        if spare is not None:
            await self._discard(spare)

    async def release_spare(self) -> None:
        """Away for a while (ADR-014 §6): free the warm CLI. ``ensure_spare`` brings one back."""
        spare = await self._take_spare(wait=False)
        if spare is not None:
            await self._discard(spare)
            logger.info("claude spare released")

    async def ensure_spare(self) -> None:
        """Have a live warm CLI ready: start one, or replace one that exited while idle."""
        if not self.prewarm or self._closed:
            return
        task = self._spare
        if task is not None and task.done():
            spare = None if task.cancelled() or task.exception() else task.result()
            if spare is None or (spare.pid is not None and not psutil.pid_exists(spare.pid)):
                self._spare = None
                if spare is not None:
                    logger.info("spare claude exited while idle; replacing it")
        self._refill()

    # ---- the spare CLI --------------------------------------------------------

    def _refill(self) -> None:
        if self.prewarm and not self._closed and self._spare is None:
            self._spare = asyncio.create_task(self._connect_spare())

    async def _connect_spare(self) -> _Spare | None:
        """Start and connect a CLI. None if that fails: requests then start cold."""
        t0 = time.perf_counter()
        try:
            await asyncio.to_thread(__import__, "claude_agent_sdk")
            binding: list[tuple[_Run, str]] = []
            options = self._options(lambda: binding[0])
            client, pid = await self._connect(options)
            spare = _Spare(client, pid, binding)
        except ExecutorUnavailable:
            return None  # reported on the first request, as an error card
        except Exception as exc:  # noqa: BLE001 - a failed warm-up only costs speed
            logger.warning("claude warm-up failed", error=type(exc).__name__, detail=str(exc)[:200])
            return None
        logger.info("claude ready", connect_s=round(time.perf_counter() - t0, 2), pid=spare.pid)
        return spare

    async def _connect(self, options: Any) -> tuple[Any, int | None]:
        """Start a CLI and connect a client to it. Returns the client and the CLI's PID."""
        factory = self._client_factory
        if factory is None:
            from claude_agent_sdk import ClaudeSDKClient as factory
        known = _claude_children()
        client = factory(options)
        await client.connect()
        return client, cli_pid(client, known)

    async def _take_spare(self, wait: bool = True) -> _Spare | None:
        """The connected spare, if there is one (waiting for one still connecting if ``wait``)."""
        task, self._spare = self._spare, None
        if task is None:
            return None
        if not task.done() and not wait:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
            return None
        try:
            spare = await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            return None
        if spare is not None and spare.pid is not None and not psutil.pid_exists(spare.pid):
            logger.warning("spare claude exited while idle; starting cold")
            return None
        return spare

    async def _discard(self, spare: _Spare) -> None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(spare.client.disconnect(), 5)
        if spare.pid is not None and psutil.pid_exists(spare.pid):
            with contextlib.suppress(Exception):
                await _kill_tree(spare.pid)

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
        return self._options(lambda: (run, run_id))

    def _options(self, current: Callable[[], tuple[_Run, str]]) -> Any:
        from claude_agent_sdk import ClaudeAgentOptions

        async def can_use_tool(name: str, args: dict[str, Any], context: Any) -> Any:
            run, run_id = current()
            return await self._ask(run, run_id, name, args)

        from claude_agent_sdk import create_sdk_mcp_server, tool

        sdk_tools: list[Any] = []
        system_prompt = SYSTEM_PROMPT
        if self.escalation:

            @tool(
                "request_stronger_model",
                "Continue this request on a more capable model. reason: a few words, e.g. 'multi-file refactor'.",
                {"reason": str},
            )
            async def request_stronger_model(args: dict[str, Any]) -> dict[str, Any]:
                run, run_id = current()
                text = await self._escalate(run, run_id, str(args.get("reason", "")).strip(), by="model")
                return {"content": [{"type": "text", "text": text}]}

            sdk_tools.append(request_stronger_model)
            system_prompt += ESCALATE_PROMPT
        if self.tools is not None:
            sdk_tools += [self._sdk_tool(tool, spec, current) for spec in self.tools.tools.values()]
            system_prompt += WORKFLOW_PROMPT
        mcp_servers = {"swift": create_sdk_mcp_server("swift", tools=sdk_tools)} if sdk_tools else {}
        extra_tools = [f"mcp__swift__{t.name}" for t in sdk_tools]
        # Present in every CLI (it is connected before the request is known), allowed per run in _ask.
        web_tools = [t for t in PROVIDER_TOOLS if t not in self.allowed_tools] if self.tools is not None or self.web else []

        return ClaudeAgentOptions(
            cwd=self._check_cwd(),
            cli_path=self._resolve_claude(),
            tools=[*self.allowed_tools, *self.confirm_tools, *web_tools, *extra_tools],
            allowed_tools=[*self.allowed_tools, *extra_tools],
            permission_mode="default",
            can_use_tool=can_use_tool,
            setting_sources=[],
            strict_mcp_config=True,
            mcp_servers=mcp_servers,
            system_prompt=system_prompt,
            max_budget_usd=self.max_budget_usd,
            extra_args={"no-session-persistence": None},
        )

    def _sdk_tool(self, tool: Any, spec: ToolSpec, current: Callable[[], tuple[_Run, str]] | None = None) -> Any:
        """One of Swift's tools for the in-process MCP server; the host runs it in this run's scope."""
        host = self.tools
        assert host is not None

        async def call(args: dict[str, Any]) -> dict[str, Any]:
            run, run_id = current() if current is not None else (None, None)
            result = await host.call(spec.name, args, run=run_id)
            if run is not None:
                run.swift_tools = True
                run.expected += not result.ok and result.expected
            return result.as_mcp()

        return tool(spec.name, spec.description, spec.schema)(call)

    # ---- Executor interface ---------------------------------------------------

    async def start(self, request: str, *, demand: str | None = None, override: str | None = None) -> str:
        run_id = f"cc-{next(self._ids)}"
        level = OVERRIDE_LEVEL.get(override or "") or (demand if demand in LEVELS else "standard")
        run = _Run(level=level)
        run.web.note_request(request)
        options = self.options(run, run_id)  # raises ExecutorUnavailable before anything starts
        spare = await self._take_spare()
        if spare is not None:
            spare.binding.append((run, run_id))
        self._runs[run_id] = run
        run.task = asyncio.create_task(self._pump(run, request, options, spare))
        logger.info("claude started", run_id=run_id, cwd=self.cwd, warm=spare is not None, model=self.models[level])
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

    async def change(self, request_id: str, text: str) -> bool:
        """The owner asked for a change on a confirm card: Claude Code revises and asks again."""
        run = self._runs.get(request_id.split(":", 1)[0])
        future = run.pending.get(request_id) if run else None
        if future is None or future.done():
            return False
        assert run is not None
        run.web.note_request(text)  # the owner's words
        future.set_result(text)
        return True

    async def redirect(self, run_id: str, text: str) -> bool:
        """The owner changed their mind mid-run ("actually, make it about the deadline"). True if taken."""
        run = self._runs.get(run_id)
        if run is None or run.finished.is_set() or run.cancelled:
            return False
        run.web.note_request(text)
        waiting = [f for f in run.pending.values() if not f.done()]
        if waiting:  # a card is open: the change answers it, and the turn goes on
            waiting[-1].set_result(text)
            return True
        run.redirects.append(text)
        interrupt = getattr(run.client, "interrupt", None)
        if interrupt is not None:
            with contextlib.suppress(Exception):
                await interrupt()  # the turn ends; _pump sends the change as the next one
        return True

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
        host = self.tools
        if name in PROVIDER_TOOLS:
            in_workflow = host is not None and host.in_workflow_for(run_id)
            if (host is not None and host.permits(PROVIDER_TOOLS[name], run_id)) or (self.web and not in_workflow):
                if name == "WebFetch" and not run.web.allows(str(args.get("url", ""))):
                    # An address the model put together could carry what it read to someone else.
                    logger.info("web fetch refused: address not given", run_id=run_id)
                    return PermissionResultDeny(message=NOT_GIVEN_URL_MESSAGE)
                return PermissionResultAllow(updated_input=args)
            return PermissionResultDeny(message=NO_WEB_MESSAGE)
        if host is not None and host.in_workflow_for(run_id):
            # The workflow's manifest lists what it may do; nothing else, not even with a card.
            return PermissionResultDeny(message=NOT_IN_WORKFLOW_MESSAGE.format(tool=name))
        title, detail = confirm_card(name, args, cwd=self.cwd)
        decision = await self._decide(run, run_id, title, detail, name)
        if decision == "approve":
            return PermissionResultAllow(updated_input=args)
        if isinstance(decision, tuple):  # ("change", the owner's words): declined, but the run goes on
            return PermissionResultDeny(message=CHANGE_MESSAGE.format(text=decision[1]), interrupt=False)
        if run.stopped_by is None and not run.cancelled:
            run.stopped_by = (decision, title)
        return PermissionResultDeny(message=REJECTED_MESSAGE, interrupt=True)

    async def _confirm(self, run: _Run, run_id: str, title: str, detail: str, tool: str) -> bool:
        return await self._decide(run, run_id, title, detail, tool) == "approve"

    async def _decide(self, run: _Run, run_id: str, title: str, detail: str, tool: str) -> Any:
        """Show a confirm card and wait: "approve", "reject", "no_answer", or ("change", the owner's words)."""
        request_id = f"{run_id}:{next(run.ids)}"
        future: asyncio.Future[bool | str] = asyncio.get_running_loop().create_future()
        run.pending[request_id] = future
        run.queue.put_nowait(ExecEvent("confirm", title, request_id=request_id, detail=detail, tool=tool))
        try:
            answer = await wait_answer(self.attention, request_id, future, self.confirm_timeout_s)
            if isinstance(answer, str):
                return ("change", answer)
            return "approve" if answer else "reject"
        except TimeoutError:
            return "no_answer"
        finally:
            run.pending.pop(request_id, None)

    # ---- escalation (ADR-007 §6) -----------------------------------------------

    async def _escalate(self, run: _Run, run_id: str, reason: str, by: str) -> str:
        """Move the run one model up. Returns what to tell Claude."""
        if not self.escalation or run.cancelled:
            return "Stay on the current model and do your best."
        index = LEVELS.index(run.level)
        if index + 1 >= len(LEVELS):
            return "You're already on the most capable model. Continue."
        target = LEVELS[index + 1]
        model = self.models[target]
        label = _model_label(model)
        if target == "strong" and self.confirm_strong:
            if not await self._confirm(run, run_id, f"Switch to {label}", reason or "Claude asked for a stronger model.", "SwitchModel"):
                return "The user declined a stronger model. Continue on this one and do your best."
        if run.client is None:
            return "Stay on the current model and do your best."
        await run.client.set_model(model)
        run.level = target
        run.steps_at_level = run.failures = 0
        run.models.append(model)
        run.escalations.append(
            {"to": model, "by": by, "reason": reason[:200], "t_ms": int((time.monotonic() - run.started) * 1000)}
        )
        shown = reason if len(reason) <= 60 else reason[:59].rsplit(" ", 1)[0] + "…"
        text = f"Switching to {label}" + (f": {shown}" if shown else "")
        run.queue.put_nowait(ExecEvent("step", text, activity="switching"))
        logger.info("claude escalated", run_id=run_id, to=model, by=by)
        return f"Switched to {label}. Continue the request."

    async def _watch(self, run: _Run, message: Any) -> None:
        """Swift's own escalation signals: many steps on one model, or tool calls failing twice in a row."""
        kind = type(message).__name__
        if kind == "AssistantMessage":
            if any(type(b).__name__ == "ToolUseBlock" for b in message.content):
                run.steps_at_level += 1
        elif kind == "UserMessage" and isinstance(message.content, list):
            for block in message.content:
                if type(block).__name__ != "ToolResultBlock":
                    continue
                run.web.note(result_text(getattr(block, "content", None)))  # addresses it may fetch next
                if block.is_error and run.expected:
                    run.expected -= 1  # the owner decided, or nobody matched: not the model struggling
                else:
                    run.failures = run.failures + 1 if block.is_error else 0
        limit = self.turn_limits.get(run.level)
        if run.swift_tools and run.level == "standard":
            limit = None  # a card revised a few times is many steps, not a hard request
        run_id = next((rid for rid, r in self._runs.items() if r is run), "?")
        if limit is not None and run.steps_at_level > limit:
            await self._escalate(run, run_id, f"more than {limit} steps on {_model_label(self.models[run.level])}", by="swift")
        elif run.failures >= 2 and run.level != "strong":
            await self._escalate(run, run_id, "tool calls kept failing", by="swift")

    # ---- the run --------------------------------------------------------------

    async def _pump(self, run: _Run, request: str, options: Any, spare: _Spare | None = None) -> None:
        outcome: Outcome | None = None
        try:
            if spare is not None:
                run.client, run.cli_pid = spare.client, spare.pid
            else:
                run.client, run.cli_pid = await self._connect(options)
            model = self.models[run.level]
            retried = False
            try:
                await run.client.set_model(model)
                run.models.append(model)
            except Exception as exc:  # noqa: BLE001 - only the model check is retried
                if not model_unconfirmed(exc):
                    raise
                retried = True
                await self._default_model(run, model)
            while True:
                try:
                    await run.client.query(request)
                    async for message in run.client.receive_response():
                        await self._watch(run, message)
                        event = as_event(message)
                        if event is None:
                            continue
                        for step in steps_for(event):
                            run.queue.put_nowait(
                                ExecEvent("step", step.text, activity=step.activity, subagent=step.subagent)  # type: ignore[arg-type]
                            )
                        outcome = outcome_for(event) or outcome
                except Exception as exc:  # noqa: BLE001 - only the model check is retried
                    if retried or outcome is not None or not model_unconfirmed(exc):
                        raise
                    retried = True
                    await self._default_model(run, run.models[-1] if run.models else model)
                    continue
                if not run.redirects or run.cancelled or run.stopped_by is not None:
                    break
                # The owner changed their mind: the same session, a new turn (ADR-014 §7).
                request = REDIRECT_MESSAGE.format(text="; ".join(run.redirects))
                run.redirects.clear()
                outcome = None
            run.result = self._final(run, outcome, None)
        except asyncio.CancelledError:
            run.result = ExecResult("cancelled", "Cancelled.")
        except Exception as exc:  # noqa: BLE001 - any SDK/CLI failure ends the run with a card
            logger.warning("claude run failed", error=type(exc).__name__, detail=str(exc)[:300])
            run.result = self._final(run, outcome, exc)
        finally:
            if run.client is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(run.client.disconnect(), 5)
            if run.cli_pid is not None and psutil.pid_exists(run.cli_pid):
                with contextlib.suppress(Exception):
                    await _kill_tree(run.cli_pid)
            run.finished.set()
            run.queue.put_nowait(_DONE)
            # One CLI per request: connect the next one now, while the owner reads the result.
            self._refill()

    @staticmethod
    async def _default_model(run: _Run, model: str) -> None:
        """The CLI couldn't confirm Swift's model with the API (owner checks, 2026-10-27): once more
        with the CLI's own default model before the run fails. The model ids stay as configured."""
        logger.warning("claude couldn't confirm its model; trying its default once", model=model)
        run.queue.put_nowait(ExecEvent("step", "Trying again with the default model", activity="switching"))
        await run.client.set_model(None)
        run.models.append("default")

    @staticmethod
    def _final(run: _Run, outcome: Outcome | None, error: Exception | None) -> ExecResult:
        meta = dict(outcome.meta) if outcome else {}
        if run.models:
            meta |= {"start_model": run.models[0], "models": list(run.models)}
        if run.escalations:
            meta["escalations"] = list(run.escalations)
        if run.cancelled:
            return ExecResult("cancelled", "Cancelled.", meta=meta)
        if run.stopped_by is not None:
            decision, title = run.stopped_by
            why = "No answer in time" if decision == "no_answer" else "Rejected"
            return ExecResult("rejected", f"{why}: {title}. Claude Code stopped there.", meta=meta | {"stopped_by": decision})
        if outcome is not None:
            status = "done" if outcome.status == "done" else "error"
            return ExecResult(status, outcome.summary, outcome.details, meta, outcome.failure)
        detail = f" ({str(error).splitlines()[0][:160]})" if error else ""
        summary = f"Claude Code stopped without an answer{detail}."
        # The exception's type often names the cause (CLIConnectionError, TimeoutError).
        raw = f"{type(error).__name__}: {error}" if error else summary
        hints = {"fallback_hint": CLAUDE_CODE.error_hint, "signin_hint": CLAUDE_CODE.signin_hint}
        failure = classify(raw, CLAUDE_CODE.name, **hints)
        if failure.code == "executor_failed":  # no known cause: the CLI went away
            failure = replace(classify(summary, CLAUDE_CODE.name, **hints), detail=clean_detail(raw))
        return ExecResult("error", summary, meta=meta, failure=failure)


_MODEL_UNCONFIRMED = re.compile(r"couldn.?t confirm model|could not confirm model", re.I)


def model_unconfirmed(error: BaseException) -> bool:
    """The CLI's "Couldn't confirm model "…" with the API": its models out of reach, not a bad request."""
    return bool(_MODEL_UNCONFIRMED.search(str(error)))


def _model_label(model: str) -> str:
    """"claude-sonnet-5-5" -> "Sonnet"."""
    for name in ("Opus", "Sonnet", "Haiku", "Fable"):
        if name.lower() in model:
            return name
    return model


def cli_pid(client: Any, known: set[int]) -> int | None:
    """The PID of the CLI this client started: the SDK's own process handle. Only when the SDK doesn't
    say, the one new ``claude`` child since ``known``, and only if there is exactly one: with two CLIs
    starting at once a guess could name the other run's, and ending this run would kill that one
    (owner's log, 2026-10-28 01:52:23; audit 2026-10, A-07)."""
    pid = getattr(getattr(getattr(client, "_transport", None), "_process", None), "pid", None)
    if isinstance(pid, int):
        return pid
    new = _claude_children() - known
    return next(iter(new)) if len(new) == 1 else None


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
