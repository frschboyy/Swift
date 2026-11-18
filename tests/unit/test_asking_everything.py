""""Ask me about everything" (the modes study §3; CLAUDE.md: it raises level 0 to 1, except reads in the read folders
and volume). One rule test per guard, each failing with that guard removed. It only ever adds questions."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from test_system_lane import lane, say

from swift import asking, memory
from swift.memory import Store
from swift.security.gateway import Action, ActionGateway
from swift.workflows.scope import RunScope


def _action(tool: str, kind: str = "") -> tuple[Action, list[str]]:
    done: list[str] = []

    async def perform() -> str:
        done.append(tool)
        return "ok"

    return Action(tool=tool, targets=(), title=tool, detail="", artifact_id=None, digest=lambda: tool, perform=perform,
                  targets_required=False, kind=kind), done


async def _run(gateway: ActionGateway, action: Action) -> list[str]:
    asked: list[str] = []

    async def confirm(title: str, *_: Any) -> str:
        asked.append(title)
        return "approve"

    async def publish(_: Any) -> None:
        return None

    await gateway.execute(RunScope(publish, confirm), action)  # type: ignore[arg-type]
    return asked


async def test_while_on_a_reversible_action_asks_on_a_card_and_volume_still_does_not() -> None:
    gateway = ActionGateway()
    write, done = _action("desktop_write")
    assert await _run(gateway, write) == [] and done == ["desktop_write"]  # off: level 0, as today
    gateway.ask_everything = lambda: True
    write, done = _action("desktop_write")
    assert await _run(gateway, write) == ["desktop_write"] and done == ["desktop_write"]
    volume, done = _action("system_action", kind="volume.step")
    assert await _run(gateway, volume) == [] and done == ["system_action"]  # volume is never asked about


async def test_it_never_removes_a_card() -> None:
    gateway = ActionGateway()
    gateway.ask_everything = lambda: True
    send, _ = _action("send_email", kind="volume.step")  # even a kind on the exempt list keeps "confirm"
    assert await _run(gateway, send) == ["send_email"]


async def test_the_system_lane_asks_before_its_own_changes_but_not_volume_or_reads() -> None:
    l, control, sched = lane()
    l.ask_everything = lambda: True
    out = await l.run("set a 10 minute timer")
    assert out is not None and out.said == "Set the timer?" and out.pending and out.note == asking.NOTE
    assert sched.items == []  # nothing set until the owner answers
    assert (await l.confirmed(out.pending)).ok and len(sched.items) == 1
    assert await say(l, "turn the volume up") != "Go ahead?"  # volume: done, not asked
    assert await say(l, "how long is left on the timer") != "Go ahead?"
    l.ask_everything = lambda: False
    assert (await say(l, "set a 5 minute timer")).startswith("Timer set")


def test_the_setting_is_kept_from_the_owners_words_and_never_from_a_worker(tmp_path: Path) -> None:
    store = Store(tmp_path)
    said, _ = memory.answer(store, "Swift, ask me about everything", "click", "r1")
    assert not asking.is_on(store) and "yourself" in said  # a button a worker may have worded never sets it
    memory.answer(store, "ask me about everything", "typed", "r2")  # typed works: it only adds questions
    assert asking.is_on(store) and asking.is_on(Store(tmp_path))  # kept until turned off, across restarts
    assert memory.answer(store, "what do you know about me", "voice", "r3")[0].startswith("You haven't")  # not a fact
    memory.answer(store, "stop asking about everything", "voice", "r4")
    assert not asking.is_on(store)


async def test_no_step_card_is_offered_or_used_while_on(tmp_path: Path) -> None:
    from test_own05_worker_approval import STEP, _executor

    ex, run = _executor(tmp_path)
    ex.ask_everything = lambda: True
    said = await asyncio.wait_for(ex._propose_step(run, "cc-1", {"step": STEP, "commands": ["git init"]}), 5)
    assert said.startswith("The owner asked to be asked about everything") and run.queue.empty()
