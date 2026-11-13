"""Executor interface contract, exercised through MockExecutor."""

from __future__ import annotations

import asyncio

import pytest

from swift.executors.base import WorkerTask
from swift.executors.base import ExecEvent, UnknownRun
from swift.executors.mock import SCENARIOS, MockExecutor


async def drain(ex: MockExecutor, run_id: str, approve: bool | None = None) -> list[ExecEvent]:
    events = []
    async for event in ex.events(run_id):
        events.append(event)
        if event.type == "confirm":
            assert event.request_id is not None
            assert approve is not None, "unexpected confirm"
            await ex.reply(event.request_id, approve)
    return events


@pytest.mark.parametrize("scenario", ["happy", "long"])
async def test_scenario_runs_to_done(scenario: str) -> None:
    ex = MockExecutor(speed=0)
    run_id = await ex.start(WorkerTask("request"), scenario=scenario)
    events = await drain(ex, run_id)
    result = await ex.result(run_id)
    assert result.status == "done"
    assert result.summary
    assert events and all(e.type == "step" for e in events)


async def test_result_details_are_card_shaped() -> None:
    ex = MockExecutor(speed=0)
    for scenario in ("happy", "long"):
        run_id = await ex.start(WorkerTask("r"), scenario=scenario)
        await drain(ex, run_id)
        details = (await ex.result(run_id)).details
        assert details is not None and details["kind"] in {"text", "list", "table"}


async def test_confirm_approve_continues() -> None:
    ex = MockExecutor(speed=0)
    run_id = await ex.start(WorkerTask("r"), scenario="confirm")
    events = await drain(ex, run_id, approve=True)
    confirm = [e for e in events if e.type == "confirm"]
    assert len(confirm) == 1 and confirm[0].tool == "Edit" and confirm[0].detail
    assert events[-1].type == "step"  # steps after approval
    assert (await ex.result(run_id)).status == "done"


async def test_confirm_reject_stops() -> None:
    ex = MockExecutor(speed=0)
    run_id = await ex.start(WorkerTask("r"), scenario="confirm")
    events = await drain(ex, run_id, approve=False)
    assert events[-1].type == "confirm"
    result = await ex.result(run_id)
    assert result.status == "rejected"
    assert "Nothing was changed" in result.summary


async def test_error_scenario() -> None:
    ex = MockExecutor(speed=0)
    run_id = await ex.start(WorkerTask("r"), scenario="error")
    await drain(ex, run_id)
    assert (await ex.result(run_id)).status == "error"


async def test_cancel_mid_run_ends_events_and_reports_cancelled() -> None:
    ex = MockExecutor(speed=0.05)
    run_id = await ex.start(WorkerTask("r"), scenario="long")
    seen = []

    async def consume() -> None:
        async for e in ex.events(run_id):
            seen.append(e)

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.06)
    await ex.cancel(run_id)
    await asyncio.wait_for(consumer, 1)
    assert (await ex.result(run_id)).status == "cancelled"
    assert len(seen) < len(SCENARIOS["long"])


async def test_cancel_while_waiting_for_confirm() -> None:
    ex = MockExecutor(speed=0)
    run_id = await ex.start(WorkerTask("r"), scenario="confirm")
    async for event in ex.events(run_id):
        if event.type == "confirm":
            await ex.cancel(run_id)
    assert (await ex.result(run_id)).status == "cancelled"


async def test_cancel_after_finish_is_harmless() -> None:
    ex = MockExecutor(speed=0)
    run_id = await ex.start(WorkerTask("r"), scenario="happy")
    await drain(ex, run_id)
    await ex.cancel(run_id)
    assert (await ex.result(run_id)).status == "done"


async def test_runs_are_independent_and_ids_unique() -> None:
    ex = MockExecutor(speed=0)
    a = await ex.start(WorkerTask("a"), scenario="happy")
    b = await ex.start(WorkerTask("b"), scenario="error")
    assert a != b
    await drain(ex, a)
    await drain(ex, b)
    assert (await ex.result(a)).status == "done"
    assert (await ex.result(b)).status == "error"


async def test_unknown_run_and_stale_reply() -> None:
    ex = MockExecutor(speed=0)
    with pytest.raises(UnknownRun):
        await ex.result("nope")
    await ex.reply("nope:1", True)  # ignored, no exception
