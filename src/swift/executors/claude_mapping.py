"""Claude Code ``stream-json`` events -> short overlay steps and a result card.

Pure functions, no I/O, so they can be tested against recorded runs
(``tests/fixtures/claude_*.jsonl``). Unknown event types are ignored: newer
CLI versions add events (``rate_limit_event``, ``system/task_summary``,
``system/thinking_tokens``, ...) and must not break the overlay.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PureWindowsPath
from typing import Any
from urllib.parse import urlparse

STEP_MAX = 80
SUMMARY_MAX = 300
LIST_MAX = 6

# Result subtypes the CLI uses when it stops without finishing.
STOP_REASONS = {
    "error_max_budget_usd": "Stopped: it reached the spending limit for one request.",
    "error_max_turns": "Stopped: it reached the turn limit.",
    "error_during_execution": "Claude Code hit an error while working.",
}


@dataclass(frozen=True)
class Step:
    text: str
    kind: str = "tool"  # "tool" | "text" | "info"


@dataclass
class Outcome:
    status: str  # "done" | "error"
    summary: str
    details: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def _short(text: str, limit: int = STEP_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _base(path: Any) -> str:
    return PureWindowsPath(str(path)).name or str(path)


def describe_tool(name: str, args: dict[str, Any]) -> str:
    """One readable line for a tool call."""
    match name:
        case "Read":
            return f"Reading {_base(args.get('file_path', 'a file'))}"
        case "Glob":
            return f"Finding files: {args.get('pattern', '')}"
        case "Grep":
            return f"Searching for '{args.get('pattern', '')}'"
        case "Bash" | "PowerShell":
            return f"Running `{_short(str(args.get('command', '')), 50)}`"
        case "Edit" | "MultiEdit":
            return f"Editing {_base(args.get('file_path', 'a file'))}"
        case "Write":
            return f"Writing {_base(args.get('file_path', 'a file'))}"
        case "NotebookEdit":
            return f"Editing notebook {_base(args.get('notebook_path', ''))}"
        case "WebFetch":
            return f"Fetching {urlparse(str(args.get('url', ''))).netloc or 'a web page'}"
        case "WebSearch":
            return f"Searching the web: {args.get('query', '')}"
        case "Task" | "Agent":
            return f"Starting a helper: {args.get('description', 'subtask')}"
        case "TodoWrite":
            return "Updating its plan"
        case _:
            return f"Using {name.removeprefix('mcp__').replace('__', ': ')}"


def _first_sentence(text: str) -> str:
    text = _plain(text).strip()
    match = re.search(r"(.+?[.!?:])(\s|$)", text)
    return _short(match.group(1) if match else text)


def _plain(text: str) -> str:
    """Drop the markdown that would show literally in the overlay."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return re.sub(r"^#+\s*", "", text, flags=re.M)


def steps_for(event: dict[str, Any]) -> list[Step]:
    kind, sub = event.get("type"), event.get("subtype")
    if kind == "system" and sub == "init":
        return [Step("Starting Claude Code…", "info")]
    if kind == "system" and sub == "permission_denied":
        return [Step(f"Blocked: {event.get('tool_name', 'a tool')} isn't allowed", "info")]
    if kind == "system" and sub == "api_retry":
        return [Step(f"Retrying ({event.get('error', 'API error').replace('_', ' ')})…", "info")]
    if kind != "assistant":
        return []
    helper = event.get("parent_tool_use_id") is not None
    out: list[Step] = []
    for block in event.get("message", {}).get("content", []):
        if block.get("type") == "tool_use":
            text = describe_tool(block.get("name", "?"), block.get("input") or {})
            out.append(Step(_short(("Helper: " if helper else "") + text)))
        elif block.get("type") == "text" and block.get("text", "").strip() and not helper:
            out.append(Step(_first_sentence(block["text"]), "text"))
    return out


def outcome_for(event: dict[str, Any]) -> Outcome | None:
    """The final result card, from the ``result`` event."""
    if event.get("type") != "result":
        return None
    meta = {
        "cost_usd": event.get("total_cost_usd"),
        "turns": event.get("num_turns"),
        "duration_ms": event.get("duration_ms"),
        "denied": [d.get("tool_name") for d in event.get("permission_denials") or []],
    }
    sub = event.get("subtype")
    text = (event.get("result") or "").strip()
    if event.get("is_error") or sub != "success":
        message = STOP_REASONS.get(str(sub)) or _short(_plain(text), SUMMARY_MAX) or "Claude Code failed."
        return Outcome("error", message, None, meta)

    summary, details = split_answer(text)
    if meta["denied"]:
        blocked = ", ".join(sorted(set(meta["denied"])))
        summary = _short(f"{summary} (Blocked: {blocked}.)", SUMMARY_MAX + 40)
    return Outcome("done", summary or "Done.", details, meta)


def split_answer(text: str) -> tuple[str, dict[str, Any] | None]:
    """First paragraph -> summary; markdown bullets -> a list; the rest -> text."""
    lines = [line.rstrip() for line in _plain(text).splitlines()]
    bullets = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line) for line in lines if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", line)]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", "\n".join(lines)) if p.strip()]
    first = next((p for p in paragraphs if not re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", p)), "")
    summary = _short(first, SUMMARY_MAX)
    if bullets:
        items = [_short(b, 120) for b in bullets[:LIST_MAX]]
        if len(bullets) > LIST_MAX:
            items.append(f"…and {len(bullets) - LIST_MAX} more")
        return summary, {"kind": "list", "items": items}
    rest = " ".join(p for p in paragraphs if p != first)
    return summary, ({"kind": "text", "text": _short(rest, 400)} if rest else None)
