"""What Swift depends on, checked before it is needed, and nothing waits on it for ever (seams audit S4)."""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Any

import pytest

from swift.connectors.base import ConnectorError
from swift.routing.rules import Route
from swift.session import lane_needs


async def _slow_stream(gaps: list[float]) -> Any:
    for gap in gaps:
        await asyncio.sleep(gap)
        yield gap


async def test_the_watchdog_ends_a_silent_run_but_waits_while_the_owner_decides(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from swift.executors.claude_code import ClaudeCodeExecutor, RunStalled, _Run

    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", prewarm=False)
    ex.stall_timeout_s = 0.2
    run = _Run()
    run.held = 1  # a card is open: 0.5 s of silence is the owner thinking, not a stall
    got = [m async for m in ex._watched(run, _slow_stream([0.5, 0.05]))]
    assert got == [0.5, 0.05]
    run.held = 0
    with pytest.raises(RunStalled):
        [m async for m in ex._watched(run, _slow_stream([0.5]))]
    got = [m async for m in ex._watched(run, _slow_stream([0.1, 0.1, 0.1]))]  # each message resets it
    assert len(got) == 3


async def test_a_google_call_has_one_deadline_and_a_change_that_overruns_is_unknown(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from swift.connectors import google

    monkeypatch.setattr(google, "CALL_DEADLINE_S", 0.2)
    conn = google.GoogleSession("Gmail")

    def hangs() -> None:
        time.sleep(2)

    t0 = time.monotonic()
    with pytest.raises(ConnectorError):
        await conn.call(hangs, retry=True)
    assert time.monotonic() - t0 < 1.5
    with pytest.raises(ConnectorError) as sent:
        await conn.call(hangs, changes=True)
    assert sent.value.code == "unknown"  # it may have gone: never "failed"


def test_lanes_say_what_they_need() -> None:
    assert lane_needs(Route("agent", "research tea")) == {"network", "claude_cli"}
    assert "network" in lane_needs(Route("local", "capital of Peru", action="quick"))
    assert lane_needs(Route("local", "volume up", action="system")) == frozenset()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' connectivity")
def test_a_connection_without_the_internet_is_offline(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from swift import network

    monkeypatch.setattr(network, "_internet_by_nlm", lambda: False)  # a LAN, a captive portal
    assert network.online() is not True
    monkeypatch.setattr(network, "_internet_by_nlm", lambda: None)  # Windows can't say: the fast answer stands
    assert network.online() in (True, False)


async def test_couldnt_confirm_the_model_while_online_offers_the_sign_in() -> None:
    from test_runs import make

    from swift.failures import classify

    session, *_ = make()
    offered: list[str] = []
    session.on_signin_refused = offered.append
    session.online = lambda: True
    failure = classify("Couldn't confirm model claude-sonnet with the API", "Claude Code")
    assert failure.code == "models"
    await session._send_failure(failure, {})
    session.online = lambda: False  # offline: it's the connection, not the sign-in
    await session._send_failure(failure, {})
    assert offered == ["claude"]


async def test_a_request_the_internet_went_from_is_ended_and_kept_in_the_stack() -> None:
    from test_runs import make, started, until
    from test_seams_audit_routing import RetryingAgent

    from swift.network import OFFLINE_SAID
    from swift.parked import ParkedThreads

    session, out, records, agent, stt = make(RetryingAgent, parked=ParkedThreads(None))
    online = {"now": True}
    session.online = lambda: online["now"]
    await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    online["now"] = False
    await until(lambda: bool(records), timeout=2.0)
    assert records[0]["error"] == "offline" and records[0]["retries"] >= 2
    assert any(m.type == "error" and m.data.get("message") == OFFLINE_SAID for m in out.messages)
    assert [p.reason for p in session.parked.all()] == ["stopped"]  # type: ignore[union-attr]
