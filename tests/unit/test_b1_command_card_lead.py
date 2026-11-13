"""B1: a command card leads with what the agent says the command is for, and the command is folded under
it. Those words are the agent's (its ``description``), so they travel apart from Swift's title and the card
marks them as the agent's (X-17). Approving is untouched: the same card, the same answers."""

from __future__ import annotations

import asyncio

from swift.executors.claude_mapping import PURPOSE_MAX, command_purpose, confirm_card

SAID = "Creates a repository called notes on your GitHub, so it can be copied to this PC."


def test_a_command_s_purpose_is_the_agent_s_description_on_one_line() -> None:
    assert command_purpose("Bash", {"command": "gh repo create notes", "description": SAID}) == SAID
    assert command_purpose("PowerShell", {"command": "dir", "description": "Lists\nthe   folder"}) == "Lists the folder"


def test_only_a_command_has_one_and_none_given_is_none() -> None:
    assert command_purpose("Bash", {"command": "dir"}) == ""
    assert command_purpose("Bash", {"command": "dir", "description": "   "}) == ""
    assert command_purpose("Write", {"file_path": "a.txt", "content": "x", "description": SAID}) == ""


def test_what_could_hide_or_reorder_text_is_shown_and_a_long_one_is_cut() -> None:
    rlo = chr(0x202E)  # right-to-left override
    assert command_purpose("Bash", {"command": "x", "description": f"safe{rlo} evil"}) == "safe" + chr(92) + "u202e evil"
    long = command_purpose("Bash", {"command": "x", "description": "word " * 200})
    assert len(long) <= PURPOSE_MAX and long.endswith("…")


def test_swift_s_title_doesn_t_take_the_agent_s_words() -> None:
    title, detail = confirm_card("Bash", {"command": "gh repo create notes", "description": SAID})
    assert title == "Run a command on your PC" and detail == "gh repo create notes"


async def test_the_card_carries_the_purpose_and_approving_is_unchanged(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from claude_agent_sdk import PermissionResultAllow

    from swift.executors.claude_code import ClaudeCodeExecutor, _Run

    ex, run = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe"), _Run()
    ex._runs["cc-1"] = run
    args = {"command": "gh repo create notes", "description": SAID}
    asking = asyncio.create_task(ex._ask(run, "cc-1", "Bash", args))
    event = await asyncio.wait_for(run.queue.get(), 5)
    assert (event.type, event.text, event.detail, event.tool, event.purpose) == (
        "confirm", "Run a command on your PC", "gh repo create notes", "Bash", SAID)
    await ex.reply(event.request_id, True)
    allowed = await asyncio.wait_for(asking, 5)
    assert isinstance(allowed, PermissionResultAllow) and allowed.updated_input == args  # runs as it came


def test_the_agent_is_asked_for_a_plain_description() -> None:
    from swift.executors.claude_code import SYSTEM_PROMPT

    assert "Give every shell command a description" in SYSTEM_PROMPT
