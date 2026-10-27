"""Swift's workflow tools and the host that runs them (ADR-010 §3).

Providers (Claude Code now; Codex and Hermes later) call these over MCP. The
provider decides what to write and when to send; Swift keeps the state, shows
it as artifacts, and runs anything with a side effect through the gateway.

| Tool | Side effect |
|---|---|
| ``find_contact(query)`` | none: resolves a person from the owner's contacts |
| ``draft_email(to, subject, body, draft_id?)`` | none: a draft held by Swift |
| ``send_email(draft_id)`` | external: through ``ActionGateway`` and the confirm card |
| ``present(kind, title, data)`` | none: shows a text, list or table |
| ``undo_last_action()`` | external: reverses the last action the owner approved, if it can be, with its own card |

More tools live next to this module: the calendar (``calendar.py``) and the desktop
(``desktop_tools.py``); ``ALL_TOOLS`` (``toolset.py``) is every one of them.

``side_effect`` is Swift's own label; a connector's description of itself is never used.
In a workflow run (ADR-011 W1) the scope's ``Grant`` decides which tools may be called.

Several requests can run at once (ADR-013 §5.4), each in its own scope. A call names its run:
a provider passes its run id (``bind`` ties it to the scope), otherwise the scope the session
opened for the task making the call is used (``CURRENT``). Only one run writes in the owner's
apps at a time (``writing``): another one waits, and says what for.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from swift.connectors.base import (
    CalendarConnector,
    ConnectorError,
    Contact,
    EmailConnector,
    OutgoingEmail,
)
from swift.security.gateway import UNDO_WINDOW_S, Action, ActionGateway
from swift.workflows.scope import Confirmer, Draft, Grant, Publisher, RunScope, Stepper

if TYPE_CHECKING:
    from swift.desktop.base import Desktop, WriteReceipt
    from swift.routing.local import LocalOpener

SideEffect = Literal["none", "read", "reversible", "external"]

MAX_BODY = 20_000
# The overlay gets at most this much of a body; the frame limit is 64 KB.
SHOWN_BODY = 16_000
_EMAIL = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")
_LEADING = re.compile(r"^(?:to |for )?(?:my |the |our )?", re.IGNORECASE)
# The scope of the request whose task is running: set by the session, inherited by the tasks
# a provider starts for it.
CURRENT: contextvars.ContextVar[RunScope | None] = contextvars.ContextVar("swift_scope", default=None)


@dataclass(frozen=True)
class KnownContact:
    """A contact from ``config.yaml``: who the owner means by "my lecturer"."""

    name: str
    email: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    text: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_mcp(self) -> dict[str, Any]:
        text = self.text + (f"\n{json.dumps(self.data, ensure_ascii=False)}" if self.data else "")
        return {"content": [{"type": "text", "text": text}], "is_error": not self.ok}


Handler = Callable[["ToolHost", RunScope, dict[str, Any]], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]
    side_effect: SideEffect
    handler: Handler


def _obj(required: list[str], **props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _normal(text: str) -> str:
    return " ".join(_LEADING.sub("", " ".join(text.lower().split())).split())


def _matches(query: str, known: KnownContact) -> bool:
    name = known.name.lower()
    words = query.split()
    return (
        query == name
        or any(query == a.lower() for a in known.aliases)
        or (bool(words) and all(w in name.split() for w in words))
        or query == known.email.lower()
    )


# ---- handlers ----------------------------------------------------------------


async def find_contact(host: ToolHost, scope: RunScope, args: dict[str, Any]) -> ToolResult:
    raw = str(args.get("query", "")).strip()
    query = _normal(raw)
    if not query:
        return ToolResult(False, "Say who to look for, e.g. 'lecturer' or 'Ada Lovelace'.")
    found = [Contact(k.name, k.email, "config") for k in host.contacts if _matches(query, k)]
    problem = ""
    if host.connector is not None:
        try:
            found += await host.connector.directory(query)
        except ConnectorError as exc:
            problem = f"{exc} {exc.hint}".strip()
    unique: dict[str, Contact] = {}
    for contact in found:
        if _EMAIL.match(contact.email):
            unique.setdefault(contact.email.lower(), contact)
    candidates = list(unique.values())
    for contact in candidates:
        scope.resolved[contact.email.lower()] = contact
    await scope.publish(
        "recipient", "recipient", "resolving", f"Looking up “{raw}”",
        {"query": raw, "candidates": [c.as_dict() for c in candidates], "chosen": 0 if len(candidates) == 1 else None},
    )
    data = {"candidates": [c.as_dict() for c in candidates]}
    if not candidates:
        return ToolResult(False, f"No contact matches “{raw}”. {problem}".strip() +
                          " Don't guess an address: tell the owner who couldn't be found.", data)
    if len(candidates) > 1:
        return ToolResult(True, "Several contacts match. Use the one the request clearly means; if it's not clear, "
                          "stop and ask the owner which one.", data)
    return ToolResult(True, f"Found {candidates[0].name}.", data)


async def draft_email(host: ToolHost, scope: RunScope, args: dict[str, Any]) -> ToolResult:
    to_arg = args.get("to", [])
    addresses = [to_arg] if isinstance(to_arg, str) else [str(a) for a in to_arg or []]
    subject = str(args.get("subject", "")).strip()
    body = str(args.get("body", "")).strip()
    if not addresses or not subject or not body:
        return ToolResult(False, "A draft needs at least one recipient, a subject and a body.")
    if len(body) > MAX_BODY:
        return ToolResult(False, f"The body is too long (over {MAX_BODY} characters).")
    recipients = []
    for address in addresses:
        contact = scope.resolved.get(address.strip().lower())
        if contact is None:
            return ToolResult(False, f"{address} isn't a contact Swift has resolved. Use find_contact first; "
                              "never type an address yourself.")
        recipients.append(contact)
    draft_id = str(args.get("draft_id") or "").strip()
    if draft_id:
        previous = scope.drafts.get(draft_id)
        if previous is None:
            return ToolResult(False, f"There is no draft {draft_id}.")
        draft = replace(previous, to=tuple(recipients), subject=subject, body=body, version=previous.version + 1)
    else:
        draft = Draft(f"draft-{next(scope.ids)}", tuple(recipients), subject, body)
    scope.drafts[draft.id] = draft
    await scope.publish(draft.id, "email_draft", "drafting", _draft_title(draft), _draft_data(draft))
    return ToolResult(True, "Draft ready. Send it with send_email; Swift will ask the owner first.",
                      {"draft_id": draft.id, "version": draft.version})


async def send_email(host: ToolHost, scope: RunScope, args: dict[str, Any]) -> ToolResult:
    draft_id = str(args.get("draft_id", "")).strip()
    connector = host.connector
    if connector is None:
        return ToolResult(False, "Email isn't connected in Swift (connectors.email in config.yaml). Nothing was sent.")

    def current() -> Draft | None:
        return scope.drafts.get(draft_id)

    draft = current()

    def validate() -> str | None:
        d = current()
        if d is None:
            return f"There is no draft {draft_id}. Write one with draft_email first."
        if not d.subject.strip() or not d.body.strip():
            return "The draft needs a subject and a body."
        if bad := [c.email for c in d.to if not _EMAIL.match(c.email)]:
            return f"Not an email address: {', '.join(bad)}"
        return None

    def digest() -> str:
        d = current()
        return d.digest() if d is not None else ""

    async def perform() -> str:
        d = current()
        assert d is not None
        # Only ever called by the gateway, after approval and the digest check.
        sent = await connector.send(OutgoingEmail(d.to, d.subject, d.body))
        return sent.message_id

    phases = {"waiting_approval": "confirming", "sending": "sending", "sent": "done", "failed": "failed",
              "rejected": "done"}

    async def on_status(state: str, extra: dict[str, str]) -> None:
        names = ", ".join(c.name for c in draft.to) if draft else ""
        await scope.publish(
            f"send-{draft_id}", "send_status", phases[state],  # type: ignore[arg-type]
            f"Email to {names}", {"state": state, "draft_id": draft_id, **extra},
        )

    names = ", ".join(c.name for c in draft.to) if draft else "?"
    action = Action(
        tool="send_email",
        targets=draft.to if draft else (),
        title=f"Send this email to {names}",
        detail=f"Subject: {draft.subject}" if draft else "",
        artifact_id=draft_id if draft else None,
        digest=digest,
        perform=perform,
        validate=validate,
        on_status=on_status,  # type: ignore[arg-type]
    )
    outcome = await host.gateway.execute(scope, action)
    match outcome.status:
        case "done":
            return ToolResult(True, f"Sent to {names}.", {"message_id": outcome.receipt})
        case "rejected":
            return ToolResult(False, f"{outcome.reason}: the email was NOT sent. Don't retry or try another way; "
                              "stop and tell the owner it wasn't sent.")
        case "revise":
            return ToolResult(False, revise_text(outcome.reason, "draft_email and then send_email", "sent"))
        case "denied":
            return ToolResult(False, f"Not sent: {outcome.reason}")
        case _:
            return ToolResult(False, f"Sending failed: {outcome.reason} Don't retry; tell the owner.")


def revise_text(feedback: str, tool: str, done: str) -> str:
    """What a provider is told when the owner asks for a change on a confirm card."""
    return (
        f"The owner wants a change before this goes ahead: “{feedback}”. Nothing was {done}. "
        f"Apply the change, keep everything else as it was, and call {tool} again: Swift shows the owner "
        "the new version to approve."
    )


async def present(host: ToolHost, scope: RunScope, args: dict[str, Any]) -> ToolResult:
    kind = args.get("kind")
    title = str(args.get("title", "")).strip()[:120]
    data = args.get("data")
    if kind == "text" and isinstance(data, dict) and isinstance(data.get("text"), str):
        shown = {"kind": "text", "text": data["text"][:SHOWN_BODY]}
    elif kind == "list" and isinstance(data, dict) and isinstance(data.get("items"), list):
        shown = {"kind": "list", "items": [str(i)[:300] for i in data["items"][:100]]}
    elif kind == "table" and isinstance(data, dict) and isinstance(data.get("columns"), list) and isinstance(data.get("rows"), list):
        shown = {"kind": "table", "columns": [str(c)[:60] for c in data["columns"][:8]],
                 "rows": [[str(c)[:120] for c in row][:8] for row in data["rows"][:100] if isinstance(row, list)]}
    else:
        return ToolResult(False, "present needs kind text {text}, list {items} or table {columns, rows}.")
    artifact = await scope.publish(f"shown-{next(scope.ids)}", kind, scope.artifacts.phase or "done", title, shown)
    return ToolResult(True, "Shown to the owner.", {"id": artifact.id})


async def undo_last_action(host: ToolHost, scope: RunScope, args: dict[str, Any]) -> ToolResult:
    """"Undo that" / "that wasn't approved": reverse what the owner last approved, if its tool can (ADR-010 §4)."""
    last, outcome = await host.gateway.undo_last(scope, UNDO_WINDOW_S)
    if last is None:
        minutes = int(UNDO_WINDOW_S // 60)
        return ToolResult(False, f"Swift hasn't done anything on the owner's approval in the last {minutes} minutes, "
                          "so there's nothing of Swift's to undo. Nothing was changed; tell the owner.")
    if not last.undoable:
        return ToolResult(False, f"The last thing the owner approved was “{last.title}”, and that can't be undone "
                          "(a sent email can't be unsent). Nothing was changed: tell the owner, and offer a follow-up "
                          "such as a correction.")
    match outcome.status:
        case "done":
            return ToolResult(True, f"Undone: “{last.title}”.", {"undid": last.tool})
        case "rejected":
            return ToolResult(False, f"{outcome.reason}: “{last.title}” stays as it is. Don't retry; tell the owner.")
        case "revise":
            return ToolResult(False, f"The owner wants something else instead: “{outcome.reason}”. Nothing was undone. "
                              "Do what they asked with the workflow's own tools; Swift asks them again before it "
                              "changes anything.")
        case "denied":
            return ToolResult(False, f"Not undone: {outcome.reason}")
        case _:
            return ToolResult(False, f"Undoing it failed: {outcome.reason} Don't retry; tell the owner.")


def _draft_title(draft: Draft) -> str:
    return "Email to " + ", ".join(c.name for c in draft.to)


def _draft_data(draft: Draft) -> dict[str, Any]:
    body = draft.body if len(draft.body) <= SHOWN_BODY else draft.body[:SHOWN_BODY] + "…"
    return {"to": [{"name": c.name, "email": c.email} for c in draft.to], "subject": draft.subject, "body": body}


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "find_contact",
        "Look up a person in the owner's contacts ('my lecturer', 'Ada'). Returns name and email. "
        "The only way to get an address Swift will email.",
        _obj(["query"], query={"type": "string", "description": "Who, as the owner said it"}),
        "none", find_contact,
    ),
    ToolSpec(
        "draft_email",
        "Write or revise an email draft held by Swift; the owner can see it. Nothing is sent. "
        "Pass draft_id to revise an existing draft.",
        _obj(
            ["to", "subject", "body"],
            to={"type": "array", "items": {"type": "string"}, "description": "Addresses from find_contact"},
            subject={"type": "string"},
            body={"type": "string", "description": "Plain text, signed as the owner"},
            draft_id={"type": "string"},
        ),
        "none", draft_email,
    ),
    ToolSpec(
        "send_email",
        "Send a draft. Swift shows the owner the draft on a confirm card and sends only if they approve.",
        _obj(["draft_id"], draft_id={"type": "string"}),
        "external", send_email,
    ),
    ToolSpec(
        "present",
        "Show the owner a result: kind 'text' with data {text}, 'list' with {items}, 'table' with {columns, rows}.",
        _obj(["kind", "title", "data"], kind={"type": "string", "enum": ["text", "list", "table"]},
             title={"type": "string"}, data={"type": "object"}),
        "none", present,
    ),
    ToolSpec(
        "undo_last_action",
        "Undo the last thing the owner approved on a Swift card (\"undo that\", \"I didn't approve that\"), "
        "e.g. remove the event just added. Swift shows the owner what will be undone on a confirm card. "
        "Says so if it can't be undone (a sent email).",
        _obj([]),
        "external", undo_last_action,
    ),
)


class ToolHost:
    """Runs Swift's tools for whichever provider calls them, each call in its own request's scope."""

    def __init__(
        self,
        connector: EmailConnector | None = None,
        contacts: tuple[KnownContact, ...] = (),
        gateway: ActionGateway | None = None,
        tools: tuple[ToolSpec, ...] = TOOLS,
        *,
        calendar: CalendarConnector | None = None,
        desktop: Desktop | None = None,
        opener: LocalOpener | None = None,
    ) -> None:
        self.connector = connector
        self.contacts = contacts
        self.gateway = gateway or ActionGateway()
        self.tools = {t.name: t for t in tools}
        self.calendar = calendar
        self.desktop = desktop
        self.opener = opener
        # Open scopes, oldest first, and the provider run ids bound to them.
        self.scopes: list[RunScope] = []
        self._bound: dict[str, RunScope] = {}
        # One writer in the owner's apps at a time (ADR-013 §5.2), and the app it writes in.
        self.writing = asyncio.Lock()
        self.writing_app = ""
        # The last thing Swift wrote in the owner's apps, for "undo that" (ADR-012 §6), and when
        # (time.monotonic()): "undo that" means the newer of it and the gateway's last approved action.
        self.last_write: WriteReceipt | None = None
        self.last_write_at = 0.0

    @property
    def scope(self) -> RunScope | None:
        """The newest open scope (one request at a time: the only one)."""
        return self.scopes[-1] if self.scopes else None

    def open(
        self, publish: Publisher, confirm: Confirmer, grant: Grant | None = None, step: Stepper | None = None
    ) -> RunScope:
        scope = RunScope(publish, confirm, grant=grant, step_fn=step)
        self.scopes.append(scope)
        return scope

    def bind(self, scope: RunScope, run_id: str) -> None:
        """The provider's run ``run_id`` works for the request with ``scope``."""
        self._bound[run_id] = scope

    def resolve(self, run: str | None = None) -> RunScope | None:
        """The open scope a call belongs to: its run's, the calling task's, or the only one open."""
        scope = self._bound.get(run) if run is not None else None
        scope = scope or CURRENT.get()
        if scope is None and len(self.scopes) == 1:
            scope = self.scopes[0]
        return scope if scope is not None and not scope.closed else None

    def permits(self, capability: str, run: str | None = None) -> bool:
        """A provider capability (``web.search``) the run's workflow declared. Outside workflows: none."""
        scope = self.resolve(run)
        return scope is not None and scope.grant is not None and capability in scope.grant.capabilities

    @property
    def in_workflow(self) -> bool:
        return self.in_workflow_for(None)

    def in_workflow_for(self, run: str | None) -> bool:
        scope = self.resolve(run)
        return scope is not None and scope.grant is not None

    def close(self, scope: RunScope) -> None:
        scope.closed = True
        if scope in self.scopes:
            self.scopes.remove(scope)
        for run_id in [r for r, s in self._bound.items() if s is scope]:
            del self._bound[run_id]

    async def call(self, name: str, args: dict[str, Any], run: str | None = None) -> ToolResult:
        spec = self.tools.get(name)
        if spec is None:
            return ToolResult(False, f"Swift has no tool named {name}.")
        scope = self.resolve(run)
        if scope is None:
            return ToolResult(False, "No Swift run is active; nothing was done.")
        if not scope.allows(name):
            assert scope.grant is not None
            logger.info("tool outside the workflow refused", tool=name, workflow=scope.grant.workflow)
            return ToolResult(False, f"The {scope.grant.workflow} workflow doesn't use {name}, so Swift refused it. "
                              "Nothing was done; carry on with the workflow's own tools.")
        try:
            return await spec.handler(self, scope, args if isinstance(args, dict) else {})
        except Exception as exc:  # noqa: BLE001 - a tool bug is reported to the provider, not a crash
            logger.exception("swift tool failed", tool=name)
            return ToolResult(False, f"Swift's {name} tool failed ({type(exc).__name__}). Nothing was sent.")
