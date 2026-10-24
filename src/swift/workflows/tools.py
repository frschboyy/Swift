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

``side_effect`` is Swift's own label; a connector's description of itself is never used.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from loguru import logger

from swift.connectors.base import Contact, ConnectorError, EmailConnector, OutgoingEmail
from swift.security.gateway import Action, ActionGateway
from swift.workflows.scope import Confirmer, Draft, Publisher, RunScope

SideEffect = Literal["none", "external"]

MAX_BODY = 20_000
# The overlay gets at most this much of a body; the frame limit is 64 KB.
SHOWN_BODY = 16_000
_EMAIL = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")
_LEADING = re.compile(r"^(?:to |for )?(?:my |the |our )?", re.IGNORECASE)


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
        case "denied":
            return ToolResult(False, f"Not sent: {outcome.reason}")
        case _:
            return ToolResult(False, f"Sending failed: {outcome.reason} Don't retry; tell the owner.")


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
)


class ToolHost:
    """Runs Swift's tools for whichever provider calls them, inside the one open run scope."""

    def __init__(
        self,
        connector: EmailConnector | None = None,
        contacts: tuple[KnownContact, ...] = (),
        gateway: ActionGateway | None = None,
        tools: tuple[ToolSpec, ...] = TOOLS,
    ) -> None:
        self.connector = connector
        self.contacts = contacts
        self.gateway = gateway or ActionGateway()
        self.tools = {t.name: t for t in tools}
        self.scope: RunScope | None = None

    def open(self, publish: Publisher, confirm: Confirmer) -> RunScope:
        if self.scope is not None:
            self.scope.closed = True
        self.scope = RunScope(publish, confirm)
        return self.scope

    def close(self, scope: RunScope) -> None:
        scope.closed = True
        if self.scope is scope:
            self.scope = None

    async def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        spec = self.tools.get(name)
        if spec is None:
            return ToolResult(False, f"Swift has no tool named {name}.")
        scope = self.scope
        if scope is None or scope.closed:
            return ToolResult(False, "No Swift run is active; nothing was done.")
        try:
            return await spec.handler(self, scope, args if isinstance(args, dict) else {})
        except Exception as exc:  # noqa: BLE001 - a tool bug is reported to the provider, not a crash
            logger.exception("swift tool failed", tool=name)
            return ToolResult(False, f"Swift's {name} tool failed ({type(exc).__name__}). Nothing was sent.")
