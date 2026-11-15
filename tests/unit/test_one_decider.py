"""Foundation decision 10: ``intake.approves`` is the one place approval is decided. Every door that can take a
yes or an "approve" asks it, with the channel it really came by, and follows its answer. ``approves`` is patched
to say yes or no; a door that decides by its own rule (OWN-01..03) disagrees with it and fails here."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from swift import intake


def _decider(monkeypatch: pytest.MonkeyPatch, allowed: bool) -> list[tuple[str, bool, int]]:
    """``intake.approves`` patched to ``allowed``; the (source, named, level) of every call."""
    calls: list[tuple[str, bool, int]] = []

    def approves(source: str, *, named: bool, level: int, paying: bool = False) -> intake.Verdict:
        calls.append((source, named, level))
        return intake.Verdict(True) if allowed else intake.Verdict(False, "typed" if source == "typed" else "name")

    monkeypatch.setattr(intake, "approves", approves)
    return calls


@pytest.mark.parametrize(("source", "named"), [("beside", False), ("beside", True), ("voice", False)])
async def test_mid_run_words_reach_the_decider_by_their_real_channel(monkeypatch: pytest.MonkeyPatch, source: str,
                                                                     named: bool) -> None:
    """The second review's note (2026-11-15): ``_midrun_text`` turned a hands-free "beside" into "voice", so a
    hands-free yes counted as a gesture. Harmless at level 1, wrong for any question above it."""
    from test_runs import finish_all
    from test_seam_replay import _lane, _wifi

    session, out, agent, stt, control, _ = _lane()
    await _wifi(session, out, stt)
    calls = _decider(monkeypatch, True)
    await session._midrun_text("yes", session._run_phase, source=source, named=named)
    await asyncio.sleep(0.05)
    assert calls == [(source, named, 1)], calls
    assert control.radio_state["wifi"] is False
    await finish_all(session, agent)


@pytest.mark.parametrize("allowed", [True, False])
@pytest.mark.parametrize("said", ["yes", "Swift, yes"])
async def test_a_hands_free_yes_to_the_correction_offer_is_what_approves_says(monkeypatch: pytest.MonkeyPatch,
                                                                             allowed: bool, said: str) -> None:
    """OWN-03: ``_hear_busy`` took "Swift, yes" for the correction offer by its own condition (the name said),
    and ignored a plain "yes" before ``approves`` was asked."""
    from test_front_rules import _correction_offered
    from test_runs import finish_all, say, until

    session, out, agent, stt, _other = await _correction_offered()
    before = len(agent.requests)
    calls = _decider(monkeypatch, allowed)
    await say(session, stt, said)
    if allowed:
        await until(lambda: len(agent.requests) == before + 1)
    else:
        await until(lambda: calls)
        await asyncio.sleep(0.05)
        assert len(agent.requests) == before and session._fix_offer is not None
    assert calls == [("beside", said.startswith("Swift"), 1)], calls
    await finish_all(session, agent)


CARD_DOORS = {  # how an "approve" reaches an open confirm card: (the words, the source and named approves sees)
    "the hotkey held": ("approve", ("voice", False)),  # a gesture: foundation decision 3
    "hands-free": ("Swift, approve.", ("beside", True)),
    "typed": ("Swift, approve", ("typed", True)),
}


@pytest.mark.parametrize("allowed", [True, False])
@pytest.mark.parametrize("door", list(CARD_DOORS))
async def test_an_approve_on_a_card_is_what_approves_says(monkeypatch: pytest.MonkeyPatch, door: str,
                                                          allowed: bool) -> None:
    """The push-to-talk card door (_answer_by_voice -> _answer_text) approved without asking ``approves``; the
    typed and hands-free doors each asked it before ``_answer_text``. Now ``_answer_text`` asks, for all three."""
    from test_hands_free import say
    from test_intake import _card, _decided

    from swift.ipc.protocol import Message

    session, out, records, stt, rid = await _card()
    words, seen = CARD_DOORS[door]
    calls = _decider(monkeypatch, allowed)
    if door == "typed":
        await session.handle(Message("text", {"text": words}))
    elif door == "hands-free":
        await say(session, stt, words)
    else:
        stt.text = words
        await session.handle(Message("ptt", {"state": "down"}))
        await asyncio.sleep(0.05)
        await session.handle(Message("ptt", {"state": "up"}))
    decision = await _decided(session, records, rid)
    assert (decision == "approve") is allowed, (door, decision)
    assert calls == [(*seen, intake.CARD)], calls
