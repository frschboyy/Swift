"""Halo A3: while a call is on, cards and speech are held (the away hold), never answered; released after."""

from __future__ import annotations

import types

import pytest

from swift.calls import CallWatch, mic_call
from swift.ipc.protocol import Message
from swift.lifecycle import Lifecycle
from swift.settings import Settings


class FakeProbe:
    def __init__(self) -> None:
        self.on = False

    def in_call(self) -> bool:
        return self.on


class Clock:
    t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_off_by_default() -> None:
    assert Settings().explore.hold_during_calls is False


def test_mic_call_ignores_swift_stale_and_non_call_apps() -> None:
    assert mic_call(["np:Zoom.exe"], {"zoom.exe"}) is True
    assert mic_call(["np:Zoom.exe"], set()) is False  # a stale key: Zoom isn't running
    assert mic_call(["np:python.exe"], {"python.exe"}) is False  # Swift's own mic
    assert mic_call(["np:recorder.exe"], {"recorder.exe"}) is False  # not a call app
    assert mic_call(["np:chrome.exe"], {"chrome.exe"}) is True


def test_store_call_apps_count_by_their_running_package_folder() -> None:
    # Review 7ab2b70 finding 2: the ConsentStore key of a Store app is its package family, never an exe name.
    teams = r"c:\program files\windowsapps\msteams_25275.2601.4002.2815_x64__8wekyb3d8bbwe\ms-teams.exe"
    assert mic_call(["MSTeams_8wekyb3d8bbwe"], {"ms-teams.exe"}, {teams}) is True
    assert mic_call(["MSTeams_8wekyb3d8bbwe"], set(), set()) is False  # not running: a stale key
    assert mic_call(["MSTeams_8wekyb3d8bbwe"], {"ms-teams.exe"}, {teams.replace("8wekyb3d8bbwe", "otherpub")}) is False
    sound = r"c:\program files\windowsapps\microsoft.windowssoundrecorder_1.0_x64__8wekyb3d8bbwe\soundrec.exe"
    assert mic_call(["Microsoft.WindowsSoundRecorder_8wekyb3d8bbwe"], set(), {sound}) is False  # not a call app


async def test_watch_holds_on_the_first_poll_and_releases_after_the_hysteresis() -> None:
    probe, clock, seen = FakeProbe(), Clock(), []

    async def changed(on: bool, seconds: float) -> None:
        seen.append((on, round(seconds)))

    watch = CallWatch(probe, changed, clock=clock, out_s=5)
    probe.on = True
    await watch.poll()
    assert seen == [(True, 0)]
    clock.t += 600
    probe.on = False
    await watch.poll()  # an app reopens the mic between prompts: not over yet
    clock.t += 3
    await watch.poll()
    assert seen == [(True, 0)]
    probe.on = True
    clock.t += 1
    await watch.poll()  # back: the quiet gap starts over
    probe.on = False
    clock.t += 1
    await watch.poll()
    clock.t += 5
    await watch.poll()
    assert seen == [(True, 0), (False, 605)]


async def test_a_failed_probe_changes_nothing() -> None:
    class Broken:
        def in_call(self) -> bool:
            raise OSError("registry")

    seen: list[bool] = []

    async def changed(on: bool, seconds: float) -> None:
        seen.append(on)

    await CallWatch(Broken(), changed, clock=Clock()).poll()
    assert seen == []


async def _life(held: list[bool], away: bool = False) -> Lifecycle:
    async def hold_cards(h: bool) -> None:
        held.append(h)

    async def send(msg: object) -> None:
        pass

    life = Lifecycle(types.SimpleNamespace(listening_paused=False, hold_cards=hold_cards), send)
    life.monitor = types.SimpleNamespace(state="away" if away else "here", listening_allowed=True, reason="input")  # type: ignore[assignment]
    return life


async def test_the_lifecycle_holds_for_a_call_and_releases_after() -> None:
    held: list[bool] = []
    life = await _life(held)
    await life.set_call(True, 0)
    await life.set_call(False, 600)
    assert held == [True, False]


