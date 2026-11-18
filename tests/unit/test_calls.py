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
