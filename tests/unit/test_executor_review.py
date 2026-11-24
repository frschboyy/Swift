"""Executor review (docs/explorations/executor-review.md): what ``_watched`` does to the SDK's stream, and the
executor bugs found there (EX-01..EX-03), each as a strict xfail that asserts the right behaviour. Fakes only."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

import anyio
import pytest
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, PermissionResultDeny
from claude_agent_sdk._internal.query import Query
from claude_agent_sdk.types import ResultMessage, ToolResultBlock, UserMessage
from test_claude_prewarm import FakeClient, make, reset_fake  # noqa: F401 - reset_fake is an autouse fixture

from swift.executors.base import WorkerTask
from swift.executors.claude_code import ClaudeCodeExecutor, _Run

ASSISTANT = {"type": "assistant", "session_id": "x", "message": {"model": "x", "content": [{"type": "text", "text": "{}"}]}}
RESULT = {"type": "result", "subtype": "success", "duration_ms": 1, "duration_api_ms": 1, "is_error": False,
          "num_turns": 1, "session_id": "x", "result": "done"}


def sdk_client() -> tuple[ClaudeSDKClient, Any]:
    """The SDK's own client and receive path (Query.receive_messages over its anyio memory stream), no CLI."""
    query = Query.__new__(Query)
    query._message_send, query._message_receive = anyio.create_memory_object_stream[dict[str, Any]](max_buffer_size=100)
    client = ClaudeSDKClient(ClaudeAgentOptions())
    client._query = query
    return client, query._message_send


def assistant(n: int) -> dict[str, Any]:
    return ASSISTANT | {"message": {"model": "x", "content": [{"type": "text", "text": str(n)}]}}


# ---- _watched and the SDK stream ----------------------------------------------------------------------------


async def test_watched_never_cancels_a_read_while_it_waits_so_no_message_is_lost(tmp_path: Path) -> None:
    """The watchdog wakes about every second (here every 50 ms) with ``asyncio.wait(timeout=)``, which doesn't
    cancel the pending ``__anext__``: across many wake-ups every message arrives, in order, and the stream ends at
    the ResultMessage."""
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", prewarm=False)
    ex.stall_timeout_s = 0.06  # each wait times out after max(0.05, ...) s
    run = _Run()
    run.held = 1  # waiting for the owner: the watchdog keeps waking but never calls it a stall
    client, send = sdk_client()

    async def produce() -> None:
        for n in range(5):
            await asyncio.sleep(0.3)  # about six wake-ups between messages
            await send.send(assistant(n))
        await send.send(RESULT)

    producer = asyncio.create_task(produce())
    got = [m async for m in ex._watched(run, client.receive_response())]
    await producer
    assert [m.content[0].text for m in got[:-1]] == ["0", "1", "2", "3", "4"]
    assert isinstance(got[-1], ResultMessage)


async def test_cancelling_a_pending_read_would_lose_a_message() -> None:
    """Why that matters: anyio 4.15's memory stream drops an item handed to a receiver that is cancelled before it
    resumes, and the cancel also closes the SDK's generator. ``_watched`` cancels only when the run is over (a stall,
    or the run cancelled), and the stream is never read again after that."""
    client, send = sdk_client()
    it = client.receive_response().__aiter__()
    nxt = asyncio.ensure_future(it.__anext__())
    for _ in range(3):
        await asyncio.sleep(0)  # the read is now waiting in MemoryObjectReceiveStream.receive
    send.send_nowait(assistant(1))  # handed to the waiting receiver...
    nxt.cancel()  # ...which is cancelled before it resumes
    with contextlib.suppress(BaseException):
        await nxt
    assert nxt.cancelled()
    with pytest.raises(StopAsyncIteration):
        await it.__anext__()  # the generator is finished
    send.send_nowait(assistant(2))
    send.send_nowait(RESULT)
    again = [m async for m in client.receive_response()]
    assert [getattr(m, "content", [None])[0].text for m in again[:-1]] == ["2"]  # message 1 is gone


async def test_a_stall_ends_the_run_and_cancels_the_read(tmp_path: Path) -> None:
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", prewarm=False)
    ex.stall_timeout_s = 0.1
    client, _send = sdk_client()
    with pytest.raises(Exception, match="no word for"):
        async for _ in ex._watched(_Run(), client.receive_response()):
            pass


# ---- EX-01: a change of mind while the run is finishing is accepted and lost ------------------------------------


class SlowDisconnect(FakeClient):
    """The real CLI takes a while to close (shielded close, process exit): the run is answered but not finished."""

    closing: asyncio.Event
    release: asyncio.Event
    prompts: list[str] = []

    async def query(self, prompt: str) -> None:
        SlowDisconnect.prompts.append(prompt)
        await super().query(prompt)

    async def disconnect(self) -> None:
        SlowDisconnect.closing.set()
        await SlowDisconnect.release.wait()
        await super().disconnect()


