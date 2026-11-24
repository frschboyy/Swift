"""Swift's guess (IA-01 phase 2; docs/explorations/intent-architecture.md §5.5 P2-1 to P2-8; CLAUDE.md "Swift's guess").

A command the grammar misses gets one question showing every slot a yes runs, never an action. These tests use a
keyword family vote in place of the model (the eval, ``test_intent_eval.py``, runs the real one).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from test_dialogue import asker, asks
from test_runs import say, until
from test_system_lane import NOW, lane

from swift import asking
from swift.ipc.protocol import Message
from swift.parked import ParkedThreads
from swift.routing.rules import guessed, route, with_guess
from swift.system import intents as it
from swift.system import understand as u

FAMILIES = {"minutes": "timer", "clock": "timer", "wifi": "radio", "bluetooth": "radio", "louder": "volume",
            "volume": "volume", "mute": "volume", "brightness": "brightness", "lock": "lock", "google": "search",
            "dark": "theme"}


def family(text: str) -> tuple[str, float]:
    """A stand-in for the classifier's family vote: the first family word in ``text``."""
    return next(((f, 0.9) for w, f in FAMILIES.items() if w in text.lower()), ("other", 0.9))


def _guess(text: str) -> it.Intent | None:
    g = u.propose(text, family)
    return g.intent if g else None


# ---- what may be guessed (P2-1, P2-3, P2-5) ------------------------------------------------------------------


def test_a_command_the_grammar_misses_is_guessed_with_slots_from_the_owners_words() -> None:
    assert _guess("time me for two minutes") == it.Intent("timer.set", {"seconds": 120.0, "label": ""})
    assert _guess("disconnect from the wifi") == it.Intent("radio", {"kind": "wifi", "on": False})
    assert _guess("set a timer for 2 minutes") is None  # the grammar's: not a guess
    assert _guess("take the volume to 30") == it.Intent("volume.set", {"level": 30})  # a level: after "to", no direction
    assert _guess("time me") is None  # no length in the owner's words: never asked for, so no guess (P2-1)
    assert u.propose("time me for two minutes", None) is None  # the classifier isn't loaded


@pytest.mark.parametrize("text", [
    "don't give me ten minutes on the clock", "Time me for two minutes. Cancel that.", "time me for two minutes?",
    "my timer just went off", "I wonder if I should disconnect the wifi", "the video says time me for two minutes",
    "give her ten minutes on the clock", "count down three minutes for Ada", "tell Ada to disconnect the wifi",
    "disconnect the wifi on my router", "time me for two minutes and email Sam", "set a timer four five minutes",
    # The phase 2 review's F1: a verb-led statement, a how-to, "let me", "can you believe", someone addressed, a host.
    "Turn on dark mode is a great feature", "Turn the volume up was the worst advice", "Mute button is broken",
    "Explain how to turn off the wifi", "Show me how to turn on dark mode", "could you explain dark mode",
    "Let me turn the volume down", "Let me turn off the bluetooth", "can you believe the volume went up",
    "Turn the volume down, Sam", "Bring the brightness up you guys", "Turn your volume up for this next song",
    "Turn off bluetooth, scrap that",
    # F2: a direction with a number is neither a level nor a step Swift can read for sure.
    "Turn the volume up 2 notches", "Nudge the volume down 3", "Bring the volume down to 5",
    "turn the brightness up 30",
])
def test_no_guess_for_what_isnt_a_plain_command_for_this_pc(text: str) -> None:
    assert _guess(text) is None


@pytest.mark.parametrize("text", ["lock the computa", "google it for me", "open the bluetooth page"])
def test_lock_search_settings_and_the_rest_are_never_guessed(text: str) -> None:
    assert _guess(text) is None


def test_a_family_not_on_the_list_is_never_guessed() -> None:
    # Whatever the vote says, only PROPOSABLE intents: a new grammar intent isn't guessed until it's listed (P2-5).
    for name in ("lock", "search", "settings", "window", "screenshot", "info", "airplane", "cancel"):
        assert name not in u.PROPOSABLE
    assert u.propose("lock the computa", lambda _t: ("lock", 1.0)) is None
    assert u.propose("time me for two minutes", lambda _t: ("timer", u.GUESS_AT - 0.01)) is None  # too unsure


# ---- who may start one (P2-4) ---------------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["followup", "beside", "answer", "over_speech", "click", None])
def test_a_guess_never_starts_from_a_source_the_owner_didnt_start(source: str | None) -> None:
    found = guessed(with_guess(route("time me for two minutes"), family), source)
    assert found.route == "agent" and found.action != "system_guess"


@pytest.mark.parametrize("source", ["voice", "wake", "typed", "debug.ask", "retry", "correction"])
def test_a_guess_starts_from_the_hotkey_the_wake_phrase_or_typing(source: str) -> None:
    found = guessed(with_guess(route("time me for two minutes"), family), source)
    assert found.route == "local" and found.action == "system_guess"
    assert dict(found.understood)["understood"] == {"act": "command", "source": "similar", "family": ["timer.set"],
                                                    "score": 0.9}  # names and numbers only (P2-8)


# ---- the question (P2-6, P2-7) --------------------------------------------------------------------------------


