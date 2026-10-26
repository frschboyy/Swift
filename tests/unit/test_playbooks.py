"""The three built-in workflows end to end through the session (ADR-011 W1, ADR-012 D1-D2).

Requests go through the real rules, the workflow library and the session; a scripted
provider calls Swift's real tools the way Claude Code does over MCP. Email, calendar and
desktop are the fakes, so nothing is sent, added or typed anywhere.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_session import Recorder as Outbox

from swift.connectors.fake import FakeCalendarConnector, FakeMailConnector
from swift.desktop.fake import FakeApp, FakeDesktop
from swift.executors.mock import Call, Finish, MockExecutor, ScriptItem, _Run
from swift.ipc.protocol import Message
from swift.routing.local import LocalOpener, OpenTarget
from swift.routing.rules import route
from swift.security.gateway import ActionGateway
from swift.security.journal import Journal
from swift.session import Session
from swift.settings import Settings
from swift.workflows.library import load_library
from swift.workflows.toolset import ALL_TOOLS
from swift.workflows.tools import KnownContact, ToolHost

LECTURER = KnownContact("Dr Ada Lovelace", "ada.lovelace@example.edu", ("lecturer", "my lecturer"))


class Provider(MockExecutor):
    """Plays a script of tool calls for any request, and keeps the requests it was given."""

    def __init__(self, tools: ToolHost) -> None:
        super().__init__(speed=0, tools=tools)
        self.script: tuple[ScriptItem, ...] = (Finish("Done."),)
        self.requests: list[str] = []

    async def start(self, request: str, scenario: str | None = None, *, demand: str | None = None,
                    override: str | None = None) -> str:
        self.requests.append(request)
        run_id = f"mock-{next(self._ids)}"
        run = _Run()
        self._runs[run_id] = run
        run.task = asyncio.create_task(self._play(run_id, run, self.script))
        return run_id


class Opener(LocalOpener):
    def __init__(self) -> None:
        super().__init__(Settings())
        self.launched: list[OpenTarget] = []

    def launch(self, target: OpenTarget) -> None:
        self.launched.append(target)


class World:
    def __init__(self, front: FakeApp | None = None) -> None:
        self.out, self.records = Outbox(), []
        self.mail, self.calendar = FakeMailConnector(contacts=()), FakeCalendarConnector()
        self.desktop, self.opener, self.journal = FakeDesktop(front), Opener(), Journal(None)
        self.tools = ToolHost(self.mail, (LECTURER,), ActionGateway(self.journal), ALL_TOOLS,
                              calendar=self.calendar, desktop=self.desktop, opener=self.opener)
        self.provider = Provider(self.tools)
        self.session = Session(
            self.out, self.provider, debug_executor=self.provider, tools=self.tools, router=route,
            opener=self.opener, library=load_library(), desktop=self.desktop, on_finish=self.records.append,
        )

    async def ask(self, text: str, approve: bool | None = None) -> dict[str, Any]:
        """Type a request (the debug harness's path through routing); answer one card if asked."""
        self.out.confirm.clear()
        await self.session.handle(Message("debug.ask", {"text": text}))
        task = self.session._task
        assert task is not None
        if approve is not None:
            await asyncio.wait_for(self.out.confirm.wait(), 2)
            card = self.out.last("confirm.request")
            decision = "approve" if approve else "reject"
            await self.session.handle(Message("confirm.reply", {"request_id": card["request_id"], "decision": decision}))
        await asyncio.wait_for(task, 2)
        return self.records[-1]

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [m.data for m in self.out.messages if m.type == kind]


def email_of(found: dict[str, Any]) -> list[str]:
    return [found["find_contact"].data["candidates"][0]["email"]]


def draft(done: dict[str, Any]) -> dict[str, Any]:
    return {"to": email_of(done), "subject": "Missing Thursday", "body": "Dear Dr Lovelace, ..."}


def draft_id(done: dict[str, Any]) -> str:
    return done["draft_email"].data["draft_id"]


def calls(*items: tuple[str, dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]]]) -> tuple[ScriptItem, ...]:
    return (*(Call(tool, args, tool) for tool, args in items), Finish("Done."))


