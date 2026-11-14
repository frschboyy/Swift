"""Web addresses the owner gave beyond this request's words (C3, owner's decisions of 2026-11-14).

Check 255, 12:35: "open usiu dot ac dot ke" opened the site; "Open my university's website." was refused. The
first decision let an address from earlier in the conversation (10 minutes) count; check 330 then showed it
opening usiu.ac.ke for "my university's website", and the owner objected: he never said that was his
university. So a recent address counts only when the request points at it ("open that site again"), and a
description only through a memory he had Swift keep. The agent's text and what tools read never count.

On a virtual clock, so "ten minutes later" takes no time.
"""

from __future__ import annotations

from settling import settled

import asyncio
from typing import Any

from test_routing import SpyExecutor
from test_session import Recorder
from virtual_clock import VIRTUAL, event_loop_policy, one_clock  # noqa: F401 - fixtures

from swift.desktop.fake import FakeApp, FakeDesktop
from swift.executors.base import ExecResult, WorkerTask
from swift.executors.mock import MockExecutor
from swift.ipc.protocol import Message
from swift.memory import Store
from swift.security.gateway import ActionGateway
from swift.security.journal import Journal
from swift.session import Session
from swift.workflows.owner_address import points_back
from swift.workflows.toolset import ALL_TOOLS
from swift.workflows.tools import ToolHost, ToolResult

pytestmark = VIRTUAL


class Agent(SpyExecutor):
    """Each run: maybe read the screen, maybe open an address with Swift's tool, then answer."""

    def __init__(self, tools: ToolHost) -> None:
        super().__init__()
        self.tools = tools
        self.plan: list[dict[str, Any]] = []
        self.opens: list[ToolResult] = []

    async def start(self, task: WorkerTask) -> str:
        self.prompts = [*getattr(self, "prompts", []), task.prompt]
        return await super().start(task)

    async def result(self, run_id: str) -> ExecResult:
        step = self.plan.pop(0) if self.plan else {}
        if step.get("look"):
            await self.tools.call("desktop_context", {}, run=run_id)
        if url := step.get("open"):
            self.opens.append(await self.tools.call("desktop_open", {"url": url}, run=run_id))
        return ExecResult("done", step.get("say", "Done."), meta={"start_model": "m"})


def make(front: FakeApp | None = None, memories: Store | None = None,
         ) -> tuple[Session, Agent, FakeDesktop, list[dict[str, Any]]]:
    desktop, records = FakeDesktop(front), []
    tools = ToolHost(None, (), ActionGateway(Journal(None)), ALL_TOOLS, desktop=desktop)  # type: ignore[arg-type]
    agent = Agent(tools)
    session = Session(Recorder(), agent, debug_executor=MockExecutor(speed=0), tools=tools,
                      on_finish=records.append)
    session.memories = tools.memories = memories  # as the backend wires them
    return session, agent, desktop, records


async def ask(session: Session, agent: Agent, text: str, **step: Any) -> None:
    agent.plan.append(step)
    await session.handle(Message("debug.ask", {"text": text}))
    await settled(session)


ASK_FOR_IT = "ask the owner to say the address"


def test_which_words_point_back_at_an_address() -> None:
    for words in ("open that site again", "Open it.", "the one I just opened", "open the same page", "reopen it",
                  "can you bring that up", "open that website please", "go to the site I mentioned"):
        assert points_back(words), words
    for words in ("Open my university's website.", "open usiu dot ac dot ke", "open my school portal",
                  "what's my university's website?", "open Gmail"):
        assert not points_back(words), words


async def test_words_pointing_at_it_reuse_the_address_said_a_moment_ago() -> None:
    session, agent, desktop, records = make()
    await ask(session, agent, "open usiu dot ac dot ke", open="usiu.ac.ke", say="I opened usiu.ac.ke in your browser.")
    await asyncio.sleep(28)
    await ask(session, agent, "Open that site again.", open="usiu.ac.ke")
    assert [r.ok for r in agent.opens] == [True, True]
    assert desktop.opened == ["https://usiu.ac.ke", "https://usiu.ac.ke"]
    assert records[1]["thread"] != records[0]["thread"]  # as at 12:35: a new thread, the same conversation
    assert records[1]["context"]["previous"] == records[0]["id"]


async def test_check_330_a_description_without_a_memory_asks_for_the_address() -> None:
    """The owner's objection (2026-11-14): he never said usiu.ac.ke was his university."""
    session, agent, desktop, _ = make()
    await ask(session, agent, "open usiu dot ac dot ke", open="usiu.ac.ke")
    await ask(session, agent, "Open my university's website.", open="usiu.ac.ke")
    refused = agent.opens[-1]
    assert not refused.ok and ASK_FOR_IT in refused.text and "don't offer one" in refused.text
    assert desktop.opened == ["https://usiu.ac.ke"]


