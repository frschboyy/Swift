"""Several requests at once (ADR-013 phase B) and changing course mid-task (ADR-014 §7).

Sequences: two requests side by side; a card from the background request waits behind the one
on screen; naming a request ("stop the research one"); Esc on the one in front; one writer in
the owner's apps; the limit of three; a change of mind before and after something that can't be
undone; hands-free, a change of mind needs Swift's name.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import time
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import numpy as np
from test_session import Recorder as Outbox
from test_voice import FakeTranscriber
from test_wake import LeadRecorder

from swift.executors.base import WorkerTask
from swift.attention import Attention, wait_answer
from swift.audio.recorder import SAMPLE_RATE
from swift.connectors.fake import FakeMailConnector
from swift.desktop.fake import FakeDesktop
from swift.executors.base import ExecEvent, ExecResult
from swift.ipc.protocol import Message
from swift.security.gateway import ActionGateway
from swift.security.journal import Journal
from swift.session import MAX_RUNS, QUEUED_HINT, REDIRECT_NAME_HINT, Session
from swift.workflows.tools import KnownContact, ToolHost
from swift.workflows.toolset import ALL_TOOLS

SHORT = np.zeros(SAMPLE_RATE // 10, dtype=np.int16)
LECTURER = KnownContact("Dr Ada Lovelace", "ada@example.edu", ("lecturer",))


class Agent:
    """A provider whose runs wait until the test lets them go. A request with "card" in it asks
    on the provider's own card (when ``ask`` is set for it); one with "email" sends an email
    through Swift's tools first."""

    name = "agent"

    def __init__(self, tools: ToolHost | None = None) -> None:
        self.tools = tools
        self.requests: list[str] = []
        self.cancelled: list[str] = []
        self.answers: dict[str, bool] = {}
        # Like Claude Code: its cards' countdown pauses while they wait (set by the test).
        self.attention: Attention | None = None
        self._ids = itertools.count(1)
        self.runs: dict[str, dict[str, Any]] = {}

    async def start(self, task: WorkerTask) -> str:
        request = task.prompt
        run_id = f"a-{next(self._ids)}"
        self.requests.append(request)
        run: dict[str, Any] = {"queue": asyncio.Queue(), "go": asyncio.Event(), "ask": asyncio.Event(),
                               "request": request, "pending": {}}
        run["task"] = asyncio.create_task(self._work(run_id, run))
        self.runs[run_id] = run
        return run_id

    async def _work(self, run_id: str, run: dict[str, Any]) -> ExecResult:
        queue, request = run["queue"], run["request"].lower()
        try:
            queue.put_nowait(ExecEvent("step", f"Reading for {run_id}", activity="reading"))
            if "email" in request and self.tools is not None:
                found = await self.tools.call("find_contact", {"query": "lecturer"}, run=run_id)
                address = found.data["candidates"][0]["email"]
                draft = await self.tools.call(
                    "draft_email", {"to": [address], "subject": "Thursday", "body": "I'll miss it."}, run=run_id,
                )
                await self.tools.call("send_email", {"draft_id": draft.data["draft_id"]}, run=run_id)
            if "card" in request:
                await run["ask"].wait()
                request_id = f"{run_id}:1"
                future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
                run["pending"][request_id] = future
                queue.put_nowait(ExecEvent("confirm", f"Edit for {run_id}", request_id=request_id, detail="", tool="Edit"))
                self.answers[request_id] = await wait_answer(self.attention, request_id, future, 120.0)
            await run["go"].wait()
            return ExecResult("done", f"Done {run_id}.")
        finally:
            queue.put_nowait(None)

    async def events(self, run_id: str) -> AsyncIterator[ExecEvent]:
        queue = self.runs[run_id]["queue"]
        while (item := await queue.get()) is not None:
            yield item

    async def result(self, run_id: str) -> ExecResult:
        task = self.runs[run_id]["task"]
        try:
            return await task
        except asyncio.CancelledError:
            return ExecResult("cancelled", "Cancelled.")

    async def cancel(self, run_id: str) -> None:
        self.cancelled.append(run_id)
        self.runs[run_id]["task"].cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.runs[run_id]["task"]

    async def reply(self, request_id: str, approve: bool) -> None:
        future = self.runs[request_id.split(":")[0]]["pending"].get(request_id)
        if future is not None and not future.done():
            future.set_result(approve)


