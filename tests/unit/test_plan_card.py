"""Modes §2 (decision 5): the plan card. One approval covers the commands of the steps Swift knows can be undone,
used in order; every step with a delete, a send, a publish or anything unknown keeps its own card. Rules, one
each; each test fails with its guard removed (see the docs/handoff/halo-b8/PROGRESS.md row)."""

from __future__ import annotations

import asyncio
from typing import Any

from test_b2_step_grant import _asks, _executor

from swift.executors.base import Grant, WorkerTask
from swift.executors.claude_code import (
    PLAN_NOT_A_PLAN_MESSAGE,
    PLAN_REJECTED_MESSAGE,
    STEP_ASK_EVERYTHING_MESSAGE,
    STEP_NOTHING_AHEAD_MESSAGE,
)

PLAN = [
    {"step": "Create the folder and start a repository.", "commands": ["mkdir tea-timer", "git init"]},
    {"step": "Write the README and make the first commit.", "commands": ["git add README.md", 'git commit -m "First"']},
    {"step": "Create the repository on GitHub.", "commands": ["gh repo create tea-timer --private"]},
    {"step": "Push the first commit.", "commands": ["git push -u origin main"]},
]


async def _plan(ex: Any, run: Any, steps: list[dict[str, Any]], approve: bool = True) -> tuple[Any, str]:
    proposing = asyncio.create_task(ex._propose_plan(run, "cc-1", {"steps": steps}))
    card = await asyncio.wait_for(run.queue.get(), 5)
    await ex.reply(card.request_id, approve)
    return card, await asyncio.wait_for(proposing, 5)