async def test_a_description_opens_the_address_the_owner_asked_swift_to_remember(tmp_path: Any) -> None:
    session, agent, desktop, records = make(memories=Store(tmp_path))
    await session.handle(Message("debug.ask", {"text": "Remember that my university is usiu dot ac dot ke"}))
    await settled(session)  # Swift's own memory store, from the owner's words: the agent isn't asked
    assert records[-1]["route"] != "agent" and session.memories is not None
    assert [r.text for r in session.memories.all("memory")] == ["my university is usiu dot ac dot ke"]
    await session.handle(Message("debug.ask", {"text": "new topic"}))  # a fresh conversation: no recent address
    await settled(session)
    await ask(session, agent, "Open my university's website.", open="usiu.ac.ke")
    assert agent.opens[-1].ok and desktop.opened == ["https://usiu.ac.ke"]
    await ask(session, agent, "Open my manager's website.", open="usiu.ac.ke")  # another subject: not that memory
    assert not agent.opens[-1].ok and desktop.opened == ["https://usiu.ac.ke"]


async def test_an_address_only_in_the_agents_answer_or_a_tool_result_is_never_opened() -> None:
    """The agent's answer and what desktop_context read are in the agent's context, not the owner's words."""
    session, agent, desktop, records = make(FakeApp("chrome.exe", title="USIU-Africa | usiu.ac.ke - Google Chrome"))
    await ask(session, agent, "what's my university's website?", look=True,
              say="Your university's website is usiu.ac.ke.")
    await ask(session, agent, "Open it.", open="usiu.ac.ke")
    assert "usiu.ac.ke" in agent.prompts[-1]  # the agent knows it from its context...
    assert records[1]["context"]["previous"] == records[0]["id"]
    assert len(agent.opens) == 1
    refused = agent.opens[0]
    assert not refused.ok and ASK_FOR_IT in refused.text  # ...but Swift doesn't open it
    assert desktop.opened == []


async def test_an_address_said_more_than_ten_minutes_ago_is_refused_in_the_same_conversation() -> None:
    session, agent, desktop, records = make()
    await ask(session, agent, "open usiu dot ac dot ke", open="usiu.ac.ke")
    for words in ("tell me a joke", "another one"):
        await asyncio.sleep(290)  # inside the follow-up window: the conversation goes on
        await ask(session, agent, words)
    await asyncio.sleep(290)
    await ask(session, agent, "Open that site again.", open="usiu.ac.ke")
    assert "open usiu dot ac dot ke" in agent.prompts[-1]  # still the same conversation...
    assert [r.ok for r in agent.opens] == [True, False]  # ...but the owner said it over ten minutes ago
    assert desktop.opened == ["https://usiu.ac.ke"]


async def test_an_address_from_another_conversation_is_refused() -> None:
    """Under ten minutes old, but the conversation ended (past the follow-up window, or "new topic")."""
    session, agent, desktop, records = make()
    await ask(session, agent, "open usiu dot ac dot ke", open="usiu.ac.ke")
    await asyncio.sleep(400)
    await ask(session, agent, "Open that site again.", open="usiu.ac.ke")
    assert "context" not in records[1] and not agent.opens[-1].ok

    await ask(session, agent, "open usiu dot ac dot ke", open="usiu.ac.ke")
    await session.handle(Message("debug.ask", {"text": "new topic"}))  # Swift's own: the agent isn't asked
    await settled(session)
    await ask(session, agent, "Open that site again.", open="usiu.ac.ke")
    assert [r.ok for r in agent.opens] == [True, False, True, False] and records[-2]["action"] == "new_topic"
    assert desktop.opened == ["https://usiu.ac.ke", "https://usiu.ac.ke"]


async def test_words_that_only_contain_open_this_dont_point_back_at_a_recent_address() -> None:
    """QA of 2026-11-14: "show this week's timetable on my university's website" isn't pointing at anything, yet
    points_back matched "show this", so the address said a moment ago opened for a description (check 330's case)."""
    session, agent, desktop, _ = make()
    await ask(session, agent, "open usiu dot ac dot ke", open="usiu.ac.ke")
    await ask(session, agent, "Show this week's timetable on my university's website.", open="usiu.ac.ke")
    assert not agent.opens[-1].ok and desktop.opened == ["https://usiu.ac.ke"]
    for words in ("show this week's timetable on my university's website", "open this year's budget on the school site",
                  "visit that store's homepage", "go to this month's newsletter page",
                  "open my university's website, then try again if it fails",
                  "look up the course list and ask again if you're unsure"):
        assert not points_back(words), words
    for words in ("open that site again", "open this site", "the same page", "the one I just opened", "open it",
                  "open it again, please", "bring that up"):
        assert points_back(words), words  # the owner's pointing words still point