class SameSession(Agent):
    """A provider that can change course in its own session (like Claude Code)."""

    def __init__(self, tools: ToolHost | None = None) -> None:
        super().__init__(tools)
        self.redirected: list[tuple[str, str]] = []

    async def redirect(self, run_id: str, text: str) -> bool:
        self.redirected.append((run_id, text))
        return True


def make(agent_cls: type[Agent] = Agent, **kw: Any) -> tuple[Session, Outbox, list[dict[str, Any]], Agent, FakeTranscriber]:
    mail = FakeMailConnector(contacts=())
    tools = ToolHost(mail, (LECTURER,), ActionGateway(Journal(None)), ALL_TOOLS, desktop=FakeDesktop())
    agent = agent_cls(tools)
    out, records, stt = Outbox(), [], FakeTranscriber(text="")
    session = Session(
        out, agent, tools=tools, recorder=LeadRecorder(), transcriber=stt, on_finish=records.append, tail_s=0.0, **kw,
    )
    return session, out, records, agent, stt


async def say(session: Session, stt: FakeTranscriber, text: str) -> None:
    """Something said near the open microphone (wake listening on)."""
    stt.text = text
    await session.hear_wake(SHORT, time.monotonic())


async def until(check: Any, timeout: float = 2.0) -> None:
    """Wait for ``check()`` (a message not there yet counts as False)."""
    deadline = time.monotonic() + timeout

    def ok() -> bool:
        try:
            return bool(check())
        except (IndexError, KeyError):
            return False

    while not ok():
        assert time.monotonic() < deadline, "timed out"
        await asyncio.sleep(0.005)


async def started(session: Session, out: Outbox, agent: Agent, stt: FakeTranscriber, text: str) -> str:
    """Say a request; return the provider run id once it's working."""
    before = len(agent.requests)
    await say(session, stt, text)
    await until(lambda: len(agent.requests) > before and f"a-{before + 1}" in agent.runs)
    run_id = f"a-{before + 1}"
    await until(lambda: any(m.type == "state" and m.data.get("run_id") == run_id for m in out.messages)
                or any(r["run_id"] == run_id for m in out.messages if m.type == "runs" for r in m.data["rows"]))
    return run_id


def runs(out: Outbox) -> dict[str, Any]:
    return out.last("runs")


def sent_for(out: Outbox, run_id: str, kind: str) -> list[dict[str, Any]]:
    return [m.data for m in out.messages if m.type == kind and m.data.get("run_id") == run_id]


async def finish_all(session: Session, agent: Agent) -> None:
    for run in agent.runs.values():
        run["ask"].set()
        run["go"].set()
        for future in run["pending"].values():
            if not future.done():
                future.set_result(True)
    deadline = time.monotonic() + 2
    for q in [*([session.dialogue.pending] if session.dialogue.pending else []), *session.dialogue.waiting]:
        session._settle(q, None)  # nobody answers it: it goes where an unanswered question goes
    for run in list(session._runs):
        while run.task is not None and not run.task.done():
            # Swift's own cards too (an email a request sends): a request ending no longer cancels
            # the cards of the others (audit 2026-10, A-08), so each is answered here.
            for future in list(session._swift_pending.values()):
                if not future.done():
                    future.set_result(False)
            assert time.monotonic() < deadline, "a request didn't finish"
            await asyncio.sleep(0.005)
        if run.task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await run.task


# ---- side by side ---------------------------------------------------------------------------


