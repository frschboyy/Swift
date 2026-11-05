"""The light lane and "show me" with no run going (ADR-007 §10), through the router and the session."""

from __future__ import annotations

from settling import settled

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock
from test_routing import SpyExecutor, ask
from test_session import Recorder

from swift.desktop.base import WriteReceipt
from swift.desktop.fake import FakeDesktop
from swift.executors.mock import MockExecutor
from swift.executors.quick import QuickModel
from swift.ipc.protocol import Message
from swift.routing import route
from swift.routing.light import kind
from swift.session import Run, Session
from swift.workflows.artifacts import ArtifactStore
from swift.workflows.library import is_show, load_library

# ---- the light lane: which requests ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("What's a synonym for happy?", "synonym"),
        ("Swift, give me another word for important", "synonym"),
        ("what's the opposite of generous", "antonym"),
        ("what does ubiquitous mean", "define"),
        ("how do you say thank you in French", "translate"),
        ("is it affect or effect", "language"),
        ("what's the plural of cactus", "language"),
        ("reply politely to say I'm late", "compose"),
        ("write a short polite message saying I'll miss my train", "compose"),
        ("what's the capital of Peru", "fact"),
        ("who wrote Middlemarch", "fact"),
        ("how tall is Mount Everest", "fact"),
    ],
)
def test_light_lane_kinds(text: str, expected: str) -> None:
    assert kind(text) == expected
    r = route(text)
    assert (r.route, r.action, r.demand) == ("agent", "quick", "light")


@pytest.mark.parametrize(
    "text",
    [
        "reply to Ada's email politely to say I'm late",
        "what's the latest news on the election",
        "what's the weather today",
        "how big is my downloads folder",
        "what does this error mean",
        "who is in my meeting tomorrow",
        "Fix the failing test.",
        "Draft an email to my supervisor about the results.",
        "rewrite this to be more polite",
    ],
)
def test_requests_needing_tools_or_fresh_data_are_not_light(text: str) -> None:
    assert kind(text) is None
    assert route(text).action != "quick"


# ---- the light lane in the session ----------------------------------------------------------


class FakeQuick:
    def __init__(self, answer: str | None) -> None:
        self.reply = answer
        self.asked: list[str] = []

    async def answer(self, request: str) -> str | None:
        self.asked.append(request)
        return self.reply


async def test_light_lane_answers_without_the_agent() -> None:
    quick = FakeQuick("Glad, cheerful, joyful.")
    session, rec, spy, records = await _ask_with("What's a synonym for happy?", quick=quick)
    assert spy.calls == [] and quick.asked == ["What's a synonym for happy?"]
    assert rec.last("result")["summary"] == "Glad, cheerful, joyful."
    assert records[0]["route"] == "light" and records[0]["status"] == "done"
    assert "transcript" in records[0] and "Glad" not in str(records[0].get("action"))


async def test_light_lane_falls_back_to_the_agent_on_haiku() -> None:
    quick = FakeQuick(None)  # failed or too slow
    _, _, spy, records = await _ask_with("who wrote Middlemarch", quick=quick)
    assert spy.calls == [("who wrote Middlemarch", {"demand": "light", "override": None})]
    assert records[0]["route"] == "agent"


async def test_without_a_quick_model_light_requests_go_to_the_agent() -> None:
    _, _, spy, _ = await ask("what does ubiquitous mean")
    assert spy.calls and spy.calls[0][1]["demand"] == "light"


async def test_fast_lane_answers_in_the_session_without_the_agent() -> None:
    _, rec, spy, records = await ask("What time will it be in two minutes?")
    assert spy.calls == [] and rec.last("result")["summary"].startswith("It'll be ")
    assert (records[0]["route"], records[0]["action"]) == ("local", "answer")


async def _ask_with(text: str, **kw: Any) -> tuple[Session, Recorder, SpyExecutor, list[dict[str, Any]]]:
    rec, records, spy = Recorder(), [], SpyExecutor()
    session = Session(rec, spy, debug_executor=MockExecutor(speed=0), on_finish=records.append, **kw)
    session._test = (rec, spy, records)  # type: ignore[attr-defined]
    return await ask(text, session)


# ---- QuickModel: one tool-free call ---------------------------------------------------------


