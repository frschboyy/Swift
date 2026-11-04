"""Claude Code ``stream-json`` events -> short overlay steps and a result card.

Pure functions, no I/O, so they can be tested against recorded runs
(``tests/fixtures/claude_*.jsonl``). Unknown event types are ignored: newer
CLI versions add events (``rate_limit_event``, ``system/task_summary``,
``system/thinking_tokens``, ...) and must not break the overlay.

``LiveMapper`` feeds the live view (ADR-017 §7): the pages a web search found and the ones
being read, from WebSearch / WebFetch calls and their results, and Claude's short notes between
tool calls. Addresses, titles and notes go to the overlay only, never to the log.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import PureWindowsPath
from typing import Any
from urllib.parse import urlparse

from swift.executors.providers import CLAUDE_CODE
from swift.failures import Failure, classify, clean_detail

STEP_MAX = 80
SUMMARY_MAX = 300
# Denials that are Swift's own rules working, not something the owner can act on: a page whose
# address the agent made up is refused (audit 2026-10), and the agent goes on without it. Kept in
# the log (``denied``), not added to the answer (owner checks 2026-11-04: "Blocked: WebFetch").
QUIET_DENIALS = frozenset({"WebFetch"})
# A command on a confirm card is shown whole, its lines kept; a longer one isn't put on a card at all
# (the owner can only approve what they can read; audit 2026-10, A-12).
COMMAND_MAX = 1500
# Every item and the whole text go to the card; these only keep one message well inside an IPC frame (64 KB).
LIST_MAX = 200
DETAILS_MAX = 24_000


# Result subtypes the CLI uses when it stops without finishing.
STOP_REASONS = {
    "error_max_budget_usd": "Stopped: it reached the spending limit for one request.",
    "error_max_turns": "Stopped: it reached the turn limit.",
    "error_during_execution": "Claude Code hit an error while working.",
}
# The same, as cards the owner can act on. error_during_execution carries no cause: classified.
STOP_FAILURES = {
    "error_max_budget_usd": Failure(
        "budget", "Spending limit reached",
        "Claude Code stopped because this request reached its spending limit.",
        "Ask for something smaller, or raise executor.max_budget_usd in config.yaml.",
    ),
    "error_max_turns": Failure(
        "max_turns", "Too many steps",
        "Claude Code stopped because the request took more steps than allowed.",
        "Split it into smaller requests, or raise the turn limit in config.yaml.",
    ),
}
# api_retry "error" values -> what the working card says while the CLI retries.
RETRY_STEPS = {
    "rate_limit": "Hit a usage limit, retrying…",
    "overloaded": "Claude is busy, retrying…",
    "authentication_failed": "Sign-in problem, retrying…",
    "server_error": "Service hiccup, retrying…",
}


@dataclass(frozen=True)
class Step:
    text: str
    kind: str = "tool"  # "tool" | "text" | "info"
    # Normalized for the overlay (``executors.base.Activity``).
    activity: str = "working"
    # Done by a helper agent Claude Code started (Task/Agent tool).
    subagent: bool = False


# Claude Code tool -> normalized activity.
TOOL_ACTIVITY = {
    "Read": "reading", "NotebookRead": "reading",
    "Glob": "searching", "Grep": "searching", "WebSearch": "searching",
    "Edit": "editing", "MultiEdit": "editing", "Write": "editing", "NotebookEdit": "editing",
    "Bash": "running", "PowerShell": "running",
    "WebFetch": "browsing",
    "Task": "delegating", "Agent": "delegating",
    "TodoWrite": "planning",
}


@dataclass
class Outcome:
    status: str  # "done" | "error"
    summary: str
    details: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    # Set when status is "error": what the owner sees instead of the raw summary.
    failure: Failure | None = None


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


def _shown_path(path: str, cwd: str | None) -> str:
    """Relative to the working folder when inside it (shorter on the card), else in full."""
    if cwd and path:
        try:
            return str(PureWindowsPath(path).relative_to(PureWindowsPath(cwd)))
        except ValueError:
            pass
    return path


def confirm_card(name: str, args: dict[str, Any], cwd: str | None = None) -> tuple[str, str]:
    """Title and detail for the overlay's confirm card: exactly what will happen."""
    path = _shown_path(str(args.get("file_path") or args.get("notebook_path") or ""), cwd)
    match name:
        case "Write":
            content = str(args.get("content", ""))
            lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            first = _short(content.splitlines()[0], 60) if content.strip() else "(empty)"
            return f"Create or overwrite {_base(path)}", f"{lines} line{'s' if lines != 1 else ''} into {path}. Starts: {first}"
        case "Edit" | "MultiEdit":
            old = _short(str(args.get("old_string", "")), 70)
            new = _short(str(args.get("new_string", "")), 70)
            return f"Edit {_base(path)}", f"In {path}: replace “{old}” with “{new}”"
        case "NotebookEdit":
            return f"Edit notebook {_base(path)}", path
        case "Bash" | "PowerShell":
            return "Run a command", str(args.get("command", "")).strip()[:COMMAND_MAX]
        case "WebFetch":
            url = str(args.get("url", ""))
            return f"Fetch {urlparse(url).netloc or 'a web page'}", _short(url, 300)
        case "WebSearch":
            return "Search the web", _short(str(args.get("query", "")), 300)
        case _:
            detail = ", ".join(f"{k}={_short(str(v), 60)}" for k, v in args.items())
            return describe_tool(name, args), _short(detail, 300)


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
        return []  # no "Starting Claude Code" line (owner, 2026-10-26): later steps and the byline name the provider
    if kind == "system" and sub == "permission_denied":
        if event.get("tool_name") in QUIET_DENIALS:
            return [Step("Skipped a page whose address wasn't from a search", "info", "blocked")]
        return [Step(f"Blocked: {event.get('tool_name', 'a tool')} isn't allowed", "info", "blocked")]
    if kind == "system" and sub == "api_retry":
        error = str(event.get("error") or "")
        return [Step(RETRY_STEPS.get(error, "Connection hiccup, retrying…"), "info", "waiting")]
    if kind != "assistant":
        return []
    helper = event.get("parent_tool_use_id") is not None
    out: list[Step] = []
    for block in event.get("message", {}).get("content", []):
        if block.get("type") == "tool_use":
            name = block.get("name", "?")
            text = describe_tool(name, block.get("input") or {})
            out.append(Step(_short(("Helper: " if helper else "") + text), "tool", TOOL_ACTIVITY.get(name, "working"), helper))
        elif block.get("type") == "text" and block.get("text", "").strip() and not helper:
            out.append(Step(_first_sentence(block["text"]), "text", "thinking"))
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
        failure = STOP_FAILURES.get(str(sub))
        if failure is None:
            failure = classify(
                text or message, CLAUDE_CODE.name, fallback_hint=CLAUDE_CODE.error_hint, signin_hint=CLAUDE_CODE.signin_hint
            )
        elif text:
            failure = replace(failure, detail=clean_detail(text))
        return Outcome("error", message, None, meta, failure)

    summary, details = split_answer(text)
    if meta["denied"] and set(meta["denied"]) - QUIET_DENIALS:
        blocked = ", ".join(sorted(set(meta["denied"]) - QUIET_DENIALS))
        summary = _short(f"{summary} (Blocked: {blocked}.)", SUMMARY_MAX + 40)
    return Outcome("done", summary or "Done.", details, meta)


