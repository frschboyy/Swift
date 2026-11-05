"""Swift's identity and the provider abstraction (ADR-008)."""

from __future__ import annotations

from settling import settled

import asyncio
from typing import Any

import pytest
from test_session import Recorder

from swift import identity
from swift.executors.base import ACTIVITIES, ExecutorUnavailable, ProviderInfo
from swift.executors.claude_code import SYSTEM_PROMPT, ClaudeCodeExecutor
from swift.executors.claude_mapping import steps_for
from swift.executors.echo import EchoExecutor
from swift.executors.mock import SCENARIOS, MockExecutor
from swift.executors.providers import CLAUDE_CODE, MOCK, Providers, provider_of
from swift.ipc.protocol import Message
from swift.routing import route
from swift.session import Session

AGENT = {"id": "mock", "name": "Demo agent"}


class Unavailable(EchoExecutor):
    name = "away"
    provider = ProviderInfo("away", "Away agent")

    async def start(self, request: str, **kw: Any) -> str:
        raise ExecutorUnavailable("Away agent isn't installed.", "Install it.")


def make(*executors: Any) -> tuple[Session, Recorder, list[dict[str, Any]]]:
    rec, records = Recorder(), []
    first, *rest = executors or (MockExecutor(speed=0),)
    session = Session(rec, first, debug_executor=MockExecutor(speed=0), on_finish=records.append, fallbacks=tuple(rest))
    return session, rec, records


async def ask(session: Session, text: str) -> None:
    await session.handle(Message("debug.ask", {"text": text}))
    await settled(session)


def of(rec: Recorder, kind: str) -> list[dict[str, Any]]:
    return [m.data for m in rec.messages if m.type == kind]


# ---- provider metadata -------------------------------------------------------------


def test_every_executor_describes_its_provider() -> None:
    assert ClaudeCodeExecutor.provider is CLAUDE_CODE and CLAUDE_CODE.name == "Claude Code"
    assert MockExecutor.provider is MOCK
    assert provider_of(EchoExecutor()).is_swift


def test_an_executor_without_provider_info_gets_a_readable_name() -> None:
    class Bare:
        name = "some_agent"

    info = provider_of(Bare())  # type: ignore[arg-type]
    assert (info.id, info.name, info.is_swift) == ("some_agent", "Some Agent", False)


def test_the_demo_never_claims_to_be_claude_code() -> None:
    texts = [getattr(item, "text", getattr(item, "message", "")) for script in SCENARIOS.values() for item in script]
    assert not any("Claude" in t for t in texts)


def test_claude_steps_carry_normalized_activities() -> None:
    event = {"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": "a.py"}},
        {"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}},
        {"type": "tool_use", "name": "mcp__x__y", "input": {}},
        {"type": "text", "text": "Looking at it."},
    ]}}
    assert [s.activity for s in steps_for(event)] == ["reading", "running", "working", "thinking"]
    helper = {**event, "parent_tool_use_id": "t1"}
    assert all(s.subagent for s in steps_for(helper))
    assert all(s.activity in ACTIVITIES for s in steps_for(event) + steps_for({"type": "system", "subtype": "init"}))


def test_claude_is_told_it_works_for_swift() -> None:
    assert "working for Swift" in SYSTEM_PROMPT and "don't introduce yourself" in SYSTEM_PROMPT


# ---- selection and fallback --------------------------------------------------------


async def test_start_falls_back_past_an_unavailable_provider() -> None:
    started = await Providers([Unavailable(), MockExecutor(speed=0)]).start("hi")
    assert started.provider is MOCK
    assert [p.id for p, _ in started.skipped] == ["away"]


async def test_start_raises_when_no_provider_is_available() -> None:
    with pytest.raises(ExecutorUnavailable, match="Away agent"):
        await Providers([Unavailable()]).start("hi")


def test_agents_leave_out_swifts_own_stand_ins() -> None:
    assert Providers([EchoExecutor()]).agents() == []
    assert Providers([MockExecutor(), EchoExecutor()]).agents() == [MOCK]


# ---- attribution on the wire ---------------------------------------------------------


async def test_run_messages_name_the_provider_and_activity() -> None:
    session, rec, records = make()
    await ask(session, "Find the open to-dos in this project.")
    working = [s for s in of(rec, "state") if s["state"] == "working"]
    assert working and all(s["agent"] == AGENT for s in working)
    steps = of(rec, "step")
    # The provider's start-up step is dropped for every provider (owner, 2026-10-26), but logged.
    assert steps[0]["activity"] == "reading" and records[0]["steps"][0]["activity"] == "starting"
    assert all(s["agent"] == AGENT and s["subagent"] is False for s in steps)
    result = of(rec, "result")[-1]
    assert result["agent"] == AGENT and result["note"] is None
    assert records[0]["provider"] == "mock"


