"""Learned trust (modes study §1; CLAUDE.md: it lowers one kind from level 1 to 0, only kinds on its table, never level 3).
One rule test per guard, each failing with that guard removed."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from test_system_lane import lane

from swift import memory, trust
from swift.memory import Store
from swift.security.gateway import Action, ActionGateway
from swift.security.journal import Journal
from swift.system import intents as it
from swift.workflows.scope import RunScope

NOW = datetime(2026, 11, 18, 12, 0).astimezone()


def _asked(journal: Journal, kind: str, run: str, days_ago: float = 1, *, tool: str = "system.radio") -> None:
    ts = (NOW - timedelta(days=days_ago)).isoformat(timespec="milliseconds")
    journal.entries.append({"ts": ts, "action": f"a-{run}-{kind}", "state": "PENDING", "run": run, "tool": tool,
                            "kind": kind, "asked": True})


def _said(text: str) -> it.Intent:
    found = it.parse(text)
    assert found is not None
    return found[0]


def test_only_kinds_on_the_table_have_a_kind() -> None:
    assert trust.kind_of(_said("turn off the wifi")) == "wifi_off"
    assert trust.kind_of(_said("turn off bluetooth")) == "bluetooth_off"
    assert trust.kind_of(_said("turn on airplane mode")) == "airplane_on"
    for text in ("turn on the wifi", "lock the pc", "turn the volume up", "set a 5 minute timer"):
        assert trust.kind_of(_said(text)) is None  # nothing that isn't disruptive, nothing irreversible, ever


def test_an_offer_needs_three_approvals_in_three_runs_within_14_days_and_none_rejected(tmp_path: Path) -> None:
    j = Journal(None)
    _asked(j, "wifi_off", "r1"), _asked(j, "wifi_off", "r2")
    assert not trust.offer_due(j, "wifi_off", NOW)
    _asked(j, "wifi_off", "r2")  # the same run twice is one run
    assert not trust.offer_due(j, "wifi_off", NOW)
    _asked(j, "wifi_off", "r3", days_ago=15)  # too old
    assert not trust.offer_due(j, "wifi_off", NOW)
    _asked(j, "wifi_off", "r4")
    assert trust.offer_due(j, "wifi_off", NOW)
    j.entries.append({"ts": NOW.isoformat(), "action": "x", "state": "CANCELLED", "reason": "rejected", "kind": "wifi_off"})
    assert not trust.offer_due(j, "wifi_off", NOW)  # one "no" in the window: never offered
    assert not trust.offer_due(j, "airplane_on", NOW)


def test_it_is_offered_once_per_kind_and_never_for_a_kind_off_the_table() -> None:
    j = Journal(None)
    for r in ("r1", "r2", "r3"):
        _asked(j, "wifi_off", r), _asked(j, "lock", r)
    assert trust.offer_due(j, "wifi_off", NOW) and not trust.offer_due(j, "lock", NOW)
    trust.note_offered(j, "wifi_off")
    assert not trust.offer_due(j, "wifi_off", NOW)


def test_a_trust_is_made_by_an_approved_card_or_spoken_words_never_typed_or_by_a_worker(tmp_path: Path) -> None:
    store = Store(tmp_path)
    assert not trust.grant(store, "wifi_off", source="typed", run="r1", words="always turn wifi off without asking")
    assert not trust.grant(store, "wifi_off", source="said", run="r1", words="x")  # "said" must be the owner's words
    assert not trust.grant(store, "lock", source="approved", run="r1", card="c1")  # not on the table
    assert not trust.is_trusted(store, "wifi_off")
    assert trust.grant(store, "wifi_off", source="approved", run="r1", card="c1")
    assert trust.is_trusted(store, "wifi_off") and trust.is_trusted(Store(tmp_path), "wifi_off")
    assert not trust.is_trusted(store, "bluetooth_off")


def test_spoken_always_makes_a_trust_and_typed_always_is_answered_not_obeyed(tmp_path: Path) -> None:
    store = Store(tmp_path)
    said, _ = memory.answer(store, "always turn off wifi without asking", "typed", "r1")
    assert not trust.is_trusted(store, "wifi_off") and "say it" in said.lower()
    memory.answer(store, "always turn off wifi without asking", "click", "r1")
    assert not trust.is_trusted(store, "wifi_off")  # a click on a worker's option is not the owner's words
    memory.answer(store, "always turn off wifi without asking", "voice", "r1")
    assert trust.is_trusted(store, "wifi_off")
    memory.answer(store, "always do lock the pc without asking", "voice", "r1")  # off the table
    assert not trust.is_trusted(store, "lock")


def test_asking_again_takes_it_back_even_when_typed_and_what_do_you_know_leaves_it_out(tmp_path: Path) -> None:
    store = Store(tmp_path)
    trust.grant(store, "wifi_off", source="approved", run="r1", card="c1")
    assert memory.answer(store, "what do you know about me", "voice", "r2")[0].endswith("And 1 thing I do without asking.") or \
        "without asking" in memory.answer(store, "what do you know about me", "voice", "r2")[0]
    said, _ = memory.answer(store, "ask me again about wifi", "typed", "r2")  # only adds questions: typed is fine
    assert not trust.is_trusted(store, "wifi_off") and "ask" in said.lower()
    assert len(store.versions("memory", "trust-wifi_off")) == 2  # kept, not erased


async def test_the_lane_skips_its_question_for_a_trusted_kind_and_still_asks_for_others(tmp_path: Path) -> None:
    store = Store(tmp_path)
    trust.grant(store, "wifi_off", source="approved", run="r1", card="c1")
    l, control, _ = lane()
    l.trusted = lambda kind: trust.is_trusted(store, kind)
    out = await l.run("turn off the wifi")
    assert out is not None and not out.pending and out.ok and trust.YOU_SAID in out.said
    assert control.radio_state["wifi"] is False
    out = await l.run("turn off bluetooth")
    assert out is not None and out.pending and out.said == "Turn off Bluetooth?"  # not trusted: asks as before
    l.ask_everything = lambda: True  # "ask me about everything" wins over a trust
    out = await l.run("turn off the wifi")
    assert out is not None and out.pending


async def test_the_lane_journals_what_it_asked_and_a_trusted_one_is_not_counted_again(tmp_path: Path) -> None:
    l, _, _ = lane()
    out = await l.run("turn off the wifi")
    assert out is not None
    await l.confirmed(out.pending)
    entry = next(e for e in l.journal.entries if e["state"] == "PENDING")
    assert entry["kind"] == "wifi_off" and entry["asked"] is True
    store = Store(tmp_path)
    trust.grant(store, "wifi_off", source="approved", run="r1", card="c1")
    l.trusted = lambda kind: trust.is_trusted(store, kind)
    await l.run("turn on the wifi")
    await l.run("turn off the wifi")
    assert [e.get("asked") for e in l.journal.entries if e["state"] == "PENDING" and e.get("kind") == "wifi_off"][-1] is False


def _disruptive(kind: str = "wifi_off", tool: str = "system_action_disruptive") -> tuple[Action, list[str]]:
    done: list[str] = []

    async def perform() -> str:
        done.append(tool)
        return "ok"

    return Action(tool=tool, targets=(), title="Turn off Wi-Fi?", detail="", artifact_id=None, digest=lambda: tool,
                  perform=perform, targets_required=False, kind="radio", trust=kind), done


async def _gate(gateway: ActionGateway, action: Action) -> list[str]:
    asked: list[str] = []

    async def confirm(title: str, *_: Any, **__: Any) -> str:
        asked.append(title)
        return "approve"

    async def publish(_: Any) -> None:
        return None

    await gateway.execute(RunScope(publish, confirm), action)  # type: ignore[arg-type]
    return asked


async def test_the_gateway_skips_the_card_only_for_a_trusted_disruptive_system_action(tmp_path: Path) -> None:
    store = Store(tmp_path)
    gateway = ActionGateway()
    gateway.trusted = lambda kind: trust.is_trusted(store, kind)
    action, done = _disruptive()
    assert await _gate(gateway, action) == ["Turn off Wi-Fi?"] and done  # no trust yet: the card
    trust.grant(store, "wifi_off", source="approved", run="r1", card="c1")
    action, done = _disruptive()
    assert await _gate(gateway, action) == [] and done  # trusted: done without a card
    assert any(e.get("trusted") == "wifi_off" for e in gateway.journal.entries)
    # A trust never covers level 3: a send, a program, a calendar change keep their cards, whatever "kind" they claim.
    for tool in ("send_email", "desktop_open_program", "create_calendar_event", "desktop_write_terminal"):
        action, done = _disruptive(tool=tool)
        assert await _gate(gateway, action) == ["Turn off Wi-Fi?"] and done
    gateway.ask_everything = lambda: True
    action, done = _disruptive()
    assert await _gate(gateway, action) == ["Turn off Wi-Fi?"]  # "ask me about everything" wins


def test_a_config_file_cannot_make_a_trust(tmp_path: Path) -> None:
    store = Store(tmp_path)
    (tmp_path / "trust-wifi_off.md").write_text("---\nsource: config\n---\nx\n", encoding="utf-8")  # a hand-made file
    assert not trust.is_trusted(store, "wifi_off")  # only said or approved counts; anything else asks


# ---- the offer card ------------------------------------------------------------------------------------------


class _Session:
    """What ``trust.offer`` needs from the session: the store, the lane, and ``_ask_owner``."""

    def __init__(self, tmp_path: Path, answer: str | None) -> None:
        self.memories = Store(tmp_path)
        self.system, _, _ = lane()
        self.answer, self.asked = answer, []

    async def _ask_owner(self, text: str, kind: str, options: tuple[str, ...], **kw: Any) -> Any:
        from swift.dialogue import Answer

        self.asked.append((text, kw))
        return None if self.answer is None else Answer(self.answer)  # type: ignore[arg-type]


async def _third_approval(s: _Session) -> Any:
    from swift.system.lane import Outcome  # noqa: F401

    for r in ("r1", "r2"):
        _asked(s.system.journal, "wifi_off", r, days_ago=2)
    out = await s.system.run("turn off the wifi")
    assert out is not None and out.pending
    s.system.journal.entries.append({"ts": NOW.isoformat(), "action": "z", "state": "PENDING", "run": "r3", "kind": "wifi_off", "asked": True})
    return await s.system.confirmed(out.pending)


async def test_the_offer_is_a_level_2_card_and_a_yes_makes_the_trust(tmp_path: Path) -> None:
    s = _Session(tmp_path, "yes")
    outcome = await _third_approval(s)
    said, ok = await trust.offer(s, outcome)
    (text, kw), = s.asked
    assert ok and text == "Turn Wi-Fi off without asking from now on?" and kw["level"] == 2  # not a plain-yes question
    assert trust.is_trusted(s.memories, "wifi_off") and "without asking" in said


async def test_not_now_or_no_answer_makes_nothing_and_is_not_asked_again(tmp_path: Path) -> None:
    for answer in ("no", None):
        s = _Session(tmp_path / str(answer), answer)
        await trust.offer(s, await _third_approval(s))
        assert not trust.is_trusted(s.memories, "wifi_off")
        await trust.offer(s, await _third_approval(s))
        assert len(s.asked) == 1  # once per kind


async def test_ask_me_about_everything_makes_no_offer(tmp_path: Path) -> None:
    s = _Session(tmp_path, "yes")
    s.system.ask_everything = lambda: True
    await trust.offer(s, await _third_approval(s))
    assert s.asked == []


def test_a_level_2_yes_is_not_a_plain_spoken_yes() -> None:
    from swift import intake

    assert not intake.approves("wake", named=False, level=2).allowed  # no name: not a trust
    assert intake.approves("wake", named=True, level=2).allowed and intake.approves("click", named=False, level=2).allowed
    assert not intake.approves("typed", named=True, level=2).allowed
