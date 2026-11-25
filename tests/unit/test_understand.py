"""IA-01 phase 1: the one understanding step (src/swift/system/understand.py) and the one splitter."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from swift.routing.rules import route
from swift.runlog import SUMMARY_FIELDS, summary
from swift.system import intents as it
from swift.system.understand import understand
from swift.workflows.system_tools import owner_intents

ROOT = Path(__file__).resolve().parents[2]
ROWS = [json.loads(x) for x in (ROOT / "eval" / "intent" / "cases.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
HA = ["write a note and lock it", "Lock the computer. No wait, don't.", "bluetooth on?"]

# The two splitters before the merge (system_tools._CLAUSE + _intents, intents._SPLIT + parse), kept here as the
# reference the merged one is compared with (review C1-2).
_OLD_SPLIT = re.compile(r"\s+(?:and then|and also|and|then|also|,)\s+|\s*,\s*(?:and |then )?")
_OLD_CLAUSE = re.compile(
    r"\b(?:and then|and also|after that|and|then|also|while|before|after|once|so that|because|but first|first)\b"
)
_OLD_SENTENCE = re.compile(r"(?<=[.!?;])\s+")


def _old_intents(said: str) -> list[it.Intent]:
    whole = it.parse(said)
    if whole is not None:
        return whole
    return [one for s in _OLD_SENTENCE.split(said) for c in _OLD_CLAUSE.split(it.normalize(s))
            if c.strip() and (one := it.parse_one(c)) is not None]


@pytest.mark.parametrize("text", [r["text"] for r in ROWS] + HA)
def test_the_merged_splitter_finds_nothing_the_old_ones_did_not(text: str) -> None:
    assert it.clauses(text) == [p for p in _OLD_SPLIT.split(it.normalize(text)) if p.strip()]
    assert it.clauses(text, loose=True) == [c for s in _OLD_SENTENCE.split(text) for c in _OLD_CLAUSE.split(it.normalize(s)) if c.strip()]
    new = understand(text, each_clause=True).intents or []
    old = _old_intents(text)
    assert all(i in old for i in new)  # the gate may drop, never add


@pytest.mark.parametrize("text", ["bluetooth on?", "wifi on?", "dark mode on?", "is the wifi on?"])
def test_a_question_asks_nothing_but_a_read(text: str) -> None:
    found = understand(text).intents
    assert found is None or all(i.name in ("radio.get",) for i in found)
    assert understand(text).act == "question"


@pytest.mark.parametrize("text", ["can you turn on bluetooth?", "turn off the wifi", "please set a timer for 5 minutes?"])
def test_a_request_with_a_question_mark_still_acts(text: str) -> None:
    assert understand(text).intents is not None and understand(text).act == "command"


@pytest.mark.parametrize("text", ["Lock the computer. No wait, don't.", "set a timer for 5 minutes. Actually cancel that"])
def test_a_retraction_drops_everything(text: str) -> None:
    assert understand(text).intents is None and understand(text).act == "negation"
    assert owner_intents(text) == []


def test_retraction_only_matches_a_clause_that_is_one() -> None:
    assert understand("cancel my timer").intents is not None  # a real intent, not a retraction
    assert understand("turn on do not disturb").intents is not None


def test_the_agent_tool_still_reads_each_clause() -> None:
    assert [i.name for i in owner_intents("Turn the volume down. Write a haiku.")] == ["volume.step"]


def test_a_word_put_back_never_asks_for_a_retracted_request() -> None:
    assert owner_intents("Don't turn off the wafer", ["wifi"]) == []


def test_the_router_carries_the_understanding_on_a_system_route_and_an_agent_one() -> None:
    sysr = dict(route("set a timer for 5 minutes").understood)["understood"]
    assert sysr == {"act": "command", "source": "grammar", "family": ["timer.set"]}
    dead = dict(route("time me for two minutes").understood)["understood"]
    assert dead["source"] is None and dead["family"] == []


def test_the_understood_field_holds_names_only() -> None:
    assert "understood" in SUMMARY_FIELDS
    rec = {"understood": understand("set a timer for 5 minutes called secretpasta").record()}
    line = json.dumps(summary(rec))
    assert "secretpasta" not in line and "300" not in line and "timer.set" in line
    assert set(rec["understood"]) == {"act", "source", "family"}


@pytest.mark.parametrize("text, name", [
    ("No. Turn the volume down.", "volume.step"),
    ("Never mind. Set a timer for 5 minutes.", "timer.set"),
    ("No, no. Lock the computer.", "lock"),
])
def test_a_retraction_takes_back_only_what_came_before_it(text: str, name: str) -> None:
    assert [i.name for i in owner_intents(text)] == [name]  # before phase 1 as well (review F1)


def test_a_request_before_the_retraction_is_taken_back_and_the_one_after_kept() -> None:
    assert [i.name for i in owner_intents("Lock the computer. No wait. Turn the volume down.")] == ["volume.step"]


@pytest.mark.parametrize("text", ["Volume up?", "Timer for 5 minutes?", "Next song?"])
def test_a_verbless_change_with_a_question_mark_is_still_a_request(text: str) -> None:
    assert understand(text).intents is not None and owner_intents(text)
