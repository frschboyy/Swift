"""OWN-05: a worker's approved tool call is bound to a digest of exactly the call its card showed. The
gateway recomputes it just before the call is handed back to run, refuses a change, never lets one
approval cover a second call, and journals it with no content (ADR-010, threat model T3, decision 8)."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from swift.executors.base import Grant
from swift.security.gateway import ActionGateway, call_digest

STEP = "Makes this folder a repository and saves the notes in it."


def _executor(tmp_path: Any) -> tuple[Any, Any]:
    from swift.executors.claude_code import ClaudeCodeExecutor, _Run

    ex, run = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe"), _Run()
    ex._runs["cc-1"] = run
    return ex, run


async def _card(ex: Any, run: Any, name: str, args: dict[str, Any]) -> tuple[asyncio.Task[Any], Any]:
    asking = asyncio.create_task(ex._ask(run, "cc-1", name, args))
    card = await asyncio.wait_for(run.queue.get(), 5)
    assert card.type == "confirm"
    return asking, card


async def test_a_command_whose_arguments_change_while_its_card_is_up_is_refused(tmp_path: Any) -> None:
    from claude_agent_sdk import PermissionResultDeny

    from swift.executors.claude_code import CHANGED_MESSAGE

    ex, run = _executor(tmp_path)
    args = {"command": "git status", "description": "See what changed"}
    asking, card = await _card(ex, run, "Bash", args)
    assert card.detail == "git status"
    args["command"] = "git push --force"  # changed after the owner saw the card
    await ex.reply(card.request_id, True)
    result = await asyncio.wait_for(asking, 5)
    assert isinstance(result, PermissionResultDeny) and result.message == CHANGED_MESSAGE
    assert [e["state"] for e in ex.gateway.journal.entries] == ["FAILED"]
    assert ex.gateway.journal.entries[0]["reason"] == "changed_after_approval"


async def test_an_approved_command_is_handed_back_as_shown_and_journalled_without_content(tmp_path: Any) -> None:
    from claude_agent_sdk import PermissionResultAllow

    ex, run = _executor(tmp_path)
    args = {"command": "git status", "description": "See what changed"}
    asking, card = await _card(ex, run, "Bash", args)
    await ex.reply(card.request_id, True)
    result = await asyncio.wait_for(asking, 5)
    assert isinstance(result, PermissionResultAllow) and result.updated_input == args
    (entry,) = ex.gateway.journal.entries
    assert (entry["state"], entry["tool"], entry["how"]) == ("ALLOWED", "Bash", "card")
    assert entry["digest"] == call_digest("Bash", args)[:16]
    assert "git" not in str(entry) and "changed" not in str(entry)


async def test_a_file_read_outside_the_read_folders_whose_path_changes_is_refused(tmp_path: Any) -> None:
    from claude_agent_sdk import PermissionResultDeny

    ex, run = _executor(tmp_path / "work")
    outside = tmp_path / "elsewhere" / "notes.md"
    args = {"file_path": str(outside)}
    asking, card = await _card(ex, run, "Read", args)
    args["file_path"] = str(tmp_path / "elsewhere" / "other.md")
    await ex.reply(card.request_id, True)
    assert isinstance(await asyncio.wait_for(asking, 5), PermissionResultDeny)


def test_one_approval_never_covers_a_second_call() -> None:
    gateway = ActionGateway()
    bound = gateway.bind("Bash", {"command": "git status"})
    assert gateway.allow(bound, "Bash", {"command": "git status"})
    assert not gateway.allow(bound, "Bash", {"command": "git status"})  # the same call again
    assert not gateway.allow(bound, "Bash", {"command": "git log"})  # a different one
    assert not gateway.allow(gateway.bind("Bash", {"command": "ls"}), "PowerShell", {"command": "ls"})
    assert [e.get("reason") for e in gateway.journal.entries] == [
        None, "approval_reused", "approval_reused", "changed_after_approval"]


async def test_a_step_binds_each_listed_command_and_hands_back_only_what_it_showed(tmp_path: Any) -> None:
    from claude_agent_sdk import PermissionResultAllow

    ex, run = _executor(tmp_path)
    proposing = asyncio.create_task(ex._propose_step(run, "cc-1", {"step": STEP, "commands": ["git init", "git status"]}))
    card = await asyncio.wait_for(run.queue.get(), 5)
    await ex.reply(card.request_id, True)
    await asyncio.wait_for(proposing, 5)
    assert set(run.step_bound) == {"git init", "git status"}
    result = await ex._ask(run, "cc-1", "Bash", {"command": "git init", "run_in_background": True, "description": "x"})
    assert isinstance(result, PermissionResultAllow) and result.updated_input == {"command": "git init"}
    (entry,) = ex.gateway.journal.entries
    assert (entry["state"], entry["tool"], entry["how"]) == ("ALLOWED", "command", "step")
    assert "git init" not in run.step_bound  # spent: the same command again asks on its own card


async def test_a_command_added_to_a_grant_without_its_own_binding_asks(tmp_path: Any) -> None:
    from swift.executors.claude_code import _set_grant

    ex, run = _executor(tmp_path)
    _set_grant(run, ex.gateway, Grant(STEP, ("git init",)))
    run.grant = replace(run.grant, commands=(*run.grant.commands, "git status"))  # not what was bound
    asking, card = await _card(ex, run, "Bash", {"command": "git status"})
    assert not card.step
    await ex.reply(card.request_id, False)
    await asyncio.wait_for(asking, 5)


async def test_a_change_of_mind_drops_the_step_s_bindings(tmp_path: Any) -> None:
    from swift.executors.claude_code import _set_grant

    ex, run = _executor(tmp_path)
    _set_grant(run, ex.gateway, Grant(STEP, ("git init",)))
    await ex.redirect("cc-1", "actually, don't")
    assert run.grant == Grant() and run.step_bound == {}