class FakeClient:
    instances: list[FakeClient] = []

    def __init__(self, options: Any) -> None:
        self.options = options
        self.queries: list[str] = []
        self.disconnected = False
        FakeClient.instances.append(self)

    async def connect(self) -> None: ...

    async def query(self, text: str) -> None:
        self.queries.append(text)

    async def receive_response(self):
        yield AssistantMessage([TextBlock("Lima.")], model="claude-haiku-5-5")

    async def disconnect(self) -> None:
        self.disconnected = True


async def test_quick_model_is_tool_free_one_turn_and_one_client_per_question() -> None:
    FakeClient.instances = []
    quick = QuickModel(claude_path="claude", prewarm=False, client_factory=FakeClient)
    assert await quick.answer("what's the capital of Peru") == "Lima."
    assert await quick.answer("and of Chile") == "Lima."
    first, second = FakeClient.instances
    o = first.options
    assert o.tools == [] and o.allowed_tools == [] and o.mcp_servers == {} and o.setting_sources == []
    assert o.max_turns == 1 and o.model == "claude-haiku-5-5" and "no-session-persistence" in o.extra_args
    assert first.queries == ["what's the capital of Peru"] and second.queries == ["and of Chile"]
    assert first.disconnected and second.disconnected


async def test_quick_model_gives_up_when_slow() -> None:
    class Slow(FakeClient):
        async def receive_response(self):
            await asyncio.sleep(5)
            yield AssistantMessage([TextBlock("late")], model="m")

    quick = QuickModel(claude_path="claude", prewarm=False, client_factory=Slow, timeout_s=0.05)
    assert await quick.answer("who wrote Middlemarch") is None


# ---- "show me" with no run going ------------------------------------------------------------


@pytest.mark.parametrize("text", ["Show me.", "Show me the Word document", "show me what you wrote", "and show me it again"])
def test_show_me_with_no_run_is_local(text: str) -> None:
    r = route(text)
    assert (r.route, r.action) == ("local", "show_last")


@pytest.mark.parametrize("text", ["Show me.", "Show me the Word document", "show me the research", "Swift, let me see it"])
def test_show_me_never_matches_a_workflow(text: str) -> None:
    library = load_library()
    assert is_show(text) and library.match(text) is None


@pytest.mark.parametrize("text", ["show me my calendar for this week", "Swift, pull up my schedule for tomorrow"])
def test_show_me_my_things_is_a_look_up_not_the_last_result(text: str) -> None:
    assert not is_show(text)
    assert route(text).action != "show_last"


def test_workflows_still_match_without_show() -> None:
    match = load_library().match("research the history of tea into word")
    assert match is not None and match.package.name == "research-into-word"


async def test_show_me_brings_up_the_app_swift_wrote_in() -> None:
    desktop = FakeDesktop()
    receipt = WriteReceipt("Word", "object_model", 3, 120, (desktop.word, ""))
    session, rec, spy, records = await _ask_with("Show me the Word document", desktop=desktop)
    # Nothing written yet: nothing to show, and no run.
    assert spy.calls == [] and rec.last("result")["summary"] == "There's nothing to show yet."
    session.tools = SimpleNamespace(last_write=receipt)  # what a research-into-Word run leaves
    await ask("Show me.", session)
    assert spy.calls == [] and desktop.shown == [receipt] and desktop.front is desktop.word
    assert rec.last("result")["summary"] == "Here it is in Word."
    assert [r["action"] for r in records] == ["show_last", "show_last"]


async def test_show_me_reopens_the_last_result_card() -> None:
    session, rec, spy, records = await _ask_with("Show me.")
    store = ArtifactStore()
    shown = store.put("shown-1", "text", "done", "Tea", {"text": "Tea is a drink."})
    last = Run()
    last.artifacts, last.artifacts_run = store, "cc-7"
    session._last_shown = last
    await ask("show me", session)
    assert spy.calls == []
    assert rec.last("artifact")["id"] == shown.id
    assert rec.last("view") == {"run_id": "cc-7", "artifact_id": shown.id, "open": True}
    assert records[-1]["status"] == "done"


async def test_show_me_is_not_sent_to_the_agent_as_a_new_request() -> None:
    rec, records, spy = Recorder(), [], SpyExecutor()
    session = Session(rec, spy, debug_executor=MockExecutor(speed=0), on_finish=records.append)
    await session.handle(Message("debug.ask", {"text": "Show me the Word document"}))
    await settled(session)
    assert spy.calls == []