SAMPLES = [
    (it.Intent("timer.set", {"seconds": 150.0, "label": ""}), ["2 minutes and 30 seconds"]),
    (it.Intent("alarm.set", {"when": it.When(hour=7, meridiem="am", day="tomorrow")}), ["7"]),
    (it.Intent("reminder.set", {"when": it.When(seconds=600.0), "label": "fold the laundry"}),
     ["fold the laundry", "10 minutes"]),
    (it.Intent("volume.step", {"delta": -10}), ["volume", "down", "10"]),
    (it.Intent("volume.set", {"level": 35}), ["volume", "35"]),
    (it.Intent("mute", {"on": False}), ["Unmute"]),
    (it.Intent("media", {"action": "prev"}), ["previous"]),
    (it.Intent("brightness.step", {"delta": 20}), ["brightness", "up", "20"]),
    (it.Intent("brightness.set", {"level": 40}), ["brightness", "40"]),
    (it.Intent("theme", {"dark": False}), ["light"]),
    (it.Intent("dnd", {"on": True}), ["on", "Do not disturb"]),
    (it.Intent("radio", {"kind": "bluetooth", "on": True}), ["on", "Bluetooth"]),
    (it.Intent("radio", {"kind": "wifi", "on": False}), ["off", "Wi-Fi"]),
]


@pytest.mark.parametrize(("intent", "shown"), SAMPLES)
async def test_the_question_shows_every_slot_a_yes_runs(intent: it.Intent, shown: list[str]) -> None:
    system, _control, _sched = lane()
    system.ask_everything = lambda: False
    out = await system.propose(intent)
    assert out.ask == ("yes_no", None) and out.pending == (intent,) and not out.done
    assert all(word in out.said for word in shown), out.said
    assert out.note != asking.NOTE  # not why Swift asks (P2-7)


def test_every_proposable_intent_has_a_sample() -> None:
    assert {i.name for i, _ in SAMPLES} == u.PROPOSABLE


async def test_a_disruptive_guess_asks_the_lanes_one_question() -> None:
    system, _control, _sched = lane()
    out = await system.propose(it.Intent("radio", {"kind": "wifi", "on": False}))
    assert out.said == "Turn off Wi-Fi?" and out.ask == ("yes_no", None)


async def test_a_guess_asks_even_for_what_swift_would_just_do() -> None:
    # Volume is asking.EXEMPT: said exactly, it just changes. Guessed, it asks (P2-7).
    assert "volume.step" in asking.EXEMPT
    system, control, _sched = lane()
    before = control.volume
    out = await system.propose(it.Intent("volume.step", {"delta": 10}))
    assert out.ask == ("yes_no", None) and control.volume == before


async def test_an_alarm_guess_shows_the_day_and_time() -> None:
    system, _control, _sched = lane()
    out = await system.propose(it.Intent("alarm.set", {"when": it.When(hour=7, minute=30, meridiem="am", day="tomorrow")}))
    due = it.resolve(it.When(hour=7, minute=30, meridiem="am", day="tomorrow"), NOW)
    assert due is not None and due - NOW < timedelta(days=2)
    assert out.said == f"Set an alarm at {it.say_when(due, NOW)}?"


# ---- through the session: only a yes runs it (P2-1, P2-2) ------------------------------------------------------


def _session() -> tuple[Any, Any, Any, Any, Any]:
    session, out, _records, agent, stt = asker(parked=ParkedThreads(None), router=lambda t: with_guess(route(t), family))
    session.system, control, sched = lane()
    return session, out, agent, stt, sched


async def _guessed(session: Any, out: Any, stt: Any) -> None:
    await say(session, stt, "Hey Swift, time me for two minutes")
    await until(lambda: asks(out)[-1].get("open") and asks(out)[-1]["question"] == "Set a timer for 2 minutes?")


async def test_a_spoken_yes_runs_the_guess() -> None:
    session, out, _agent, stt, sched = _session()
    await _guessed(session, out, stt)
    assert not sched.items
    await session._take_answer("yes", source="answer")
    await until(lambda: len(sched.items) == 1)
    assert sched.items[0].kind == "timer" and sched.items[0].due - NOW.timestamp() == 120


async def test_a_guess_and_then_a_slot_answer_runs_nothing() -> None:
    # "Five minutes" from the room is no yes: the guess isn't filled and run (P2-1).
    session, out, _agent, stt, sched = _session()
    await _guessed(session, out, stt)
    await session._take_answer("five minutes", source="answer")
    await asyncio.sleep(0.2)
    assert not sched.items


async def test_saying_the_guessed_from_words_again_asks_again() -> None:
    session, out, _agent, stt, sched = _session()
    await _guessed(session, out, stt)
    q = session.dialogue.pending
    await session._take_answer("time me for two minutes", source="answer")
    await asyncio.sleep(0.1)
    assert not sched.items, "the words Swift guessed from approved its guess (P2-2)"
    assert session.dialogue.pending is q and q.reask_text  # asked once more
    await session._take_answer("set a timer for 2 minutes", source="answer")  # the action itself, exactly: a yes
    await until(lambda: len(sched.items) == 1)


async def test_a_typed_yes_never_approves_a_guess() -> None:
    session, out, _agent, stt, sched = _session()
    await _guessed(session, out, stt)
    await session.handle(Message("text", {"text": "yes"}))
    await asyncio.sleep(0.2)
    assert not sched.items
    assert session.dialogue.pending is not None and session.dialogue.pending.reask_text.startswith("Typing can't approve")


async def test_a_guess_heard_in_the_follow_up_window_goes_to_the_agent() -> None:
    session, _out, agent, _stt, sched = _session()
    before = len(agent.requests)
    session._start_beside("time me for two minutes", source="beside")
    await until(lambda: len(agent.requests) == before + 1)
    assert not sched.items and session.dialogue.pending is None
