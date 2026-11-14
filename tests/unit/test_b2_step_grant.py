"""B2: one approval covers one coherent step, with its commands listed on the card (owner, 2026-11-13).
A command outside the list asks again, and anything irreversible (deleting, sending, paying, unknown)
always gets its own card: Swift decides that (``step_grant.reversible``), never the agent."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from swift.executors.base import Grant, WorkerTask
from swift.executors.step_grant import reversible

STEP = "Makes this folder a repository and saves the notes in it."
COMMANDS = ["git init", "git add notes.md", 'git commit -m "First notes"']


@pytest.mark.parametrize("command", [
    "git init", "git add notes.md", 'git commit -m "First notes"', "git status", "mkdir notes",
    "git remote add origin https://github.com/someone/notes.git", "git remote add origin git@github.com:someone/notes.git",
    "GIT.EXE status", "git -C C:/Users/someone/Documents/notes init", 'git -C "C:/My notes" add notes.md',
])
def test_plain_commands_swift_knows_can_be_undone_are_reversible(command: str) -> None:
    assert reversible(command)


@pytest.mark.parametrize("command", [
    # deletes (ADR-019)
    "rm notes.md", "rm -rf notes", "del notes.md", "Remove-Item notes.md", "git rm notes.md", "git clean -fd",
    "git reset --hard", "git checkout -- notes.md", "rmdir notes", "gh repo delete notes",
    # sends, publishes, signs in
    "git push", "git push -u origin main", "gh repo create notes --private", "gh auth login", "curl -X POST x",
    # a listed command with a destructive form
    "git add -f secret.env", "git diff --output=notes.md", "git commit --force",
    # chained, redirected, expanded or hidden
    "git add . && rm notes.md", "git status; rm x", "git status | sh", "git log > notes.md", "git add $(rm x)",
    "git add `rm x`", "git status\nrm x", " git status", "git status ", "git add notes.md‮",
    # hooks a later commit in the same step would run (review of B2), and git's long-option prefixes
    "git init --template=x", "git init --template x", "git init --templ=x", "git init --separate-git=x",
    "git diff --out=notes.md", "git commit --forc", "git add -fA notes.md", "git add -Af notes.md",
    # config that can run code, a folder flag with nothing after it
    "git -c core.sshCommand=evil status", "git -C", "git -C notes",
    # unknown
    "foo", "python script.py", "npm install", "",
])
def test_deletes_sends_chains_and_unknown_commands_are_not(command: str) -> None:
    assert not reversible(command)


def _executor(tmp_path: Any) -> tuple[Any, Any]:
    from swift.executors.claude_code import ClaudeCodeExecutor, _Run

    ex, run = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe"), _Run()
    ex._runs["cc-1"] = run
    return ex, run


async def _approve_step(ex: Any, run: Any, commands: list[str], approve: bool = True) -> tuple[Any, str]:
    proposing = asyncio.create_task(ex._propose_step(run, "cc-1", {"step": STEP, "commands": commands}))
    card = await asyncio.wait_for(run.queue.get(), 5)
    await ex.reply(card.request_id, approve)
    return card, await asyncio.wait_for(proposing, 5)


async def _asks(ex: Any, run: Any, command: str) -> bool:
    """True if running ``command`` put a card up (answered no), False if it ran without one."""
    from claude_agent_sdk import PermissionResultAllow

    asking = asyncio.create_task(ex._ask(run, "cc-1", "Bash", {"command": command, "description": "x"}))
    await asyncio.sleep(0.05)
    if asking.done():
        assert isinstance(asking.result(), PermissionResultAllow)
        return False
    card = await asyncio.wait_for(run.queue.get(), 5)
    assert card.type == "confirm" and not card.step and card.detail == command.strip()
    await ex.reply(card.request_id, False)
    await asyncio.wait_for(asking, 5)
    run.stopped_by = None  # only this card was refused; the next check starts clean
    return True


async def test_a_step_card_extends_the_command_card_and_lists_its_commands(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    card, said = await _approve_step(ex, run, COMMANDS)
    assert (card.type, card.tool, card.step, card.purpose) == ("confirm", "Bash", True, STEP)
    assert card.text == "Run 3 commands on your PC" and card.detail.split("\n") == COMMANDS
    assert "approved this step" in said and run.grant == Grant(STEP, tuple(COMMANDS))


async def test_once_approved_a_listed_command_runs_without_another_card(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    await _approve_step(ex, run, COMMANDS)
    for command in COMMANDS:
        assert not await _asks(ex, run, command)
    assert run.grant.commands == ()  # the step is used up: its grant ended with it
    assert run.grant_counts == {"steps": 1, "covered": 3, "asked_again": 0}


async def test_a_command_outside_the_list_asks_again(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    await _approve_step(ex, run, COMMANDS)
    assert await _asks(ex, run, "git status")  # reversible, but not what the owner saw
    assert await _asks(ex, run, "git add  notes.md")  # not exactly as the owner saw it
    assert await _asks(ex, run, "git init ")
    assert run.grant_counts["asked_again"] == 3 and len(run.grant.commands) == 3


async def test_a_listed_command_runs_once_then_asks(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    await _approve_step(ex, run, COMMANDS)
    assert not await _asks(ex, run, "git init")
    assert await _asks(ex, run, "git init")


async def test_a_delete_and_a_send_listed_in_a_step_still_ask_on_their_own_card(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    card, said = await _approve_step(ex, run, [*COMMANDS, "rm old-notes.md", "git push -u origin main"])
    assert card.detail.split("\n") == COMMANDS  # never on the step card, so never approved ahead
    assert "including 2 of the ones you listed" in said
    assert await _asks(ex, run, "rm old-notes.md")
    assert await _asks(ex, run, "git push -u origin main")


async def test_a_grant_from_the_task_never_covers_a_delete_or_a_send(tmp_path: Any) -> None:
    """Whatever puts commands in a grant, Swift's own classification decides what it covers."""
    ex, run = _executor(tmp_path)
    run.grant = Grant(STEP, ("rm notes.md", "git push", "git init"))
    assert await _asks(ex, run, "rm notes.md")
    assert await _asks(ex, run, "git push")
    assert not await _asks(ex, run, "git init")