async def test_a_clear_new_request_runs_beside_the_first_which_becomes_a_row() -> None:
    session, out, records, agent, stt = make()
    first = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    await say(session, stt, "Hey Swift, what time is it?")  # a run is going: a new request beside it
    await until(lambda: out.last("result")["summary"].startswith("It's"))
    view = runs(out)
    assert view["focus"].startswith("local-")
    assert [(r["run_id"], r["state"], r["title"]) for r in view["rows"]] == [(first, "working", "research the history of tea")]
    assert not agent.cancelled and session._runs[0].alive  # the first was never dropped
    # The first goes on in the background: its news updates its row, never the card in front.
    shown = len(sent_for(out, first, "step"))
    agent.runs[first]["queue"].put_nowait(ExecEvent("step", "Searching the web", activity="searching"))
    await until(lambda: runs(out)["rows"][0]["activity"] == "searching")
    assert len(sent_for(out, first, "step")) == shown
    # The answer in front fades and the overlay asks for the next one: its card is drawn again.
    await session.handle(Message("focus", {"run_id": first}))
    assert runs(out)["focus"] == first and runs(out)["rows"] == [] or runs(out)["focus"] == first
    assert out.messages[-1].type == "step" and out.messages[-1].data["text"] == "Searching the web"
    agent.runs[first]["go"].set()
    await until(lambda: out.last("result").get("run_id") == first)
    await finish_all(session, agent)
    assert [r["status"] for r in records] == ["done", "done"]
    assert records[0]["thread"] != records[1]["thread"]  # separate requests, separate threads


async def test_esc_stops_the_one_in_front_and_the_other_comes_forward() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    second = await started(session, out, agent, stt, "Hey Swift, summarise my notes from Monday")
    assert runs(out)["focus"] == first
    await session.handle(Message("cancel", {}))
    await until(lambda: agent.cancelled == [first])
    await until(lambda: out.last("result")["status"] == "cancelled")
    assert out.last("result")["run_id"] == first
    assert session._runs[-1].alive  # the second goes on
    # "Cancelled" fades; the overlay brings the one still running forward, and Esc reaches it.
    await session.handle(Message("focus", {"run_id": second}))
    assert runs(out)["focus"] == second and runs(out)["rows"] == []
    assert session._task is session._runs[-1].task and not session._task.done()
    await finish_all(session, agent)


# ---- ADR-018 §4.1: a request said beside a working card stays behind it --------------------------


async def test_a_request_beside_a_working_card_stays_behind_it_and_its_news_stays_on_its_edge() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    second = await started(session, out, agent, stt, "Hey Swift, summarise my notes from Monday")
    await asyncio.sleep(0.05)
    assert runs(out)["focus"] == first
    assert [r["run_id"] for r in runs(out)["rows"]] == [second]
    assert sent_for(out, second, "state") == [] and sent_for(out, second, "step") == []
    agent.runs[second]["queue"].put_nowait(ExecEvent("step", "Reading the notes", activity="reading"))
    await until(lambda: runs(out)["rows"][0]["activity"] == "reading")
    assert runs(out)["focus"] == first and sent_for(out, second, "step") == []
    await finish_all(session, agent)


async def test_it_comes_forward_with_its_answer_drawn_whole() -> None:
    session, out, _records, agent, stt = make()
    await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    second = await started(session, out, agent, stt, "Hey Swift, summarise my notes from Monday")
    agent.runs[second]["go"].set()
    await until(lambda: out.last("result").get("run_id") == second)
    assert runs(out)["focus"] == second
    frames = [m.type for m in out.messages if m.data.get("run_id") == second and m.type in ("state", "result")]
    assert frames[-2:] == ["state", "result"] and frames.count("result") == 1
    await finish_all(session, agent)


async def test_it_comes_forward_when_clicked_with_what_it_did_behind_the_card() -> None:
    session, out, _records, agent, stt = make()
    await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    second = await started(session, out, agent, stt, "Hey Swift, summarise my notes from Monday")
    agent.runs[second]["queue"].put_nowait(ExecEvent("step", "Reading the notes", activity="reading"))
    await until(lambda: runs(out)["rows"][0]["activity"] == "reading")
    await session.handle(Message("focus", {"run_id": second}))
    assert runs(out)["focus"] == second
    assert sent_for(out, second, "state")[-1]["state"] == "working"
    assert sent_for(out, second, "step")[-1]["text"] == "Reading the notes"
    await finish_all(session, agent)


