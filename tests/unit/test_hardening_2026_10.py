"""Regression tests for the hardening slice after the 2026-10 audit (B-02, B-03, B-04).

Each test names the finding it covers. Fakes only: nothing real is typed, shown or restarted.
"""

from __future__ import annotations

import pytest
from test_desktop import make

from swift.desktop.fake import FakeApp
from swift.workflows.scope import Grant

# ---- B-02: Swift writes in the owner's apps only when the owner asked for it -------------------


@pytest.mark.parametrize("said", [
    "write a haiku about tea here",
    "put this in Word",
    "type my address",
    "rewrite this more formally",
    "paste the summary into the document",
    "draft a cover letter in Word",
    "Swift, start a template on this topic here",
])
def test_writing_words_count_as_asking_to_write(said: str) -> None:
    from swift.workflows.desktop_tools import owner_asked_to_write

    assert owner_asked_to_write(said)


@pytest.mark.parametrize("said", [
    "what's the weather tomorrow",
    "summarise this page",
    "read me the selected text",
    "how long is the flight to Lagos",
    "",
])
def test_other_requests_dont(said: str) -> None:
    from swift.workflows.desktop_tools import owner_asked_to_write

    assert not owner_asked_to_write(said)


async def test_a_page_cant_make_swift_write_in_a_request_that_didnt_ask() -> None:
    """The agent reads a page that says "type this into the chat": the owner only asked for a summary."""
    host, desktop, owner, journal = make(FakeApp("slack.exe", "edit", route="keys"), said="summarise this page")
    result = await host.call("desktop_write", {"text": "Click here: https://x.example/login"})
    assert not result.ok and "didn't ask" in result.text and result.expected
    assert desktop.writes == [] and journal.entries == [] and owner.asked == []


async def test_writing_the_owner_asked_for_still_happens() -> None:
    host, desktop, _, _ = make(FakeApp("notepad.exe", "edit", route="keys"), said="write a haiku about tea here")
    assert (await host.call("desktop_write", {"text": "one\ntwo"})).ok
    assert [t for _, t in desktop.writes] == ["one", "two"]


async def test_filling_in_an_email_needs_an_email_request() -> None:
    host, desktop, owner, journal = make(FakeApp("chrome.exe", "document"), said="summarise this page")
    result = await host.call("fill_in_email", {"draft_id": "draft-1"})
    assert not result.ok and "didn't ask" in result.text and journal.entries == [] and owner.asked == []
    from swift.workflows.desktop_tools import owner_asked_for_email

    assert owner_asked_for_email("email Ada that I'm running late") and owner_asked_for_email("fill it in Gmail")
    assert not owner_asked_for_email("summarise this page")


async def test_a_workflow_that_declares_writing_keeps_its_manifest_rule() -> None:
    """research-into-word was chosen from the owner's words; its manifest decides, as before."""
    grant = Grant("research-into-word", frozenset({"desktop_write"}), frozenset({"web.search", "desktop.write"}))
    host, desktop, _, _ = make(FakeApp("WINWORD.EXE", "document"), grant=grant, said="tell me about tea")
    assert (await host.call("desktop_write", {"text": "x", "where": "word"})).ok


# ---- B-03: a due timer, alarm or reminder is kept until it has been shown -----------------------


async def _fire(sched, clock_t: float | None = None) -> list[tuple[str, bool]]:  # type: ignore[no-untyped-def]
    import asyncio

    fired: list[tuple[str, bool]] = []

    async def on_fire(item, missed):  # type: ignore[no-untyped-def]
        fired.append((item.label, missed))

    task = asyncio.create_task(sched.run(on_fire))
    await asyncio.sleep(0.05)
    task.cancel()
    return fired


async def test_a_due_item_stays_in_the_file_until_it_is_shown(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import json

    from swift.system.scheduler import Scheduler

    path = tmp_path / "schedule.json"
    a = Scheduler(path, lambda: 1000.0)
    tea = a.add("timer", 999.0, "tea")
    assert await _fire(a) == [("tea", False)]
    assert await _fire(a) == []  # handed over once in this run of Swift
    assert a.pending() == []  # it rang: "what timers do I have" doesn't list it
    assert [r["label"] for r in json.loads(path.read_text(encoding="utf-8"))] == ["tea"]  # but it's kept
    # Swift restarts before the card was shown: it comes due again, as missed.
    b = Scheduler(path, lambda: 1100.0)
    assert await _fire(b) == [("tea", True)]
    b.shown(tea.id)
    assert json.loads(path.read_text(encoding="utf-8")) == []
    assert await _fire(Scheduler(path, lambda: 1200.0)) == []  # never shown twice


async def _due_session():  # type: ignore[no-untyped-def]
    from test_system_lane import _session

    session, rec, _, _ = await _session()
    assert session.system is not None
    return session, rec, session.system.scheduler


def _results(rec) -> list[str]:  # type: ignore[no-untyped-def]
    return [m.data["summary"] for m in rec.messages if m.type == "result"]


async def _settle() -> None:
    import asyncio

    for _ in range(20):
        await asyncio.sleep(0)


async def test_a_due_item_waits_for_the_overlay_and_is_shown_once() -> None:
    from swift.ipc.protocol import Message

    session, rec, sched = await _due_session()
    connected = False
    session.overlay_connected = lambda: connected  # Swift just started: the overlay isn't there yet
    tea = sched.add("timer", sched.clock(), "tea")
    sched.items[-1].fired = True
    await session.notify_due(tea, True)
    await _settle()
    assert _results(rec) == [] and [i.id for i in sched.items] == [tea.id]  # held, still in the file
    connected = True
    await session.handle(Message("ready", {"startup_ms": 1}))
    await _settle()
    assert len(_results(rec)) == 1 and "tea" in _results(rec)[0] and sched.items == []
    await session.handle(Message("ready", {"startup_ms": 1}))  # an overlay reload: not again
    await _settle()
    assert len(_results(rec)) == 1


async def test_a_due_item_never_covers_a_card_waiting_for_an_answer() -> None:
    session, rec, sched = await _due_session()
    open_card: str | None = "req-1"
    session._open_confirm = lambda: open_card  # type: ignore[method-assign]
    tea = sched.add("timer", sched.clock(), "tea")
    await session.notify_due(tea, False)
    await _settle()
    assert _results(rec) == [] and len(sched.items) == 1
    open_card = None  # answered
    await session._kick_due()
    await _settle()
    assert _results(rec) == ["Your tea timer is up."] and sched.items == []


async def test_items_due_together_share_one_card() -> None:
    session, rec, sched = await _due_session()
    session._open_confirm = lambda: "req-1"  # type: ignore[method-assign]
    tea = sched.add("timer", sched.clock(), "tea")
    call = sched.add("reminder", sched.clock(), "call Sam")
    await session.notify_due(tea, False)
    await session.notify_due(call, False)
    session._open_confirm = lambda: None  # type: ignore[method-assign]
    await session._kick_due()
    await _settle()
    assert len(_results(rec)) == 1  # the second didn't replace the first on screen
    assert "tea" in _results(rec)[0] and "call Sam" in _results(rec)[0] and sched.items == []


async def test_a_due_item_while_away_stays_in_the_file_until_back() -> None:
    session, rec, sched = await _due_session()
    await session.hold_cards(True)
    tea = sched.add("timer", sched.clock(), "tea")
    await session.notify_due(tea, False)
    await _settle()
    assert _results(rec) == [] and len(sched.items) == 1
    await session.hold_cards(False)
    await _settle()
    assert _results(rec)[0].startswith("While you were away: Your tea timer is up") and sched.items == []
