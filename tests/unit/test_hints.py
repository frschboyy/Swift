"""A10/A11: every phrase a card lists is one Swift's grammar really takes; none is invented."""

from swift import hints
from swift.routing import rules
from swift.settings import ExploreSettings


def test_card_phrases_are_in_the_grammar():
    for text, ok in hints.CARD_PHRASES["confirm"]:
        route = rules.route_midrun(text)
        assert route is not None and route.route == "control", text
        assert not ok  # a card's own words approve or reject that card; they open no other OK
    assert rules.route_midrun("approve").action == "approve"
    assert rules.route_midrun("reject").action == "reject"
    assert rules.route("show me again").action == "show_last"
    assert rules.route("undo that").action == "undo"


def test_verbs_route_as_swift_does():
    by = {v["learn"]: v for v in hints.VERBS}
    assert rules.route(by["show"]["say"]).action == "show_last"
    word = rules.route(by["copy"]["say"])
    assert word.route == "agent"  # a request to the worker, so what it writes asks for an OK first
    assert by["copy"]["ok"] is True and by["show"]["ok"] is False
    assert all(v["say"] and v["label"] for v in hints.VERBS)


def test_explore_off_by_default_and_payload_shape():
    assert ExploreSettings().what_can_i_say is False and ExploreSettings().next_steps is False
    p = hints.for_overlay()
    assert set(p) == {"say", "verbs"} and p["say"]["confirm"][0] == {"text": "approve", "ok": False}