async def test_plain_stop_asks_which_while_the_one_just_said_runs_behind_the_card() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    second = await started(session, out, agent, stt, "Hey Swift, summarise my notes from Monday")
    await say(session, stt, "stop")
    await until(lambda: "Which one?" in out.last("run.voice")["text"])
    assert agent.cancelled == []
    # Naming one needs no question.
    await say(session, stt, "stop the notes one")
    await until(lambda: agent.cancelled == [second])
    # Stopped by name, it doesn't come forward to say so: the card in front stays.
    await until(lambda: not session._next_focus)
    await asyncio.sleep(0.05)
    assert runs(out)["focus"] == first and sent_for(out, second, "result") == []
    # Nothing else behind the card: a plain "stop" is the card in front again.
    await say(session, stt, "stop")
    await until(lambda: agent.cancelled == [second, first])
    await finish_all(session, agent)


async def test_esc_never_asks_which_it_stops_the_card_it_says_it_stops() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    await started(session, out, agent, stt, "Hey Swift, summarise my notes from Monday")
    await session.handle(Message("cancel", {}))
    await until(lambda: agent.cancelled == [first])
    await finish_all(session, agent)


async def test_plain_stop_is_the_card_in_front_once_the_other_has_been_seen() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    second = await started(session, out, agent, stt, "Hey Swift, summarise my notes from Monday")
    await session.handle(Message("focus", {"run_id": second}))
    await session.handle(Message("focus", {"run_id": first}))
    await say(session, stt, "stop")
    await until(lambda: agent.cancelled == [first])
    await finish_all(session, agent)


async def test_a_change_of_mind_never_goes_to_the_wrong_request() -> None:
    session, out, _records, agent, stt = make()
    await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    await started(session, out, agent, stt, "Hey Swift, summarise my notes from Monday")
    before = len(agent.requests)
    await say(session, stt, "Swift, actually make it about coffee")
    await until(lambda: "Which one?" in out.last("run.voice")["text"])
    assert len(agent.requests) == before and agent.cancelled == []
    await finish_all(session, agent)


# ---- one confirm card at a time -------------------------------------------------------------


async def test_a_card_from_the_background_waits_for_the_card_on_screen() -> None:
    attention = Attention()
    session, out, records, agent, stt = make(attention=attention)
    agent.attention = attention
    first = await started(session, out, agent, stt, "Hey Swift, tidy the readme with a card")
    second = await started(session, out, agent, stt, "Hey Swift, rename the notes file with a card")
    agent.runs[first]["ask"].set()  # the background request asks first: it comes to the front
    await until(lambda: sent_for(out, first, "confirm.request"))
    assert runs(out)["focus"] == first and session.state == "confirm"
    agent.runs[second]["ask"].set()
    await until(lambda: runs(out)["waiting"] == 1)
    assert sent_for(out, second, "confirm.request") == []  # it waits off screen...
    assert attention.left(f"{second}:1") is not None and attention._waits[f"{second}:1"].deadline is None
    # ...its countdown not started. The answer to the card on screen brings it forward.
    await session.handle(Message("confirm.reply", {"request_id": f"{first}:1", "decision": "approve"}))
    await until(lambda: sent_for(out, second, "confirm.request"))
    assert runs(out)["focus"] == second and runs(out)["waiting"] == 0
    await until(lambda: agent.answers == {f"{first}:1": True})
    assert session._open_confirm() == f"{second}:1"
    await session.handle(Message("confirm.reply", {"request_id": f"{second}:1", "decision": "reject"}))
    await until(lambda: f"{second}:1" in agent.answers)
    assert agent.answers[f"{second}:1"] is False
    await finish_all(session, agent)
    queued = [a for r in records for a in r["approvals"] if a.get("queued")]
    assert [a["request_id"] for a in queued] == [f"{second}:1"]