_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def split_answer(text: str) -> tuple[str, dict[str, Any] | None]:
    """The answer's opening lines -> summary; the rest whole, for the card's "Read more".

    Nothing the agent wrote is cut short (owner checks 2026-11-04: a research answer arrived as six
    bullets cut at 120 characters, "...and 5 more", and nothing more to read). Only bullets: a list,
    every item. Anything else: the text with its markdown, which the overlay draws as paragraphs and lists.
    """
    lines = text.replace("\r\n", "\n").strip().split("\n")
    head: list[str] = []
    while lines and lines[0].strip() and not _BULLET.match(lines[0]):
        head.append(lines.pop(0))
    first = _plain("\n".join(head))
    summary = _short(first, SUMMARY_MAX)
    if summary != " ".join(first.split()):
        lines = [*head, "", *lines]  # too long for the summary: kept whole below it
    body = [line for line in lines if line.strip()]
    if not body:
        return summary, None
    if all(_BULLET.match(line) for line in body):
        items = [_plain(_BULLET.sub("", line)).strip() for line in body]
        return summary, {"kind": "list", "items": items[:LIST_MAX]}
    rest = "\n".join(lines).strip()
    return summary, {"kind": "text", "text": rest if len(rest) <= DETAILS_MAX else rest[: DETAILS_MAX - 1] + "…"}