async def test_nothing_reversible_puts_up_no_step_card(tmp_path: Any) -> None:
    from swift.executors.claude_code import STEP_NOTHING_AHEAD_MESSAGE

    ex, run = _executor(tmp_path)
    said = await ex._propose_step(run, "cc-1", {"step": STEP, "commands": ["rm x", "git push"]})
    assert said == STEP_NOTHING_AHEAD_MESSAGE and run.queue.empty() and run.grant == Grant()
    said = await ex._propose_step(run, "cc-1", {"step": "", "commands": COMMANDS})  # nothing to lead the card
    assert said == STEP_NOTHING_AHEAD_MESSAGE and run.queue.empty()


async def test_a_rejected_step_stops_the_run_and_grants_nothing(tmp_path: Any) -> None:
    from swift.executors.claude_code import STEP_REJECTED_MESSAGE

    ex, run = _executor(tmp_path)
    _card, said = await _approve_step(ex, run, COMMANDS, approve=False)
    assert said == STEP_REJECTED_MESSAGE and run.grant == Grant()
    assert run.stopped_by == ("reject", "Run 3 commands on your PC")


async def test_a_change_of_mind_ends_the_step(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    await _approve_step(ex, run, COMMANDS)
    assert await ex.redirect("cc-1", "actually, call it journal")
    assert run.grant == Grant()


async def test_a_new_step_replaces_the_last(tmp_path: Any) -> None:
    ex, run = _executor(tmp_path)
    await _approve_step(ex, run, COMMANDS)
    await _approve_step(ex, run, ["git status"])
    assert await _asks(ex, run, "git init")


async def test_a_never_read_place_never_goes_on_a_step_card(tmp_path: Any) -> None:
    from swift.executors.claude_code import ClaudeCodeExecutor, _Run

    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", never_read=[str(tmp_path / "secrets")])
    run = _Run()
    ex._runs["cc-1"] = run
    card, _said = await _approve_step(ex, run, ["git init", f"git add {tmp_path / 'secrets' / 'key'}".replace("\\", "/")])
    assert card.detail == "git init"


def test_the_log_gets_counts_never_the_commands() -> None:
    from swift.executors.claude_code import ClaudeCodeExecutor, _Run
    from swift.runlog import summary

    run = _Run(grant=Grant(STEP, tuple(COMMANDS)))
    run.grant_counts.update(steps=1, covered=2, asked_again=1)
    meta = ClaudeCodeExecutor._final(run, None, None).meta
    assert meta["step_grant"] == {"steps": 1, "covered": 2, "asked_again": 1}
    line = str(summary({"step_grant": meta["step_grant"]}))
    assert "step_grant" in line and not any(c in line for c in COMMANDS) and "git" not in line


def test_the_task_s_grant_seeds_the_run(tmp_path: Any) -> None:
    from swift.executors.claude_code import _Run

    grant = Grant(STEP, ("git init",))
    assert _Run(grant=WorkerTask("x", grant=grant).grant).grant == grant


def test_the_agent_is_asked_to_propose_a_step() -> None:
    from swift.executors.claude_code import STEP_PROMPT

    assert "propose_step" in STEP_PROMPT and "deletes, sends" in STEP_PROMPT