async def test_confirm_card_names_who_asks() -> None:
    rec = Recorder()
    mock = MockExecutor(speed=0, default_scenario="confirm")
    session = Session(rec, mock, debug_executor=mock, router=None)
    await session.handle(Message("debug.ask", {"text": "Add a next steps section."}))
    await asyncio.wait_for(rec.confirm.wait(), 2)
    assert rec.last("confirm.request")["agent"] == AGENT
    await session.handle(Message("confirm.reply", {"request_id": rec.last("confirm.request")["request_id"], "decision": "approve"}))
    await settled(session)
    after = [s for s in of(rec, "state") if s["state"] == "working"][-1]
    assert after["agent"] == AGENT


async def test_errors_are_attributed_and_use_the_providers_hint() -> None:
    rec = Recorder()
    mock = MockExecutor(speed=0, default_scenario="error")
    session = Session(rec, mock, debug_executor=mock, router=None)
    await ask(session, "Check the packages.")
    err = rec.last("error")
    assert err["agent"] == AGENT and err["hint"] == MOCK.error_hint


async def test_swifts_own_answers_have_no_agent() -> None:
    session, rec, _ = make()
    await ask(session, "what time is it")
    assert of(rec, "result")[-1]["agent"] is None


async def test_repeat_keeps_the_original_attribution() -> None:
    session, rec, _ = make()
    await ask(session, "Find the open to-dos in this project.")
    await ask(session, "repeat that")
    assert of(rec, "result")[-1]["agent"] == AGENT


async def test_fallback_is_shown_as_a_swift_handoff_step() -> None:
    session, rec, records = make(Unavailable(), MockExecutor(speed=0))
    await ask(session, "Find the open to-dos in this project.")
    first = of(rec, "step")[0]
    assert first["kind"] == "handoff" and first["agent"] == {"id": "swift", "name": "Swift"}
    assert first["text"] == "Away agent isn't available, so Demo agent is taking this"
    assert records[0]["provider"] == "mock" and records[0]["skipped"] == ["away"]


# ---- identity -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "route_name", "called", "sent"),
    [
        ("Hey Claude", "local", "claude", None),
        ("hey claude, review this code", "agent", "claude", "review this code"),
        ("Hey Swift, can you review this code?", "agent", None, "can you review this code?"),
        ("ok codex stop", "control", "codex", None),
        ("Claude Code is slow today", "agent", None, "Claude Code is slow today"),
        ("are you codex?", "local", "codex", None),
        ("who are you", "local", None, None),
    ],
)
def test_routing_recognizes_how_swift_was_addressed(text: str, route_name: str, called: str | None, sent: str | None) -> None:
    r = route(text)
    assert (r.route, r.addressed_as) == (route_name, called)
    if sent is not None:
        assert r.text == sent


def test_clarification_only_names_configured_agents() -> None:
    agents = [CLAUDE_CODE]
    assert identity.clarification("claude", agents) == "No, I'm Swift. Claude Code is one of the agents I work with."
    assert identity.clarification("codex", agents) == "No, I'm Swift. The agent I work with right now is Claude Code."
    assert identity.clarification("codex", []) == "No, I'm Swift, your voice assistant."
    assert "Claude Code is the agent I hand work to" in identity.introduction(agents)


async def test_hey_claude_alone_gets_a_gentle_clarification() -> None:
    session, rec, records = make(as_claude())
    await ask(session, "Hey Claude")
    result = of(rec, "result")[-1]
    assert result["summary"] == "No, I'm Swift. Claude Code is one of the agents I work with."
    assert result["note"] is None and result["agent"] is None
    assert records[0]["addressed_as"] == "claude"


async def test_a_misnamed_request_still_runs_and_is_clarified_once() -> None:
    executor = as_claude()
    session, rec, _ = make(executor)
    await ask(session, "Hey Claude, find the to-dos.")
    assert executor.requests[-1].endswith("find the to-dos.")
    assert of(rec, "result")[-1]["note"] == "No, I'm Swift. Claude Code is one of the agents I work with."
    await ask(session, "Hey Claude, now the README.")
    assert of(rec, "result")[-1]["note"] is None  # not repeated within the hour


async def test_who_are_you_introduces_swift() -> None:
    session, rec, _ = make(as_claude())
    await ask(session, "who are you?")
    assert of(rec, "result")[-1]["summary"].startswith("I'm Swift, your voice assistant.")


def as_claude() -> MockExecutor:
    """A mock that presents as Claude Code, to check the wording owners will see."""

    class AsClaude(MockExecutor):
        provider = CLAUDE_CODE

        def __init__(self) -> None:
            super().__init__(speed=0)
            self.requests: list[str] = []

        async def start(self, request: str, scenario: str | None = None, **kw: Any) -> str:
            self.requests.append(request)
            return await super().start(request, scenario, **kw)

    return AsClaude()
