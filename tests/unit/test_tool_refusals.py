"""IA-01 phase 0: a tool's refusal leaves a reason code on the run record and in swift.log, never the owner's words."""

from __future__ import annotations

import json

from loguru import logger
from test_system_phase_a2 import _host_and_scope

from swift.executors.base import ExecResult
from swift.runlog import summary
from swift.workflows.scope import Grant, note_refusal
from swift.workflows.system_tools import system_action

SAID = "time me for two minutes"


async def test_a_system_action_the_grammar_misses_is_recorded_as_not_asked() -> None:
    host, scope, _, _, _ = _host_and_scope(SAID)
    record: dict = {"transcript": SAID}
    scope.on_refusal = lambda e: note_refusal(record, e)
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m) + json.dumps(m.record["extra"])), level="INFO")
    try:
        result = await system_action(host, scope, {"request": "set a timer for 2 minutes"})
    finally:
        logger.remove(sink)
    assert not result.ok
    assert record["tool_refusals"] == [{"tool": "system_action", "reason": "not_asked", "intents": ["timer.set"]}]
    logged = [line for line in lines if "tool refused" in line]
    assert logged and "not_asked" in logged[0] and "time me" not in logged[0] and "2 minutes" not in logged[0]
    line = summary(record)  # what swift.log's interaction line may say
    assert line["tool_refusals"] == record["tool_refusals"] and "transcript" not in line


async def test_each_refusal_has_its_own_reason() -> None:
    host, scope, _, _, _ = _host_and_scope("turn the wifey off")
    seen: list[dict] = []
    scope.on_refusal = seen.append
    await system_action(host, scope, {"request": "turn off wifi"})  # the agent may offer its guess
    await system_action(host, scope, {"request": "make me a sandwich"})
    await system_action(host, scope, {"request": "set a timer"})
    assert [e["reason"] for e in seen] == ["not_asked_offer", "unknown", "missing_slot"]


async def test_a_tool_outside_the_workflow_is_recorded() -> None:
    host, scope, _, _, _ = _host_and_scope("turn off wifi and send Sam an email")
    scope.grant = Grant("email-draft", frozenset({"draft_email"}), frozenset())
    host.scopes.append(scope)
    seen: list[dict] = []
    scope.on_refusal = seen.append
    result = await host.call("system_action", {"request": "turn off wifi"}, run=None)
    assert not result.ok and seen == [{"tool": "system_action", "reason": "outside_workflow"}]


async def test_nothing_refused_leaves_no_field() -> None:
    host, scope, _, _, _ = _host_and_scope("set a timer for 2 minutes")
    record: dict = {}
    scope.on_refusal = lambda e: note_refusal(record, e)
    assert (await system_action(host, scope, {"request": "set a timer for 2 minutes"})).ok
    assert "tool_refusals" not in record


async def test_the_session_puts_a_run_s_refusals_on_its_record() -> None:
    # The whole path: the session opens the run's scope (session._open_scope), the provider calls the tool, and the
    # interaction record says what was refused; swift.log's line says so too, without the words.
    from test_dialogue import Asker
    from test_runs import finish_all, make, started, until

    class Calls(Asker):
        async def _work(self, run_id: str, run: dict) -> ExecResult:
            assert self.tools is not None
            self.results[run_id] = await self.tools.call("system_action", {"request": "set a timer for 2 minutes"}, run=run_id)
            run["queue"].put_nowait(None)
            return ExecResult("done", "I couldn't set the timer.")

    session, _, records, agent, stt = make(Calls)
    run_id = await started(session, _, agent, stt, "Hey Swift, time me for two minutes")
    await until(lambda: run_id in agent.results)
    await finish_all(session, agent)
    assert records[0]["status"] == "done"  # what the run says: the reason is now beside it
    assert records[0]["tool_refusals"] and records[0]["tool_refusals"][0]["tool"] == "system_action"
    assert summary(records[0])["tool_refusals"] == records[0]["tool_refusals"]
