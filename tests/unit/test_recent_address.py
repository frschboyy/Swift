"""Web addresses the owner gave beyond this request's words (C3; foundation decision 4, 2026-11-15).

Check 255, 12:35: "open usiu dot ac dot ke" opened the site; "Open my university's website." was refused. The
first decision let an address from earlier in the conversation (10 minutes) count; check 330 then showed it
opening usiu.ac.ke for "my university's website", and the owner objected: he never said that was his
university. A pattern then guessed which words point back ("open that site again": ``points_back``), and QA kept
finding requests it misread (QA-02, QA-04). Decision 4 replaces it: Swift asks "Open usiu.ac.ke?", a level 1
question, about the owner's own earlier addresses (or one they had Swift remember). The agent's text and what
tools read never count.

On a virtual clock, so "ten minutes later" takes no time.
"""

from __future__ import annotations

from settling import settled

import asyncio

import pytest
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
        if text := step.get("write"):  # decision 6's tests (test_unclear_writes.py) share this agent
            self.opens.append(await self.tools.call("desktop_write", {"text": text}, run=run_id))
        return ExecResult("done", step.get("say", "Done."), meta={"start_model": "m"})


def make(front: FakeApp | None = None, memories: Store | None = None, out: Recorder | None = None,
         ) -> tuple[Session, Agent, FakeDesktop, list[dict[str, Any]]]:
    desktop, records = FakeDesktop(front), []
    tools = ToolHost(None, (), ActionGateway(Journal(None)), ALL_TOOLS, desktop=desktop)  # type: ignore[arg-type]
    agent = Agent(tools)
    session = Session(out or Recorder(), agent, debug_executor=MockExecutor(speed=0), tools=tools,
                      on_finish=records.append)
    session.memories = tools.memories = memories  # as the backend wires them
    return session, agent, desktop, records


async def ask(session: Session, agent: Agent, text: str, **step: Any) -> None:
    agent.plan.append(step)
    await session.handle(Message("debug.ask", {"text": text}))
    await settled(session)


ASK_FOR_IT = "ask the owner to say the address"


async def asked(session: Session, agent: Agent, text: str, **step: Any) -> Any:
    """The request starts, and Swift's question about an address is on screen: the question."""
    agent.plan.append(step)
    await session.handle(Message("debug.ask", {"text": text}))
    for _ in range(400):
        q = session.dialogue.pending
        if q is not None and q.window is not None:
            return q
        await asyncio.sleep(0.005)
    raise AssertionError("Swift didn't ask")


async def answer(session: Session, how: str, words: str = "yes") -> None:
    """The owner answers the question on screen: spoken (the open microphone), typed, or a click."""
    if how == "spoken":
        await session._take_answer(words, source="answer")
    elif how == "typed":
        await session.handle(Message("text", {"text": words}))
    else:
        q = session.dialogue.pending
        assert q is not None
        await session.handle(Message("ask.reply", {"ask_id": q.id, "text": words}))
    await asyncio.sleep(0.05)


async def test_words_pointing_at_it_ask_to_reopen_the_address_said_a_moment_ago() -> None:
    session, agent, desktop, records = make()
    await ask(session, agent, "open usiu dot ac dot ke", open="usiu.ac.ke", say="I opened usiu.ac.ke in your browser.")
    await asyncio.sleep(28)
    q = await asked(session, agent, "Open that site again.", open="usiu.ac.ke")
    assert q.text == "Open usiu.ac.ke?" and q.approval and desktop.opened == ["https://usiu.ac.ke"]
    await answer(session, "spoken")  # a plain spoken yes, on screen: level 1
    await settled(session)
    assert [r.ok for r in agent.opens] == [True, True]
    assert desktop.opened == ["https://usiu.ac.ke", "https://usiu.ac.ke"]
    assert records[1]["thread"] != records[0]["thread"]  # as at 12:35: a new thread, the same conversation
    assert records[1]["context"]["previous"] == records[0]["id"]


async def test_a_typed_yes_never_opens_it_and_a_click_does() -> None:
    """Typing never approves (foundation decision 1): the question asks again; a click on Yes opens it."""
    session, agent, desktop, _ = make()
    await ask(session, agent, "open usiu dot ac dot ke", open="usiu.ac.ke")
    q = await asked(session, agent, "Open that site again.", open="usiu.ac.ke")
    await answer(session, "typed", "Swift, yes")
    assert session.dialogue.pending is q and desktop.opened == ["https://usiu.ac.ke"]
    await answer(session, "click", "Yes")
    await settled(session)
    assert desktop.opened == ["https://usiu.ac.ke"] * 2


async def test_check_330_a_description_without_a_memory_asks_and_no_opens_nothing() -> None:
    """The owner's objection (2026-11-14): he never said usiu.ac.ke was his university, and it opened. Now the
    question shows the address before anything opens."""
    session, agent, desktop, _ = make()
    await ask(session, agent, "open usiu dot ac dot ke", open="usiu.ac.ke")
    q = await asked(session, agent, "Open my university's website.", open="usiu.ac.ke")
    assert q.text == "Open usiu.ac.ke?"
    await answer(session, "spoken", "no")
    await settled(session)
    refused = agent.opens[-1]
    assert not refused.ok and "said not to open it" in refused.text
    assert desktop.opened == ["https://usiu.ac.ke"]