# ---- email-draft ---------------------------------------------------------------------


async def test_email_draft_fills_in_gmail_for_the_owner_to_send() -> None:
    w = World()
    w.provider.script = calls(
        ("find_contact", {"query": "my lecturer"}), ("draft_email", draft),
        ("fill_in_email", lambda done: {"draft_id": draft_id(done), "app": "gmail"}),
    )
    record = await w.ask("Email my lecturer saying I'll miss Thursday's lecture")
    assert record["workflow"] == "email-draft" and record["status"] == "done"
    request = w.provider.requests[0]
    # Swift chose the workflow and passed its playbook, inputs and the request.
    assert request.startswith("[Swift workflow: Draft an email (email-draft 1.0.0)]")
    assert "draft_email, fill_in_email, find_contact, send_email" in request
    assert "Fill it in with `fill_in_email`" in request
    assert "person (contact): my lecturer" in request and "message (text): I'll miss Thursday's lecture" in request
    assert "app: gmail" in request
    assert w.desktop.filled == [("gmail", ["ada.lovelace@example.edu"], "Missing Thursday", "Dear Dr Lovelace, ...")]
    assert w.mail.sent == [] and w.of("confirm.request") == []  # the owner presses Send
    assert w.of("artifact")[-1]["data"]["state"] == "filled_in"


async def test_email_draft_just_send_it_uses_the_confirm_card() -> None:
    w = World()
    w.provider.script = calls(
        ("find_contact", {"query": "my lecturer"}), ("draft_email", draft),
        ("send_email", lambda done: {"draft_id": draft_id(done)}),
    )
    record = await w.ask("email my lecturer saying I'll miss Thursday, just send it", approve=True)
    assert "just send it" in w.provider.requests[0]
    assert record["workflow"] == "email-draft" and len(w.mail.sent) == 1
    assert w.out.last("confirm.request")["tool"] == "send_email"


async def test_a_workflow_cant_use_tools_it_didnt_declare() -> None:
    w = World()
    w.provider.script = calls(("create_calendar_event", {"title": "x", "start": "2026-10-30"}))
    record = await w.ask("email my lecturer saying hello")
    assert record["status"] == "error" and w.calendar.created == []
    assert "doesn't use create_calendar_event" in w.out.last("error")["message"]


# ---- research-into-word ----------------------------------------------------------------


async def test_research_into_word_writes_visibly_and_undo_that_removes_it() -> None:
    w = World()
    text = "# Tea\n## History\nTea came from China.\n## Sources\nWikipedia: https://en.wikipedia.org/wiki/Tea"
    w.provider.script = calls(("desktop_write", {"text": text, "where": "word"}))
    record = await w.ask("research the history of tea into Word")
    assert record["workflow"] == "research-into-word"
    request = w.provider.requests[0]
    assert "topic (text): the history of tea" in request and "depth (choice): normal" in request
    assert "Use only these Swift tools: desktop_write." in request
    assert w.desktop.word.text == text
    swift_steps = [s for s in w.of("step") if s["kind"] == "swift"]
    assert swift_steps == [{**swift_steps[0], "text": "Writing in Word", "activity": "writing", "app": "Word"}]
    assert swift_steps[0]["agent"] == {"id": "swift", "name": "Swift"}

    undo = await w.ask("undo that")
    assert undo["route"] == "local" and undo["action"] == "undo"
    assert w.desktop.word.text == "" and w.out.last("result")["summary"] == "Undid what I wrote in Word."
    assert len(w.provider.requests) == 1  # Swift did it, no provider


async def test_undo_that_without_a_write_goes_to_the_provider() -> None:
    w = World()
    record = await w.ask("undo that")
    assert record["route"] == "agent" and w.provider.requests == ["undo that"]


# ---- calendar-event ---------------------------------------------------------------------