async def test_a_card_never_disappears_when_its_neighbour_ends() -> None:
    session, out, _records, agent, stt = make()
    first = await started(session, out, agent, stt, "Hey Swift, tidy the readme with a card")
    second = await started(session, out, agent, stt, "Hey Swift, rename the notes file with a card")
    agent.runs[second]["ask"].set()
    await until(lambda: sent_for(out, second, "confirm.request"))
    agent.runs[first]["ask"].set()
    await until(lambda: runs(out)["waiting"] == 1)
    # The request whose card is on screen is stopped: the waiting card takes its place.
    await session.handle(Message("cancel", {}))
    await until(lambda: sent_for(out, first, "confirm.request"))
    assert runs(out)["focus"] == first and session._open_confirm() == f"{first}:1"
    await finish_all(session, agent)


# ---- naming a request -----------------------------------------------------------------------


async def test_voice_targeting_by_what_a_request_is_about() -> None:
    session, out, records, agent, stt = make()
    research = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    notes = await started(session, out, agent, stt, "Hey Swift, summarise my notes from Monday")
    assert runs(out)["focus"] == research
    await say(session, stt, "show me the notes one")  # no name needed, like "show me"
    await until(lambda: runs(out)["focus"] == notes)
    assert sent_for(out, notes, "state")[-1]["state"] == "working"  # its card drawn
    await say(session, stt, "stop the research one")
    await until(lambda: agent.cancelled == [research])
    assert out.last("run.voice")["text"] == "Stopped “research the history of tea”."
    assert runs(out)["focus"] == notes and session._runs[-1].alive
    await say(session, stt, "stop the weather one")  # matches nothing: nothing stops
    await until(lambda: out.last("run.voice")["text"] == "I couldn't tell which request you mean.")
    await finish_all(session, agent)
    assert [r["status"] for r in records] == ["cancelled", "done"]


async def test_stop_everything() -> None:
    session, out, records, agent, stt = make()
    await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    await started(session, out, agent, stt, "Hey Swift, summarise my notes from Monday")
    await say(session, stt, "Hey Swift, stop everything")
    await until(lambda: len(records) == 2)
    assert sorted(agent.cancelled) == ["a-1", "a-2"] and all(r["status"] == "cancelled" for r in records)


# ---- limits ---------------------------------------------------------------------------------


async def test_three_at_once_and_a_fourth_waits_for_a_slot() -> None:
    session, out, records, agent, stt = make()
    ids = [await started(session, out, agent, stt, f"Hey Swift, research topic number {n} for me") for n in range(MAX_RUNS)]
    await say(session, stt, "Hey Swift, research the fourth topic for me")
    await until(lambda: any(r["state"] == "queued" for r in runs(out)["rows"]))
    assert len(agent.requests) == MAX_RUNS  # not started yet
    assert out.last("run.voice")["text"] == QUEUED_HINT.format(n=MAX_RUNS)
    agent.runs[ids[0]]["go"].set()
    await until(lambda: len(agent.requests) == MAX_RUNS + 1)
    assert "fourth" in agent.requests[-1]
    await finish_all(session, agent)
    assert len(records) == MAX_RUNS + 1 and records[-1]["queued"]


