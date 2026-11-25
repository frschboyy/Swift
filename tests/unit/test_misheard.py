"""Misheard words (IA-01 phase 4; docs/explorations/intent-architecture.md §5.5 P4-1 to P4-4, §5.6 R4 and R5).

A sound-alike of one of Swift's own slot words ("wafer" for Wi-Fi) is Swift's guess: it asks, never acts, and never
counts as the owner asking. A yes to a guess is a candidate example the owner reviews; the pair stays local.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from test_routing import ask
from test_runs import until
from test_system_lane import _session, lane

from swift import runlog
from swift.routing.classifier import load_families
from swift.routing.rules import guessed, route, with_guess
from swift.system import intents as it
from swift.system import understand as u
from swift.workflows.system_tools import owner_intents

ROOT = Path(__file__).resolve().parents[2]

# One request per slot word, with the sound-alike in the slot word's place.
SAID = {"wifi": "turn off the {}", "bluetooth": "turn off the {}", "timer": "set a {} for 2 minutes",
        "minute": "set a timer for 1 {}", "minutes": "set a timer for 2 {}", "dark mode": "turn on {}"}
ALIKES = [(meant, alike) for meant, seen in u.SOUNDS_LIKE.items() for alikes in seen.values() for alike in alikes]


def test_every_slot_word_has_a_request_to_test() -> None:
    assert set(SAID) == set(u.SOUNDS_LIKE)


@pytest.mark.parametrize(("meant", "alike"), ALIKES)
async def test_each_sound_alike_only_asks(meant: str, alike: str) -> None:
    said = SAID[meant].format(alike)
    guess = u.propose(said, None)
    assert guess is not None and guess.heard, said
    assert guess.intent == it.parse(SAID[meant].format(meant))[0]  # type: ignore[index]  # what the words as meant say
    found = guessed(route(said), {"source": "voice"})
    assert found.action == "system_guess" and dict(found.understood)["understood"]["source"] == "heard"
    system, control, sched = lane()
    out = await system.propose(guess.intent)
    assert out.ask == ("yes_no", None) and not out.done and not sched.items
    assert control.radio_state == {"wifi": True, "bluetooth": True}


@pytest.mark.parametrize(("meant", "alike"), ALIKES)
def test_a_sound_alike_never_counts_as_the_owner_asking(meant: str, alike: str) -> None:
    said = SAID[meant].format(alike)
    assert it.parse(said) is None and u.understand(said).intents is None
    assert owner_intents(said) == []


@pytest.mark.parametrize("source", ["followup", "beside", "answer", "over_speech", None])
def test_a_sound_alike_never_guesses_from_a_source_the_owner_didnt_start(source: str | None) -> None:
    assert guessed(route("turn on the wafer"), {"source": source}).route == "agent"


async def test_saying_the_misheard_words_again_asks_again() -> None:
    # The guessed-from words never approve their own guess (P2-2): before phase 4 "turn off the wafer" was a grammar
    # match, so saying it again over "Turn off Wi-Fi?" approved it. Now it asks again.
    session, rec, _spy, _records = await _session()
    await ask("turn off the wafer", session)
    assert rec.last("ask")["question"] == "Turn off Wi-Fi?"
    q = session.dialogue.pending
    await session._take_answer("turn off the wafer", source="answer")
    await asyncio.sleep(0.1)
    assert session.system.control.radio_state["wifi"] is True  # type: ignore[union-attr]
    assert session.dialogue.pending is q and q.reask_text  # asked once more
    await session._take_answer("turn off the wifi", source="answer")  # the action itself, exactly: a yes
    await until(lambda: session.system.control.radio_state["wifi"] is False)  # type: ignore[union-attr]


async def test_a_guessed_on_asks_turn_on() -> None:
    # The deliberate widening (P4-1): a guessed "on" asks too.
    session, rec, _spy, _records = await _session()
    session.system.control.radio_state["wifi"] = False  # type: ignore[union-attr]
    await ask("turn on the wafer", session)
    assert rec.last("ask")["question"] == "Turn on Wi-Fi?"
    assert session.system.control.radio_state["wifi"] is False  # type: ignore[union-attr]


# ---- an unsure word lowers the bar to ask, never fills a slot (P4-4) ------------------------------------------


def _low(text: str) -> tuple[str, float]:
    return ("timer", 0.4)  # under GUESS_AT, over GUESS_UNSURE_AT


@pytest.mark.parametrize(("unclear", "asks"), [
    (None, False), ([], False),
    (["clock"], True),  # unsure of a word no slot is read from: the lower bar
    (["ten"], False),  # unsure of the length the question would show: the usual bar
    (["kettle"], False),  # not a word of this request
])
def test_an_unsure_word_lowers_the_bar_to_ask_only_off_the_slots(unclear: list[str] | None, asks: bool) -> None:
    found = guessed(with_guess(route("give me ten minutes on the clock"), _low), {"source": "voice", "unclear": unclear})
    assert (found.action == "system_guess") is asks


def test_an_unsure_word_never_fills_a_slot() -> None:
    # No length in the owner's words: no guess, however unsure the speech was.
    assert guessed(with_guess(route("give me some on the clock"), _low), {"source": "voice", "unclear": ["clock"]}).route == "agent"


# ---- a yes is a candidate the owner reviews (P4-2, R4), and stays local (P4-3, R5) ----------------------------


def _learn() -> object:
    spec = importlib.util.spec_from_file_location("learn_demand", ROOT / "spikes" / "routing" / "learn_demand.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _yes_to_a_guess() -> dict:
    session, _rec, _spy, records = await _session()
    await ask("turn on the wafer", session)
    await ask("yes", session)
    return next(r for r in records if r.get("confirmed") is True)


async def test_a_yes_adds_a_candidate_never_an_active_example(tmp_path: Path) -> None:
    record = await _yes_to_a_guess()
    learn = _learn()
    candidates = learn.propose_guesses([record], set())  # type: ignore[attr-defined]
    assert [(c["text"], c["family"]) for c in candidates] == [("turn on the wafer", "radio")]
    store = tmp_path / "guess_examples.jsonl"
    before = load_families(learned=[store])
    assert ("turn on the wafer", "radio") not in before  # nothing is kept until the owner keeps it
    learn.append(store, {"text": "turn on the wafer", "family": "radio", "rejected": True})  # type: ignore[attr-defined]
    assert load_families(learned=[store]) == before  # nor when the owner rejects it
    learn.append(store, {"text": "turn on the wafer", "family": "radio"})  # type: ignore[attr-defined]
    assert ("turn on the wafer", "radio") in load_families(learned=[store])
    assert it.parse("turn on the wafer") is None and owner_intents("turn on the wafer") == []  # never the grammar


async def test_the_heard_and_meant_pair_never_reaches_swift_log() -> None:
    record = await _yes_to_a_guess()
    assert record["transcript"] == "turn on the wafer" and record["intents"] == ["radio"]  # the local log's pair
    line = json.dumps(runlog.summary(record), default=str)
    assert "wafer" not in line and runlog.unclassified(record) == set()
    assert dict(record)["understood"] == {"act": "command", "source": "heard", "family": ["radio"], "score": 1.0}


def test_the_pair_goes_into_the_recordings_index(tmp_path: Path) -> None:
    from swift.stt.recordings import Recordings

    clip = "a" * 32
    recs = Recordings(tmp_path / "audio", tmp_path / "test", keep_days=7)
    (tmp_path / "audio").mkdir()
    record = {"id": clip, "source": "voice", "transcript": "turn on the wafer", "audio_file": f"{clip}.wav",
              "confirmed": True, "intents": ["radio"], "status": "done",
              "understood": {"act": "command", "source": "heard", "family": ["radio"], "score": 1.0}}
    recs.note(record)
    entry = next(e for e in recs.entries() if e["id"] == clip)
    assert entry["guessed"] == {"heard": "turn on the wafer", "meant": ["radio"]}
