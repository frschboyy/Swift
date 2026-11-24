"""A11: every verb a chip offers is one Swift's grammar really takes; none is invented."""

from swift import hints
from swift.routing import rules
from swift.settings import ExploreSettings


def test_verbs_route_as_swift_does():
    by = {v["learn"]: v for v in hints.VERBS}
    assert rules.route(by["show"]["say"]).action == "show_last"
    word = rules.route(by["copy"]["say"])
    assert word.route == "agent"  # a request to the worker, so what it writes asks for an OK first
    assert by["copy"]["ok"] is True and by["show"]["ok"] is False
    assert all(v["say"] and v["label"] for v in hints.VERBS)


def test_explore_off_by_default_and_payload_shape():
    assert ExploreSettings().next_steps is False
    assert "what_can_i_say" not in ExploreSettings.model_fields  # A10 removed (2026-11-24)
    assert hints.for_overlay() == {"verbs": hints.VERBS}
