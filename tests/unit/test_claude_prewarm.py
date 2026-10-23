"""ClaudeCodeExecutor pre-warming: one CLI connected ahead of time, replaced after every run."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import PermissionResultAllow
from test_claude_executor import sdk_messages

from swift.executors.claude_code import ClaudeCodeExecutor


class FakeClient:
    """Stands in for ClaudeSDKClient: replays a recorded run for whatever it's asked."""

    made: list[FakeClient] = []
    fail_connect = False
    ask_tool: str | None = None  # call can_use_tool for this tool before answering

    def __init__(self, options: Any) -> None:
        self.options = options
        self.prompt: str | None = None
        self.connected = False
        self.disconnected = False
        self.permission: Any = None
        FakeClient.made.append(self)

    async def connect(self) -> None:
        if FakeClient.fail_connect:
            raise ConnectionError("CLI exited")
        self.connected = True

    async def query(self, prompt: str) -> None:
        self.prompt = prompt

    async def receive_response(self):
        if FakeClient.ask_tool:
            self.permission = await self.options.can_use_tool(FakeClient.ask_tool, {"file_path": "C:\\p\\a.txt", "content": "x"}, None)
        for message in sdk_messages("claude_read_only.jsonl"):
            yield message

    async def disconnect(self) -> None:
        self.disconnected = True


@pytest.fixture(autouse=True)
def reset_fake() -> None:
    FakeClient.made = []
    FakeClient.fail_connect = False
    FakeClient.ask_tool = None


def make(tmp_path: Path, **kw: Any) -> ClaudeCodeExecutor:
    return ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", client_factory=FakeClient, **kw)


async def run_to_end(ex: ClaudeCodeExecutor, text: str) -> tuple[str, list[str]]:
    run_id = await ex.start(text)
    steps = [e.text async for e in ex.events(run_id) if e.type == "step"]
    result = await ex.result(run_id)
    assert result.status == "done"
    return run_id, steps


async def test_request_goes_to_the_spare_and_a_new_one_is_connected(tmp_path: Path) -> None:
    ex = make(tmp_path)
    ex.prepare()
    await asyncio.sleep(0.05)
    assert len(FakeClient.made) == 1 and FakeClient.made[0].connected

    _, steps = await run_to_end(ex, "what's in the executors folder?")
    first = FakeClient.made[0]
    assert first.prompt == "what's in the executors folder?" and first.disconnected
    assert steps[0] == "Starting Claude Code…"

    await asyncio.sleep(0.05)
    assert len(FakeClient.made) == 2 and FakeClient.made[1].connected and FakeClient.made[1].prompt is None
    await run_to_end(ex, "second request")
    assert FakeClient.made[1].prompt == "second request"  # each request gets its own CLI
    await ex.close()


async def test_request_waits_for_a_spare_still_connecting(tmp_path: Path) -> None:
    ex = make(tmp_path)
    ex.prepare()  # not awaited: start() must wait for it rather than start cold
    await run_to_end(ex, "hello")
    assert FakeClient.made[0].prompt == "hello"
    await ex.close()


async def test_permission_requests_reach_the_run_the_spare_was_given(tmp_path: Path) -> None:
    FakeClient.ask_tool = "Write"
    ex = make(tmp_path)
    ex.prepare()
    run_id = await ex.start("write a file")
    confirm = None
    async for event in ex.events(run_id):
        if event.type == "confirm":
            confirm = event
            await ex.reply(event.request_id, True)
    assert confirm is not None and confirm.request_id == f"{run_id}:1"
    assert isinstance(FakeClient.made[0].permission, PermissionResultAllow)
    await ex.close()


async def test_failed_warm_up_falls_back_to_a_cold_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClient.fail_connect = True
    cold_prompts: list[str] = []

    async def fake_query(prompt: str, options: Any):
        cold_prompts.append(prompt)
        for message in sdk_messages("claude_read_only.jsonl"):
            yield message

    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    ex = make(tmp_path)
    ex.prepare()
    await run_to_end(ex, "hello")
    assert cold_prompts == ["hello"]
    await ex.close()


async def test_prewarm_off_never_connects_ahead(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_query(prompt: str, options: Any):
        for message in sdk_messages("claude_read_only.jsonl"):
            yield message

    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    ex = make(tmp_path, prewarm=False)
    ex.prepare()
    await run_to_end(ex, "hello")
    await asyncio.sleep(0.05)
    assert FakeClient.made == []


async def test_close_disconnects_the_waiting_spare(tmp_path: Path) -> None:
    ex = make(tmp_path)
    ex.prepare()
    await asyncio.sleep(0.05)
    await ex.close()
    assert FakeClient.made[0].disconnected
    ex._refill()  # after close, nothing new is started
    assert ex._spare is None
