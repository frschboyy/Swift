"""ClaudeCodeExecutor pre-warming: one CLI connected ahead of time, replaced after every run."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import PermissionResultAllow
from loguru import logger
from test_claude_executor import sdk_messages

from swift.executors.claude_code import ClaudeCodeExecutor


class FakeClient:
    """Stands in for ClaudeSDKClient: replays a recorded run for whatever it's asked."""

    made: list[FakeClient] = []
    fail_connect = 0  # how many connects fail before they start working
    ask_tool: str | None = None  # call can_use_tool for this tool before answering
    escalate: str | None = None  # ask the executor for a stronger model, with this reason
    executor: Any = None

    def __init__(self, options: Any) -> None:
        self.options = options
        self.prompt: str | None = None
        self.connected = False
        self.disconnected = False
        self.permission: Any = None
        self.models: list[str] = []
        FakeClient.made.append(self)

    async def set_model(self, model: str) -> None:
        self.models.append(model)

    async def connect(self) -> None:
        if FakeClient.fail_connect:
            FakeClient.fail_connect -= 1
            raise ConnectionError("CLI exited")
        self.connected = True

    async def query(self, prompt: str) -> None:
        self.prompt = prompt

    async def receive_response(self):
        if FakeClient.escalate:
            ex = FakeClient.executor
            run_id, run = next((rid, r) for rid, r in ex._runs.items() if r.client is self)
            self.escalation_reply = await ex._escalate(run, run_id, FakeClient.escalate, by="model")
        if FakeClient.ask_tool:
            self.permission = await self.options.can_use_tool(FakeClient.ask_tool, {"file_path": "C:\\p\\a.txt", "content": "x"}, None)
        for message in sdk_messages("claude_read_only.jsonl"):
            yield message

    async def disconnect(self) -> None:
        self.disconnected = True


@pytest.fixture(autouse=True)
def reset_fake() -> None:
    FakeClient.made = []
    FakeClient.fail_connect = 0
    FakeClient.ask_tool = None
    FakeClient.escalate = None


def make(tmp_path: Path, **kw: Any) -> ClaudeCodeExecutor:
    FakeClient.executor = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", client_factory=FakeClient, **kw)
    return FakeClient.executor


async def run_to_end(ex: ClaudeCodeExecutor, text: str) -> tuple[str, list[str]]:
    run_id = await ex.start(text)
    steps = [e.text async for e in ex.events(run_id) if e.type == "step"]
    result = await ex.result(run_id)
    assert result.status == "done"
    return run_id, steps


async def test_a_failed_run_s_text_stays_out_of_swift_log(tmp_path: Path) -> None:
    class Failing(FakeClient):
        async def receive_response(self):
            raise ValueError("the CLI repeated the request: letter about the visa interview")
            yield  # pragma: no cover - makes this a generator, like the real one

    lines: list[str] = []
    sink = logger.add(lambda line: lines.append(str(line)), level="INFO", format="{message} {extra}")
    try:
        ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", client_factory=Failing)
        run_id = await ex.start("write a letter")
        async for _ in ex.events(run_id):
            pass
        result = await ex.result(run_id)
        await ex.close()
    finally:
        logger.remove(sink)
    assert any("claude run failed" in line and "ValueError" in line for line in lines), lines
    assert not any("visa interview" in line for line in lines), lines
    assert result.status == "error" and "visa interview" in str(result.failure.detail)  # type: ignore[union-attr]


async def test_a_failure_after_the_answer_keeps_its_text_for_the_local_log(tmp_path: Path) -> None:
    class FailsLate(FakeClient):
        async def receive_response(self):
            for message in sdk_messages("claude_read_only.jsonl"):
                yield message
            raise ValueError(TEXT)

    TEXT = "exit code 1, about the visa interview, Authorization: Bearer abcdef123456"
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", client_factory=FailsLate)
    run_id = await ex.start("write a letter")
    async for _ in ex.events(run_id):
        pass
    result = await ex.result(run_id)
    await ex.close()
    assert result.status == "done"  # the owner has the answer: no error card
    assert "ValueError" in result.meta["error_detail"] and "visa interview" in result.meta["error_detail"]
    assert "abcdef123456" not in result.meta["error_detail"]


async def test_request_goes_to_the_spare_and_a_new_one_is_connected(tmp_path: Path) -> None:
    ex = make(tmp_path)
    ex.prepare()
    await asyncio.sleep(0.05)
    assert len(FakeClient.made) == 1 and FakeClient.made[0].connected

    _, steps = await run_to_end(ex, "what's in the executors folder?")
    first = FakeClient.made[0]
    assert first.prompt == "what's in the executors folder?" and first.disconnected
    assert "Starting Claude Code…" not in steps

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


