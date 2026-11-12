"""Health audit 2026-11-12, group SYS: strict xfail repros. Fakes only; nothing touches the real PC."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

import pytest

from swift.system import intents as it
from swift.system.control import FakeSystem, SystemUnavailable
from swift.system.lane import SystemLane
from swift.system.scheduler import Scheduler
from swift.workflows.system_tools import owner_intents

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


def lane(now: datetime = NOW) -> tuple[SystemLane, FakeSystem, Scheduler]:
    control = FakeSystem()
    sched = Scheduler(None, lambda: now.timestamp())
    return SystemLane(control, sched, now=lambda: now), control, sched


@pytest.mark.xfail(strict=True, reason="HA-SYS-01: airplane mode leaves Wi-Fi off, unsaid and with no undo, when Bluetooth raises")
async def test_airplane_half_done_is_said_and_undoable() -> None:
    l, dev, _ = lane()
    real = dev.set_radio

    async def refuse_bluetooth(kind: str, on: bool) -> None:
        if kind == "bluetooth":  # WindowsSystem.set_radio raises like this when Windows says no
            raise SystemUnavailable("Windows didn't let Swift switch Bluetooth. Check Settings, Privacy, Radios.")
        await real(kind, on)

    dev.set_radio = refuse_bluetooth  # type: ignore[method-assign]
    out = await l.run("turn on airplane mode")
    assert out is not None
    done = await l.confirmed(out.pending)
    assert dev.radio_state["wifi"] is False  # Wi-Fi really went off
    assert "Wi-Fi" in done.said and l.can_undo()


class _London(tzinfo):
    """Just enough of Europe/London for March 2027 (BST from 2027-03-28 01:00 UTC); no tzdata here."""

    def utcoffset(self, dt: datetime | None) -> timedelta:
        assert dt is not None
        return timedelta(hours=1) if dt.replace(tzinfo=None) >= datetime(2027, 3, 28, 2, 0) else timedelta(0)

    def dst(self, dt: datetime | None) -> timedelta:
        return self.utcoffset(dt)

    def tzname(self, dt: datetime | None) -> str:
        return "BST" if self.utcoffset(dt) else "GMT"


@pytest.mark.xfail(strict=True, reason="HA-SYS-02: an alarm set before a DST change rings an hour off (fixed-offset now)")
async def test_alarm_across_dst_rings_at_the_wall_clock_time() -> None:
    # The lane's default now is datetime.now().astimezone(): a fixed offset, as here (GMT, +00:00).
    evening = datetime(2027, 3, 27, 22, 0, tzinfo=timezone.utc)
    l, _, sched = lane(evening)
    out = await l.run("set an alarm for 7am tomorrow")
    assert out is not None and out.ok
    wanted = datetime(2027, 3, 28, 7, 0, tzinfo=_London()).timestamp()  # 06:00 UTC
    assert sched.pending("alarm")[0].due == wanted


@pytest.mark.parametrize("text", ["bluetooth on?", "wifi on?", "dark mode on?"])
@pytest.mark.xfail(strict=True, reason="HA-SYS-03: a question with the device and on/off is parsed as switching it")
def test_a_question_is_not_a_switch(text: str) -> None:
    found = it.parse(text)
    assert found is None or all(i.name.endswith(".get") for i in found)


@pytest.mark.xfail(strict=True, reason="HA-SYS-03: 'bluetooth on?' switches Bluetooth on, no question asked")
async def test_bluetooth_question_changes_nothing() -> None:
    l, dev, _ = lane()
    dev.radio_state["bluetooth"] = False
    await l.run("Bluetooth on?")
    assert dev.radio_state["bluetooth"] is False


@pytest.mark.xfail(strict=True, reason="HA-SYS-04: 'turn on the light' switches Windows to light mode")
def test_turn_on_the_light_is_not_the_theme() -> None:
    assert it.parse("turn on the light") is None


@pytest.mark.xfail(strict=True, reason="HA-SYS-05: 'undo that' after an action with no undo reverses an older change")
async def test_undo_follows_the_last_action_not_an_older_one() -> None:
    l, dev, _ = lane()
    await l.run("set the volume to 20")
    await l.run("skip this song")  # nothing to undo: the volume's undo is still held
    assert not l.can_undo()


@pytest.mark.xfail(strict=True, reason="HA-SYS-06: a schedule row with a bad due loads, then kills Scheduler.run")
async def test_a_bad_due_row_does_not_kill_the_clock(tmp_path: Path) -> None:
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps([{"id": 1, "kind": "timer", "due": None, "label": ""}]), encoding="utf-8")
    sched = Scheduler(path, lambda: NOW.timestamp())

    async def on_fire(item: object, missed: bool) -> None:
        pass

    with pytest.raises(TimeoutError):  # still running: the loop never ends by itself
        await asyncio.wait_for(sched.run(on_fire), 0.2)


@pytest.mark.xfail(strict=True, reason="HA-SYS-07: one failed read sets the whole schedule aside and drops every timer")
def test_a_transient_read_error_keeps_the_schedule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "schedule.json"
    Scheduler(path, lambda: NOW.timestamp()).add("alarm", NOW.timestamp() + 3600)
    real = Path.read_text

    def locked(self: Path, *a: object, **k: object) -> str:
        if self == path:
            raise PermissionError("in use by another process")  # antivirus or backup holding the file
        return real(self, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", locked)
    Scheduler(path, lambda: NOW.timestamp())
    monkeypatch.undo()
    assert len(Scheduler(path, lambda: NOW.timestamp()).items) == 1


@pytest.mark.xfail(strict=True, reason="HA-SYS-08: a radio that didn't switch is reported as ok and done")
async def test_a_radio_that_didnt_switch_is_not_ok() -> None:
    l, dev, _ = lane()
    dev.radio_state["bluetooth"] = False

    async def ignored(kind: str, on: bool) -> None:
        pass

    dev.set_radio = ignored  # type: ignore[method-assign]
    out = await l.run("turn on bluetooth")
    assert out is not None and "didn't switch" in out.said
    assert not out.ok and not out.done


@pytest.mark.xfail(strict=True, reason="HA-SYS-09: 'lock it' about something else counts as the owner asking to lock the PC")
def test_lock_it_in_another_request_is_not_lock_the_pc() -> None:
    assert not any(i.name == "lock" for i in owner_intents("write a note and lock it"))


@pytest.mark.xfail(strict=True, reason="HA-SYS-10: a retraction in the next sentence still leaves the lock asked for")
def test_a_retracted_lock_is_not_asked_for() -> None:
    assert not any(i.name == "lock" for i in owner_intents("Lock the computer. No wait, don't."))
