"""The live view of a running request (ADR-017 §7).

Claude Code's WebSearch / WebFetch calls and their results become sources, its text between tool
calls notes; the desktop writer sends each paragraph as it writes it. The session sends these for
every request, in front or not, opens the view on "show me", and stops only the request whose
view says Stop. The log and the interaction record get counts, never addresses, titles or text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from test_runs import Agent, finish_all, make, runs, say, sent_for, started, until

from swift.desktop.fake import FakeApp, FakeDesktop
from swift.executors.base import ExecEvent, ExecResult
from swift.executors.claude_code import as_event
from swift.executors.claude_mapping import LiveMapper, search_links, site_of, steps_for, structured_links
from swift.ipc.protocol import Message, decode
from swift.security.gateway import ActionGateway
from swift.security.journal import Journal
from swift.workflows.desktop_tools import desktop_write
from swift.workflows.scope import RunScope
from swift.workflows.tools import ToolHost

SECRET_URL = "https://www.britannica.com/topic/tea-beverage"
SECRET_TITLE = "Tea | Origin, History, Types"
SECRET_NOTE = "Tea was first drunk in Yunnan as a medicine"


def tool_use(id: str, name: str, **args: Any) -> dict[str, Any]:
    return {"type": "assistant", "parent_tool_use_id": None,
            "message": {"content": [{"type": "tool_use", "id": id, "name": name, "input": args}]}}


def tool_result(id: str, content: str, *, error: bool = False, structured: Any = None) -> dict[str, Any]:
    return {"type": "user", "parent_tool_use_id": None, "tool_use_result": structured,
            "message": {"content": [{"type": "tool_result", "tool_use_id": id, "content": content, "is_error": error}]}}


SEARCH_RESULT = (
    'Web search results for query: "history of tea"\n\n'
    "Links: " + json.dumps([
        {"title": SECRET_TITLE, "url": SECRET_URL},
        {"title": "History of tea - Wikipedia", "url": "https://en.wikipedia.org/wiki/History_of_tea"},
        {"title": "dup", "url": SECRET_URL},
        {"title": "not the web", "url": "file:///C:/secret.txt"},
    ]) + "\n\nTea originated in China."
)


# ---- the mapping ------------------------------------------------------------------------------


def test_a_search_result_becomes_sources_with_titles_and_sites() -> None:
    live = LiveMapper()
    assert live.feed(tool_use("t1", "WebSearch", query="history of tea")) == []
    items = live.feed(tool_result("t1", SEARCH_RESULT))
    assert [(i["title"], i["site"], i["state"]) for i in items] == [
        (SECRET_TITLE, "britannica.com", "found"), ("History of tea - Wikipedia", "en.wikipedia.org", "found"),
    ]
    assert all(i["kind"] == "source" and i["url"].startswith("https://") for i in items)


def test_the_structured_search_result_wins_and_other_formats_still_work() -> None:
    structured = {"query": "tea", "results": [{"tool_use_id": "x", "content": [{"title": "A", "url": "https://a.example/1"}]}, "text"]}
    live = LiveMapper()
    live.feed(tool_use("t1", "WebSearch", query="tea"))
    assert [i["url"] for i in live.feed(tool_result("t1", SEARCH_RESULT, structured=structured))] == ["https://a.example/1"]
    assert structured_links({"results": "nope"}) == []
    assert search_links("See [Tea](https://b.example/tea) and more") == [("Tea", "https://b.example/tea")]
    assert search_links("bare https://c.example/x, done.") == [("", "https://c.example/x")]
    many = "Links: " + json.dumps([{"title": str(n), "url": f"https://d.example/{n}"} for n in range(20)])
    assert len(search_links(many)) == 8


def test_a_fetch_is_reading_then_read_or_failed() -> None:
    live = LiveMapper()
    [reading] = live.feed(tool_use("f1", "WebFetch", url=SECRET_URL, prompt="summarise"))
    assert (reading["state"], reading["site"]) == ("reading", "britannica.com")
    assert live.feed(tool_result("f1", "page summary"))[0]["state"] == "read"
    live.feed(tool_use("f2", "WebFetch", url="https://slow.example/"))
    assert live.feed(tool_result("f2", "timed out", error=True))[0]["state"] == "failed"
    # Not a web address: nothing to show or open.
    assert live.feed(tool_use("f3", "WebFetch", url="javascript:alert(1)")) == []
    # Results of other tools, or unknown ids, add nothing.
    live.feed(tool_use("r1", "Read", file_path="C:/notes.md"))
    assert live.feed(tool_result("r1", f"see {SECRET_URL}")) == []
    assert live.feed(tool_result("nope", SEARCH_RESULT)) == []


def test_notes_are_claudes_text_between_tools_not_a_helpers() -> None:
    live = LiveMapper()
    text = {"type": "assistant", "parent_tool_use_id": None, "message": {"content": [{"type": "text", "text": f"**{SECRET_NOTE}**, it seems."}]}}
    assert live.feed(text) == [{"kind": "note", "text": f"{SECRET_NOTE}, it seems."}]
    helper = {**text, "parent_tool_use_id": "task-1"}
    assert live.feed(helper) == []
    long = {**text, "message": {"content": [{"type": "text", "text": "word " * 200}]}}
    assert len(live.feed(long)[0]["text"]) <= 280


def test_tool_results_reach_the_mapping_and_the_steps_ignore_them() -> None:
    @dataclass
    class ToolResultBlock:
        tool_use_id: str
        content: Any = None
        is_error: bool | None = None

    @dataclass
    class UserMessage:
        content: Any
        parent_tool_use_id: str | None = None
        tool_use_result: Any = None

    @dataclass
    class TextBlock:
        text: str

    event = as_event(UserMessage([ToolResultBlock("t1", [{"type": "text", "text": SEARCH_RESULT}])]))
    assert event is not None and event["type"] == "user"
    assert SEARCH_RESULT in event["message"]["content"][0]["content"]
    assert [i["state"] for i in LiveMapper({"t1": ("WebSearch", "")}).feed(event)] == ["found", "found"]
    assert steps_for(event) == []
    assert as_event(UserMessage("typed by the owner")) is None
    assert as_event(UserMessage([TextBlock("hi")])) is None  # no tool result in it


def test_site_of() -> None:
    assert site_of("https://WWW.Example.com:8443/a") == "example.com"
    assert site_of("not a url") == ""


# ---- the protocol -------------------------------------------------------------------------------


def frame(kind: str, data: dict[str, Any]) -> str:
    return json.dumps({"v": 1, "type": kind, "ts": 0, "data": data})


def test_the_inbound_live_messages_are_validated() -> None:
    assert decode(frame("watch", {"run_id": "a-1", "open": True})).data["open"] is True
    assert decode(frame("run.stop", {"run_id": "a-1"})).type == "run.stop"
    assert decode(frame("live.app", {"run_id": "a-1"})).type == "live.app"
    for bad in (frame("watch", {"run_id": "a-1"}), frame("run.stop", {})):
        try:
            decode(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


# ---- the session ----------------------------------------------------------------------------------


class Researcher(Agent):
    """Searches and reads before it waits: what the live view shows."""

    async def _work(self, run_id: str, run: dict[str, Any]) -> ExecResult:
        if "research" in run["request"].lower():
            queue = run["queue"]
            queue.put_nowait(ExecEvent("step", "Searching the web: history of tea", activity="searching"))
            queue.put_nowait(ExecEvent("live", "source", data={"kind": "source", "url": SECRET_URL, "title": SECRET_TITLE,
                                                                "site": "britannica.com", "state": "found"}))
            queue.put_nowait(ExecEvent("live", "note", data={"kind": "note", "text": SECRET_NOTE}))
        return await super()._work(run_id, run)


@dataclass
class Logs:
    lines: list[str] = field(default_factory=list)

    def __enter__(self) -> Logs:
        self.id = logger.add(lambda m: self.lines.append(str(m) + json.dumps(m.record["extra"], default=str)), level="DEBUG")
        return self

    def __exit__(self, *a: Any) -> None:
        logger.remove(self.id)


async def test_a_background_request_sends_its_live_items_and_logs_only_counts() -> None:
    session, out, records, agent, stt = make(Researcher)
    with Logs() as logs:
        research = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
        notes = await started(session, out, agent, stt, "Hey Swift, summarise my notes from Monday")
        assert runs(out)["focus"] == notes
        await until(lambda: any(m["kind"] == "note" for m in sent_for(out, research, "live")))
        items = sent_for(out, research, "live")
        kinds = [m["kind"] for m in items]
        assert "doing" in kinds and "source" in kinds and "note" in kinds
        source = next(m for m in items if m["kind"] == "source")
        assert (source["url"], source["title"], source["site"]) == (SECRET_URL, SECRET_TITLE, "britannica.com")
        doing = next(m for m in items if m["kind"] == "doing" and "history" in m["text"])
        assert doing["activity"] == "searching"
        await finish_all(session, agent)
    research_record = next(r for r in records if "research" in str(r.get("transcript")))
    assert research_record["live"] == {"source": 1, "note": 1}
    dumped = json.dumps(records, default=str) + "\n".join(logs.lines)
    for secret in (SECRET_URL, SECRET_TITLE, SECRET_NOTE, "britannica"):
        assert secret not in dumped, secret


async def test_show_me_the_research_one_opens_its_live_view() -> None:
    session, out, _records, agent, stt = make(Researcher)
    research = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    await started(session, out, agent, stt, "Hey Swift, summarise my notes from Monday")
    await say(session, stt, "show me the research one")
    await until(lambda: out.last("watch")["run_id"] == research)
    assert out.last("watch")["open"] is True and "tea" in out.last("watch")["title"]
    await finish_all(session, agent)


async def test_show_me_said_while_another_runs_opens_the_live_view() -> None:
    session, out, records, agent, stt = make(Researcher)
    research = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    await say(session, stt, "Hey Swift, show me")
    await until(lambda: out.last("watch")["run_id"] == research)
    await finish_all(session, agent)
    assert any({"source": "voice", "kind": "live"} in (r.get("views") or []) for r in records)


async def test_stop_in_a_live_view_stops_that_request_only() -> None:
    session, out, records, agent, stt = make(Researcher)
    research = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    notes = await started(session, out, agent, stt, "Hey Swift, summarise my notes from Monday")
    await session.handle(Message("run.stop", {"run_id": research}))
    await until(lambda: agent.cancelled == [research])
    assert any(r.alive for r in session._runs)  # the notes request goes on
    await session.handle(Message("run.stop", {"run_id": "nobody"}))  # unknown: nothing happens
    await session.handle(Message("watch", {"run_id": notes, "open": False}))
    await finish_all(session, agent)
    assert agent.cancelled == [research]
    assert sorted(r["status"] for r in records) == ["cancelled", "done"]


async def test_show_in_word_from_the_live_view() -> None:
    session, out, _records, agent, stt = make(Researcher)
    research = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    await session.handle(Message("live.app", {"run_id": research}))
    await until(lambda: [m for m in sent_for(out, research, "live") if m["kind"] == "hint"])
    assert sent_for(out, research, "live")[-1]["text"] == "It hasn't written in an app."
    # It writes in Word: the button brings Word forward, during the run and after it.
    run = next(r for r in session._runs if r.ui_id == research)
    tools = session.tools
    assert tools is not None and tools.desktop is not None and run.scope is not None
    session.desktop = tools.desktop
    writer = await tools.desktop.writer("word", "insert")
    tools.last_write, tools.last_write_scope = await writer.finish(), run.scope
    await session.handle(Message("live.app", {"run_id": research}))
    await until(lambda: sent_for(out, research, "live")[-1]["text"] != "It hasn't written in an app.")
    assert tools.desktop.shown  # type: ignore[attr-defined]
    await finish_all(session, agent)


# ---- the desktop writer ---------------------------------------------------------------------------


async def test_the_writer_sends_each_paragraph_as_it_writes_it() -> None:
    desktop = FakeDesktop(front=FakeApp("notepad.exe"))
    tools = ToolHost(gateway=ActionGateway(Journal(None)), desktop=desktop)
    items: list[dict[str, Any]] = []

    async def publish(*a: Any) -> None:
        return None

    async def confirm(*a: Any) -> str:
        return "approve"

    async def live(item: dict[str, Any]) -> None:
        items.append(item)

    # The owner asked for the writing (the B-02 gate: only the owner's own words can).
    scope = RunScope(publish, confirm, live_fn=live, said="write a short history of tea in Word")  # type: ignore[arg-type]
    result = await desktop_write(tools, scope, {"text": "Tea\n\nIt began in China.", "where": "word"})
    assert result.ok
    assert [i["text"] for i in items] == ["Tea", "", "It began in China."]
    assert {i["kind"] for i in items} == {"text"} and {i["app"] for i in items} == {"Word"}
    # Without a live view hooked up, writing works as before.
    plain = RunScope(publish, confirm, said="write it in Word")  # type: ignore[arg-type]
    assert (await desktop_write(tools, plain, {"text": "x", "where": "word"})).ok


def test_long_written_text_is_clipped_for_the_overlay() -> None:
    from swift.session import LIVE_TEXT_MAX

    assert LIVE_TEXT_MAX >= 4000


async def test_a_long_paragraph_is_clipped_when_sent() -> None:
    session, out, _records, agent, stt = make(Researcher)
    research = await started(session, out, agent, stt, "Hey Swift, research the history of tea")
    run = next(r for r in session._runs if r.ui_id == research)
    with session._as(run):
        await session._send_live(research, {"kind": "text", "text": "x" * 20000, "app": "Word"})
    assert len(sent_for(out, research, "live")[-1]["text"]) == 8000
    await finish_all(session, agent)


# ---- the owner-checks report --------------------------------------------------------------------


def test_the_owner_checks_report_sees_the_live_view_from_counts_and_lines() -> None:
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("owner_report", root / "spikes" / "owner_checks" / "report.py")
    report = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(report)  # type: ignore[union-attr]
    rows = [{"views": [{"source": "voice", "kind": "live"}], "live": {"source": 5, "note": 2, "text": 7}}]
    log = [
        "10:00:01 | INFO | live view | run_id='cc-1' open=True",
        "10:00:05 | INFO | request stopped from the live view | run_id='cc-1'",
        "10:00:09 | INFO | live view: app shown | run_id='cc-1' shown=True",
    ]
    results = {name.split(" ")[0]: (ok, detail) for name, ok, detail in report.checks(rows, log)}
    for check in ("90", "91", "92", "93", "94", "95"):
        assert results[check][0], (check, results[check])
    assert results["91"][1] == "5 source item(s), 2 note(s)"
    # Nothing seen: each says NOT SEEN.
    assert not any(ok for name, ok, _ in report.checks([], []) if name[:2] in ("90", "91", "92", "93", "94", "95"))