async def test_one_writer_in_the_owners_apps() -> None:
    desktop = FakeDesktop()
    host = ToolHost(None, (), ActionGateway(Journal(None)), ALL_TOOLS, desktop=desktop)
    steps: dict[str, list[str]] = {"a": [], "b": []}
    let_go = asyncio.Event()

    async def slow(chunk: int) -> None:
        if not let_go.is_set():
            await let_go.wait()  # the first writer is mid-document

    desktop.on_write = slow

    def scope(name: str) -> None:
        async def publish(_: Any) -> None: ...

        async def confirm(*_: Any) -> str:
            return "approve"

        async def step(text: str, activity: str, app: str | None) -> None:
            steps[name].append(text)

        opened = host.open(publish, confirm, step=step)
        opened.said = "put it in Word"
        host.bind(opened, name)

    scope("a")
    scope("b")
    first = asyncio.create_task(host.call("desktop_write", {"text": "One.\nTwo.", "where": "word"}, run="a"))
    await until(lambda: steps["a"] == ["Writing in Word"])
    second = asyncio.create_task(host.call("desktop_write", {"text": "Three.", "where": "word"}, run="b"))
    await until(lambda: steps["b"] != [])
    assert steps["b"] == ["Waiting for Word: another request is writing there"]
    assert [t for _, t in desktop.writes] == ["One."]  # nothing of the second yet
    let_go.set()
    assert (await first).ok and (await second).ok
    assert [t for _, t in desktop.writes] == ["One.", "Two.", "Three."]  # one after the other, never mixed
    assert steps["b"][-1] == "Writing in Word" and not host.writing.locked()


# ---- changing course (ADR-014 §7) -----------------------------------------------------------


async def test_a_change_of_mind_goes_to_the_same_session_when_the_provider_can() -> None:
    session, out, records, agent, stt = make(SameSession)
    run_id = await started(session, out, agent, stt, "Hey Swift, write a summary of the meeting")
    await say(session, stt, "Swift, actually make it about the deadline instead")
    await until(lambda: agent.redirected)  # type: ignore[attr-defined]
    assert agent.redirected == [(run_id, "actually make it about the deadline instead")]  # type: ignore[attr-defined]
    assert len(agent.requests) == 1 and not agent.cancelled
    assert out.last("step")["text"].startswith("Changing course: actually make it about")
    await finish_all(session, agent)
    assert records[0]["redirected"] == "same_session" and records[0]["status"] == "done"


async def test_other_providers_start_again_with_the_change() -> None:
    session, out, records, agent, stt = make()
    first = await started(session, out, agent, stt, "Hey Swift, write a summary of the meeting")
    stt.text = "no, I meant the meeting on Tuesday"
    await session.handle(Message("ptt", {"state": "down"}))  # the hotkey: no name needed
    await asyncio.sleep(0)
    await session.handle(Message("ptt", {"state": "up"}))
    await until(lambda: len(agent.requests) == 2)
    assert agent.cancelled == [first]
    assert "write a summary of the meeting" in agent.requests[1].lower()
    assert "the meeting on Tuesday" in agent.requests[1]
    second = "a-2"
    await until(lambda: sent_for(out, second, "state"))
    assert sent_for(out, second, "state")[0]["thread_id"] == sent_for(out, first, "state")[0]["thread_id"]
    await finish_all(session, agent)
    assert len(records) == 1 and records[0]["redirected"] == "restart" and records[0]["status"] == "done"


async def test_hands_free_a_change_of_mind_needs_swifts_name() -> None:
    session, out, _records, agent, stt = make(SameSession)
    await started(session, out, agent, stt, "Hey Swift, write a summary of the meeting")
    await say(session, stt, "actually make it about the deadline")  # the TV, or someone else
    await until(lambda: any(m.type == "run.voice" for m in out.messages))
    assert out.last("run.voice")["text"] == REDIRECT_NAME_HINT and agent.redirected == []  # type: ignore[attr-defined]
    await say(session, stt, "Hey Swift, actually make it about the deadline")
    await until(lambda: agent.redirected)  # type: ignore[attr-defined]
    await finish_all(session, agent)


