"""The light lane's model call (ADR-007 §10): one question, one short answer, no tools, no session.

``QuickModel.answer`` sends a light-lane request (``swift.routing.light``) to the cheapest
model through the path Swift already has, the Claude Code CLI over the Agent SDK, with
every tool off, no MCP servers, no settings files, no persisted session and one turn. It
uses the owner's existing Claude Code sign-in; Swift adds no credentials.

Starting ``claude`` costs seconds, so one tool-free CLI is connected ahead of time and
waits (like the agent's spare, ``claude_code.py``); each question uses it once and a fresh
one connects behind it, so questions never see each other. Any failure or a slow answer
returns None and the session hands the request to the agent instead: the light lane can
only ever make a request faster, never lose it. Nothing about the question is logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil
from loguru import logger

from swift.executors.claude_code import _claude_children, _kill_tree, cli_pid
from swift.routing.light import PROMPT

DEFAULT_TIMEOUT_S = 20.0


class QuickModel:
    def __init__(
        self,
        model: str = "claude-haiku-5-5",
        *,
        claude_path: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        prewarm: bool = True,
        client_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self.model = model
        self._claude = claude_path
        self.timeout_s = timeout_s
        self.prewarm = prewarm
        self._client_factory = client_factory
        self._spare: asyncio.Task[tuple[Any, int | None] | None] | None = None
        self._closed = False

    def prepare(self) -> None:
        """Connect the first spare CLI (call once the event loop runs)."""
        self._refill()

    async def close(self) -> None:
        self._closed = True
        spare = await self._take()
        if spare is not None:
            await self._discard(*spare)

    def _options(self) -> Any:
        from claude_agent_sdk import ClaudeAgentOptions

        path = self._claude or shutil.which("claude")
        if not path:
            raise RuntimeError("claude isn't on PATH")
        return ClaudeAgentOptions(
            cwd=str(Path.home()),
            cli_path=path,
            model=self.model,
            tools=[],
            allowed_tools=[],
            setting_sources=[],
            strict_mcp_config=True,
            mcp_servers={},
            system_prompt=PROMPT,
            max_turns=1,
            extra_args={"no-session-persistence": None},
        )

    async def _connect(self) -> tuple[Any, int | None]:
        factory = self._client_factory
        if factory is None:
            from claude_agent_sdk import ClaudeSDKClient as factory
        known = _claude_children()
        client = factory(self._options())
        await client.connect()
        return client, cli_pid(client, known)

    async def _connect_spare(self) -> tuple[Any, int | None] | None:
        try:
            return await self._connect()
        except Exception as exc:  # noqa: BLE001 - a failed warm-up only costs speed
            logger.warning("quick model warm-up failed", error=type(exc).__name__)
            return None

    def _refill(self) -> None:
        if self.prewarm and not self._closed and self._spare is None:
            self._spare = asyncio.create_task(self._connect_spare())

    async def _take(self) -> tuple[Any, int | None] | None:
        task, self._spare = self._spare, None
        if task is None:
            return None
        try:
            spare = await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            return None
        if spare is not None and spare[1] is not None and not psutil.pid_exists(spare[1]):
            return None
        return spare

    async def _discard(self, client: Any, pid: int | None) -> None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(client.disconnect(), 5)
        if pid is not None and psutil.pid_exists(pid):
            with contextlib.suppress(Exception):
                await _kill_tree(pid)

    async def answer(self, request: str) -> str | None:
        """The model's short answer, or None (failed, empty or too slow: the agent takes it)."""
        t0 = time.perf_counter()
        spare = await self._take()
        try:
            return await asyncio.wait_for(self._ask(request, spare), self.timeout_s)
        except Exception as exc:  # noqa: BLE001 - TimeoutError, CLI or SDK errors: the agent answers instead
            logger.warning("quick answer failed", error=type(exc).__name__)
            return None
        finally:
            logger.info("quick answer", warm=spare is not None, ms=round((time.perf_counter() - t0) * 1000))
            self._refill()

    async def _ask(self, request: str, spare: tuple[Any, int | None] | None) -> str | None:
        from claude_agent_sdk import AssistantMessage, TextBlock

        client, pid = spare if spare is not None else await self._connect()
        try:
            await client.query(request)
            parts: list[str] = []
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    parts += [b.text for b in message.content if isinstance(b, TextBlock)]
            text = " ".join(" ".join(parts).split())
            return text or None
        finally:
            await self._discard(client, pid)


__all__ = ["QuickModel"]