# ---- the live view (ADR-017 §7) ---------------------------------------------------------------

NOTE_MAX = 280
TITLE_MAX = 120
URL_MAX = 2048
# Sources one search adds at most (a results page lists about ten).
SEARCH_SOURCES = 8
_LINKS = re.compile(r"Links:\s*(?=\[)")
_MD_LINK = re.compile(r"\[([^\]\n]{1,200})\]\((https?://[^\s)]+)\)")
_BARE_URL = re.compile(r"https?://[^\s\"'<>()\[\]{}`|\\^]+")


def site_of(url: str) -> str:
    """"https://www.britannica.com/topic/tea" -> "britannica.com"."""
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def _web_url(url: Any) -> str:
    """An http(s) address fit to show and open, or ""."""
    url = str(url or "").strip().rstrip(".,;:!?")
    if len(url) > URL_MAX or not re.match(r"https?://", url, re.I) or not site_of(url):
        return ""
    return url


def search_links(text: str) -> list[tuple[str, str]]:
    """(title, url) pairs from a WebSearch result: its ``Links: [{"title", "url"}, …]`` line, or
    markdown links, or bare addresses. At most SEARCH_SOURCES, each address once."""
    found: list[tuple[str, str]] = []
    if (m := _LINKS.search(text)) is not None:
        try:
            links, _ = json.JSONDecoder().raw_decode(text[m.end():])
        except ValueError:
            links = []
        for link in links if isinstance(links, list) else []:
            if isinstance(link, dict):
                found.append((str(link.get("title") or ""), str(link.get("url") or "")))
    if not found:
        found = [(t, u) for t, u in _MD_LINK.findall(text)]
    if not found:
        found = [("", u) for u in _BARE_URL.findall(text)]
    return _links(found)


def _links(found: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Addresses fit to show, each once, titles shortened; at most SEARCH_SOURCES."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for title, url in found:
        url = _web_url(url)
        if url and url not in seen:
            seen.add(url)
            out.append((_short(title, TITLE_MAX), url))
        if len(out) >= SEARCH_SOURCES:
            break
    return out


def structured_links(result: Any) -> list[tuple[str, str]]:
    """(title, url) pairs from the CLI's structured WebSearch result
    (``{"results": [{"content": [{"title", "url"}, …]}, "text", …]}``), when it sends one."""
    if not isinstance(result, dict) or not isinstance(result.get("results"), list):
        return []
    found = [
        (str(link.get("title") or ""), str(link.get("url") or ""))
        for part in result["results"] if isinstance(part, dict) and isinstance(part.get("content"), list)
        for link in part["content"] if isinstance(link, dict)
    ]
    return _links(found)


def _source(url: str, state: str, title: str = "") -> dict[str, Any]:
    return {"kind": "source", "url": url, "title": title, "site": site_of(url), "state": state}


@dataclass
class LiveMapper:
    """One run's tool calls, to turn their results into live-view items. Not thread-safe: one per run."""

    # tool_use id -> (tool name, the address a WebFetch reads)
    calls: dict[str, tuple[str, str]] = field(default_factory=dict)

    def feed(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        kind = event.get("type")
        content = event.get("message", {}).get("content", [])
        if not isinstance(content, list):
            return []
        out: list[dict[str, Any]] = []
        if kind == "assistant":
            helper = event.get("parent_tool_use_id") is not None
            for block in content:
                if block.get("type") == "tool_use" and block.get("name") in ("WebSearch", "WebFetch"):
                    url = _web_url((block.get("input") or {}).get("url")) if block["name"] == "WebFetch" else ""
                    self.calls[str(block.get("id"))] = (block["name"], url)
                    if url:
                        out.append(_source(url, "reading"))
                elif block.get("type") == "text" and not helper and (text := _plain(block.get("text", "")).strip()):
                    out.append({"kind": "note", "text": _short(text, NOTE_MAX)})
        elif kind == "user":
            for block in content:
                if block.get("type") != "tool_result":
                    continue
                name, url = self.calls.pop(str(block.get("tool_use_id")), ("", ""))
                if name == "WebFetch" and url:
                    out.append(_source(url, "failed" if block.get("is_error") else "read"))
                elif name == "WebSearch" and not block.get("is_error"):
                    links = structured_links(event.get("tool_use_result")) or search_links(str(block.get("content") or ""))
                    out += [_source(u, "found", t) for t, u in links]
        return out
