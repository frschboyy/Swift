"""Owner checks of 2026-10-27, 17:00: calendar changes named by title go to the calendar
workflow (on the light model), and an email's follow-ups keep the subject a summary and the
body the message.

Calendar: "Move swift check to two p.m.", "Add a Google Meet link to Swift check", "Change swift
check to three p.m." and "Cancel Swift Check" all went to the general agent (one took 148 s and
ran `git status`), and misheard titles ("swift deck", "Flift Tech") weren't found.

Email: "email myself" then "The email should ask me how I am doing today…", "Can you send it for
me?" and "actually say that I am not coming" each started without the draft before it, outside
the email workflow. Fakes only: nothing is sent, added or typed anywhere.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pytest

from swift.connectors.base import CalendarEvent, StoredEvent
from swift.executors.mock import Call, Finish
from swift.ipc.protocol import Message
from swift.routing.rules import route
from swift.workflows.library import likeness, load_library
from swift.workflows.scope import RunScope
from swift.workflows.tools import KnownContact

from test_playbooks import World, calls

ME = KnownContact("Francis Chianu", "francis@example.com", ("myself", "me"))
TITLES = ("Swift check", "Lunch with Ada")


def swift_check() -> StoredEvent:
    start = (datetime.now() + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0).astimezone()
    return StoredEvent("ev-swift", CalendarEvent("Swift check", start, start + timedelta(minutes=30)))


class Demands(World):
    """The World of test_playbooks, keeping the model each request started on."""

    def __init__(self) -> None:
        super().__init__()
        self.tools.contacts = (*self.tools.contacts, ME)
        self.demands: list[str | None] = []
        start = self.provider.start

        async def started(request: str, scenario: str | None = None, *, demand: str | None = None,
                          override: str | None = None) -> str:
            self.demands.append(demand)
            return await start(request, scenario, demand=demand, override=override)

        self.provider.start = started  # type: ignore[method-assign]

    async def follow_up(self, text: str, approve: bool | None = None) -> dict[str, Any]:
        """Said in the reply window after Swift answered: the same thread (source "followup")."""
        self.out.confirm.clear()

        async def capture(record: dict[str, Any]) -> str:
            return text

        self.session._launch({"executor": "mock", "source": "followup"}, capture, self.provider, self.provider.start)
        task = self.session._task
        assert task is not None
        if approve is not None:
            await asyncio.wait_for(self.out.confirm.wait(), 2)
            card = self.out.last("confirm.request")
            decision = "approve" if approve else "reject"
            await self.session.handle(Message("confirm.reply", {"request_id": card["request_id"], "decision": decision}))
        await asyncio.wait_for(task, 2)
        return self.records[-1]


# ---- calendar: routed to the calendar workflow -------------------------------------------------


@pytest.mark.parametrize("said", [
    "Move swift check to two p.m.",
    "Move swift check to two PM",
    "Add a Google Meet link to Swift check",
    "Change swift check to three p.m.",
    "Cancel Swift Check.",
    # Misheard titles: found by how they sound.
    "Move swift deck to two p.m.",
    "Add a Google Meet link to Flift Tech.",
    "cancel swift deck",
    "Hey Swift, delete Swift check",
    "reschedule swift check",
    "push swift check to Friday",
])
def test_calendar_changes_named_by_title_run_the_calendar_workflow(said: str) -> None:
    match = load_library(None).match(said, TITLES)
    assert match is not None and (match.package.name, match.kind) == ("calendar-event", "run"), said
    assert route(said).route == "agent", said  # not a control word


def test_a_new_time_is_enough_without_knowing_the_title() -> None:
    library = load_library(None)
    for said in ("Move swift check to two p.m.", "Change swift check to three p.m.", "push the review to Friday",
                 "move it to 14:00"):
        match = library.match(said)
        assert match is not None and match.package.name == "calendar-event", said


@pytest.mark.parametrize("said", [
    "cancel the order", "delete the file", "change the font to 12", "move the file to downloads",
    "push the branch to origin", "remove the event listener in main.ts", "update the function call in session.py",
    "cancel my uber", "what is a meeting",
])
def test_other_requests_still_dont_run_it(said: str) -> None:
    match = load_library(None).match(said, TITLES)
    assert match is None or match.package.name != "calendar-event" or match.kind != "run", said


def test_cancel_and_stop_alone_still_stop_a_run() -> None:
    for said in ("cancel", "Cancel.", "stop", "cancel it", "never mind"):
        assert route(said).route == "control", said
    assert route("Cancel Swift Check.").route == "agent"
    assert load_library(None).match("cancel", TITLES) is None


def test_misheard_titles_sound_alike() -> None:
    assert likeness("swift deck", "Swift check") > 0.8
    assert likeness("Flift Tech", "Swift check") >= 0.5
    assert likeness("the file", "Swift check") < 0.5


def test_the_calendar_workflow_starts_on_the_light_model() -> None:
    assert load_library(None).packages["calendar-event"].demand == "light"
    assert load_library(None).packages["email-draft"].demand is None


async def test_list_finds_an_event_by_a_misheard_title() -> None:
    w = World()
    w.calendar.store["ev-swift"] = swift_check()
    scope = w.tools.open(_publish, _confirm)
    for heard in ("swift deck", "Flift Tech"):
        result = await w.tools.call("list_calendar_events", {"query": heard})
        events = result.data["events"]
        assert [e["title"] for e in events] == ["Swift check"] and events[0]["sounds_like"] == heard, heard
        assert "sound like it" in result.text
    assert "ev-swift" in scope.events  # so it can be changed or removed after
    nothing = await w.tools.call("list_calendar_events", {"query": "dentist"})
    assert nothing.data["events"] == []


async def test_titles_come_from_the_calendar_and_from_runs() -> None:
    w = World()
    w.calendar.store["ev-swift"] = swift_check()
    assert w.tools.known_titles() == ()  # asked for in the background
    assert w.tools._titles_task is not None
    await w.tools._titles_task
    assert w.tools.known_titles() == ("Swift check",)
    w.tools.saw_titles("Dentist")
    assert set(w.tools.known_titles()) == {"Swift check", "Dentist"}


@pytest.mark.parametrize("said", ["Cancel Swift Check.", "Move swift deck to two p.m.",
                                  "Add a Google Meet link to Swift check"])
async def test_session_runs_calendar_changes_in_the_workflow_on_the_light_model(said: str) -> None:
    w = Demands()
    w.calendar.store["ev-swift"] = swift_check()
    await w.tools.refresh_titles()
    w.provider.script = calls(("list_calendar_events", {"query": "swift check"}))
    record = await w.ask(said)
    assert record["workflow"] == "calendar-event" and record["route"] == "agent"
    assert w.demands[-1] == "light" and record["demand"] == "light"
    assert w.provider.requests[-1].startswith("[Swift workflow: Calendar events (calendar-event 2.1.0)]")


async def test_a_named_model_still_wins() -> None:
    w = Demands()
    w.calendar.store["ev-swift"] = swift_check()
    await w.tools.refresh_titles()
    record = await w.ask("use opus to cancel Swift check")
    assert record["workflow"] == "calendar-event" and record.get("override") == "opus"


# ---- email: the subject a summary, the body the message ------------------------------------------


def _me(done: dict[str, Any]) -> list[str]:
    return [done["find_contact"].data["candidates"][0]["email"]]


async def test_content_given_in_a_follow_up_goes_in_the_body_not_the_subject() -> None:
    """18:09: "email myself", then "The email should ask me how I am doing today…"."""
    w = Demands()
    w.provider.script = (Call("find_contact", {"query": "myself"}, "find_contact"),
                         Finish("I found you. What should it say?"))
    first = await w.ask("email myself.")
    assert first["workflow"] == "email-draft"
    said = "The email should ask me how I am doing today and what I have done today."
    # (The instruction itself as the subject is refused: test_a_subject_that_is_the_message_is_refused.)
    w.provider.script = (
        Call("draft_email", {"to": ["francis@example.com"], "subject": "Checking in",
                             "message": "How are you doing today, and what have you done today?"}, "draft_email"),
        Call("fill_in_email", lambda done: {"draft_id": done["draft_email"].data["draft_id"], "app": "gmail"},
             "fill_in_email"),
        Finish("It's ready in Gmail."),
    )
    second = await w.follow_up(said)
    assert second["workflow"] == "email-draft" and second["thread"] == first["thread"]
    # The contact found before is still resolved: no second find_contact needed.
    app, to, subject, body = w.desktop.filled[-1]
    assert to == ["francis@example.com"] and subject == "Checking in"
    assert body == "Hello Francis,\n\nHow are you doing today, and what have you done today?\n\nRegards,"


async def test_send_it_sends_the_draft_before_in_the_email_workflow() -> None:
    """18:16:21: "Can you send it for me?" after a draft was filled in."""
    w = Demands()
    w.provider.script = calls(
        ("find_contact", {"query": "Francis Chianu"}),
        ("draft_email", lambda done: {"to": _me(done), "subject": "Running late",
                                      "message": "I wanted to let you know that I'm running late."}),
        ("fill_in_email", {"draft_id": "draft-1", "app": "gmail"}),
    )
    await w.ask("email Francis Chianu that I am running late.")
    w.provider.script = calls(("send_email", {"draft_id": "draft-1"}))
    record = await w.follow_up("Can you send it for me?", approve=True)
    assert record["workflow"] == "email-draft"  # not the general agent
    request = w.provider.requests[-1]
    assert "email draft draft-1 to Francis Chianu <francis@example.com>, subject “Running late”" in request
    assert "message: I wanted to let you know that I'm running late." in request
    assert "Hello Francis" not in request.split("message:")[1].split("(")[0]  # no greeting to write twice
    [sent] = w.mail.sent
    assert sent.subject == "Running late"
    assert sent.body == "Hello Francis,\n\nI wanted to let you know that I'm running late.\n\nRegards,"


async def test_a_correction_rewrites_the_body_and_keeps_the_subject() -> None:
    """18:16:52: "actually say that I am not coming"."""
    w = Demands()
    w.provider.script = calls(
        ("find_contact", {"query": "Francis Chianu"}),
        ("draft_email", lambda done: {"to": _me(done), "subject": "Running late",
                                      "message": "I wanted to let you know that I'm running late."}),
        ("fill_in_email", {"draft_id": "draft-1", "app": "gmail"}),
    )
    await w.ask("email Francis Chianu that I am running late.")
    w.provider.script = calls(
        ("draft_email", {"draft_id": "draft-1", "message": "I'm sorry, but I won't be coming."}),
        ("fill_in_email", {"draft_id": "draft-1", "app": "gmail"}),
    )
    record = await w.follow_up("actually say that I am not coming.")
    assert record["workflow"] == "email-draft"
    app, to, subject, body = w.desktop.filled[-1]
    assert subject == "Running late" and to == ["francis@example.com"]
    assert body == "Hello Francis,\n\nI'm sorry, but I won't be coming.\n\nRegards,"


async def test_a_sent_draft_isnt_sent_twice_by_a_follow_up() -> None:
    w = Demands()
    w.provider.script = calls(
        ("find_contact", {"query": "Francis Chianu"}),
        ("draft_email", lambda done: {"to": _me(done), "subject": "Running late", "message": "I'm running late."}),
        ("send_email", {"draft_id": "draft-1"}),
    )
    await w.ask("email Francis Chianu that I am running late and just send it", approve=True)
    w.provider.script = calls(("send_email", {"draft_id": "draft-1"}))
    await w.follow_up("send it again")
    assert len(w.mail.sent) == 1


async def test_a_new_request_starts_without_the_draft_before() -> None:
    w = Demands()
    w.provider.script = calls(
        ("find_contact", {"query": "Francis Chianu"}),
        ("draft_email", lambda done: {"to": _me(done), "subject": "Running late", "message": "I'm running late."}),
    )
    await w.ask("email Francis Chianu that I am running late.")
    w.provider.script = calls(("send_email", {"draft_id": "draft-1"}))
    record = await w.ask("send draft one")  # typed fresh: a new thread
    assert w.mail.sent == [] and "workflow" not in record


# ---- draft_email itself ----------------------------------------------------------------------------


@pytest.mark.parametrize("subject", ["I am not coming", "I'm running late", "Hello Francis",
                                     "The email should ask how I am"])
async def test_a_subject_that_is_the_message_is_refused(subject: str) -> None:
    w = World()
    w.tools.open(_publish, _confirm)
    await w.tools.call("find_contact", {"query": "my lecturer"})
    result = await w.tools.call("draft_email", {"to": ["ada.lovelace@example.edu"], "subject": subject,
                                                "message": "I won't be coming today."})
    assert not result.ok and "subject" in result.text.lower(), subject


async def test_a_revision_keeps_the_subject_and_recipients() -> None:
    w = World()
    scope = w.tools.open(_publish, _confirm)
    await w.tools.call("find_contact", {"query": "my lecturer"})
    await w.tools.call("draft_email", {"to": ["ada.lovelace@example.edu"], "subject": "Running late",
                                       "message": "I'm running late."})
    result = await w.tools.call("draft_email", {"draft_id": "draft-1", "message": "I'm not coming."})
    assert result.ok and result.data == {"draft_id": "draft-1", "version": 2}
    draft = scope.drafts["draft-1"]
    assert draft.subject == "Running late" and [c.email for c in draft.to] == ["ada.lovelace@example.edu"]
    assert draft.body == "Hello Dr Lovelace,\n\nI'm not coming.\n\nRegards,"
    missing = await w.tools.call("draft_email", {"draft_id": "draft-9", "message": "Hi"})
    assert not missing.ok and "draft-9" in missing.text
    new = await w.tools.call("draft_email", {"message": "Hi there."})
    assert not new.ok  # a new draft still needs recipients and a subject


def test_a_scope_goes_on_from_the_one_before() -> None:
    before = RunScope(_publish, _confirm)
    next(before.ids)
    before.sent.add("digest")
    after = RunScope(_publish, _confirm)
    after.carry_from(before)
    assert next(after.ids) == 2 and after.sent == {"digest"}


async def _publish(artifact: Any) -> None:
    return None


async def _confirm(*args: Any) -> bool:
    return True