async def test_the_end_of_a_call_does_not_release_while_the_owner_is_away() -> None:
    held: list[bool] = []
    life = await _life(held, away=True)
    await life.set_call(True, 0)
    await life.set_call(False, 600)
    assert held == [True, True]


async def test_coming_back_from_away_mid_call_keeps_the_hold() -> None:
    held: list[bool] = []
    life = await _life(held)
    await life.set_call(True, 0)
    change = types.SimpleNamespace(new="here", locked_or_asleep=False, returned=False, reason="input")
    await life.handle(change)  # type: ignore[arg-type]
    assert held == [True, True]


@pytest.mark.parametrize("n", [1])
def test_example_config_documents_the_switch(n: int) -> None:
    assert "hold_during_calls" in open("config.example.yaml", encoding="utf-8").read()


# ---- review 7ab2b70 finding 1: a card that arrives during a call is held too ------------------------


async def test_a_card_arriving_during_a_call_is_held_not_drawn() -> None:
    import asyncio

    from swift.attention import Attention
    from swift.parked import ParkedThreads
    from test_corrections import finish, make, start

    session, out, records, calendar, agent, stt = make(attention=Attention(), parked=ParkedThreads(None))
    await session.hold_cards(True)  # the call started before the card (Lifecycle.set_call)
    await start(session, out, stt)
    card = out.last("confirm.request")
    after = [m for m in out.messages[out.messages.index(next(m for m in out.messages if m.type == "confirm.request")):]]
    assert {"request_id": card["request_id"], "held": True} in [m.data for m in after if m.type == "confirm.hold"]
    assert any(i["id"] == f"card:{card['request_id']}" and i["reason"] == "held" for i in out.last("stack")["items"])
    await asyncio.sleep(0.01)
    assert session.state == "confirm" and records == []  # frozen, never answered for the owner
    await session.hold_cards(False)
    assert out.last("confirm.hold") == {"request_id": card["request_id"], "held": False}
    await session.handle(Message("confirm.reply", {"request_id": card["request_id"], "decision": "reject"}))
    await finish(session)
    assert calendar.created == []


# ---- review 7ab2b70 finding 3: a hold says so, and a key left open for hours doesn't hold ---------------


async def test_a_call_hold_is_announced_and_its_end_too() -> None:
    sent: list[Message] = []

    async def send(msg: Message) -> None:
        sent.append(msg)

    async def hold_cards(h: bool) -> None:
        pass

    life = Lifecycle(types.SimpleNamespace(listening_paused=False, hold_cards=hold_cards), send)
    await life.set_call(True, 0)
    assert sent[-1].type == "presence" and sent[-1].data["call"] is True
    await life.set_call(False, 600)
    assert sent[-1].type == "presence" and "call" not in sent[-1].data


def test_a_key_opened_hours_ago_is_stale() -> None:
    from swift.calls import STALE_S, opened_recently

    now = 1_800_000_000.0
    ticks = 10_000_000  # Windows' FILETIME: 100 ns ticks since 1601
    assert opened_recently(int((now - 60 + 11644473600) * ticks), now) is True
    assert opened_recently(int((now - STALE_S - 1 + 11644473600) * ticks), now) is False


# ---- review 7ab2b70 finding 4: the owner can bring a held card back during a call ----------------------


async def test_opening_the_held_card_lifts_the_call_hold_until_the_next_call() -> None:
    held: list[bool] = []
    life = await _life(held)
    await life.set_call(True, 0)
    await life.lift_call()  # the owner opened the held card from the stack: they chose to show it
    change = types.SimpleNamespace(new="idle", locked_or_asleep=False, returned=False, reason="input")
    await life.handle(change)  # type: ignore[arg-type]
    assert held == [True, False, False]
    await life.set_call(False, 60)
    await life.set_call(True, 0)  # a new call holds again
    assert held[-1] is True