async def test_failed_warm_up_falls_back_to_a_cold_start(tmp_path: Path) -> None:
    FakeClient.fail_connect = 1  # the spare fails; the request's own connect works
    ex = make(tmp_path)
    ex.prepare()
    await run_to_end(ex, "hello")
    assert [c.prompt for c in FakeClient.made[:2]] == [None, "hello"]
    await ex.close()


async def test_prewarm_off_never_connects_ahead(tmp_path: Path) -> None:
    ex = make(tmp_path, prewarm=False)
    ex.prepare()
    await asyncio.sleep(0.05)
    assert FakeClient.made == []
    await run_to_end(ex, "hello")
    await asyncio.sleep(0.05)
    assert len(FakeClient.made) == 1  # the request's own client, nothing spare


async def test_close_disconnects_the_waiting_spare(tmp_path: Path) -> None:
    ex = make(tmp_path)
    ex.prepare()
    await asyncio.sleep(0.05)
    await ex.close()
    assert FakeClient.made[0].disconnected
    ex._refill()  # after close, nothing new is started
    assert ex._spare is None


# ---- starting model and escalation (ADR-007) ---------------------------------------


@pytest.mark.parametrize(
    ("demand", "override", "model"),
    [
        ("light", None, "claude-haiku-5-5"),
        ("standard", None, "claude-sonnet-5-5"),
        (None, None, "claude-sonnet-5-5"),
        ("light", "opus", "claude-opus-5-5"),
        ("standard", "haiku", "claude-haiku-5-5"),
    ],
)
async def test_run_starts_on_the_model_for_its_demand(tmp_path: Path, demand: str | None, override: str | None, model: str) -> None:
    ex = make(tmp_path)
    run_id = await ex.start("hello", demand=demand, override=override)
    [_ async for _ in ex.events(run_id)]
    result = await ex.result(run_id)
    assert FakeClient.made[-1].models == [model]
    assert result.meta["start_model"] == model and result.meta["models"] == [model]
    assert "escalations" not in result.meta
    await ex.close()


async def test_model_asking_for_more_moves_the_run_up_one_step(tmp_path: Path) -> None:
    FakeClient.escalate = "needs edits in three files"
    ex = make(tmp_path)
    run_id = await ex.start("refactor it", demand="light")
    steps = [e.text async for e in ex.events(run_id) if e.type == "step"]
    result = await ex.result(run_id)
    client = FakeClient.made[-1]
    assert client.models == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    assert client.escalation_reply.startswith("Switched to Sonnet")
    assert "Switching to Sonnet: needs edits in three files" in steps
    assert result.meta["models"] == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    [esc] = result.meta["escalations"]
    assert esc["to"] == "claude-sonnet-5-5" and esc["by"] == "model" and esc["reason"] == "needs edits in three files"
    await ex.close()


async def test_nothing_above_the_strongest_model(tmp_path: Path) -> None:
    FakeClient.escalate = "harder"
    ex = make(tmp_path)
    run_id = await ex.start("x", override="opus")
    [_ async for _ in ex.events(run_id)]
    assert FakeClient.made[-1].models == ["claude-opus-5-5"]
    assert FakeClient.made[-1].escalation_reply.startswith("You're already on the most capable model")
    await ex.close()


async def test_escalation_off_keeps_the_model(tmp_path: Path) -> None:
    FakeClient.escalate = "harder"
    ex = make(tmp_path, escalation=False)
    run_id = await ex.start("x", demand="light")
    [_ async for _ in ex.events(run_id)]
    assert FakeClient.made[-1].models == ["claude-haiku-5-5"]
    await ex.close()


async def test_confirm_strong_asks_before_opus(tmp_path: Path) -> None:
    FakeClient.escalate = "design decision"
    ex = make(tmp_path, confirm_strong=True)
    run_id = await ex.start("x", demand="standard")
    asked = None
    async for event in ex.events(run_id):
        if event.type == "confirm":
            asked = event
            await ex.reply(event.request_id, False)
    assert asked is not None and asked.text == "Switch to Opus" and asked.tool == "SwitchModel"
    assert FakeClient.made[-1].models == ["claude-sonnet-5-5"]  # declined: stays
    assert (await ex.result(run_id)).status == "done"  # declining a model doesn't stop the run
    await ex.close()


async def test_swift_moves_a_run_up_after_too_many_steps(tmp_path: Path) -> None:
    ex = make(tmp_path, turn_limits={"light": 2})
    run_id = await ex.start("x", demand="light")
    steps = [e.text async for e in ex.events(run_id) if e.type == "step"]
    result = await ex.result(run_id)  # the recorded run makes 5 tool-using steps
    [esc] = result.meta["escalations"]
    assert esc["by"] == "swift" and esc["to"] == "claude-sonnet-5-5" and "more than 2 steps" in esc["reason"]
    assert any(s.startswith("Switching to Sonnet") for s in steps)
    await ex.close()
