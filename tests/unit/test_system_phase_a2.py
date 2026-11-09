"""ADR-016 Phase A2: radios and Do Not Disturb, asking before a disruptive change, the agent's
``system_action`` tool, and the owner-checks report's lanes."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from test_routing import ask
from test_system_lane import _session, lane, names, say

from swift.system import intents as it

# ---- radios and Do Not Disturb --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "name", "slots"),
    [
        ("turn off wifi", "radio", {"kind": "wifi", "on": False}),
        ("turn the wi-fi off", "radio", {"kind": "wifi", "on": False}),
        ("turn on bluetooth", "radio", {"kind": "bluetooth", "on": True}),
        ("disable bluetooth", "radio", {"kind": "bluetooth", "on": False}),
        ("is my wifi on", "radio.get", {"kind": "wifi"}),
        ("turn on airplane mode", "airplane", {"on": True}),
        ("airplane mode off", "airplane", {"on": False}),
        ("turn on do not disturb", "dnd", {"on": True}),
    ],
)
def test_radio_intents(text: str, name: str, slots: dict) -> None:
    (intent,) = it.parse(text) or []
    assert (intent.name, intent.slots) == (name, slots)


@pytest.mark.parametrize("text", ["wifi password", "connect to wifi", "turn off the heating"])
def test_not_radio_intents(text: str) -> None:
    assert names(text) is None


async def test_turning_a_radio_on_just_happens_and_undoes() -> None:
    l, dev, _ = lane(radio_state={"wifi": True, "bluetooth": False})
    assert await say(l, "turn on bluetooth") == "Bluetooth on."
    assert await say(l, "turn on bluetooth") == "Bluetooth is already on."
    assert await say(l, "is my wifi on") == "Wi-Fi is on."
    l2, dev2, _ = lane(radio_state={"wifi": True, "bluetooth": False})
    await say(l2, "turn on bluetooth")
    assert await l2.undo() == "Bluetooth back off." and dev2.radio_state["bluetooth"] is False


async def test_turning_a_radio_off_asks_first() -> None:
    l, dev, _ = lane()
    out = await l.run("turn off wifi")
    assert out is not None and out.said.endswith("Turn off Wi-Fi?") and out.pending
    assert dev.radio_state["wifi"] is True  # nothing done yet
    done = await l.confirmed(out.pending)
    assert done.said == "Wi-Fi off." and dev.radio_state["wifi"] is False


async def test_airplane_mode_switches_every_radio_and_says_so() -> None:
    l, dev, _ = lane()
    out = await l.run("turn on airplane mode")
    assert out is not None and out.pending
    assert out.said.endswith("Turn off Wi-Fi and Bluetooth instead?")  # never promised as airplane mode
    assert (await l.confirmed(out.pending)).said == "Wi-Fi and Bluetooth are off. Windows' own airplane mode switch is unchanged."
    assert dev.radio_state == {"wifi": False, "bluetooth": False}
    assert await l.undo() == "Radios back as they were." and dev.radio_state == {"wifi": True, "bluetooth": True}


async def test_do_not_disturb_opens_the_setting_honestly() -> None:
    l, dev, _ = lane()
    said = await say(l, "turn on do not disturb")
    assert said.startswith("Windows doesn't let apps switch Do Not Disturb")
    assert ("open_uri", ("ms-settings:notifications",)) in dev.calls


# ---- asking first, in the session -----------------------------------------------------------


async def test_the_session_asks_and_a_yes_does_it() -> None:
    session, rec, spy, records = await _session()
    await ask("turn off the wifi", session)
    assert rec.last("ask")["question"] == "Turn off Wi-Fi?"
    assert session.system.control.radio_state["wifi"] is True  # type: ignore[union-attr]
    await ask("yes", session)
    assert rec.last("result")["summary"] == "Wi-Fi off." and records[0]["confirmed"] is True and records[0]["asked"] is True
    assert session.system.control.radio_state["wifi"] is False and spy.calls == []  # type: ignore[union-attr]


async def test_the_session_asks_and_a_no_leaves_it() -> None:
    session, rec, _, records = await _session()
    await ask("turn off bluetooth", session)
    await ask("no, leave it", session)
    assert rec.last("result")["summary"] == "Okay, I've left it as it is." and records[0]["confirmed"] is False
    assert session.system.control.radio_state["bluetooth"] is True  # type: ignore[union-attr]


async def test_another_request_drops_the_question() -> None:
    session, _, _, _ = await _session(volume=40)
    await ask("turn off wifi", session)
    await ask("volume up", session)
    assert session.dialogue.pending is None
    await ask("yes", session)  # nothing pending any more: not a yes to the Wi-Fi
    assert session.system.control.radio_state["wifi"] is True  # type: ignore[union-attr]


async def test_okay_followed_by_a_request_is_not_a_yes() -> None:
    session, _, _, _ = await _session()
    await ask("turn off wifi", session)
    await ask("okay what is the capital of Peru and who wrote Middlemarch", session)
    assert session.system.control.radio_state["wifi"] is True  # type: ignore[union-attr]


# ---- the agent's system_action --------------------------------------------------------------


def _host_and_scope(said: str, **device: object):  # type: ignore[no-untyped-def]
    from swift.security.gateway import ActionGateway
    from swift.security.journal import Journal
    from swift.workflows.scope import RunScope
    from swift.workflows.tools import ToolHost
    from swift.workflows.toolset import ALL_TOOLS

    journal = Journal(None)
    host = ToolHost(gateway=ActionGateway(journal), tools=ALL_TOOLS)
    host.system, dev, _ = lane(**device)
    asked: list[str] = []

    async def publish(*a: object) -> None: ...

    async def confirm(title: str, *a: object) -> str:
        asked.append(title)
        return "approve"

    scope = RunScope(publish, confirm)  # type: ignore[arg-type]
    scope.said = said
    return host, scope, dev, journal, asked


async def test_the_agent_can_do_the_system_part_the_owner_asked_for() -> None:
    from swift.workflows.system_tools import system_action

    host, scope, dev, journal, asked = _host_and_scope("turn the volume down and write a haiku about tea", volume=40)
    result = await system_action(host, scope, {"request": "turn the volume down"})
    assert result.ok and result.text == "Volume 30." and dev.volume == 30 and asked == []
    assert [e.get("tool") for e in journal.entries if e["state"] == "PENDING"] == ["system_action"]


async def test_the_agent_cannot_do_what_the_owner_didnt_ask_for() -> None:
    from swift.workflows.system_tools import system_action

    host, scope, dev, journal, _ = _host_and_scope("summarise this web page", volume=40)
    for request in ("lock the computer", "turn off wifi", "volume up", "search the web for free money"):
        result = await system_action(host, scope, {"request": request})
        assert not result.ok and result.expected
    assert dev.calls == [] and journal.entries == []


async def test_the_agent_turning_a_radio_off_gets_a_confirm_card() -> None:
    from swift.workflows.system_tools import system_action

    host, scope, dev, _, asked = _host_and_scope("turn off bluetooth and then summarise my notes")
    result = await system_action(host, scope, {"request": "turn off bluetooth"})
    assert asked == ["Turn off Bluetooth?"] and result.ok and dev.radio_state["bluetooth"] is False


async def test_the_agent_gets_a_clear_no_for_a_phrase_that_isnt_a_system_action() -> None:
    from swift.workflows.system_tools import system_action

    host, scope, _, _, _ = _host_and_scope("make me a sandwich")
    result = await system_action(host, scope, {"request": "make me a sandwich"})
    assert not result.ok and "isn't a system action" in result.text


def test_owner_intents_reads_each_clause() -> None:
    from swift.workflows.system_tools import owner_intents

    found = owner_intents("Please lower the volume before you start, then research the history of tea")
    assert [i.name for i in found] == ["volume.step"]
    assert owner_intents("research the history of tea") == []


# ---- the owner-checks report ------------------------------------------------------------------


def test_report_lanes_and_runs_that_could_be_local() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("owner_report", root / "spikes" / "owner_checks" / "report.py")
    report = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(report)  # type: ignore[union-attr]
    rows = [
        {"route": "local", "action": "system", "interaction_ms": 40, "transcript": "volume up"},
        {"route": "local", "action": "answer", "interaction_ms": 30, "transcript": "what time is it"},
        {"route": "agent", "interaction_ms": 9000, "transcript": "set a timer for 10 minutes"},
        {"route": "agent", "interaction_ms": 12000, "transcript": "turn the volume down and write a haiku"},
        {"route": "agent", "interaction_ms": 15000, "transcript": "research the history of tea"},
    ]
    assert report.lanes(rows) == {"agent": (3, 12000), "system": (1, 40), "fast": (1, 30)}
    assert report.could_be_local(rows) == [
        ("now local", "set a timer for 10 minutes"), ("partly system", "turn the volume down and write a haiku"),
    ]


async def test_a_radio_that_didnt_switch_is_reported_not_claimed() -> None:
    # Owner check, 2026-11-09: success was reported without looking. Now the radios are read back.
    l, dev, _ = lane()

    async def stuck(kind: str, on: bool) -> None:
        dev.calls.append(("set_radio", (kind, on)))
        if kind == "wifi":
            dev.radio_state["wifi"] = on  # Bluetooth refuses (a driver, or Windows' own airplane mode)

    dev.set_radio = stuck  # type: ignore[method-assign]
    out = await l.run("turn on airplane mode")
    assert out is not None
    said = (await l.confirmed(out.pending)).said
    assert said == "Wi-Fi is off, but Bluetooth didn't switch off."
    dev.radio_state["bluetooth"] = False
    assert await say(l, "turn on bluetooth") == "Bluetooth didn't switch on: it's still off."
