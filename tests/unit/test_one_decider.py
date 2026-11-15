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
