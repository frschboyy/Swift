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

# Measured at 7d83958 (2026-11-24). Lower these when a change improves them; never raise them.
MAX_DEAD_ENDS = 31
MAX_FALSE_ACTIONS = 1  # rem-c01: a compound's second half becomes the reminder's label


def test_the_intent_set_never_gets_worse() -> None:
    total = score.score(score.load())["total"]
    assert total["wrong_confirm"] == 0
    assert total["false_action"] <= MAX_FALSE_ACTIONS
    assert total["dead_end"] <= MAX_DEAD_ENDS


def test_questions_and_negations_never_act() -> None:
    s = score.score(score.load())
    assert s["kind"]["question"]["correct"] == sum(s["kind"]["question"].values())
    assert s["kind"]["negation"]["correct"] == sum(s["kind"]["negation"].values())


@pytest.mark.xfail(strict=True, reason="IA-01: a phrasing the grammar misses dead-ends on the agent path")
async def test_a_timer_the_owner_asked_for_in_other_words_is_never_a_dead_end() -> None:
    from swift.workflows.system_tools import system_action

    host, scope, _, _, _ = _host_and_scope("time me for two minutes")
    result = await system_action(host, scope, {"request": "set a timer for 2 minutes"})
    assert result.ok  # today: "Not done: the owner didn't ask for that." and the agent may not try another way
