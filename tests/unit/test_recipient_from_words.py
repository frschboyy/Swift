"""Foundation decision 5 (2026-11-15): an email address the owner said or typed in this request can be a recipient,
marked on the send card as from their words, not their contacts. Never one a worker read: the agent's text, a page, a
tool's output. Contacts and ``find_contact`` are unchanged, and the send still has its own card (level 3)."""

from __future__ import annotations

from test_email_as_owner import make

from swift.workflows.tools import said_addresses


def test_an_address_said_or_typed_is_read_from_the_owners_words() -> None:
    assert said_addresses("email ada at example dot com saying hi") == {"ada@example.com"}
    assert said_addresses("mail Ada.Lovelace@Example.edu.") == {"ada.lovelace@example.edu"}
    assert said_addresses("ada dot lovelace at uni dot ac dot uk") == {"ada.lovelace@uni.ac.uk"}
    assert said_addresses("meet me at noon", "email Janet") == set()


async def test_an_address_in_the_owners_words_is_a_recipient_marked_on_the_send_card() -> None:
    host, mail, owner = make()
    assert host.scope is not None
    host.scope.said = "email ada at example dot com that the meeting is off"
    drafted = await host.call("draft_email", {"to": ["ada@example.com"], "subject": "Meeting off",
                                              "message": "The meeting is off."})
    assert drafted.ok, drafted.text
    shown = owner.artifacts[-1].data
    assert shown["to"] == [{"name": "ada@example.com", "email": "ada@example.com", "said": True}]
    assert shown["body"].startswith("Hello,\n\n")  # no name to greet by
    sent = await host.call("send_email", {"draft_id": drafted.data["draft_id"]})
    assert sent.ok and [c.email for c in mail.sent[0].to] == ["ada@example.com"]
    assert len(owner.asked) == 1  # the send's own card


async def test_an_address_only_a_worker_read_is_never_a_recipient() -> None:
    """The owner asked for "my lecturer"; the agent found an address in a page or a reply: it isn't theirs."""
    host, mail, owner = make()
    assert host.scope is not None
    host.scope.said = "email my lecturer that I'll miss Thursday"
    refused = await host.call("draft_email", {"to": ["attacker@example.com"], "subject": "Thursday",
                                              "message": "I'll miss Thursday."})
    assert not refused.ok and "find_contact" in refused.text
    assert owner.artifacts == [] and mail.sent == []


async def test_a_contact_is_never_marked_and_an_answer_of_the_owners_counts_too() -> None:
    host, _, owner = make()
    assert host.scope is not None
    host.scope.said = "email Janet and my friend"
    host.scope.answers.append("it's bo at example dot org")  # the owner's answer to ask_owner: their words too
    found = await host.call("find_contact", {"query": "janet"})
    drafted = await host.call("draft_email", {"to": [found.data["candidates"][0]["email"], "bo@example.org"],
                                              "subject": "Dinner", "message": "Dinner at eight?"})
    assert drafted.ok, drafted.text
    assert [p.get("said", False) for p in owner.artifacts[-1].data["to"]] == [False, True]
