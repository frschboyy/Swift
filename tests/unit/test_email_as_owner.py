"""Drafts read as the owner wrote them (owner check 37, 2026-10-27): a short subject, and a body
from the owner to the recipient with a greeting and the owner's name. Also: contacts found in
Google show a detail to choose by, and outcomes the owner decides aren't counted as the model failing.
"""

from __future__ import annotations

from typing import Any

from test_workflows import LECTURER, Owner

from swift.connectors.base import Contact
from swift.connectors.fake import FakeMailConnector
from swift.security.gateway import ActionGateway
from swift.security.journal import Journal
from swift.workflows.tools import ToolHost, compose, greeting, message_only

JANET = Contact("Janet Okafor", "j.okafor@uni.example", "gmail", "you've emailed them")


def make(owner_name: str = "", google_name: str = "", decision: str = "approve",
         contacts: tuple[Contact, ...] = (JANET,)) -> tuple[ToolHost, FakeMailConnector, Owner]:
    mail = FakeMailConnector(contacts=contacts, owner=google_name)
    host = ToolHost(mail, (LECTURER,), ActionGateway(Journal(None)), owner_name=owner_name)
    owner = Owner(decision)
    host.open(owner.publish, owner.confirm)
    return host, mail, owner


async def draft(host: ToolHost, **args: Any) -> Any:
    found = await host.call("find_contact", {"query": "janet"})
    return await host.call("draft_email", {"to": [found.data["candidates"][0]["email"]], **args})


async def test_the_draft_greets_the_recipient_and_is_signed_with_the_google_name() -> None:
    host, mail, owner = make(google_name="Francis Chianu")
    result = await draft(host, subject="Meeting cancelled", message="I wanted to let you know that the meeting is off.")
    assert result.ok, result.text
    shown = owner.artifacts[-1].data
    assert shown["subject"] == "Meeting cancelled"
    assert shown["body"] == ("Hello Janet,\n\nI wanted to let you know that the meeting is off.\n\n"
                             "Regards,\nFrancis Chianu")
    sent = await host.call("send_email", {"draft_id": result.data["draft_id"]})
    assert sent.ok and mail.sent[0].body.endswith("Regards,\nFrancis Chianu")


async def test_the_name_in_config_wins_over_the_google_account() -> None:
    host, _, owner = make(owner_name="Francis", google_name="Francis Chianu")
    await draft(host, subject="Running late", message="I'm running about ten minutes late.")
    assert owner.artifacts[-1].data["body"].endswith("Regards,\nFrancis")


async def test_the_content_never_lands_in_the_subject() -> None:
    """Check 37: the whole message was the subject."""
    host, _, owner = make()
    message = "I wanted to let you know that the meeting this afternoon is off, sorry for the short notice."
    long_subject = await draft(host, subject=message, message=message)
    assert not long_subject.ok and "few words" in long_subject.text
    same = await draft(host, subject="The meeting is off", message="The meeting is off.")
    assert not same.ok and "repeats the message" in same.text
    missing = await draft(host, subject="", message="The meeting is off.")
    assert not missing.ok and "subject" in missing.text
    assert [a.kind for a in owner.artifacts] == ["recipient"] * 3  # no draft was shown


async def test_a_greeting_and_sign_off_from_the_model_are_not_doubled() -> None:
    host, _, owner = make(google_name="Francis Chianu")
    await draft(host, subject="Meeting cancelled",
                message="Hi Janet,\n\nThe meeting is off today.\n\nBest regards,\nFrancis")
    assert owner.artifacts[-1].data["body"] == "Hello Janet,\n\nThe meeting is off today.\n\nRegards,\nFrancis Chianu"


async def test_a_revision_keeps_the_greeting_and_sign_off() -> None:
    host, _, owner = make(google_name="Francis Chianu")
    first = await draft(host, subject="Meeting cancelled", message="The meeting is off.")
    await host.call("draft_email", {"to": [JANET.email], "subject": "Meeting moved",
                                    "message": "The meeting has moved to Friday.", "draft_id": first.data["draft_id"]})
    revised = owner.artifacts[-1]
    assert revised.version == 2
    assert revised.data["body"] == "Hello Janet,\n\nThe meeting has moved to Friday.\n\nRegards,\nFrancis Chianu"


async def test_the_older_body_argument_still_works() -> None:
    host, _, owner = make()
    result = await draft(host, subject="Thursday", body="I'll miss Thursday.")
    assert result.ok and owner.artifacts[-1].data["body"] == "Hello Janet,\n\nI'll miss Thursday.\n\nRegards,"


def test_greetings() -> None:
    assert greeting((Contact("Dr Ada Lovelace", "a@x.edu"),)) == "Hello Dr Lovelace,"
    assert greeting((JANET, Contact("Ada Lovelace", "a@x.edu"))) == "Hello Janet and Ada,"
    assert greeting((Contact("a@x.edu", "a@x.edu"),)) == "Hello,"


def test_message_only_keeps_a_sentence_that_starts_like_a_greeting() -> None:
    assert message_only("Hello again, the meeting is off.") == "Hello again, the meeting is off."
    assert message_only("Thanks for yesterday.\nThe meeting is off.") == "Thanks for yesterday.\nThe meeting is off."
    assert compose((JANET,), "Thanks!", "F") == "Hello Janet,\n\nThanks!\n\nRegards,\nF"


# ---- choosing between contacts -----------------------------------------------


async def test_several_matches_are_told_apart_by_email_and_a_detail() -> None:
    other = Contact("Janet Bloggs", "jb@shop.example", "gmail", "Shop Ltd")
    host, _, owner = make(contacts=(JANET, other))
    found = await host.call("find_contact", {"query": "janet"})
    assert found.ok and "<j.okafor@uni.example>, you've emailed them" in found.text
    assert "<jb@shop.example>, Shop Ltd" in found.text
    assert [c.get("detail") for c in owner.artifacts[-1].data["candidates"]] == ["you've emailed them", "Shop Ltd"]


async def test_nobody_found_is_an_outcome_not_a_failure() -> None:
    host, _, _ = make(contacts=())
    missing = await host.call("find_contact", {"query": "janet"})
    assert not missing.ok and missing.expected and "Don't guess" in missing.text


async def test_the_owner_saying_no_or_asking_for_a_change_is_expected() -> None:
    host, _, _ = make(decision="reject")
    first = await draft(host, subject="Meeting cancelled", message="The meeting is off.")
    rejected = await host.call("send_email", {"draft_id": first.data["draft_id"]})
    assert not rejected.ok and rejected.expected
    host, _, _ = make(decision="revise")
    assert host.scope is not None
    host.scope.feedback = "use the same contact name"
    first = await draft(host, subject="Meeting cancelled", message="The meeting is off.")
    revise = await host.call("send_email", {"draft_id": first.data["draft_id"]})
    assert not revise.ok and revise.expected and "use the same contact name" in revise.text