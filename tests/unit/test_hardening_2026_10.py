"""Regression tests for the hardening slice after the 2026-10 audit (B-02, B-03, B-04).

Each test names the finding it covers. Fakes only: nothing real is typed, shown or restarted.
"""

from __future__ import annotations

import pytest
from test_desktop import make

from swift.desktop.fake import FakeApp
from swift.workflows.scope import Grant

# ---- B-02: Swift writes in the owner's apps only when the owner asked for it -------------------


@pytest.mark.parametrize("said", [
    "write a haiku about tea here",
    "put this in Word",
    "type my address",
    "rewrite this more formally",
    "paste the summary into the document",
    "draft a cover letter in Word",
    "Swift, start a template on this topic here",
])
def test_writing_words_count_as_asking_to_write(said: str) -> None:
    from swift.workflows.desktop_tools import owner_asked_to_write

    assert owner_asked_to_write(said)


@pytest.mark.parametrize("said", [
    "what's the weather tomorrow",
    "summarise this page",
    "read me the selected text",
    "how long is the flight to Lagos",
    "",
])
def test_other_requests_dont(said: str) -> None:
    from swift.workflows.desktop_tools import owner_asked_to_write

    assert not owner_asked_to_write(said)


async def test_a_page_cant_make_swift_write_in_a_request_that_didnt_ask() -> None:
    """The agent reads a page that says "type this into the chat": the owner only asked for a summary."""
    host, desktop, owner, journal = make(FakeApp("slack.exe", "edit", route="keys"), said="summarise this page")
    result = await host.call("desktop_write", {"text": "Click here: https://x.example/login"})
    assert not result.ok and "didn't ask" in result.text and result.expected
    assert desktop.writes == [] and journal.entries == [] and owner.asked == []


async def test_writing_the_owner_asked_for_still_happens() -> None:
    host, desktop, _, _ = make(FakeApp("notepad.exe", "edit", route="keys"), said="write a haiku about tea here")
    assert (await host.call("desktop_write", {"text": "one\ntwo"})).ok
    assert [t for _, t in desktop.writes] == ["one", "two"]


async def test_filling_in_an_email_needs_an_email_request() -> None:
    host, desktop, owner, journal = make(FakeApp("chrome.exe", "document"), said="summarise this page")
    result = await host.call("fill_in_email", {"draft_id": "draft-1"})
    assert not result.ok and "didn't ask" in result.text and journal.entries == [] and owner.asked == []
    from swift.workflows.desktop_tools import owner_asked_for_email

    assert owner_asked_for_email("email Ada that I'm running late") and owner_asked_for_email("fill it in Gmail")
    assert not owner_asked_for_email("summarise this page")


async def test_a_workflow_that_declares_writing_keeps_its_manifest_rule() -> None:
    """research-into-word was chosen from the owner's words; its manifest decides, as before."""
    grant = Grant("research-into-word", frozenset({"desktop_write"}), frozenset({"web.search", "desktop.write"}))
    host, desktop, _, _ = make(FakeApp("WINWORD.EXE", "document"), grant=grant, said="tell me about tea")
    assert (await host.call("desktop_write", {"text": "x", "where": "word"})).ok