async def test_the_stack_open_of_the_held_card_asks_the_lifecycle_to_lift_the_hold() -> None:
    from swift.attention import Attention
    from swift.parked import ParkedThreads
    from test_corrections import finish, make, start

    session, out, records, calendar, agent, stt = make(attention=Attention(), parked=ParkedThreads(None))
    lifted: list[bool] = []

    async def lift() -> None:
        lifted.append(True)
        await session.hold_cards(False)

    session.on_open_held = lift
    await session.hold_cards(True)
    await start(session, out, stt)
    card = out.last("confirm.request")
    await session.handle(Message("stack.action", {"id": f"card:{card['request_id']}", "action": "open"}))
    assert lifted == [True] and out.last("confirm.hold") == {"request_id": card["request_id"], "held": False}
    await session.handle(Message("confirm.reply", {"request_id": card["request_id"], "decision": "reject"}))
    await finish(session)


# ---- review 7ab2b70 finding 5: an error while holding doesn't end call detection -------------------------


async def test_a_failing_hold_keeps_the_watch_polling() -> None:
    import asyncio

    probe, calls = FakeProbe(), []

    async def on_change(on: bool, seconds: float) -> None:
        calls.append(on)
        raise RuntimeError("hold_cards broke")

    watch = CallWatch(probe, on_change, out_s=0)
    probe.on = True
    task = asyncio.create_task(watch.run(every_s=0.01))
    await asyncio.sleep(0.2)
    probe.on = False
    await asyncio.sleep(0.2)
    assert not task.done() and calls == [True, False]
    task.cancel()


# ---- review 7ab2b70 findings 6 and 9: the probe runs off the event loop, and a failing one logs once ---------


async def test_the_probe_runs_off_the_event_loop() -> None:
    import threading

    threads: list[int] = []

    class Where(FakeProbe):
        def in_call(self) -> bool:
            threads.append(threading.get_ident())
            return False

    async def on_change(on: bool, seconds: float) -> None:
        pass

    await CallWatch(Where(), on_change).poll()
    assert threads and threads[0] != threading.get_ident()


# ---- review 7ab2b70 finding 7: what was said is forgotten when the hold begins, not at every presence change ----


async def test_the_dialogue_is_forgotten_once_when_the_hold_begins() -> None:
    from swift.attention import Attention
    from swift.parked import ParkedThreads
    from test_corrections import make

    session, out, records, calendar, agent, stt = make(attention=Attention(), parked=ParkedThreads(None))
    forgot: list[bool] = []
    session.dialogue.forget = lambda: forgot.append(True)  # type: ignore[method-assign]
    await session.hold_cards(True)
    await session.hold_cards(True)  # an idle/here flip mid-call holds again: nothing new to forget
    await session.hold_cards(False)
    await session.hold_cards(True)
    assert forgot == [True, True]


# ---- review 7ab2b70 finding 8: desktop call apps by exact exe name -------------------------------------


def test_lookalike_exes_are_not_call_apps() -> None:
    for exe in ("msedgewebview2.exe", "zoomit.exe", "chromedriver.exe"):
        assert mic_call([f"np:{exe}"], {exe}) is False, exe
    for exe in ("ms-teams.exe", "teams.exe", "zoom.exe", "msedge.exe", "firefox.exe"):
        assert mic_call([f"np:{exe}"], {exe}) is True, exe


async def test_a_failing_probe_logs_once_per_error_until_it_works() -> None:
    from loguru import logger

    class Broken(FakeProbe):
        def in_call(self) -> bool:
            if self.on:
                return False
            raise OSError("registry")

    async def on_change(on: bool, seconds: float) -> None:
        pass

    logged: list[str] = []
    sink = logger.add(lambda m: logged.append(m.record["message"]), level="WARNING")
    try:
        probe = Broken()
        watch = CallWatch(probe, on_change)
        for _ in range(3):
            await watch.poll()
        probe.on = True
        await watch.poll()  # working again
        probe.on = False
        await watch.poll()  # a new failure is logged again
    finally:
        logger.remove(sink)
    assert logged == ["call probe failed", "call probe failed"]
