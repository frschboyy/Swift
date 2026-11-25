"""The intent evaluation set (eval/intent, docs/explorations/intent-architecture.md §4) as a ratchet, and finding
IA-01's dead end reproduced with the fakes: a system action the owner plainly asked for that no path accepts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from test_system_phase_a2 import _host_and_scope

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("intent_score", ROOT / "eval" / "intent" / "score.py")
assert _spec is not None and _spec.loader is not None
score = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(score)

# Lower these when a change improves them; never raise them. The grammar alone: 31 at 7d83958 (2026-11-24).
# With Swift's guess (IA-01 phase 2, the real model's family vote): 17 (2026-11-25). Both counts then grew by 2 with
# two rows the phase 2 review added (rv-14, rv-15: a direction with a number, where no guess is the chosen outcome),
# not by a change getting worse.
NEW_DEAD_END_ROWS = 2
# Phase 3 (the workflow grant) took one off each: radio-c02, "turn off wifi and send Sam an email".
MAX_DEAD_ENDS_GRAMMAR = 30 + NEW_DEAD_END_ROWS
MAX_DEAD_ENDS = 16 + NEW_DEAD_END_ROWS
MAX_FALSE_ACTIONS = 1  # rem-c01: a compound's second half becomes the reminder's label


@pytest.fixture(scope="module")
def family() -> object:
    vote = score.family_vote()
    if vote is None:
        pytest.skip("the classifier's model isn't on this PC (settings.demand_classifier.model_dir)")
    return vote


def _never_worse(s: dict, dead_ends: int) -> None:
    total = s["total"]
    assert total["wrong_confirm"] == 0 and total["wrong_guess"] == 0
    assert total["false_action"] <= MAX_FALSE_ACTIONS
    assert total["dead_end"] <= dead_ends
    # Nothing that isn't a request for this PC acts or gets a guess (P2-3): every one of these rows is correct.
    for kind in ("question", "negation", "statement", "unsupported"):
        assert s["kind"][kind]["correct"] == sum(s["kind"][kind].values()), kind


def test_the_intent_set_never_gets_worse_with_the_grammar_alone() -> None:
    _never_worse(score.score(score.load()), MAX_DEAD_ENDS_GRAMMAR)


def test_the_intent_set_never_gets_worse_with_swifts_guess(family: object) -> None:
    s = score.score(score.load(), family)
    _never_worse(s, MAX_DEAD_ENDS)
    assert s["total"]["asks_guess"] >= MAX_DEAD_ENDS_GRAMMAR - MAX_DEAD_ENDS  # the dead ends fell because Swift asks, not elsewhere


@pytest.mark.xfail(strict=True, reason="IA-01: a phrasing the grammar misses dead-ends on the agent path")
async def test_a_timer_the_owner_asked_for_in_other_words_is_never_a_dead_end() -> None:
    from swift.workflows.system_tools import system_action

    host, scope, _, _, _ = _host_and_scope("time me for two minutes")
    result = await system_action(host, scope, {"request": "set a timer for 2 minutes"})
    assert result.ok  # today: "Not done: the owner didn't ask for that." and the agent may not try another way
