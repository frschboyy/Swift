"""Router tier 1 (ADR-007 §3): rules for control, local and model overrides, plus the demand estimate."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from test_session import Recorder

from swift.executors.base import ExecEvent, ExecResult
from swift.ipc.protocol import Message
from swift.routing import route
from swift.session import Session

ROOT = Path(__file__).resolve().parents[2]
EVAL = [json.loads(line) for line in (ROOT / "eval" / "routes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.parametrize(
    ("text", "action"),
    [
        ("Stop.", "stop"),
        ("Hey Swift stop talking", "stop"),
        ("never mind", "cancel"),
        ("Cancel that.", "cancel"),
        ("um cancel", "cancel"),
        ("Approve.", "approve"),
        ("Yes, go ahead and run it.", "approve"),
        ("No, don't do that.", "reject"),
        ("say that again", "repeat"),
        ("What can you do?", "help"),
    ],
)
def test_whole_utterance_commands_are_control(text: str, action: str) -> None:
    r = route(text)
    assert (r.route, r.action) == ("control", action)


@pytest.mark.parametrize(
    "text",
    [
        "Stop reminding me to take a break.",
        "Cancel the Friday reminder.",
        "Yes, and also add tests for it.",
        "No wonder the tests fail, fix them.",
        "Go ahead and send the email to my dean.",
        "What time is it in Bucharest?",
    ],
)
def test_requests_that_start_like_commands_still_reach_claude(text: str) -> None:
    assert route(text).route == "claude"


@pytest.mark.parametrize(("text", "action"), [("What time is it?", "time"), ("what's the date today", "date"), ("Hey Swift what day is it", "date")])
def test_time_and_date_are_answered_locally(text: str, action: str) -> None:
    r = route(text)
    assert (r.route, r.action) == ("local", action)


def test_use_model_prefix_is_removed_and_forces_the_model() -> None:
    r = route("Use opus to review the routing design for gaps.")
    assert (r.route, r.override, r.demand) == ("claude", "opus", "standard")
    assert r.text == "Review the routing design for gaps."
    r = route("hey swift, use haiku to list the files in docs")
    assert (r.override, r.demand, r.text) == ("haiku", "light", "List the files in docs")


def test_think_hard_asks_for_opus_and_keeps_the_words() -> None:
    r = route("Think hard about whether we should keep Whisper.")
    assert r.override == "opus" and r.text.startswith("Think hard")


def test_wake_word_is_not_sent_to_claude() -> None:
    assert route("Hey Swift, what's in the executors folder?").text == "what's in the executors folder?"


@pytest.mark.parametrize(
    ("text", "demand"),
    [
        ("What's in the executors folder?", "light"),
        ("Draft an email to my supervisor about the results.", "light"),
        ("Fix the failing test in test voice dot py.", "standard"),
        ("Why is the backend using so much memory?", "standard"),
        ("Hmm, the overlay thing from before.", "standard"),  # unclear: the safe default
    ],
)
def test_demand_estimate(text: str, demand: str) -> None:
    assert route(text).demand == demand


def test_no_request_in_the_eval_set_is_lost_to_a_command() -> None:
    # Taking a request for control/local drops it; the eval set must never show that.
    dropped = [r["text"] for r in EVAL if r["route"] == "claude" and route(r["text"]).route != "claude"]
    assert dropped == []


def test_eval_test_split_has_no_demand_under_estimates() -> None:
    under = [
        r["text"] for r in EVAL
        if r["split"] == "test" and r["route"] == "claude" and r["demand"] == "standard" and route(r["text"]).demand == "light"
    ]
    assert under == []


# ---- routing inside the session -------------------------------------------------------


class SpyExecutor:
    """Records what it was asked and how; answers "done" at once."""

    name = "spy"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def start(self, request: str, **kw: Any) -> str:
        self.calls.append((request, kw))
        return f"spy-{len(self.calls)}"

    async def events(self, run_id: str):
        return
        yield ExecEvent("log", "")  # pragma: no cover

    async def cancel(self, run_id: str) -> None: ...

    async def result(self, run_id: str) -> ExecResult:
        return ExecResult("done", f"answer {run_id}", meta={"start_model": "m"})

    async def reply(self, request_id: str, approve: bool) -> None: ...


async def ask(text: str, session: Session | None = None) -> tuple[Session, Recorder, SpyExecutor, list[dict[str, Any]]]:
    from swift.executors.mock import MockExecutor

    if session is None:
        rec, records, spy = Recorder(), [], SpyExecutor()
        session = Session(rec, spy, debug_executor=MockExecutor(speed=0), on_finish=records.append)
        session._test = (rec, spy, records)  # type: ignore[attr-defined]
    rec, spy, records = session._test  # type: ignore[attr-defined]
    await session.handle(Message("debug.ask", {"text": text}))
    await asyncio.wait_for(session._task, 2)  # type: ignore[arg-type]
    return session, rec, spy, records


async def test_claude_requests_carry_their_demand_and_override() -> None:
    session, _, spy, records = await ask("Fix the failing test.")
    await ask("Use haiku to list the docs folder.", session)
    assert spy.calls == [("Fix the failing test.", {"demand": "standard", "override": None}),
                         ("List the docs folder.", {"demand": "light", "override": "haiku"})]
    assert records[0]["route"] == "claude" and records[0]["demand"] == "standard"
    assert records[1]["override"] == "haiku" and records[1]["start_model"] == "m"


async def test_stop_goes_idle_without_the_executor() -> None:
    _, rec, spy, records = await ask("never mind")
    assert spy.calls == [] and rec.states()[-1] == "idle"
    assert records[0]["route"] == "control" and records[0]["action"] == "cancel" and records[0]["status"] == "cancelled"


async def test_time_is_answered_on_this_pc() -> None:
    _, rec, spy, records = await ask("What time is it?")
    assert spy.calls == [] and rec.states()[-1] == "result"
    assert rec.last("result")["summary"].startswith("It's ")
    assert records[0]["route"] == "local" and records[0]["action"] == "time"


async def test_repeat_shows_the_last_answer_again() -> None:
    session, rec, _, _ = await ask("What's in the docs folder?")
    first = rec.last("result")
    await ask("repeat that", session)
    assert rec.last("result") == first


async def test_approve_with_nothing_open_says_so() -> None:
    _, rec, spy, _ = await ask("Approve.")
    assert spy.calls == [] and "nothing waiting" in rec.last("result")["summary"]
