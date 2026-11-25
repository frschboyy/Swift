"""IA-01 phase 3 (P3-1, R3): a workflow run's grant gets ``system_action`` only from the owner's own words, by grammar."""

from __future__ import annotations

from test_system_phase_a2 import _host_and_scope

from swift.workflows.scope import Grant, with_system

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


def _granted(said: str):  # type: ignore[no-untyped-def]
    host, scope, _, _, asked = _host_and_scope(said)
    scope.grant = with_system(G, said)
    host.scopes.append(scope)
    return host, asked


async def test_the_widened_grant_runs_what_was_named_and_refuses_the_rest_through_the_host() -> None:
    said = "mute the sound and draft an email to Sam"
    host, asked = _granted(said)
    assert (await host.call("system_action", {"request": "mute the sound"})).ok
    refused = await host.call("system_action", {"request": "turn off the wifi"})
    assert not refused.ok and not asked  # not named: refused, and no card
    other = await host.call("desktop_open", {"target": "notepad"})
    assert not other.ok and "doesn't use desktop_open" in other.text  # another tool stays outside the workflow


async def test_no_system_words_means_the_host_refuses_system_action() -> None:
    host, _ = _granted("draft an email to Sam about turning off the wifi")
    result = await host.call("system_action", {"request": "turn off the wifi"})
    assert not result.ok and "doesn't use system_action" in result.text


async def test_a_disruptive_named_intent_still_gets_its_card() -> None:
    host, asked = _granted("turn off the wifi and draft an email to Sam")
    await host.call("system_action", {"request": "turn off the wifi"})
    assert asked


def test_the_session_makes_the_grant_from_the_transcript_not_the_decision_text() -> None:
    # _open_scope gets only the record: the decision's text (carried-over words, "undo that", a resumed playbook)
    # never reaches it. Same workflow, two transcripts.
    from test_playbooks import World

    w = World()
    for transcript, widened in (("email my lecturer saying hello", False), ("mute the sound and email my lecturer", True)):
        match = w.session.library.match(transcript)
        assert match is not None and match.package.name == "email-draft"
        record: dict = {"transcript": transcript, "id": "r1"}
        w.session._open_scope(record, match)
        assert w.session._scope is not None and w.session._scope.grant is not None
        assert ("system_action" in w.session._scope.grant.tools) is widened
