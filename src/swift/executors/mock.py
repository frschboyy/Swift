"""Scripted fake executor for UI development and tests.

Each scenario is a list of script items. ``speed`` scales every delay, so
tests run with ``speed=0``.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from swift.executors.base import ExecEvent, ExecResult, UnknownRun


@dataclass(frozen=True)
class Step:
    text: str
    delay: float = 0.7


@dataclass(frozen=True)
class Confirm:
    title: str
    detail: str
    tool: str
    on_approve: tuple[Step, ...] = ()
    delay: float = 0.5


@dataclass(frozen=True)
class Fail:
    message: str
    delay: float = 0.6


@dataclass(frozen=True)
class Finish:
    summary: str
    details: dict[str, Any] | None = None
    delay: float = 0.5


ScriptItem = Step | Confirm | Fail | Finish

SCENARIOS: dict[str, tuple[ScriptItem, ...]] = {
    "happy": (
        Step("Starting Claude Code…", 0.4),
        Step("Reading README.md"),
        Step("Searching for 'TODO'"),
        Step("Reading src/swift/session.py"),
        Finish(
            "Found 3 open TODOs across 2 files.",
            {"kind": "list", "items": ["session.py: handle mic unplug", "session.py: retry STT once", "README: setup steps"]},
        ),
    ),
    "confirm": (
        Step("Starting Claude Code…", 0.4),
        Step("Reading notes.md"),
        Confirm(
            title="Edit notes.md",
            detail="Append a 'Next steps' section (4 lines) to notes.md",
            tool="Edit",
            on_approve=(Step("Editing notes.md"), Step("Verifying the change")),
        ),
        Finish("Added a 'Next steps' section to notes.md."),
    ),
    "error": (
        Step("Starting Claude Code…", 0.4),
        Step("Reading package.json"),
        Fail("Claude Code exited with code 1."),
    ),
    "long": (
        Step("Starting Claude Code…", 0.4),
        *(Step(text, 0.9) for text in (
            "Listing files in src/",
            "Reading config.yaml",
            "Reading src/swift/ipc/protocol.py",
            "Reading src/swift/session.py",
            "Searching for 'async def'",
            "Reading tests/unit/test_protocol.py",
            "Running pytest -q",
            "Reading the test output",
            "Comparing with PLAN.md",
        )),
        Finish(
            "Tests pass: 42 passed, 0 failed.",
            {"kind": "table", "columns": ["Suite", "Passed", "Failed"],
             "rows": [["protocol", "18", "0"], ["session", "16", "0"], ["mock", "8", "0"]]},
        ),
    ),
}

_DONE = object()


@dataclass
class _Run:
    queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)
    task: asyncio.Task[None] | None = None
    result: ExecResult | None = None
    finished: asyncio.Event = field(default_factory=asyncio.Event)


class MockExecutor:
    name = "mock"

    def __init__(self, speed: float = 1.0, default_scenario: str = "happy") -> None:
        self.speed = speed
        self.default_scenario = default_scenario
        self._runs: dict[str, _Run] = {}
        self._pending: dict[str, asyncio.Future[bool]] = {}
        self._ids = itertools.count(1)

    async def start(
        self, request: str, scenario: str | None = None, *, demand: str | None = None, override: str | None = None
    ) -> str:
        script = SCENARIOS[scenario or self.default_scenario]
        run_id = f"mock-{next(self._ids)}"
        run = _Run()
        self._runs[run_id] = run
        run.task = asyncio.create_task(self._play(run_id, run, script))
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
        if run.task is not None and not run.task.done():
            run.task.cancel()
            try:
                await run.task
            except asyncio.CancelledError:
                pass

    async def result(self, run_id: str) -> ExecResult:
        run = self._get(run_id)
        await run.finished.wait()
        assert run.result is not None
        return run.result

    async def reply(self, request_id: str, approve: bool) -> None:
        future = self._pending.get(request_id)
        if future is not None and not future.done():
            future.set_result(approve)

    def _get(self, run_id: str) -> _Run:
        try:
            return self._runs[run_id]
        except KeyError:
            raise UnknownRun(run_id) from None

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds * self.speed)

    async def _play(self, run_id: str, run: _Run, script: tuple[ScriptItem, ...]) -> None:
        try:
            run.result = await self._play_items(run_id, run, script)
        except asyncio.CancelledError:
            run.result = ExecResult("cancelled", "Cancelled.")
            raise
        finally:
            for rid in [r for r in self._pending if r.startswith(run_id + ":")]:
                self._pending.pop(rid).cancel()
            run.finished.set()
            run.queue.put_nowait(_DONE)

    async def _play_items(self, run_id: str, run: _Run, script: tuple[ScriptItem, ...]) -> ExecResult:
        for n, item in enumerate(script):
            await self._sleep(item.delay)
            match item:
                case Step(text=text):
                    run.queue.put_nowait(ExecEvent("step", text))
                case Confirm():
                    request_id = f"{run_id}:{n}"
                    future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
                    self._pending[request_id] = future
                    run.queue.put_nowait(
                        ExecEvent("confirm", item.title, request_id=request_id, detail=item.detail, tool=item.tool)
                    )
                    approved = await future
                    self._pending.pop(request_id, None)
                    if not approved:
                        return ExecResult("rejected", f"Rejected: {item.title}. Nothing was changed.")
                    for step in item.on_approve:
                        await self._sleep(step.delay)
                        run.queue.put_nowait(ExecEvent("step", step.text))
                case Fail(message=message):
                    return ExecResult("error", message)
                case Finish(summary=summary, details=details):
                    return ExecResult("done", summary, details)
        return ExecResult("done", "Done.")