async def test_the_card_shows_each_step_covered_or_asking_and_a_yes_covers_only_the_covered(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    card, said = await _plan(ex, run, PLAN)
    rows = card.data["plan"]
    assert (card.type, card.step, card.text) == ("confirm", True, "A plan in 4 steps")
    assert [r["covered"] for r in rows] == [True, True, False, False]
    assert [r["asks"] for r in rows] == ["", "", "it publishes", "it sends"]
    assert rows[0]["commands"] == ["mkdir tea-timer", "git init"] and rows[2]["commands"] == []  # an asking step lists none
    assert "steps 1, 2 of the plan" in said
    assert run.grant == Grant(PLAN[0]["step"], tuple(PLAN[0]["commands"])) and run.later == (
        Grant(PLAN[1]["step"], tuple(PLAN[1]["commands"])),)
    for command in [*PLAN[0]["commands"], *PLAN[1]["commands"]]:
        assert not await _asks(ex, run, command)
    assert (run.grant.commands, run.later, run.step_bound) == ((), (), {})  # the plan is used up
    assert run.grant_counts == {"steps": 2, "covered": 4, "asked_again": 0}


async def test_a_later_step_s_command_is_covered_before_the_earlier_step_is_done(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    await _plan(ex, run, PLAN)
    assert not await _asks(ex, run, "git add README.md")  # step 2's, while step 1 is untouched
    assert len(run.grant.commands) == 2 and len(run.later[0].commands) == 1


async def test_a_delete_a_send_and_a_publish_in_a_plan_still_ask_on_their_own_card(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    await _plan(ex, run, PLAN)
    for command in ("gh repo create tea-timer --private", "git push -u origin main"):
        assert await _asks(ex, run, command)
    ex, run = _executor(tmp_path)
    card, _ = await _plan(ex, run, [PLAN[0], {"step": "Clear out the old notes.", "commands": ["rm old.md"]}, PLAN[1]])
    assert [r["asks"] for r in card.data["plan"]] == ["", "it deletes", ""]
    assert await _asks(ex, run, "rm old.md")


async def test_a_step_with_one_command_swift_cannot_vouch_for_is_not_covered_at_all(tmp_path: Any) -> None:
    """All or nothing: the card's "covered" is exactly what the grant holds."""
    ex, run = _executor(tmp_path)
    mixed = {"step": "Tidy up and commit.", "commands": ["git add README.md", "git clean -fd"]}
    card, _ = await _plan(ex, run, [PLAN[0], mixed])
    assert [r["covered"] for r in card.data["plan"]] == [True, False] and card.data["plan"][1]["commands"] == []
    assert await _asks(ex, run, "git add README.md")


async def test_commands_not_known_yet_show_will_ask_and_ask_when_they_come(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    card, _ = await _plan(ex, run, [PLAN[0], {"step": "Write whatever the README needs.", "commands": []}])
    assert card.data["plan"][1]["asks"] == "its commands aren't known yet"
    assert await _asks(ex, run, "git add README.md")  # not listed on the card, so not covered by it


async def test_a_plan_never_covers_a_file_edit(tmp_path: Any) -> None:
    """Decision 5: commands only. A write or an edit, listed or not, asks as it always did."""
    from claude_agent_sdk import PermissionResultAllow

    ex, run = _executor(tmp_path)
    await _plan(ex, run, [{**PLAN[0], "commands": [*PLAN[0]["commands"], "README.md"]}, PLAN[1]])
    asking = asyncio.create_task(ex._ask(run, "cc-1", "Write", {"file_path": str(tmp_path / "README.md"), "content": "x"}))
    card = await asyncio.wait_for(run.queue.get(), 5)
    assert card.type == "confirm" and card.tool == "Write" and not card.step
    await ex.reply(card.request_id, False)
    assert not isinstance(await asyncio.wait_for(asking, 5), PermissionResultAllow)


async def test_each_command_is_covered_once_per_listing_and_only_as_shown(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    twice = [{"step": "First commit.", "commands": ["git add a.md"]}, {"step": "Second commit.", "commands": ["git add a.md"]}]
    await _plan(ex, run, twice)
    assert await _asks(ex, run, "git add  a.md")  # not exactly as the owner saw it
    assert not await _asks(ex, run, "git add a.md") and not await _asks(ex, run, "git add a.md")  # once for each listing
    assert await _asks(ex, run, "git add a.md")  # a third time asks


async def test_a_changed_plan_is_a_new_card_and_the_old_plan_covers_nothing_more(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    await _plan(ex, run, PLAN)
    card, _ = await _plan(ex, run, [PLAN[1], {"step": "Check it.", "commands": ["git status"]}])  # the agent changed its plan
    assert card.type == "confirm"
    assert await _asks(ex, run, "mkdir tea-timer")  # step 1 of the first plan: replaced
    assert not await _asks(ex, run, "git status")
    await ex.redirect("cc-1", "actually, call it tea")  # the owner changed their mind: nothing is left
    assert run.grant == Grant() and run.later == () and run.step_bound == {}


async def test_no_plan_covers_anything_while_asking_about_everything(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    ex.ask_everything = lambda: True
    said = await asyncio.wait_for(ex._propose_plan(run, "cc-1", {"steps": PLAN}), 5)
    assert said == STEP_ASK_EVERYTHING_MESSAGE and run.queue.empty() and run.grant == Grant()
    ex.ask_everything = lambda: False
    await _plan(ex, run, PLAN)  # approved while off, then the owner turns it on: nothing is covered
    ex.ask_everything = lambda: True
    assert await _asks(ex, run, "git init")


async def test_a_plan_is_for_several_steps_and_a_plan_of_nothing_swift_can_cover_has_no_card(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    for steps in ([PLAN[0]], [], "git init", [{"step": "", "commands": ["git init"]}, PLAN[1]], PLAN * 3):
        assert await ex._propose_plan(run, "cc-1", {"steps": steps}) == PLAN_NOT_A_PLAN_MESSAGE.format(most=8)
    assert await ex._propose_plan(run, "cc-1", {"steps": PLAN[2:]}) == STEP_NOTHING_AHEAD_MESSAGE
    assert run.queue.empty()


async def test_a_no_stops_the_run_and_covers_nothing(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    _, said = await _plan(ex, run, PLAN, approve=False)
    assert said == PLAN_REJECTED_MESSAGE and run.stopped_by is not None and run.grant == Grant() and run.later == ()


async def test_what_a_worker_wrote_never_decides_what_is_covered(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    sneaky = [{"step": "Safe things.", "commands": ["git status"], "covered": True, "asks": ""},
              {"step": "More safe things.", "commands": ["git push"], "covered": True, "reversible": True}]
    card, _ = await _plan(ex, run, sneaky)
    assert [r["covered"] for r in card.data["plan"]] == [True, False] and await _asks(ex, run, "git push")


def test_a_task_s_plan_seeds_the_run(tmp_path: Any) -> None:
    from swift.executors.claude_code import _Run, _set_grant

    ex, run = _executor(tmp_path)
    steps = (Grant("A.", ("git init",)), Grant("B.", ("git status",)))
    _set_grant(run, ex.gateway, *WorkerTask("x", grant=steps).grant)
    assert (run.grant, run.later) == (steps[0], (steps[1],)) and set(run.step_bound) == {"git init", "git status"}
    assert _Run().later == ()


async def test_a_change_on_the_plan_card_ends_the_earlier_approval(tmp_path: Any) -> None:
    """Review of dcac4c8: asking for something else on a plan card must not leave the last plan in force."""
    ex, run = _executor(tmp_path)
    await _plan(ex, run, PLAN)
    proposing = asyncio.create_task(ex._propose_plan(run, "cc-1", {"steps": PLAN}))
    card = await asyncio.wait_for(run.queue.get(), 5)
    await ex.reply(card.request_id, "call it tea instead")
    await asyncio.wait_for(proposing, 5)
    assert run.grant == Grant() and run.later == () and run.step_bound == {}


async def test_a_plan_does_not_come_back_when_asking_about_everything_goes_off(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    await _plan(ex, run, PLAN)
    ex.ask_everything = lambda: True
    assert await _asks(ex, run, "git init")
    ex.ask_everything = lambda: False
    assert await _asks(ex, run, "mkdir tea-timer")
