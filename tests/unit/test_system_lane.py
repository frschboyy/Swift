"""The system lane (ADR-016 §3): the grammar, Swift's clock, the lane on a fake device, and the session."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_routing import SpyExecutor, ask
from test_session import Recorder

from swift.executors.mock import MockExecutor
from swift.routing import route
from swift.session import Session
from swift.system import intents as it
from swift.system.control import Battery, FakeSystem, SystemControl
from swift.system.lane import SystemLane
from swift.system.scheduler import Scheduler

# Tuesday 27 October 2026, 14:05 local (UTC+2).
NOW = datetime(2026, 10, 27, 14, 5, 0, tzinfo=timezone(timedelta(hours=2)))


def names(text: str) -> list[str] | None:
    found = it.parse(text)
    return None if found is None else [i.name for i in found]


# ---- the grammar: what is an intent ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("set a timer for 10 minutes", ["timer.set"]),
        ("Swift, set a timer for ten minutes", ["timer.set"]),
        ("start a 5 minute timer for the pasta", ["timer.set"]),
        ("timer for an hour and a half", ["timer.set"]),
        ("how long is left on the timer", ["timer.left"]),
        ("cancel the timer", ["cancel"]),
        ("cancel all my timers", ["cancel"]),
        ("what timers do I have", ["list"]),
        ("wake me up at seven", ["alarm.set"]),
        ("set an alarm for 6:30 am", ["alarm.set"]),
        ("set an alarm for seven thirty tomorrow", ["alarm.set"]),
        ("remind me to call Sam at five", ["reminder.set"]),
        ("remind me in 20 minutes to take the pizza out", ["reminder.set"]),
        ("remind me to call mum tomorrow at 9 am", ["reminder.set"]),
        ("volume up", ["volume.step"]),
        ("turn the volume down a bit", ["volume.step"]),
        ("set the volume to 30 percent", ["volume.set"]),
        ("make it quieter", ["volume.step"]),
        ("what's the volume", ["volume.get"]),
        ("mute the sound", ["mute"]),
        ("unmute", ["mute"]),
        ("pause the music", ["media"]),
        ("next song", ["media"]),
        ("turn on dark mode", ["theme"]),
        ("switch to light mode", ["theme"]),
        ("set brightness to 40", ["brightness.set"]),
        ("dim the screen", ["brightness.step"]),
        ("lock the computer", ["lock"]),
        ("what's my battery", ["info"]),
        ("how much space do I have left", ["info"]),
        ("open bluetooth settings", ["settings"]),
        ("open the Wi-Fi settings", ["settings"]),
        ("minimize this window", ["window"]),
        ("show the desktop", ["window"]),
        ("take a screenshot", ["screenshot"]),
        ("search the web for pasta recipes", ["search"]),
        ("google best laptops 2026", ["search"]),
        ("turn the volume down and pause the music", ["volume.step", "media"]),
        ("set a timer for 5 minutes and remind me to stretch at 5 pm", ["timer.set", "reminder.set"]),
    ],
)
def test_intents(text: str, expected: list[str]) -> None:
    assert names(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "remind me to buy 15 apples",  # "15" is not a clock time
        "Remind me every weekday at 9 to check the lab bookings.",  # repeating: not a one-off
        "Cancel the Friday reminder.",  # may be a calendar event
        "Search the codebase for every place we call transcribe.",  # the web isn't named
        "search for pasta",
        "turn up the heat",
        "open word",
        "shut down the computer",  # power actions wait for a confirmation (ADR-016 §3.1)
        "restart my pc",
        "put the computer to sleep",
        "research the history of tea",
        "what time is it",
        "cancel my meeting",
        "mute",  # Swift's own mute
        "stop",
        "remind me on friday to call Sam",  # a day but no time: the agent (Phase C asks only the plain shape)
        "remind me what we decided about the logo",  # a question, not a reminder
        "set a timer and write a haiku about tea",  # a missing detail only in a whole utterance
        "search the web for pasta recipes and email them to me",
        "turn the volume down and write a haiku about tea",  # one part isn't an intent
    ],
)
def test_not_intents(text: str) -> None:
    assert names(text) is None


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("set a timer for 10 minutes", "timer.set"),
        ("what's my battery", "info"),
        ("turn on dark mode", "theme"),
    ],
)
def test_router_sends_system_requests_to_the_lane(text: str, kind: str) -> None:
    r = route(text)
    assert (r.route, r.action) == ("local", "system")
    assert names(text) == [kind]


# ---- clock times ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("remind me to call sam at 5", "2026-10-27 17:00"),  # 14:05 now: the next 5 is this evening
        ("remind me to call sam at 3 pm", "2026-10-27 15:00"),
        ("remind me to call sam at 2 pm", "2026-10-28 14:00"),  # already past today
        ("remind me to call sam tomorrow at 9 am", "2026-10-28 09:00"),
        ("remind me to call sam at 9", "2026-10-28 09:00"),  # 9 am has passed, 9 pm is later... the earlier future one
        ("remind me to call sam on friday at 10 am", "2026-10-30 10:00"),
        ("remind me to call sam tonight at 8", "2026-10-27 20:00"),
        ("remind me to call sam at 17:30", "2026-10-27 17:30"),
        ("remind me to call sam at half past six", "2026-10-27 18:30"),
        ("remind me to call sam at noon", "2026-10-28 12:00"),
    ],
)
def test_reminder_times(text: str, expected: str) -> None:
    (intent,) = it.parse(text) or []
    due = it.resolve(intent["when"], NOW)
    # "at 9" with now 14:05: 9 am tomorrow is later than 9 pm today? No: 21:00 today is first.
    if text.endswith("at 9"):
        expected = "2026-10-27 21:00"
    assert due is not None and due.strftime("%Y-%m-%d %H:%M") == expected


def test_wake_me_means_the_morning() -> None:
    (intent,) = it.parse("wake me up at seven") or []
    assert it.resolve(intent["when"], NOW).strftime("%Y-%m-%d %H:%M") == "2026-10-28 07:00"
    (intent,) = it.parse("set an alarm for seven") or []
    assert it.resolve(intent["when"], NOW).strftime("%Y-%m-%d %H:%M") == "2026-10-27 19:00"


def test_say_duration() -> None:
    assert it.say_duration(600) == "10 minutes"
    assert it.say_duration(90) == "1 minute and 30 seconds"
    assert it.say_duration(3725) == "1 hour and 2 minutes"
    assert it.say_duration(45) == "45 seconds"


# ---- Swift's clock ----------------------------------------------------------------------------


class Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_scheduler_keeps_items_across_a_restart(tmp_path: Path) -> None:
    clock = Clock()
    path = tmp_path / "schedule.json"
    a = Scheduler(path, clock)
    a.add("timer", 1600, "pasta")
    a.add("reminder", 1900, "call sam")
    b = Scheduler(path, clock)
    assert [(i.kind, i.label) for i in b.pending()] == [("timer", "pasta"), ("reminder", "call sam")]
    assert b.add("alarm", 2000).id == 3  # ids keep counting
    assert b.remove(1) is not None
    assert [i.id for i in Scheduler(path, clock).pending()] == [2, 3]


def test_scheduler_survives_a_damaged_file(tmp_path: Path) -> None:
    path = tmp_path / "schedule.json"
    path.write_text("{ not json", encoding="utf-8")
    assert Scheduler(path).pending() == []
    assert (tmp_path / "schedule.json.bad").read_text(encoding="utf-8") == "{ not json"


def test_one_bad_row_keeps_the_others_and_the_file(tmp_path: Path) -> None:
    # Audit 2026-11-09: one row that didn't fit dropped every item, and the next save overwrote the file.
    clock = Clock()
    path = tmp_path / "schedule.json"
    rows = [
        {"id": 1, "kind": "reminder", "due": 1900, "label": "call sam", "created": 0, "fired": False, "repeat": "daily"},
        {"id": 2, "kind": "timer"},  # no due time
        {"id": 3, "kind": "alarm", "due": 2000, "label": "", "created": 0, "fired": False},
    ]
    path.write_text(json.dumps(rows), encoding="utf-8")
    sched = Scheduler(path, clock)
    assert [(i.id, i.label) for i in sched.pending()] == [(1, "call sam"), (3, "")]
    assert json.loads((tmp_path / "schedule.json.bad").read_text(encoding="utf-8")) == rows
    sched.add("timer", 2100, "pasta")
    assert [i.id for i in Scheduler(path, clock).pending()] == [1, 3, 4]


async def test_scheduler_fires_due_items_once_and_marks_missed_ones() -> None:
    clock = Clock(1000.0)
    sched = Scheduler(None, clock)
    sched.add("timer", 1000.5, "tea")
    sched.add("reminder", 900.0, "old one")  # due 100 s ago: missed
    fired: list[tuple[str, bool]] = []

    async def on_fire(item, missed):  # type: ignore[no-untyped-def]
        fired.append((item.label, missed))

    task = asyncio.create_task(sched.run(on_fire))
    await asyncio.sleep(0.05)
    assert fired == [("old one", True)]
    clock.t = 1001.0
    sched._wake.set()
    await asyncio.sleep(0.05)
    task.cancel()
    assert fired == [("old one", True), ("tea", False)] and sched.pending() == []


# ---- the lane on a fake device --------------------------------------------------------------


def lane(**device: object) -> tuple[SystemLane, FakeSystem, Scheduler]:
    control = FakeSystem(**device)  # type: ignore[arg-type]
    sched = Scheduler(None, lambda: NOW.timestamp())
    return SystemLane(control, sched, now=lambda: NOW), control, sched


async def say(l: SystemLane, text: str) -> str:
    out = await l.run(text)
    assert out is not None, text
    return out.said


async def test_timers_are_set_listed_and_cancelled() -> None:
    l, _, sched = lane()
    assert await say(l, "set a 10 minute timer for the pasta") == "Timer set for 10 minutes for pasta."
    assert len(sched.pending("timer")) == 1
    assert await say(l, "how long is left on the timer") == "10 minutes left on pasta."
    assert await say(l, "what timers do I have") == "You have 1 timer: pasta timer, 10 minutes left."
    assert await say(l, "cancel the timer") == "Cancelled your pasta timer, 10 minutes left."
    assert await say(l, "how long is left on the timer") == "There's no timer running."
    assert await say(l, "cancel the timer") == "There's no timer to cancel."


async def test_several_timers_need_a_name_or_all() -> None:
    l, _, sched = lane()
    await say(l, "set a 10 minute timer for pasta")
    await say(l, "set a 5 minute timer for tea")
    assert "Say “cancel all timers” or name one" in await say(l, "cancel the timer")
    assert len(sched.pending("timer")) == 2
    assert (await say(l, "cancel the tea timer")).startswith("Cancelled your tea timer")
    assert (await say(l, "cancel all timers")).startswith("Cancelled your pasta timer")


async def test_reminders_and_alarms() -> None:
    l, _, sched = lane()
    assert await say(l, "remind me to call Sam at 5") == "I'll remind you to call sam at 17:00."
    assert await say(l, "remind me in 20 minutes to check the oven") == "I'll remind you to check the oven in 20 minutes."
    assert await say(l, "wake me up at seven") == "Alarm set for 07:00 tomorrow."
    assert await say(l, "remind me to leave at 2 pm") == "I'll remind you to leave at 14:00 tomorrow."
    assert len(sched.pending("reminder")) == 3 and len(sched.pending("alarm")) == 1
    assert (await say(l, "what are my reminders")).startswith("You have 3 reminders: ")


async def test_a_reminder_for_a_time_that_has_gone_is_refused() -> None:
    l, _, sched = lane()
    assert await say(l, "remind me to call sam today at 9 am") == "That time has already passed."
    assert sched.pending() == []


async def test_volume_steps_sets_and_undoes() -> None:
    l, dev, _ = lane(volume=40)
    assert await say(l, "volume up") == "Volume 50."
    assert await say(l, "turn the volume down a bit") == "Volume 45."
    assert await say(l, "set the volume to 20 percent") == "Volume set to 20."
    assert l.can_undo() and await l.undo() == "Volume back to 45."
    assert dev.volume == 45
    assert not l.can_undo() or await l.undo()  # nothing more to undo, or one more step: never an error
    assert await say(l, "what's the volume") == "The volume is 45%."


async def test_volume_limits_and_unmuting() -> None:
    l, dev, _ = lane(volume=100)
    assert await say(l, "volume up") == "The volume is already at the top."
    dev.volume, dev.muted = 0, False
    assert await say(l, "volume down") == "The volume is already off."
    dev.volume, dev.muted = 30, True
    assert await say(l, "turn it up") == "Volume 40."
    assert dev.muted is False


async def test_play_with_no_music_app_open_says_nothing_played(monkeypatch: pytest.MonkeyPatch) -> None:
    # Owner check 235, 2026-11-13: "play some music" said "Playing." and nothing played.
    from swift.system import lane as lane_mod

    monkeypatch.setattr(lane_mod, "PLAY_CHECK_S", 0.0)
    l, dev, _ = lane(playing=False, player=False)
    assert await say(l, "play some music") == lane_mod.NOTHING_PLAYED
    assert ("media_key", ("play_pause",)) in dev.calls and not dev.playing


async def test_mute_and_media() -> None:
    l, dev, _ = lane(playing=True)
    assert await say(l, "mute the sound") == "Muted." and dev.muted
    assert await l.undo() == "Unmuted." and not dev.muted
    assert await say(l, "pause the music") == "Paused." and not dev.playing
    assert await say(l, "pause the music") == "Nothing seems to be playing."
    assert await say(l, "play the music") == "Playing." and dev.playing
    assert await say(l, "play the music") == "It's already playing."
    assert await say(l, "next song") == "Next track."
    assert [c for c in dev.calls if c[0] == "media_key"] == [
        ("media_key", ("play_pause",)), ("media_key", ("play_pause",)), ("media_key", ("next",)),
    ]


async def test_theme_and_brightness() -> None:
    l, dev, _ = lane(dark=True, brightness=60)
    assert await say(l, "turn on dark mode") == "It's already in dark mode."
    assert await say(l, "switch to light mode") == "Switched to light mode." and not dev.dark
    assert await l.undo() == "Back to dark mode." and dev.dark
    assert await say(l, "turn the brightness down") == "Brightness 40."
    assert await say(l, "set brightness to 90") == "Brightness set to 90."
    assert await l.undo() == "Brightness back to 40."


async def test_a_display_that_cannot_dim_says_so() -> None:
    l, _, _ = lane(brightness=None)
    out = await l.run("turn the brightness down")
    assert out is not None and not out.ok
    assert out.said == "This display doesn't let Windows change its brightness."


async def test_information() -> None:
    l, _, _ = lane()
    assert await say(l, "what's my battery") == "Battery's at 76%, on battery, about 3 hours and 10 minutes left."
    assert await say(l, "how much space do I have left") == "212 GB free of 476 GB on C:."
    assert await say(l, "what's my cpu usage") == "The processor is at 14%."
    assert await say(l, "how much ram am I using") == "9.1 GB of 16 GB of memory in use."
    assert await say(l, "how long has my computer been on") == "Up for 3 hours and 25 minutes."
    l2, _, _ = lane(battery_state=None)
    assert await say(l2, "what's my battery") == "This computer has no battery."
    l3, _, _ = lane(battery_state=Battery(100, True))
    assert await say(l3, "am I plugged in") == "Battery's at 100%, plugged in."


async def test_windows_settings_and_search() -> None:
    l, dev, _ = lane()
    assert await say(l, "open the bluetooth settings") == "Opening Bluetooth settings."
    assert await say(l, "search the web for pasta recipes") == "Searching the web for pasta recipes."
    assert await say(l, "lock the computer") == "Locked."
    assert await say(l, "minimize this window") == "Minimized."
    assert dev.calls[0] == ("open_uri", ("ms-settings:bluetooth",))
    assert dev.calls[1] == ("open_uri", ("https://www.google.com/search?q=pasta+recipes",))
    assert ("lock", ()) in dev.calls and ("window", ("minimize",)) in dev.calls


async def test_a_compound_is_done_in_order_and_undone_together() -> None:
    l, dev, _ = lane(volume=40, playing=True)
    assert await say(l, "turn the volume down and pause the music") == "Volume 30. Paused."
    assert await l.undo() == "Volume back to 40."


async def test_the_base_device_refuses_with_a_sentence() -> None:
    l = SystemLane(SystemControl(), Scheduler(None), now=lambda: NOW)
    out = await l.run("volume up")
    assert out is not None and not out.ok and out.said == "I can't read the volume here."


def test_due_text() -> None:
    l, _, sched = lane()
    timer = sched.add("timer", NOW.timestamp(), "pasta")
    assert l.due_text(timer, False) == "Your pasta timer is up."
    reminder = sched.add("reminder", NOW.timestamp(), "call sam")
    assert l.due_text(reminder, True).startswith("Reminder: call sam. (It was due at ")


def test_claims_leaves_unknown_reminders_to_the_agent() -> None:
    l, _, sched = lane()
    assert not l.claims("what reminders do I have")  # none set here: maybe in the calendar
    assert not l.claims("cancel my reminder about the parking permit")
    assert l.claims("what timers do I have")
    sched.add("reminder", NOW.timestamp() + 60, "parking permit")
    assert l.claims("what reminders do I have")


# ---- through the session --------------------------------------------------------------------


async def _session(**device: object) -> tuple[Session, Recorder, SpyExecutor, list[dict]]:
    rec, records, spy = Recorder(), [], SpyExecutor()
    session = Session(rec, spy, debug_executor=MockExecutor(speed=0), on_finish=records.append)
    session._test = (rec, spy, records)  # type: ignore[attr-defined]
    session.system, _, _ = lane(**device)
    return session, rec, spy, records


async def test_the_session_does_it_without_the_agent() -> None:
    session, rec, spy, records = await _session(volume=40)
    await ask("turn the volume up", session)
    assert spy.calls == []
    assert rec.last("result")["summary"] == "Volume 50."
    assert (records[0]["route"], records[0]["action"], records[0]["status"]) == ("local", "system", "done")
    assert records[0]["intents"] == ["volume.step"]


async def test_undo_that_undoes_the_system_change() -> None:
    session, rec, spy, records = await _session(volume=40)
    await ask("volume up", session)
    await ask("undo that", session)
    assert rec.last("result")["summary"] == "Volume back to 40."
    assert spy.calls == [] and records[1]["action"] == "system_undo"


async def test_without_the_lane_requests_go_to_the_agent() -> None:
    rec, records, spy = Recorder(), [], SpyExecutor()
    session = Session(rec, spy, debug_executor=MockExecutor(speed=0), on_finish=records.append)
    session._test = (rec, spy, records)  # type: ignore[attr-defined]
    await ask("set a timer for 10 minutes", session)
    assert spy.calls and records[0]["route"] == "agent"


async def test_a_reminder_question_with_nothing_set_here_goes_to_the_agent() -> None:
    session, _, spy, records = await _session()
    await ask("what reminders do I have", session)
    assert spy.calls and records[0]["route"] == "agent"


async def test_a_failure_is_an_error_record_with_a_sentence() -> None:
    session, rec, _, records = await _session(brightness=None)
    await ask("brightness down", session)
    assert rec.last("result")["summary"] == "This display doesn't let Windows change its brightness."
    assert records[0]["status"] == "error" and records[0]["error"] == "system_failed"


async def test_a_due_timer_shows_a_card_and_chimes() -> None:
    session, rec, _, _ = await _session()
    assert session.system is not None
    item = session.system.scheduler.add("timer", NOW.timestamp(), "tea")
    await session.notify_due(item, False)
    await asyncio.sleep(0)
    assert rec.last("result")["summary"] == "Your tea timer is up."
    assert ("chime", (3,)) in session.system.control.calls  # type: ignore[attr-defined]


# ---- the eval set agrees with the router ----------------------------------------------------


def test_system_rows_in_the_eval_set_are_local() -> None:
    root = Path(__file__).resolve().parents[2]
    rows = [json.loads(x) for x in (root / "eval" / "routes.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    system = [r for r in rows if "system" in r["tags"]]
    assert system and all(r["route"] == "local" and route(r["text"]).action == "system" for r in system)


# ---- the journal, held cards, short clips (fixes before the A1 commit) -----------------------


async def test_device_changes_are_journaled_without_content() -> None:
    from swift.security.journal import Journal

    journal = Journal(None)
    control = FakeSystem(volume=40)
    l = SystemLane(control, Scheduler(None, lambda: NOW.timestamp()), now=lambda: NOW, journal=journal)
    await l.run("volume up")
    await l.run("search the web for my secret plans")
    await l.run("remind me to call Sam at 5")  # Swift's own list: not a device change
    await l.run("what's my battery")  # a read
    await l.undo()
    tools = [e.get("tool") for e in journal.entries if e["state"] == "PENDING"]
    assert tools == ["system.volume.step", "system.search", "system.undo"]
    assert [e["state"] for e in journal.entries] == ["PENDING", "DONE"] * 3
    assert journal.entries[1]["undoable"] is True
    assert journal.entries[2]["domains"] == ["google.com"]
    assert "secret" not in json.dumps(journal.entries) and "Sam" not in json.dumps(journal.entries)


async def test_a_failed_change_is_journaled_as_failed() -> None:
    from swift.security.journal import Journal

    journal = Journal(None)
    l = SystemLane(FakeSystem(brightness=None), Scheduler(None), now=lambda: NOW, journal=journal)
    await l.run("dim the screen")
    assert [(e["state"], e.get("reason")) for e in journal.entries] == [("PENDING", None), ("FAILED", "unavailable")]


async def test_due_items_wait_while_the_owner_is_away() -> None:
    session, rec, _, _ = await _session()
    assert session.system is not None
    await session.hold_cards(True)  # locked, asleep or idle
    tea = session.system.scheduler.add("timer", NOW.timestamp(), "tea")
    call = session.system.scheduler.add("reminder", NOW.timestamp() + 60, "call Sam")
    await session.notify_due(tea, False)
    await session.notify_due(call, False)
    assert not [m for m in rec.messages if m.type == "result"]  # nothing shown to an empty room
    await session.hold_cards(False)  # back
    for _ in range(5):
        await asyncio.sleep(0)
    assert [c for c in session.system.control.calls if c[0] == "chime"] == [("chime", (3,)), ("chime", (2,))]  # type: ignore[attr-defined]
    summary = rec.last("result")["summary"]
    assert summary.startswith("While you were away: Your tea timer is up (") and "Reminder: call Sam (" in summary


async def test_one_due_item_while_away_reads_naturally() -> None:
    session, rec, _, _ = await _session()
    assert session.system is not None
    await session.hold_cards(True)
    tea = session.system.scheduler.add("timer", NOW.timestamp(), "tea")
    await session.notify_due(tea, False)
    await session.hold_cards(False)
    for _ in range(5):
        await asyncio.sleep(0)
    assert rec.last("result")["summary"].startswith("While you were away: Your tea timer is up, at ")


@pytest.mark.parametrize("text", ["louder", "volume up", "unmute", "next song", "pause the music", "turn it down"])
async def test_short_volume_and_media_commands_are_kept(text: str) -> None:
    session, _, _, _ = await _session()
    assert session._short_kept(text, busy=False) == text


@pytest.mark.parametrize("text", ["lock the computer", "turn up the heat", "dark mode on", "uh huh"])
async def test_other_short_clips_are_still_dropped(text: str) -> None:
    session, _, _, _ = await _session()
    assert session._short_kept(text, busy=False) is None


def test_help_mentions_what_swift_does_itself() -> None:
    from swift.session import HELP_TEXT

    for word in ("timers", "reminders", "volume", "dark mode", "Bluetooth", "undo that"):
        assert word in HELP_TEXT