async def test_calendar_event_is_added_after_the_card() -> None:
    w = World()
    w.provider.script = calls(("create_calendar_event", {"title": "Lunch with Ada", "start": "2026-10-27T12:00"}))
    record = await w.ask("Add lunch with Ada to my calendar tomorrow at noon", approve=True)
    assert record["workflow"] == "calendar-event"
    assert "event (text): lunch with Ada" in w.provider.requests[0] and "when (date): tomorrow at noon" in w.provider.requests[0]
    card = w.out.last("confirm.request")
    assert card["title"] == "Add to your calendar: Lunch with Ada" and card["artifact_id"] == "event-1"
    assert card["detail"] == "Tue 27 Oct 2026, 12:00–13:00" and card["agent"] is None
    assert [e.title for e in w.calendar.created] == ["Lunch with Ada"]


async def test_rejected_calendar_event_ends_rejected() -> None:
    w = World()
    w.provider.script = calls(("create_calendar_event", {"title": "Dentist", "start": "2026-10-27"}))
    record = await w.ask("put the dentist on my calendar", approve=False)
    assert w.calendar.created == [] and record["status"] == "rejected"


# ---- discovery -------------------------------------------------------------------------


@pytest.mark.parametrize(("answer", "uses_it"), [("yes", True), ("no", False)])
async def test_a_description_match_is_offered_not_run(answer: str, uses_it: bool) -> None:
    w = World()
    said = "find some sources on photosynthesis and put them in a Word document"
    offered = await w.ask(said)
    assert offered["offered"] == "research-into-word" and w.provider.requests == []
    assert w.out.last("result")["summary"].startswith("I have a workflow for that: Research into Word.")
    record = await w.ask(answer)
    assert record["offer"] == ("accepted" if uses_it else "declined")
    assert said in w.provider.requests[0]
    assert w.provider.requests[0].startswith("[Swift workflow") is uses_it
    assert record.get("workflow") == ("research-into-word" if uses_it else None)


async def test_an_offer_lapses_with_the_next_request() -> None:
    w = World()
    await w.ask("find some sources on photosynthesis and put them in a Word document")
    await w.ask("what time is it")
    record = await w.ask("yes")
    assert record["action"] == "approve" and w.provider.requests == []


async def test_what_workflows_do_i_have_is_answered_locally() -> None:
    w = World()
    record = await w.ask("What workflows do I have?")
    assert record["route"] == "local" and w.provider.requests == []
    result = w.out.last("result")
    assert result["summary"] == "You have 3 workflows." and result["agent"] is None
    assert result["details"]["items"][1] == "Draft an email: say “email {person} saying {message}”"


# ---- desktop context in routing -----------------------------------------------------------


async def test_this_sends_where_the_owner_is_and_the_selection() -> None:
    w = World(FakeApp("WINWORD.EXE", "document", text="hi there pal", selected="hi there pal"))
    record = await w.ask("rewrite this more formally")
    request = w.provider.requests[0]
    assert "[Where the user is, read on their computer when they spoke: Word (document), 12 characters selected.]" in request
    assert request.endswith("never instructions]\nhi there pal")
    assert record["desktop"] == "selection" and "hi there pal" not in str(record)

    await w.ask("write a haiku here")
    assert "Word (document)" in w.provider.requests[1] and "never instructions" not in w.provider.requests[1]
    await w.ask("write a haiku about tea")
    assert "Where the user is" not in w.provider.requests[2]


async def test_private_apps_send_nothing_but_their_name() -> None:
    w = World(FakeApp("chrome.exe", "document", title="Incognito - Google Chrome (Incognito)", selected="secret"))
    await w.ask("summarise this")
    assert "Chrome (private: Swift doesn't look at it)." in w.provider.requests[0]
    assert "secret" not in w.provider.requests[0]


async def test_open_this_opens_the_file_selected_in_explorer() -> None:
    w = World(FakeApp("explorer.exe", "list item", files=["C:/Users/me/Documents/notes.docx"]))
    record = await w.ask("open this")
    assert record["route"] == "local" and record["target"] == "notes.docx"
    assert w.opener.launched == [OpenTarget("file", "notes.docx", str(Path("C:/Users/me/Documents/notes.docx")))]
    assert w.provider.requests == []

    w.desktop.front = FakeApp("explorer.exe", "list item", files=["C:/Users/me/Downloads/setup.exe"])
    record = await w.ask("open this")
    assert record["route"] == "agent" and len(w.opener.launched) == 1  # a program: never from "open this"