async def test_a_description_asks_about_the_address_the_owner_asked_swift_to_remember(tmp_path: Any) -> None:
    session, agent, desktop, records = make(memories=Store(tmp_path))
    await session.handle(Message("debug.ask", {"text": "Remember that my university is usiu dot ac dot ke"}))
    await settled(session)  # Swift's own memory store, from the owner's words: the agent isn't asked
    assert records[-1]["route"] != "agent" and session.memories is not None
    assert [r.text for r in session.memories.all("memory")] == ["my university is usiu dot ac dot ke"]
    await session.handle(Message("debug.ask", {"text": "new topic"}))  # a fresh conversation: no recent address
    await settled(session)
    q = await asked(session, agent, "Open my university's website.", open="usiu.ac.ke")
    assert q.text == "Open usiu.ac.ke?"
    await answer(session, "spoken")
    await settled(session)
    assert agent.opens[-1].ok and desktop.opened == ["https://usiu.ac.ke"]
    await ask(session, agent, "Open my manager's website.", open="usiu.ac.ke")  # another subject: not that memory
    assert not agent.opens[-1].ok and ASK_FOR_IT in agent.opens[-1].text
    assert desktop.opened == ["https://usiu.ac.ke"]


async def test_only_the_owners_own_address_is_offered_never_the_agents_page() -> None:
    """The agent asks for a page of the site with what it read in the address: Swift asks about the owner's
    address as they gave it, and opens that, never the agent's."""
    session, agent, desktop, _ = make()
    await ask(session, agent, "open usiu dot ac dot ke", open="usiu.ac.ke")
    q = await asked(session, agent, "Open that site again.", open="https://usiu.ac.ke/?q=what-it-read")
    assert q.text == "Open usiu.ac.ke?"
    await answer(session, "spoken")
    await settled(session)
    assert desktop.opened == ["https://usiu.ac.ke"] * 2


async def test_several_earlier_addresses_are_offered_as_a_choice() -> None:
    session, agent, desktop, _ = make()
    await ask(session, agent, "open usiu dot ac dot ke", open="usiu.ac.ke")
    await ask(session, agent, "now open python.org", open="python.org")
    q = await asked(session, agent, "Open my university's website.", open="university.example")
    assert q.kind == "choice" and q.approval and q.text == "Open which: python.org or usiu.ac.ke?"  # newest first
    await answer(session, "typed", "usiu.ac.ke")  # typing never picks one either
    assert session.dialogue.pending is q
    await answer(session, "click", "usiu.ac.ke")
    await settled(session)
    assert desktop.opened == ["https://usiu.ac.ke", "https://python.org", "https://usiu.ac.ke"]


async def test_an_earlier_address_the_agent_asks_for_is_the_only_one_offered() -> None:
    session, agent, desktop, _ = make()
    await ask(session, agent, "open usiu dot ac dot ke", open="usiu.ac.ke")
    await ask(session, agent, "now open python.org", open="python.org")
    q = await asked(session, agent, "Open my university's website.", open="https://www.usiu.ac.ke/timetable")
    assert q.kind == "yes_no" and q.text == "Open usiu.ac.ke?"
    await answer(session, "spoken", "no")
    await settled(session)
    assert desktop.opened == ["https://usiu.ac.ke", "https://python.org"]


async def test_an_address_only_in_the_agents_answer_or_a_tool_result_is_never_opened_or_offered() -> None:
    """The agent's answer and what desktop_context read are in the agent's context, not the owner's words."""
    session, agent, desktop, records = make(FakeApp("chrome.exe", title="USIU-Africa | usiu.ac.ke - Google Chrome"))
    await ask(session, agent, "what's my university's website?", look=True,
              say="Your university's website is usiu.ac.ke.")
    await ask(session, agent, "Open it.", open="usiu.ac.ke")
    assert "usiu.ac.ke" in agent.prompts[-1]  # the agent knows it from its context...
    assert records[1]["context"]["previous"] == records[0]["id"]
    assert len(agent.opens) == 1
    refused = agent.opens[0]
    assert not refused.ok and ASK_FOR_IT in refused.text  # ...but Swift doesn't open or offer it
    assert desktop.opened == []


async def test_an_address_said_more_than_ten_minutes_ago_isnt_offered_in_the_same_conversation() -> None:
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


async def test_an_address_from_another_conversation_isnt_offered() -> None:
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


# QA-02 and QA-04 (2026-11-14, 2026-11-15): each of these opened usiu.ac.ke said a moment ago, or was refused,
# depending on how ``points_back`` read it. With the question, none opens anything until the owner answers it.
REQUESTS = (
    "Show this week's timetable on my university's website again.",
    "Once again, show this week's timetable on my university's website.",
    "Open that site's contact page.",
    "Open that one drive folder.",
    "Find my university's website and open it.",
    "Try that again.",
    "That one.",
    "Open it in Edge.",
    "Open that site again.",
    "The one I just opened.",
    "Go ahead and open that site again.",
    "Take me there.",
)


@pytest.mark.parametrize("words", REQUESTS)
async def test_whatever_the_request_says_a_recent_address_opens_only_after_the_question(words: str) -> None:
    session, agent, desktop, _ = make()
    await ask(session, agent, "open usiu dot ac dot ke", open="usiu.ac.ke")
    q = await asked(session, agent, words, open="usiu.ac.ke")
    assert q.text == "Open usiu.ac.ke?" and desktop.opened == ["https://usiu.ac.ke"], words
    await answer(session, "spoken", "no")
    await settled(session)
    assert not agent.opens[-1].ok and desktop.opened == ["https://usiu.ac.ke"], words
