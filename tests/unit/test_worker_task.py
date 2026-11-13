"""The ``WorkerTask`` contract: the same tasks on the mock and on Claude Code (handoff §4, groundwork).

Claude Code runs on a fake client here: no CLI starts and nothing is paid for. Each task is one the
mock has a scenario for; the fake plays the same thing through the real executor's permission bridge.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import PermissionResultDeny
from test_claude_executor import sdk_messages

from swift.executors.base import ContextPack, ExecEvent, ExecutorUnavailable, Grant, UnknownRun, WorkerTask
from swift.executors.claude_code import ClaudeCodeExecutor
from swift.executors.echo import EchoExecutor
from swift.executors.improve import ImproveExecutor
from swift.executors.mock import MockExecutor
from swift.executors.providers import CLAUDE_CODE, MOCK, Providers
from swift.executors.signin import SigninExecutor

# The tasks every worker must handle, by the mock scenario that plays each.
SCENARIO = {"answer": "happy", "side_effect": "confirm", "slow": "long"}


class FakeClient:
    """Stands in for ClaudeSDKClient: asks to write a file if the task has a side effect, then answers."""

    prompts: list[str] = []
    made = 0

    def __init__(self, options: Any) -> None:
        self.options = options
        FakeClient.made += 1

    async def connect(self) -> None: ...

    async def set_model(self, model: str) -> None: ...

    async def query(self, prompt: str) -> None:
        FakeClient.prompts.append(prompt)
        self.prompt = prompt

    async def receive_response(self):
        if "[slow]" in self.prompt:
            await asyncio.Event().wait()  # until cancelled
        if "[side_effect]" in self.prompt:
            answer = await self.options.can_use_tool("Write", {"file_path": "notes.md", "content": "hi\n"}, None)
            if isinstance(answer, PermissionResultDeny) and answer.interrupt:
                return
        for message in sdk_messages("claude_read_only.jsonl"):
            yield message

    async def disconnect(self) -> None: ...


class Worker:
    """One executor, started on a task by name."""

    def __init__(self, kind: str, tmp_path: Path) -> None:
        self.kind = kind
        if kind == "mock":
            self.ex: Any = MockExecutor(speed=0)
        else:
            self.ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", client_factory=FakeClient)

    async def start(self, task: WorkerTask, name: str = "answer") -> str:
        if self.kind == "mock":
            self.ex.speed = 0.05 if name == "slow" else 0
            return await self.ex.start(task, scenario=SCENARIO[name])
        return await self.ex.start(WorkerTask(f"{task.request} [{name}]", task.context, task.grant, task.budget, task.privacy))


@pytest.fixture(params=["mock", "claude_code"])
async def worker(request: pytest.FixtureRequest, tmp_path: Path):
    FakeClient.prompts, FakeClient.made = [], 0
    w = Worker(request.param, tmp_path)
    yield w
    if w.kind == "claude_code":
        await w.ex.close()


async def drain(ex: Any, run_id: str, approve: bool | None = None) -> list[ExecEvent]:
    events = []
    async for event in ex.events(run_id):
        events.append(event)
        if event.type == "confirm":
            assert approve is not None, "unexpected confirm"
            await ex.reply(event.request_id, approve)
    return events


async def test_a_task_runs_to_its_answer(worker: Worker) -> None:
    run_id = await worker.start(WorkerTask("What's in the README?"))
    events = await drain(worker.ex, run_id)
    result = await worker.ex.result(run_id)
    assert result.status == "done" and result.summary
    assert not [e for e in events if e.type == "confirm"]


# Until B2, no executor acts on a grant: one listing the very step still gets its card.
@pytest.mark.parametrize("grant", [Grant(), Grant("Write the notes", ("Write notes.md", "Edit notes.md"))])
async def test_a_side_effect_asks_on_a_card_whatever_the_grant(worker: Worker, grant: Grant) -> None:
    run_id = await worker.start(WorkerTask("Write the notes", grant=grant), "side_effect")
    events = await drain(worker.ex, run_id, approve=True)
    [confirm] = [e for e in events if e.type == "confirm"]
    assert confirm.request_id and confirm.tool in {"Write", "Edit"} and confirm.detail
    assert (await worker.ex.result(run_id)).status == "done"


async def test_a_rejected_card_stops_the_task(worker: Worker) -> None:
    run_id = await worker.start(WorkerTask("Write the notes"), "side_effect")
    events = await drain(worker.ex, run_id, approve=False)
    assert events[-1].type == "confirm"
    assert (await worker.ex.result(run_id)).status == "rejected"


async def test_a_cancelled_task_ends_its_events(worker: Worker) -> None:
    run_id = await worker.start(WorkerTask("Research tea"), "slow")
    consumer = asyncio.create_task(drain(worker.ex, run_id))
    await asyncio.sleep(0.05)
    await worker.ex.cancel(run_id)
    await asyncio.wait_for(consumer, 2)
    assert (await worker.ex.result(run_id)).status == "cancelled"


async def test_an_unknown_run_is_refused(worker: Worker) -> None:
    with pytest.raises(UnknownRun):
        await worker.ex.result("nope")


async def test_a_local_only_task_never_reaches_a_cloud_worker(worker: Worker) -> None:
    task = WorkerTask("Summarise my marked file", privacy="local")
    if worker.kind == "mock":  # scripted, on this PC
        run_id = await worker.start(task)
        await drain(worker.ex, run_id)
        assert (await worker.ex.result(run_id)).status == "done"
        return
    with pytest.raises(ExecutorUnavailable):
        await worker.start(task)
    assert FakeClient.made == 0 and FakeClient.prompts == []  # nothing connected, nothing sent


async def test_providers_pass_a_local_only_task_to_a_local_worker(tmp_path: Path) -> None:
    claude = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", client_factory=FakeClient)
    started = await Providers([claude, MockExecutor(speed=0)]).start(WorkerTask("x", privacy="local"))
    assert started.provider is MOCK and [p for p, _ in started.skipped] == [CLAUDE_CODE]


async def test_claude_code_is_sent_the_request_inside_its_context_pack(tmp_path: Path) -> None:
    FakeClient.prompts = []
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", client_factory=FakeClient)
    task = WorkerTask("Reply to Ada", ContextPack("[Previous: Ada's email]\n", ("[Where the user is: Outlook]",)))
    await drain(ex, await ex.start(task))
    await ex.close()
    assert FakeClient.prompts == ["[Previous: Ada's email]\nReply to Ada\n\n[Where the user is: Outlook]"]


def test_the_prompt_keeps_the_order_swift_has_always_sent() -> None:
    # thread + request, then each note after a blank line: the text sent before the WorkerTask existed.
    task = WorkerTask("r", ContextPack("T\n", ("desktop", "unclear", "catalogue")))
    assert task.prompt == "T\nr\n\ndesktop\n\nunclear\n\ncatalogue"
    assert WorkerTask("r").prompt == "r"


def test_a_grant_covers_its_listed_commands_and_never_an_irreversible_one() -> None:
    grant = Grant("Create the repository", ("git init", "gh repo create swift-notes --private"))
    assert grant.covers("git init", irreversible=False)
    assert not grant.covers("git push", irreversible=False)  # outside the step: asks again
    assert not grant.covers("git init", irreversible=True)  # deleting, paying, sending: its own card
    assert not Grant().covers("git init", irreversible=False)  # the default covers nothing


@pytest.mark.parametrize(
    "start",
    [ClaudeCodeExecutor.start, MockExecutor.start, EchoExecutor.start, ImproveExecutor.start, SigninExecutor.start, Providers.start],
)
def test_a_worker_task_is_the_one_way_to_start_a_run(start: Any) -> None:
    params = list(inspect.signature(start).parameters)
    assert params[1] == "task" and not {"request", "demand", "override"} & set(params)
