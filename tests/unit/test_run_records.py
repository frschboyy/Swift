"""Run records (groundwork, handoff §4; ``swift/runs.py``): one content-free event log per request."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from swift.connectors.fake import FakeCalendarConnector
from swift.ipc.protocol import Message
from swift.runs import RunRecords
from swift.security.gateway import ActionGateway
from swift.security.journal import Journal
from swift.session import Session
from swift.workflows.toolset import ALL_TOOLS
from swift.workflows.tools import ToolHost

from test_calendar_lifecycle import UndoAgent, say
from test_corrections import finish
from test_session import Recorder as Outbox
from test_voice import FakeTranscriber
from test_wake import LeadRecorder

SRC = Path(__file__).resolve().parents[2] / "src" / "swift"


async def test_a_request_leaves_one_record_its_log_line_and_journal_agree_with() -> None:
    calendar, journal = FakeCalendarConnector(), Journal(None)
    tools = ToolHost(gateway=ActionGateway(journal), tools=ALL_TOOLS, calendar=calendar)
    runs, out, records, stt = RunRecords(None), Outbox(), [], FakeTranscriber(text="")
    session = Session(out, UndoAgent(tools), debug_executor=None, tools=tools, recorder=LeadRecorder(), transcriber=stt,
                      on_finish=records.append, tail_s=0.0, runs=runs)
    await say(session, stt, "Hey Swift, set up a meeting with Professor Smith on Friday at three")
    await asyncio.wait_for(out.confirm.wait(), 2)
    live = list(runs._live)
    assert len(live) == 1 and runs.status(live[0]) == "running"  # a card from the stack can ask (A6)
    await session.handle(Message("confirm.reply", {"request_id": out.last("confirm.request")["request_id"],
                                                   "decision": "approve"}))
    await finish(session)

    record = records[-1]
    events = runs.events(record["id"])
    kinds = [e["event"] for e in events]
    assert kinds[0] == "started" and kinds[-1] == "ended" and runs.status(record["id"]) == "ended"
    assert events[0]["origin"] == "asked" and events[0]["source"] == "wake"
    assert kinds.count("worker") == 1 and events[kinds.index("worker")]["provider"] == record["provider"]
    # One door: the log line's steps and approvals are the ones the record wrote as they happened.
    assert len(record["steps"]) == kinds.count("step")
    assert len(record["approvals"]) == kinds.count("asked") == 1
    assert events[-1]["approvals"] == [{k: v for k, v in record["approvals"][0].items() if k not in ("request_id", "heard")}]
    assert events[-1]["status"] == record["status"] == "done"
    # Content-free: nothing the owner said or the worker wrote.
    assert "Smith" not in str(events) and "meeting" not in str(events).lower()
    # The side effect names its run: the journal is the run's side-effect part.
    assert [e["run"] for e in journal.entries if e["state"] == "PENDING"] == [record["id"]]


def test_a_run_that_never_ended_reads_as_interrupted_after_a_restart(tmp_path: Path) -> None:
    before = RunRecords(tmp_path)
    before.begin(record := {"id": "r1", "source": "voice", "thread": "t1"})
    before.step(record, 10, "Reading your calendar for Friday", "reading")
    assert before.status("r1") == "running"
    after = RunRecords(tmp_path)  # Swift started again
    assert after.status("r1") == "interrupted" and after.status("nope") is None
    assert "calendar" not in (tmp_path / "r1.jsonl").read_text(encoding="utf-8")
    assert record["steps"] == [{"t_ms": 10, "text": "Reading your calendar for Friday", "activity": "reading"}]
    after.end({**record, "status": "done", "transcript": "what's on Friday"})
    assert after.status("r1") == "ended" and "Friday" not in (tmp_path / "r1.jsonl").read_text(encoding="utf-8")


def test_a_journal_entry_in_a_request_names_its_run_and_the_gateway_s_own_wins() -> None:
    journal, runs = Journal(None), RunRecords(None)

    async def in_a_request() -> None:
        runs.begin({"id": "r2"})
        journal.write("a1", "PENDING", tool="system.wifi")  # the system lane, in the request's own task
        journal.write("a2", "PENDING", run=None, tool="create_calendar_event")  # a gateway scope with no run
        journal.write("a1", "DONE")

    asyncio.run(in_a_request())
    assert [e.get("run") for e in journal.entries] == ["r2", None, None]


def test_steps_approvals_and_artifacts_are_written_through_the_run_record_only() -> None:
    """Fails if a second writer appends to the interaction record's lists beside ``runs.py``."""
    pattern = re.compile(r"""\[["'](steps|approvals|artifacts)["']\]\.append|\(["'](steps|approvals|artifacts)["'], \[\]\)\.append""")
    writers = [f"{p.name}:{n}" for p in SRC.rglob("*.py") if p.name != "runs.py"
               for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if pattern.search(line)]
    assert writers == []
