"""Foundation decision 6 (2026-11-15): when the owner's words don't clearly ask for writing into an app, Swift asks
("Write this in Notepad?"), a level 1 question, instead of refusing (audit B-02's refusal). The question shows every
character a yes writes, marked as the worker's (``quote``; second review, 2026-11-15: a 100-character preview
approved the whole text). A terminal also gets its own card (test_audit_2026_10.py, A-02)."""

from __future__ import annotations

from settling import settled

from dataclasses import replace
from typing import Any

from test_desktop import make
from test_recent_address import answer, asked
from test_recent_address import make as session_make
from virtual_clock import VIRTUAL, event_loop_policy, one_clock  # noqa: F401 - fixtures

from swift.desktop.fake import FakeApp
from swift.dialogue import Answer

pytestmark = VIRTUAL

PAGE_SAYS = "Click here: https://x.example/login"


def _answering(host: Any, said: str | None, then: Any = None) -> list[tuple[str, bool, str]]:
    """The tool scope asks with ``said`` as the owner's answer (None: no answer); the questions it got, with the
    worker's text each showed."""
    questions: list[tuple[str, bool, str]] = []

    async def ask(question: str, kind: str, options: tuple[str, ...], *, approval: bool = False,
                  quote: str = "") -> Answer | None:
        questions.append((question, approval, quote))
        if then is not None:
            then()
        return None if said is None else Answer(said)  # type: ignore[arg-type]

    host.scope.ask_fn = ask
    return questions


async def test_an_unclear_write_is_asked_about_showing_the_text_and_a_yes_writes_it() -> None:
    host, desktop, owner, _ = make(FakeApp("notepad.exe", "edit", route="keys"), said="summarise this page")
    questions = _answering(host, "yes")
    result = await host.call("desktop_write", {"text": PAGE_SAYS})
    assert questions == [("Write this in Notepad?", True, PAGE_SAYS)]  # level 1: typing never answers it
    assert result.ok and [t for _, t in desktop.writes] == [PAGE_SAYS] and owner.asked == []


async def test_a_no_or_no_answer_writes_nothing() -> None:
    for said, told in (("no", "said not to"), (None, "didn't answer")):
        host, desktop, _, journal = make(FakeApp("notepad.exe", "edit", route="keys"), said="summarise this page")
        _answering(host, said)
        result = await host.call("desktop_write", {"text": PAGE_SAYS})
        assert not result.ok and told in result.text and result.expected
        assert desktop.writes == [] and journal.entries == []


async def test_a_long_text_is_shown_whole_and_the_owners_own_words_need_no_question() -> None:
    """Second review (2026-11-15): the question showed 100 characters and a yes wrote all of them."""
    host, desktop, _, _ = make(FakeApp("notepad.exe", "edit", route="keys"), said="summarise this page")
    questions = _answering(host, "yes")
    long = "\n".join(f"Paragraph {i}: " + "word " * 60 for i in range(40))
    assert (await host.call("desktop_write", {"text": long})).ok
    assert questions[0][2] == long == "\n".join(t for _, t in desktop.writes)  # shown is exactly what's written
    host, desktop, _, _ = make(FakeApp("notepad.exe", "edit", route="keys"), said="write a haiku about tea here")
    questions = _answering(host, "no")
    assert (await host.call("desktop_write", {"text": "one"})).ok and questions == []


async def test_the_app_in_front_changing_while_swift_asks_writes_nothing() -> None:
    host, desktop, _, _ = make(FakeApp("notepad.exe", "edit", route="keys"), said="summarise this page")
    _answering(host, "yes", then=lambda: setattr(desktop, "front", FakeApp("slack.exe", "edit", route="keys")))
    result = await host.call("desktop_write", {"text": PAGE_SAYS})
    assert not result.ok and "changed" in result.text and desktop.writes == []


async def test_an_unclear_terminal_write_asks_and_then_still_has_its_own_card() -> None:
    host, desktop, owner, _ = make(FakeApp("cmd.exe", "edit", route="keys"), said="summarise this page", decision="reject")
    questions = _answering(host, "yes")
    result = await host.call("desktop_write", {"text": "dir"})
    assert len(questions) == 1 and [tool for _, _, tool, _ in owner.asked] == ["desktop_write_terminal"]
    assert not result.ok and desktop.writes == []


async def test_filling_in_an_email_the_words_didnt_ask_for_is_asked_about() -> None:
    host, desktop, _, _ = make(FakeApp("chrome.exe", "document"), said="summarise this page")
    found = await host.call("find_contact", {"query": "lecturer"})
    draft = await host.call("draft_email", {"to": [found.data["candidates"][0]["email"]], "subject": "Thursday",
                                            "message": "I'll miss Thursday."})
    questions = _answering(host, "yes")
    filled = await host.call("fill_in_email", {"draft_id": draft.data["draft_id"]})
    [(question, approval, quote)] = questions
    to, subject, body = desktop.filled[0][1:]
    assert (question, approval) == ("Fill in this email in Gmail?", True)
    assert quote == f"To: {', '.join(to)}\nSubject: {subject}\n\n{body}"  # all of what it fills in
    assert filled.ok and len(desktop.filled) == 1


async def test_a_draft_revised_after_the_question_isnt_filled_in() -> None:
    host, desktop, _, _ = make(FakeApp("chrome.exe", "document"), said="summarise this page")
    found = await host.call("find_contact", {"query": "lecturer"})
    draft = await host.call("draft_email", {"to": [found.data["candidates"][0]["email"]], "subject": "Thursday",
                                            "message": "I'll miss Thursday."})
    draft_id = draft.data["draft_id"]
    assert host.scope is not None
    scope = host.scope
    _answering(host, "yes", then=lambda: scope.drafts.update({draft_id: replace(scope.drafts[draft_id], body="x")}))
    filled = await host.call("fill_in_email", {"draft_id": draft_id})
    assert not filled.ok and "changed" in filled.text and desktop.filled == []


async def test_through_the_session_a_typed_yes_never_writes_and_a_spoken_one_does() -> None:
    session, agent, desktop, _ = session_make(FakeApp("notepad.exe", "edit", route="keys"))
    q = await asked(session, agent, "summarise this page", write=PAGE_SAYS)
    assert (q.text, q.quote) == ("Write this in Notepad?", PAGE_SAYS) and q.approval
    await answer(session, "typed", "yes")
    assert session.dialogue.pending is q and desktop.writes == []
    await answer(session, "spoken")
    await settled(session)
    assert [t for _, t in desktop.writes] == [PAGE_SAYS]