@pytest.mark.xfail(strict=True, reason="EX-01: redirect() takes a change after the last turn ended, and drops it")
async def test_a_change_of_mind_while_the_run_closes_is_refused_not_dropped(tmp_path: Path) -> None:
    SlowDisconnect.closing, SlowDisconnect.release, SlowDisconnect.prompts = asyncio.Event(), asyncio.Event(), []
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", client_factory=SlowDisconnect, prewarm=False)
    run_id = await ex.start(WorkerTask("what is in my notes"))
    await SlowDisconnect.closing.wait()  # the answer is in; the CLI is closing
    taken = await ex.redirect(run_id, "actually, only the ones from today")
    SlowDisconnect.release.set()
    result = await ex.result(run_id)
    # Taken means the change runs: the session then logs "passed on in the same session" and shows this result.
    assert not taken or len(SlowDisconnect.prompts) == 2, (taken, result.status, SlowDisconnect.prompts)


# ---- EX-02: the owner asking for a change on a card counts as the model failing ---------------------------------


class Escalations:
    def __init__(self) -> None:
        self.models: list[str | None] = []

    async def set_model(self, model: str | None) -> None:
        self.models.append(model)


@pytest.mark.xfail(strict=True, reason="EX-02: a denied card (change, declined read) is counted as a failed tool call")
async def test_asking_for_a_change_twice_is_not_the_model_struggling(tmp_path: Path) -> None:
    """The module docstring: a result that is the owner asking for a change "isn't a failure". Swift's own tools get
    that (``ToolResult.expected``); Claude Code's own tools' cards don't, so two changes in a row move the run up."""
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", prewarm=False)
    run = _Run(level="standard")
    run.client = Escalations()
    ex._runs["cc-1"] = run
    for n in range(2):
        asked = asyncio.create_task(ex._ask(run, "cc-1", "Bash", {"command": f"git status {n}", "description": "x"}))
        card = await run.queue.get()
        assert await ex.change(card.request_id, "use the other folder")
        denied = await asked
        assert isinstance(denied, PermissionResultDeny) and denied.interrupt is False
        # What the CLI sends back for a denied call: a tool result with is_error (fixture claude_denied_write.jsonl).
        await ex._watch(run, UserMessage([ToolResultBlock(f"t{n}", denied.message, is_error=True)]))
    assert run.escalations == [], run.escalations


# ---- EX-03: a failed mid-run model switch re-sends the request into the same turn -------------------------------


class Unconfirmed(FakeClient):
    prompts: list[str] = []
    refuse_next_switch = True

    async def query(self, prompt: str) -> None:
        Unconfirmed.prompts.append(prompt)
        await super().query(prompt)

    async def set_model(self, model: str | None) -> None:
        if model == "claude-opus-5-5" and Unconfirmed.refuse_next_switch:
            Unconfirmed.refuse_next_switch = False
            raise Exception('Couldn\'t confirm model "claude-opus-5-5" with the API')
        await super().set_model(model)  # type: ignore[arg-type]


@pytest.mark.xfail(strict=True, reason="EX-03: the start-model retry also catches Swift's own escalation mid-turn")
async def test_a_failed_switch_mid_turn_never_sends_the_request_again(tmp_path: Path) -> None:
    Unconfirmed.prompts, Unconfirmed.refuse_next_switch = [], True
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", client_factory=Unconfirmed, prewarm=False,
                            turn_limits={"standard": 1})  # Swift moves the run up after its second step
    run_id = await ex.start(WorkerTask("tidy the notes folder"))
    _ = [e async for e in ex.events(run_id)]
    await ex.result(run_id)
    assert Unconfirmed.prompts == ["tidy the notes folder"], Unconfirmed.prompts


# ---- EX-04: a cancel that lands while the run closes never finishes ---------------------------------------------


async def test_a_cancel_while_the_run_closes_still_finishes_it(tmp_path: Path) -> None:
    SlowDisconnect.closing, SlowDisconnect.release, SlowDisconnect.prompts = asyncio.Event(), asyncio.Event(), []
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", client_factory=SlowDisconnect, prewarm=False)
    run_id = await ex.start(WorkerTask("what is in my notes"))
    await SlowDisconnect.closing.wait()  # answered; disconnect() is in progress (up to 5 s for the real CLI)
    asyncio.get_running_loop().call_later(0.1, SlowDisconnect.release.set)
    await asyncio.wait_for(ex.cancel(run_id), 1.0)  # Esc: waits for the close, which is the honest wait
    assert ex._runs[run_id].finished.is_set()
    assert (await ex.result(run_id)).status == "done"  # it had its answer


async def test_the_task_cancelled_inside_the_close_still_finishes_the_run(tmp_path: Path) -> None:
    """Swift quitting cancels the run's task wherever it is: here, inside ``disconnect()``."""
    SlowDisconnect.closing, SlowDisconnect.release, SlowDisconnect.prompts = asyncio.Event(), asyncio.Event(), []
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", client_factory=SlowDisconnect, prewarm=False)
    run_id = await ex.start(WorkerTask("what is in my notes"))
    await SlowDisconnect.closing.wait()
    run = ex._runs[run_id]
    assert run.task is not None
    run.task.cancel()
    await asyncio.wait_for(run.finished.wait(), 1.0)
