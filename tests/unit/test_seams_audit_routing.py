"""Seams audit 2026-11-04 (routing, lanes, fallback): failing tests that reproduce findings.

Marked xfail(strict) until fixed (docs/audit/2026-11-seams-audit.md). Each test names the finding it reproduces (R-xx in the audit notes). They fail
today by design; a fix makes them pass.
"""

from __future__ import annotations

import pytest

import asyncio
from typing import Any

from test_lanes import FakeQuick
from test_routing import ask
from test_runs import Agent, make, say, started, until
from test_system_lane import _session, lane

from swift.executors.base import ExecEvent, ExecResult
from swift.failures import classify
from swift.network import OFFLINE_SAID
from swift.session import MAX_RUNS
from swift.signin import SigninWatch

# ---- R-01: offline, the light lane is still tried first ------------------------------------------


class HangingQuick(FakeQuick):
    """A light-lane model that, offline, waits on the CLI's retries until its own timeout."""

    def __init__(self) -> None:
        super().__init__(None)

    async def answer(self, request: str) -> str | None:
        self.asked.append(request)
        await asyncio.sleep(0.5)  # stands in for QuickModel's 20 s timeout
        return None


@pytest.mark.xfail(strict=True, reason="seams audit R-01: open finding; remove this marker with the fix")
async def test_r01_offline_a_light_request_is_answered_at_once_without_the_light_model() -> None:
    session, rec, spy, records = await _session()
    session.online = lambda: False
    session.quick = HangingQuick()  # type: ignore[assignment]
    await ask("what's the capital of Peru", session)
    assert rec.last("result")["summary"] == OFFLINE_SAID
    assert session.quick.asked == [], "offline, the light lane (a Claude CLI call) was tried first"  # type: ignore[union-attr]


# ---- R-03: a local request waits behind three agent runs -----------------------------------------


@pytest.mark.xfail(strict=True, reason="seams audit R-03: open finding; remove this marker with the fix")
async def test_r03_a_system_request_is_not_queued_behind_three_agent_runs() -> None:
    session, out, records, agent, stt = make()
    session.system, control, _ = lane(volume=40)
    for n in range(MAX_RUNS):
        await started(session, out, agent, stt, f"Hey Swift, research topic number {n} for me")
    await say(session, stt, "Hey Swift, turn the volume up")
    # Local work needs no agent slot: it should be done at once, not "That's waiting: 3 requests are running".
    try:
        await until(lambda: control.volume == 50, timeout=1.0)
    except AssertionError:
        queued = any(m.type == "run.voice" and "waiting" in str(m.data.get("text")) for m in out.messages)
        raise AssertionError(f"volume request not done while 3 agent runs work; queued hint shown: {queued}") from None


async def test_r03_control_with_one_run_the_same_request_is_done_beside_it() -> None:
    session, out, records, agent, stt = make()
    session.system, control, _ = lane(volume=40)
    await started(session, out, agent, stt, "Hey Swift, research topic number 1 for me")
    await say(session, stt, "Hey Swift, turn the volume up")
    await until(lambda: control.volume == 50, timeout=1.0)  # passes: the slot limit is the cause


# ---- R-04: connection lost mid-run: the run keeps "retrying" -------------------------------------


class RetryingAgent(Agent):
    """A provider whose CLI lost the internet: it reports retries and never ends by itself."""

    async def _work(self, run_id: str, run: dict[str, Any]) -> ExecResult:
        queue = run["queue"]
        try:
            for _ in range(3):
                queue.put_nowait(ExecEvent("step", "Connection hiccup, retrying…", activity="waiting"))
                await asyncio.sleep(0.05)
            await run["go"].wait()
            return ExecResult("done", "late")
        finally:
            queue.put_nowait(None)


@pytest.mark.xfail(strict=True, reason="seams audit R-04: open finding; remove this marker with the fix")
async def test_r04_offline_mid_run_swift_ends_the_run_and_says_why() -> None:
    session, out, records, agent, stt = make(RetryingAgent)
    online = {"now": True}
    session.online = lambda: online["now"]
    await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    online["now"] = False  # Wi-Fi off while it works
    await until(lambda: any(m.type == "result" and m.data.get("summary") == OFFLINE_SAID for m in out.messages)
                or bool(records), timeout=1.0)


# ---- R-05: a Claude refusal right after the start-up check is not offered ------------------------


@pytest.mark.xfail(strict=True, reason="seams audit R-05: open finding; remove this marker with the fix")
async def test_r05_a_refusal_soon_after_the_start_up_check_still_offers_the_sign_in() -> None:
    offered: list[set[str]] = []
    watch = SigninWatch(offered.append, google=None, claude=lambda: "ok")  # local status looks fine
    await watch.check()  # start-up check (+20 s): the revoked token still reads "ok" locally
    assert offered == []
    watch.refused("claude")  # the owner's first request, a minute later, is refused by the server
    assert offered == [{"claude"}], "refusal within 10 minutes of the check was swallowed: no card"


def test_r05_the_real_refusal_text_is_classified_as_sign_in() -> None:
    raw = "Exception: Unable to validate model: OAuth refresh token is no longer valid; run /login to re-authenticate"
    assert classify(raw, "Claude Code").code == "auth"  # passes: the classification itself is right


# ---- R-06: a CLI that hangs never ends -----------------------------------------------------------


class HangClient:
    def __init__(self, options: object) -> None: ...
    async def connect(self) -> None: ...
    async def set_model(self, model: str | None) -> None: ...
    async def query(self, prompt: str) -> None: ...

    async def receive_response(self):  # type: ignore[no-untyped-def]
        await asyncio.Event().wait()  # no message, ever
        yield None

    async def disconnect(self) -> None: ...


@pytest.mark.xfail(strict=True, reason="seams audit R-06: open finding; remove this marker with the fix")
async def test_r06_a_silent_cli_ends_with_a_card_by_itself(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from swift.executors.claude_code import ClaudeCodeExecutor

    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", prewarm=False, client_factory=HangClient)
    assert hasattr(ex, "stall_timeout_s"), "no watchdog: a CLI that goes silent keeps the run 'working' forever"
    ex.stall_timeout_s = 0.2  # type: ignore[attr-defined]
    run_id = await ex.start("Summarise the README", demand="light")
    result = await asyncio.wait_for(ex.result(run_id), 2)
    assert result.status == "error" and result.failure is not None and result.failure.code == "timeout"
