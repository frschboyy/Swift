"""The dialogue as a model on a virtual clock (seams audit 2026-11, layer C).

Hypothesis drives a real ``Session`` (the test provider that asks or shows a card, the system lane,
a fake voice and microphone, and an overlay that reports each card drawn) with random sequences of
what happens in a day:
- a request that asks something, one with a card, a lane question;
- Swift finishing saying it;
- an answer said, or a question or card clicked;
- something said that stops mid-thought;
- the screen locking and unlocking;
- requests ending, and time passing.

Time is virtual (tests/virtual_clock.py), so a 25 s answer window runs out in microseconds and every
run is reproducible.

After every step these must hold:
- LOCKED: nothing heard acts while the screen is locked (threat model T7; T-07);
- APPROVE: no card approved except by "Swift, approve" / "Swift, yes" or a click;
- OWN_DEADLINE: a question waiting for its answer has one live deadline, and it is its own;
- DEADLINE: the overlay counts down to the backend's deadline, to 0.2 s.

Once everything is let go and time runs on:
- ENDS: every request has ended;
- CLOSED, CARDS: layer A's ``Dialogue`` holds over all the frames.

A failure prints the shortest sequence of steps that breaks it. Findings still open are in ``KNOWN``:
each names its audit ID and is replayed to check it still fails, so a fix shows up here too.

A longer search, at random (a few minutes):
    SWIFT_MODEL_RANDOM=1 SWIFT_MODEL_EXAMPLES=3000 uv run pytest tests/unit/test_dialogue_model.py
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule
from protocol_contract import Dialogue
from virtual_clock import VirtualLoop

from swift.ipc.protocol import Message
from swift.parked import ParkedThreads
from swift.speech import FakeSpeaker

QUESTION_S = 25.0
ANSWERS = ("Paris", "the second one", "Rome please", "Swift, yes", "yes", "no", "no, leave it", "um",
           "what time is it", "Swift, stop", "turn off the wifi", "approve", "Swift, approve", "Swift, approve and",
           "Hey Swift, remind me to call Sam and")


class Problem(AssertionError):
    def __init__(self, finding: str, text: str) -> None:
        super().__init__(f"{finding}: {text}")
        self.finding = finding


class DialogueModel(RuleBasedStateMachine):
    # Which findings' checks run (each check names the audit finding it guards).
    checks: frozenset[str] = frozenset()
    # Open findings whose known trigger the steps leave out, so the checks still run everywhere else.
    avoid: frozenset[str] = frozenset()

    def _asked(self) -> str | None:
        """Whose question waits on screen: "run", "lane" or None."""
        q = self.session.dialogue.pending
        return None if q is None else q.source

    def _steered(self, finding: str, trigger: bool) -> bool:
        """True: leave this step out, it would only show ``finding`` (still open) again."""
        return finding in self.avoid and trigger

    def _problem(self, finding: str, text: str) -> None:
        if finding in self.checks:
            raise Problem(finding, text)

    def __init__(self) -> None:
        super().__init__()
        self.loop = VirtualLoop()
        self.stamped: list[tuple[float, Message]] = []
        self.locked = False
        # When the screen locked: the requests there were (one said in full before it may still start,
        # queued behind another), and how many answers and hands-free commands had been taken.
        self.at_lock: tuple[set[int], int] | None = None
        self.said_before_lock: set[int] = set()
        # Approvals the owner gave: "Swift, approve" said, or Approve clicked, while a card was open.
        self.approvals_given = 0
        self.loop.run_until_complete(self._make())

    async def _make(self) -> None:
        from test_dialogue import asker
        from test_system_lane import lane

        self.session, self.out, self.records, self.agent, self.stt = asker(
            wake_question_s=QUESTION_S, parked=ParkedThreads(None))
        self.session.system, _, _ = lane()
        self.speaker = FakeSpeaker()
        self.session.speaker, self.speaker.on_done = self.speaker, self.session.speech_done
        send = self.session._raw_send

        async def stamped(msg: Message) -> None:
            self.stamped.append((self.loop.time(), msg))
            await send(msg)
            # Like the overlay: a card it draws is reported seen, so its countdown runs (ADR-015 §4.2).
            shown = msg.type == "confirm.request" or (msg.type == "confirm.hold" and not msg.data.get("held"))
            if shown:
                seen = Message("card.seen", {"request_id": msg.data["request_id"], "visible": True})
                self.session._background(self.session.handle(seen))

        self.session._raw_send = stamped

    # ---- driving ------------------------------------------------------------------------------

    def _run(self, coro: Any) -> Any:
        return self.loop.run_until_complete(coro)

    async def _settle(self) -> None:
        for _ in range(30):
            await asyncio.sleep(0)
        await asyncio.sleep(0.05)  # the short holds (end of a sentence) fire too

    async def _say(self, text: str) -> None:
        from test_runs import SHORT

        if not self.locked and self.session._open_confirm() is not None and text.lower().startswith(("swift, approve", "swift, yes")):
            self.approvals_given += 1
        self.stt.text = text
        await self.session.hear_wake(SHORT, self.loop.time())
        await self._settle()

    def _heard(self) -> tuple[set[int], int]:
        stats = self.session.wake_stats
        return {id(r) for r in self.session._runs}, stats["answer"] + stats["hands_free"] + stats["short_answer"]

    def _started_while_locked(self) -> list[Any]:
        """Requests that started after the lock from something heard. Every request here starts from
        something heard (nothing is typed), except what was said in full before the lock and carried
        out after it: one that waited for a free slot (``_queue_wake``), or a change said on a card,
        run once its request ended."""
        assert self.at_lock is not None
        new = [r for r in self.session._runs if id(r) not in self.at_lock[0]]
        for r in new:  # remembered: a request's record is replaced when it ends
            if (r.record or {}).get("queued_behind") or (r.record or {}).get("source") == "correction":
                self.said_before_lock.add(id(r))
        return [r for r in new if id(r) not in self.said_before_lock]

    def _live_runs(self) -> list[Any]:
        return [r for r in self.session._runs if r.task is not None and not r.task.done()]

    # ---- rules ------------------------------------------------------------------------------

    @precondition(lambda self: len(self.agent.requests) < 3)
    @rule()
    def a_request_that_asks(self) -> None:
        self._run(self._say("Hey Swift, plan the trip and ask me where"))

    @precondition(lambda self: len(self.agent.requests) < 3)
    @rule()
    def a_request_with_a_card(self) -> None:
        self._run(self._say("Hey Swift, tidy the notes card"))
        for run in self.agent.runs.values():
            run["ask"].set()
        self._run(self._settle())

    @precondition(lambda self: not self.locked)  # nothing to click on a locked screen
    @rule(decision=st.sampled_from(("approve", "reject")))
    def a_click_on_the_card(self, decision: str) -> None:
        request_id = self.session._open_confirm()
        if request_id is None:
            return
        if decision == "approve":
            self.approvals_given += 1
        self._run(self.session.handle(Message("card.seen", {"request_id": request_id, "visible": True})))
        self._run(self.session.handle(Message("confirm.reply", {"request_id": request_id, "decision": decision})))
        self._run(self._settle())

    @rule()
    def a_lane_question(self) -> None:
        self._run(self._say("Hey Swift, turn off the wifi"))

    @rule()
    def swift_finishes_speaking(self) -> None:
        async def finish() -> None:
            self.speaker.finish()
            await self._settle()

        self._run(finish())

    @rule(text=st.sampled_from(ANSWERS))
    def something_said(self, text: str) -> None:
        self._run(self._say(text))

    @precondition(lambda self: not self.locked)  # nothing to click on a locked screen
    @rule(pick=st.sampled_from(("Paris", "Rome", "Yes", "No")))
    def a_click_on_the_question(self, pick: str) -> None:
        shown = self._open_asks()
        if not shown:
            return
        ask_id = sorted(shown)[-1]
        self._run(self.session.handle(Message("ask.reply", {"ask_id": ask_id, "text": pick})))
        self._run(self._settle())

    @precondition(lambda self: not self.locked)
    @rule()
    def lock(self) -> None:
        self.locked = True
        self.at_lock = self._heard()
        self.session.listening_paused = self.session.hands_free_blocked = True
        self._run(self.session.hold_cards(True))
        self._run(self._settle())

    @precondition(lambda self: self.locked)
    @rule()
    def unlock(self) -> None:
        self.locked = False
        self.session.listening_paused = self.session.hands_free_blocked = False
        self._run(self.session.hold_cards(False))
        self._run(self._settle())

    @rule()
    def requests_end(self) -> None:
        for run in self.agent.runs.values():
            run["go"].set()
        self._run(self._settle())

    @rule(seconds=st.sampled_from((0.5, 2.0, 10.0, QUESTION_S - 1, QUESTION_S + 1, 60.0)))
    def time_passes(self, seconds: float) -> None:
        self._run(asyncio.sleep(seconds))
        self._run(self._settle())

    # ---- invariants ---------------------------------------------------------------------------

    def _open_asks(self) -> dict[str, dict[str, Any]]:
        shown: dict[str, dict[str, Any]] = {}
        for _, m in self.stamped:
            if m.type == "ask":
                if m.data.get("open"):
                    shown[m.data["ask_id"]] = m.data
                else:
                    shown.pop(m.data["ask_id"], None)
        return shown

    @invariant()
    def nothing_heard_acts_while_locked(self) -> None:
        if self.locked and self.at_lock is not None and (
                self._started_while_locked() or self._heard()[1] != self.at_lock[1]):
            self._problem("LOCKED", "something heard started or answered while the screen was locked")

    @invariant()
    def only_the_owner_approves(self) -> None:
        approved = sum(1 for ok in self.agent.answers.values() if ok)
        if approved > self.approvals_given:
            self._problem("APPROVE", f"{approved} card(s) approved, the owner approved {self.approvals_given}")

    @invariant()
    def a_waiting_question_has_its_own_live_deadline(self) -> None:
        s = self.session
        for behind in s.dialogue.waiting:
            if behind.window is not None and behind.window.timer is not None:
                self._problem("OWN_DEADLINE", "a question waiting behind another has a deadline running")
        q = s.dialogue.pending
        if q is None or s._away or s._cards or (q.future is not None and q.future.done()):
            return
        w = q.window
        timer = w.timer if w is not None else None
        if w is None or not w.open or timer is None or timer.cancelled() or timer.when() < self.loop.time() - 0.5:
            self._problem("OWN_DEADLINE", "the question on screen has no live deadline; it can wait for ever")

    @invariant()
    def the_overlay_counts_down_to_the_backends_deadline(self) -> None:
        s = self.session
        q = s.dialogue.pending
        w = q.window if q is not None else None
        if q is None or w is None or w.state != "listening" or w.deadline is None or s._cards:
            return
        if q.source == "run" and q.owner is not s._focus:
            return  # not drawn: the overlay shows a question only for the request in front (replayed fresh)
        sent = [(t, m.data) for t, m in self.stamped if m.type == "ask" and m.data.get("ask_id") == q.id
                and m.data.get("open") and m.data.get("phase") in ("listening", "again") and m.data.get("seconds")]
        if not sent:
            return
        at, data = sent[-1]
        shown = at + float(data.get("seconds") or 0)
        if abs(shown - w.deadline) > 0.2:
            self._problem("DEADLINE", f"the overlay counts down to {shown - self.loop.time():.1f} s, "
                                  f"the backend to {w.deadline - self.loop.time():.1f} s")

    # ---- the end ------------------------------------------------------------------------------

    async def _wind_down(self) -> None:
        if self.locked:
            self.locked = False
            self.session.listening_paused = self.session.hands_free_blocked = False
            await self.session.hold_cards(False)
        for _ in range(4):
            self.speaker.finish()
            for run in self.agent.runs.values():
                run["go"].set()
                run["ask"].set()
            while (request_id := self.session._open_confirm()) is not None:
                await self.session.handle(Message("confirm.reply", {"request_id": request_id, "decision": "reject"}))
                await self._settle()
            await asyncio.sleep(QUESTION_S + 35)
            await self._settle()

    def everything_ends(self) -> None:
        self._run(self._wind_down())
        if self._live_runs():
            self._problem("ENDS", f"{len(self._live_runs())} request(s) still running after everything was let go")
        d = Dialogue()
        for _, m in self.stamped:
            d.sent(m.type, m.data)
        for p in d.finished():
            self._problem("CARDS" if p.startswith("two cards") else "CLOSED", p)

    def teardown(self) -> None:
        try:
            self.everything_ends()
        finally:
            self._close()

    def _close(self) -> None:
        tasks = [t for t in asyncio.all_tasks(self.loop) if not t.done()]
        for t in tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            async def drain() -> None:
                await asyncio.gather(*tasks, return_exceptions=True)

            self.loop.run_until_complete(drain())
        self.loop.close()


ALL = frozenset({"LOCKED", "OWN_DEADLINE", "DEADLINE", "ENDS", "CLOSED", "APPROVE", "CARDS"})

# Found by this model and still open (docs/audit/2026-11-seams-audit.md). Each: the check it breaks and
# its shortest sequence of steps. The main test steers around the trigger (``avoid``) or, where it
# can't, leaves that one check out (``UNSTEERABLE``); the replay must still break the check, so a fix
# shows up here: then delete the entry.
KNOWN: dict[str, tuple[str, list[tuple[str, dict[str, Any]]]]] = {
    # A new request said while a run's question waits takes the front; the question's close is then
    # only remembered (``ask`` is FOCUS_ONLY), so the overlay keeps holding it (new in layer C).
    "O-15": ("CLOSED", [("a_request_that_asks", {}), ("swift_finishes_speaking", {}), ("time_passes", {"seconds": 2.0}),
                        ("something_said", {"text": "what time is it"})]),
}

SETTINGS = settings(max_examples=int(os.environ.get("SWIFT_MODEL_EXAMPLES", "60")), stateful_step_count=20,
                    deadline=None, derandomize=not os.environ.get("SWIFT_MODEL_RANDOM"),
                    suppress_health_check=list(HealthCheck), print_blob=True)


def _model(checks: frozenset[str], avoid: frozenset[str] = frozenset()) -> type[DialogueModel]:
    return type("Model", (DialogueModel,), {"checks": checks, "avoid": avoid})


# A question is closed while another request is in front whenever a request takes the front while it
# waits (a new one said, one started a moment before): too many paths to steer around.
UNSTEERABLE = {"O-15"}


def test_the_dialogue_model_holds() -> None:
    """Every check, on random days that steer around the known open findings' triggers."""
    from hypothesis.stateful import run_state_machine_as_test

    left_out = {KNOWN[f][0] for f in UNSTEERABLE}
    run_state_machine_as_test(_model(ALL - left_out, frozenset(KNOWN)), settings=SETTINGS)


@pytest.mark.parametrize("finding", sorted(KNOWN))
def test_a_known_finding_still_breaks_the_model(finding: str) -> None:
    check, steps = KNOWN[finding]
    model = _model(frozenset({check}))()
    with pytest.raises(Problem) as broke:
        try:
            for name, args in steps:
                getattr(model, name)(**args)
                for inv in ("nothing_heard_acts_while_locked", "only_the_owner_approves",
                            "a_waiting_question_has_its_own_live_deadline",
                            "the_overlay_counts_down_to_the_backends_deadline"):
                    getattr(model, inv)()
        finally:
            model.teardown()
    assert broke.value.finding == check
