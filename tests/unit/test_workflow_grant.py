"""IA-01 phase 3 (P3-1, R3): a workflow run's grant gets ``system_action`` only from the owner's own words, by grammar."""

from __future__ import annotations

from test_system_phase_a2 import _host_and_scope

from swift.workflows.scope import Grant, with_system
from swift.workflows.system_tools import system_action

G = Grant("email-draft", frozenset({"draft_email", "find_contact"}), frozenset())


def test_a_grammar_match_in_the_owners_words_widens_the_grant() -> None:
    wider = with_system(G, "turn off wifi and send Sam an email")
    assert wider is not None and wider.tools == G.tools | {"system_action"} and wider.capabilities == G.capabilities


def test_no_system_intent_or_no_workflow_leaves_the_grant_alone() -> None:
    assert with_system(G, "draft an email to Sam about turning off the wifi") is G
    assert with_system(None, "mute the sound") is None


def test_a_guess_never_widens_it() -> None:
    # "time me for two minutes" is a timer only by Swift's guess; the grammar doesn't know it (IA-01).
    assert with_system(G, "time me for two minutes and draft an email to Sam") is G


def test_text_a_worker_read_is_not_the_owners_words() -> None:
    # The grant is made from the transcript alone; an email body saying "mute the sound" never reaches it.
    assert with_system(G, "reply to Sam's email") is G


async def test_the_widened_run_still_refuses_what_the_owner_did_not_name() -> None:
    said = "mute the sound and draft an email to Sam"
    assert with_system(G, said).tools >= {"system_action"}  # type: ignore[union-attr]
    host, scope, _, _, _ = _host_and_scope(said)
    result = await system_action(host, scope, {"request": "turn off the wifi"})
    assert not result.ok
