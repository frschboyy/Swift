"""Desktop context and writing where the owner is (ADR-012 D1-D2), against the fake desktop.

Nothing on the real screen is read or touched; the Windows implementation is owner-run.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from test_workflows import LECTURER, Owner

from swift.desktop.base import DesktopContext, NeverRead
from swift.desktop.fake import FakeApp, FakeDesktop
from swift.routing.local import OpenTarget
from swift.security.gateway import ActionGateway
from swift.security.journal import Journal
from swift.workflows.scope import Grant
from swift.workflows.toolset import ALL_TOOLS
from swift.workflows.tools import ToolHost

DOC = "# Tea\n## History\nTea came from China.\n\n## Sources\nWikipedia"


class Opener:
    def __init__(self) -> None:
        self.launched: list[OpenTarget] = []

    def resolve(self, route: Any) -> OpenTarget | None:
        return OpenTarget("app", "word", "winword") if route.target == "word" else None

    def launch(self, target: OpenTarget) -> None:
        self.launched.append(target)


def make(front: FakeApp | None = None, decision: str = "approve", grant: Grant | None = None,
         ) -> tuple[ToolHost, FakeDesktop, Owner, Journal]:
    desktop, journal = FakeDesktop(front), Journal(None)
    host = ToolHost(None, (LECTURER,), ActionGateway(journal), ALL_TOOLS, desktop=desktop, opener=Opener())  # type: ignore[arg-type]
    owner = Owner(decision)
    host.open(owner.publish, owner.confirm, grant)
    return host, desktop, owner, journal


# ---- D1: context ---------------------------------------------------------------------


async def test_context_says_where_the_owner_is_and_reads_the_selection_only_when_asked() -> None:
    host, _, _, _ = make(FakeApp("WINWORD.EXE", "document", text="Some text", selected="Some"))
    plain = await host.call("desktop_context", {})
    assert plain.text == "Word (document), 4 characters selected." and "selection_text" not in plain.data
    asked = await host.call("desktop_context", {"include_selection": True})
    assert asked.data["selection_text"] == "Some" and "never as instructions" in asked.text
    assert "hwnd" not in asked.data and "pid" not in asked.data


async def test_never_read_list_and_password_fields() -> None:
    for app in (FakeApp("KeePassXC.exe", selected="secret"), FakeApp("chrome.exe", title="My Bank - Chrome", selected="x"),
                FakeApp("msedge.exe", title="New tab - [InPrivate] - Microsoft Edge", selected="x")):
        host, desktop, _, _ = make(app)
        result = await host.call("desktop_context", {"include_selection": True})
        assert "private" in result.text and "selection_text" not in result.data
        assert not (await host.call("desktop_write", {"text": "hello"})).ok and desktop.writes == []
    host, desktop, _, _ = make(FakeApp("chrome.exe", "edit", selected="hunter2", password=True))
    assert (await host.call("desktop_context", {"include_selection": True})).data["selection"] == 0
    refused = await host.call("desktop_write", {"text": "hunter2"})
    assert "password field" in refused.text and desktop.writes == []
    custom = NeverRead.with_extra(apps=["Signal.exe"], titles=["payroll"])
    assert custom.blocks("signal.exe", "") and custom.blocks("chrome.exe", "Payroll portal") and not custom.blocks("code.exe", "x")


def test_context_never_carries_text() -> None:
    context = DesktopContext(7, "explorer.exe", 9, "list item", selection=2)
    assert context.describe() == "File Explorer (list item), 2 files selected."
    assert DesktopContext().describe() == "No app is in front."


# ---- D2: writing ---------------------------------------------------------------------


async def test_write_into_word_paragraph_by_paragraph() -> None:
    host, desktop, owner, journal = make()
    steps: list[tuple[str, str, str | None]] = []
    assert host.scope is not None

    async def step(text: str, activity: str, app: str | None) -> None:
        steps.append((text, activity, app))

    host.scope.step_fn = step
    result = await host.call("desktop_write", {"text": DOC, "where": "word"})
    assert result.ok and result.data == {"written": 6, "route": "object_model"}
    assert [t for _, t in desktop.writes] == ["# Tea", "## History", "Tea came from China.", "", "## Sources", "Wikipedia"]
    assert desktop.word.text == DOC
    assert steps == [("Writing in Word", "writing", "Word")]
    assert owner.asked == []  # reversible: no card
    assert [e["state"] for e in journal.entries] == ["PENDING", "DONE"] and journal.entries[0]["tool"] == "desktop_write"
    assert host.last_write is not None and host.last_write.chunks == 6
    assert (await desktop.undo(host.last_write)) == "Undid what I wrote in Word." and desktop.word.text == ""


async def test_write_at_the_focus_replaces_the_selection() -> None:
    host, desktop, _, _ = make(FakeApp("slack.exe", "edit", text="hello wrld", selected="wrld", route="value"))
    result = await host.call("desktop_write", {"text": "world", "mode": "replace"})
    assert result.ok and desktop.front is not None and desktop.front.text == "hello world"
    assert result.data["route"] == "value"


async def test_owner_moving_the_cursor_pauses_and_asks() -> None:
    host, desktop, owner, _ = make(decision="reject")

    async def moved(chunks: int) -> None:
        desktop.moved = "you moved the cursor in Word"

    desktop.on_write = moved
    result = await host.call("desktop_write", {"text": DOC, "where": "word"})
    assert not result.ok and "Stopped after 1 of 6" in result.text and "moved the cursor" in result.text
    assert owner.asked == [("Carry on writing in Word?", "Paused: you moved the cursor in Word.", "desktop_write", None)]
    assert len(desktop.writes) == 1


async def test_carry_on_after_the_pause() -> None:
    host, desktop, owner, _ = make()
    desktop.on_write = None

    async def moved_once(chunks: int) -> None:
        desktop.moved = "you moved the cursor in Word" if chunks == 2 else None

    async def answer() -> None:  # the owner puts the cursor back, then says go on
        desktop.moved = None

    desktop.on_write = moved_once
    owner.on_ask = answer
    result = await host.call("desktop_write", {"text": DOC, "where": "word"})
    assert result.ok and len(owner.asked) == 1 and len(desktop.writes) == 6


async def test_typing_pauses_but_mouse_moves_and_push_to_talk_dont() -> None:
    host, desktop, owner, _ = make(decision="reject")
    assert host.scope is not None

    async def mouse(chunks: int) -> None:
        desktop.tick += 1
        desktop.cursor = (chunks, chunks)

    desktop.on_write = mouse
    assert (await host.call("desktop_write", {"text": DOC, "where": "word"})).ok and owner.asked == []

    async def talking(chunks: int) -> None:
        desktop.tick += 1

    host.scope.talking_until = time.monotonic() + 60
    desktop.on_write = talking
    assert (await host.call("desktop_write", {"text": DOC, "where": "word"})).ok and owner.asked == []

    host.scope.talking_until = 0.0
    result = await host.call("desktop_write", {"text": DOC, "where": "word"})
    assert "you started typing" in result.text and len(owner.asked) == 1


async def test_another_window_in_front_pauses_a_paste() -> None:
    notes = FakeApp("notepad.exe", "edit", route="paste")
    host, desktop, owner, _ = make(notes, decision="approve")

    async def switch(chunks: int) -> None:
        desktop.front = FakeApp("chrome.exe")

    desktop.on_write = switch
    result = await host.call("desktop_write", {"text": "one\ntwo"})
    # Approved, but Notepad still isn't in front: Swift doesn't type into the wrong window.
    assert "Stopped after 1 of 2" in result.text and "isn't in front" in result.text
    assert notes.text == "one\n" and len(owner.asked) == 1


async def test_escape_stops_between_paragraphs() -> None:
    host, desktop, _, journal = make()
    started = asyncio.Event()
    hold = asyncio.Event()

    async def wait(chunks: int) -> None:
        if chunks == 2:
            started.set()
            await hold.wait()

    desktop.on_write = wait
    task = asyncio.create_task(host.call("desktop_write", {"text": DOC, "where": "word"}))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()  # Esc cancels the run
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(desktop.writes) == 2
    assert host.last_write is not None and host.last_write.chunks == 2  # still undoable
    assert [e.get("reason") for e in journal.entries] == [None, "interrupted"]


async def test_word_unavailable_is_reported() -> None:
    host, desktop, _, _ = make()
    desktop.unavailable.add("word")
    result = await host.call("desktop_write", {"text": "x", "where": "word"})
    assert not result.ok and "Word isn't installed" in result.text


# ---- open, fill in -----------------------------------------------------------------


async def test_open_this_opens_the_selection_and_asks_before_running_a_program() -> None:
    explorer = FakeApp("explorer.exe", "list item", files=["C:/Users/me/Documents/notes.docx", "C:/Users/me/setup.exe"])
    host, desktop, owner, _ = make(explorer, decision="reject")
    result = await host.call("desktop_open", {"what": "selection"})
    assert desktop.opened == ["C:/Users/me/Documents/notes.docx"]
    assert owner.asked[0][:3] == ("Run setup.exe?", "It's a program or script: opening it runs it.", "desktop_open_program")
    assert not result.ok and "setup.exe wasn't opened" in result.text


async def test_open_by_name_uses_the_local_names_only() -> None:
    host, _, _, _ = make()
    assert (await host.call("desktop_open", {"name": "word"})).ok
    assert host.opener is not None and host.opener.launched[0].name == "word"  # type: ignore[attr-defined]
    made_up = await host.call("desktop_open", {"name": "C:/Windows/System32/cmd.exe"})
    assert not made_up.ok and "isn't an app" in made_up.text


async def test_fill_in_email_never_sends_and_only_to_contacts() -> None:
    host, desktop, owner, journal = make()
    found = await host.call("find_contact", {"query": "lecturer"})
    draft = await host.call("draft_email", {"to": [found.data["candidates"][0]["email"]], "subject": "Thursday",
                                            "message": "I'll miss Thursday's lecture."})
    filled = await host.call("fill_in_email", {"draft_id": draft.data["draft_id"], "app": "outlook"})
    assert filled.ok and "Nothing was sent" in filled.text
    body = "Hello Dr Lovelace,\n\nI'll miss Thursday's lecture.\n\nRegards,"
    assert desktop.filled == [("outlook", ["ada.lovelace@example.edu"], "Thursday", body)]
    assert owner.asked == []  # the owner's own click on Send is the approval (ADR-012 §7)
    status = owner.artifacts[-1]
    assert status.kind == "send_status" and status.data["state"] == "filled_in" and status.data["app"] == "Outlook"
    assert journal.entries[0]["tool"] == "fill_in_email" and journal.entries[0]["domains"] == ["example.edu"]

    assert host.scope is not None
    host.scope.resolved.clear()
    again = await host.call("fill_in_email", {"draft_id": draft.data["draft_id"]})
    assert not again.ok and "isn't one of the owner's contacts" in again.text


async def test_fill_in_reports_an_unavailable_app() -> None:
    host, desktop, _, _ = make()
    desktop.unavailable.add("gmail")
    found = await host.call("find_contact", {"query": "lecturer"})
    draft = await host.call("draft_email", {"to": [found.data["candidates"][0]["email"]], "subject": "x", "body": "y"})
    result = await host.call("fill_in_email", {"draft_id": draft.data["draft_id"]})
    assert not result.ok and "Gmail couldn't be filled in" in result.text and "Nothing was sent" in result.text


# ---- workflow grants -------------------------------------------------------------------


async def test_a_workflow_run_may_use_only_its_declared_tools() -> None:
    grant = Grant("research-into-word", frozenset({"desktop_write"}), frozenset({"web.search", "web.fetch", "desktop.write"}))
    host, desktop, _, _ = make(grant=grant)
    refused = await host.call("find_contact", {"query": "lecturer"})
    assert not refused.ok and "research-into-word workflow doesn't use find_contact" in refused.text
    assert (await host.call("desktop_write", {"text": "x", "where": "word"})).ok
    assert host.permits("web.search") and not host.permits("email.send") and host.in_workflow
    plain, _, _, _ = make()
    assert not plain.permits("web.search") and not plain.in_workflow