async def test_after_an_email_was_sent_swift_says_so_and_offers_a_correction() -> None:
    session, out, records, agent, stt = make(SameSession)
    run_id = await started(session, out, agent, stt, "Hey Swift, email my lecturer that I'll miss Thursday")
    await until(lambda: out.messages and out.last("confirm.request").get("tool") == "send_email" if any(
        m.type == "confirm.request" for m in out.messages) else False)
    await session.handle(Message("confirm.reply", {"request_id": out.last("confirm.request")["request_id"],
                                                   "decision": "approve"}))
    await until(lambda: session._runs[0].scope is not None and session._runs[0].scope.done)
    await say(session, stt, "Swift, actually say I'll miss Friday instead")
    await until(lambda: any(m.type == "run.voice" and m.data["phase"] == "hint" for m in out.messages))
    hint = out.last("run.voice")["text"]
    assert hint == "The email was already sent, so I can't take it back. Say “yes” and I'll send a correction."
    assert agent.redirected == [] and len(agent.requests) == 1  # type: ignore[attr-defined]  # nothing pretends to undo
    await say(session, stt, "yes")  # approving the follow-up needs the name too
    await asyncio.sleep(0.05)
    assert len(agent.requests) == 1
    await say(session, stt, "Swift, yes")
    await until(lambda: len(agent.requests) == 2)
    assert agent.requests[1].startswith("actually say I'll miss Friday instead")
    assert "can't be undone: Send this email to Dr Ada Lovelace" in agent.requests[1]
    await until(lambda: sent_for(out, "a-2", "state") or any(
        r["run_id"] == "a-2" for m in out.messages if m.type == "runs" for r in m.data["rows"]))
    await finish_all(session, agent)
    assert records[0]["redirected"] == "after_done"
    by_id = {r["id"]: r for r in records}
    assert len(by_id) == 2 and records[0]["thread"] == records[1]["thread"]  # the correction continues it
    assert run_id == "a-1"


async def test_a_change_of_mind_on_an_open_card_is_a_change_to_the_card() -> None:
    session, out, records, agent, stt = make(SameSession)
    run_id = await started(session, out, agent, stt, "Hey Swift, email my lecturer that I'll miss Thursday")
    await until(lambda: any(m.type == "confirm.request" for m in out.messages))
    await say(session, stt, "Swift, actually make the subject Friday")
    await until(lambda: records or session._runs[0].record and any(
        a.get("decision") == "revise" for a in session._runs[0].record["approvals"]))
    assert agent.redirected == []  # type: ignore[attr-defined]  # the card took it
    await finish_all(session, agent)
    assert run_id == "a-1"


# ---- Claude Code: the change as a new turn of the same session ------------------------------


class TurnClient:
    """Stands in for ClaudeSDKClient: the first turn works until interrupted, the next answers."""

    made: ClassVar[list[TurnClient]] = []

    def __init__(self, options: Any) -> None:
        self.prompts: list[str] = []
        self.interrupted = asyncio.Event()
        TurnClient.made.append(self)

    async def connect(self) -> None: ...

    async def set_model(self, model: str) -> None: ...

    async def query(self, prompt: str) -> None:
        self.prompts.append(prompt)

    async def receive_response(self) -> AsyncIterator[Any]:
        from test_claude_executor import sdk_messages

        if len(self.prompts) == 1:
            await self.interrupted.wait()
            return
        for message in sdk_messages("claude_read_only.jsonl"):
            yield message

    async def interrupt(self) -> None:
        self.interrupted.set()

    async def disconnect(self) -> None: ...


async def test_claude_code_takes_a_change_of_mind_as_the_next_turn(tmp_path: Any) -> None:
    from swift.executors.claude_code import ClaudeCodeExecutor

    TurnClient.made = []
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", prewarm=False, client_factory=TurnClient)
    run_id = await ex.start(WorkerTask("Summarise the README"))
    await until(lambda: TurnClient.made and TurnClient.made[0].prompts)
    assert await ex.redirect(run_id, "actually only the setup section")
    result = await asyncio.wait_for(ex.result(run_id), 5)
    client = TurnClient.made[0]
    assert len(TurnClient.made) == 1 and len(client.prompts) == 2  # one CLI, one session, two turns
    assert "changed their mind" in client.prompts[1] and "only the setup section" in client.prompts[1]
    assert result.status == "done"
    assert not await ex.redirect(run_id, "too late")  # finished: nothing to change
