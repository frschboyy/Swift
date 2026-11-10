"""Swift's workflow tools and the host that runs them (ADR-010 §3).

Providers (Claude Code now; Codex and Hermes later) call these over MCP. The
provider decides what to write and when to send; Swift keeps the state, shows
it as artifacts, and runs anything with a side effect through the gateway.

| Tool | Side effect |
|---|---|
| ``find_contact(query)`` | none: resolves a person from the owner's contacts; with several matches it asks the owner which |
| ``ask_owner(question, kind, options?)`` | none: asks the owner and waits for the answer (ADR-016 §5.1) |
| ``draft_email(to, subject, message, draft_id?)`` | none: a draft held by Swift, written as the owner; a revision keeps what it leaves out |
| ``send_email(draft_id)`` | external: through ``ActionGateway`` and the confirm card |
| ``present(kind, title, data)`` | none: shows a text, list or table |
| ``undo_last_action()`` | external: reverses the last action the owner approved, if it can be, with its own card |

More tools live next to this module: the calendar (``calendar.py``) and the desktop
(``desktop_tools.py``); ``ALL_TOOLS`` (``toolset.py``) is every one of them.

``side_effect`` is Swift's own label; a connector's description of itself is never used.
In a workflow run (ADR-011 W1) the scope's ``Grant`` decides which tools may be called.

A draft reads as the owner wrote it: the provider writes a short subject and the message,
and Swift puts "Hello Janet," above it and "Regards," and the owner's name under it. The name
is ``owner_name`` in ``config.yaml``, else the name on the owner's Google account. A subject
that is a sentence to the recipient ("I am not coming") is the message, and is refused. A
revision (``draft_id``) keeps the subject and recipients it doesn't give: "actually say I'm not
coming" rewrites the message, never the subject.

A ``ToolResult`` that is ``expected`` didn't go ahead for a reason that isn't the provider
struggling (the owner said no or asked for a change; nobody matched): Swift doesn't count it
towards moving the run to a stronger model.

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
import time
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
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
from swift.workflows import names
from swift.workflows.scope import Asker, Confirmer, Draft, Grant, Liver, Publisher, RunScope, Stepper

if TYPE_CHECKING:
    from swift.desktop.base import Desktop, WriteReceipt
    from swift.routing.local import LocalOpener

SideEffect = Literal["none", "read", "reversible", "external"]

MAX_BODY = 20_000
# A subject is a few words ("Meeting cancelled"), never the message.
MAX_SUBJECT = 78
MAX_SUBJECT_WORDS = 10
_GREETING = re.compile(r"^(?:hi|hello|hey|dear|good (?:morning|afternoon|evening))\b[^.!?\n]{0,60},?\s*$", re.IGNORECASE)
_SIGN_OFF = re.compile(
    r"^(?:regards|kind regards|best regards|warm regards|best|best wishes|many thanks|thanks|thank you|cheers|"
    r"sincerely|yours sincerely|yours faithfully|yours|all the best|take care)\b[^.!?,\n]{0,12}[,!]?\s*$",
    re.IGNORECASE,
)
_TITLES = {"dr", "prof", "professor", "mr", "mrs", "ms", "miss", "mx", "sir", "dame"}
# A subject opening like this is a sentence to the recipient: the message, not what it's about.
_SPOKEN = re.compile(
    r"^(?:i|i'm|im|i've|i'll|i'd|hello|hi|hey|dear|just wanted|(?:the|this|my) email)\b", re.IGNORECASE,
)
# The owner's calendar titles Swift knows ("cancel Swift check" is a calendar request): asked for
# again after this long, for events from yesterday to this many days ahead.
TITLES_TTL_S = 600.0
TITLES_DAYS = 30
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
    # Not ok, but not the provider failing either: the owner decided, or nobody matched.
    expected: bool = False

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
    candidates = _unique(found)
    guessed = False
    if not candidates and host.connector is not None and 2 <= len(names.words(raw)) <= 4:
        # Nobody by the whole name as heard ("Francis Chernu"): each name alone, then those close to all of it.
        more: list[Contact] = []
        for word in dict.fromkeys(w for w in names.words(raw) if len(w) > 2):
            try:
                more += await host.connector.directory(word)
            except ConnectorError:
                break
        candidates = [c for c in names.by_query(raw, _unique(more), exact=False) if isinstance(c, Contact)]
        guessed = bool(candidates) and not names.by_query(raw, candidates)  # "Dr Lovelace": a surname search, but named
    elif candidates:
        # The search matches the start of a name: "Sam" found only Alex Samia, and the email went to
        # him (owner checks 2026-11-05). Someone named by every word said is a match; anyone else is
        # only a guess, and the owner is asked. Contacts in the config matched by name or alias.
        named = [c for c in candidates if c.source == "config" or c in names.by_query(raw, candidates)]
        if named:
            candidates = named
        else:
            guessed = True
    # The ones the owner named ("Francis Chianu", not every Francis): by the whole name, then their words.
    candidates = [c for c in names.narrow(raw, scope.said, candidates) if isinstance(c, Contact)]
    # One match, but the owner said a name it doesn't have: only a guess, so the owner is asked (X-01).
    if len(candidates) == 1 and candidates[0].source != "config" and names.said_otherwise(raw, scope.said, candidates[0]):
        guessed = True
    # Content-free: how many, and where from ("gmail_emailed": someone the owner has emailed).
    logger.info("contact lookup", found=len(candidates), sources=sorted({c.source for c in candidates}),
                problem=bool(problem))
    # A contact the owner has to confirm isn't a recipient until they do (``_is_it``): only then does a
    # "no" leave nothing behind (2026-11-05: a rejected guess still passed the recipient check).
    asks_first = guessed and len(candidates) == 1 and scope.ask_fn is not None
    if not asks_first:
        for contact in candidates:
            scope.resolved[contact.email.lower()] = contact
    await scope.publish(
        "recipient", "recipient", "resolving", f"Looking up “{raw}”",
        {"query": raw, "candidates": [c.as_dict() for c in candidates], "chosen": 0 if len(candidates) == 1 else None},
    )
    data = {"candidates": [c.as_dict() for c in candidates]}
    if not candidates:
        return ToolResult(False, f"No contact matches “{raw}”. {problem}".strip() +
                          " Don't guess an address: tell the owner who couldn't be found.", data, expected=not problem)
    if guessed and len(candidates) == 1:
        if not asks_first:
            return ToolResult(True, f"No contact is named exactly “{raw}”; the closest is {_described(candidates[0])}. "
                              "Ask the owner whether that's who they mean before using it.", data)
        sure = await _is_it(scope, raw, candidates[0])
        if isinstance(sure, ToolResult):
            return sure
        logger.info("contact chosen by the owner", options=1)
        scope.resolved[candidates[0].email.lower()] = candidates[0]
        return ToolResult(True, f"The owner chose {_described(candidates[0])}. Use this contact only.",
                          {"candidates": [candidates[0].as_dict()], "chosen_by_owner": True})
    if len(candidates) > 1 and (chosen := await _which(scope, raw, candidates)) is not None:
        if isinstance(chosen, ToolResult):
            return chosen
        await scope.publish(
            "recipient", "recipient", "resolving", f"Looking up “{raw}”",
            {"query": raw, "candidates": [c.as_dict() for c in candidates], "chosen": candidates.index(chosen)},
        )
        return ToolResult(True, f"The owner chose {_described(chosen)}. Use this contact only.",
                          {"candidates": [chosen.as_dict()], "chosen_by_owner": True})
    if len(candidates) > 1:
        listed = "; ".join(_described(c) for c in candidates)
        return ToolResult(True, f"Several contacts match: {listed}. Use the one the request clearly means; if it's "
                          "not clear, stop and ask the owner which one, naming each by email and the detail shown.",
                          data)
    return ToolResult(True, f"Found {_described(candidates[0])}.", data)


def _unique(found: list[Contact]) -> list[Contact]:
    """Each address once, and only real addresses."""
    unique: dict[str, Contact] = {}
    for contact in found:
        if _EMAIL.match(contact.email):
            unique.setdefault(contact.email.lower(), contact)
    return list(unique.values())


# At most this many matches are offered as a spoken choice; more and the provider narrows it down.
MAX_CHOICES = 4


def _labels(candidates: list[Contact]) -> tuple[str, ...]:
    """How each match is named in the question: the name, with the address only where names repeat."""
    names = [c.name.strip() or c.email for c in candidates]
    return tuple(n if names.count(n) == 1 else f"{n} ({c.email})" for n, c in zip(names, candidates, strict=True))


async def _which(scope: RunScope, raw: str, candidates: list[Contact]) -> Contact | ToolResult | None:
    """Several contacts match: ask the owner which ("Which Sam: Sam Lee or Sam Okoro?", ADR-016 §5.1).
    The answer can only pick one of these matches, so a recipient still comes only from the contacts.
    None: not asked, or no answer (the provider then asks in its own answer, as before)."""
    if scope.ask_fn is None or len(candidates) > MAX_CHOICES:
        return None
    labels = _labels(candidates)
    who = " ".join(w.capitalize() for w in raw.split()) if len(raw) <= 30 else "one"
    question = f"Which {who}: {', '.join(labels[:-1])} or {labels[-1]}?"
    answer = await scope.ask(question, "choice", labels)
    if answer is None:
        return None
    if answer.kind == "choice" and answer.index is not None and 0 <= answer.index < len(candidates):
        logger.info("contact chosen by the owner", options=len(candidates))
        return candidates[answer.index]
    if answer.kind == "cancel":
        return ToolResult(False, "The owner said never mind: don't email anyone. Stop and say so.", expected=True)
    return None


async def _is_it(scope: RunScope, raw: str, guess: Contact) -> bool | ToolResult:
    """Nobody is named what the owner said, but one contact is close: Swift asks before using it
    ("I couldn't find Sam. Did you mean Alex Samia?"). True: yes. A ToolResult: anything else,
    including no answer, so the contact is not used."""
    who = " ".join(w.capitalize() for w in raw.split()) if len(raw) <= 30 else "them"
    named = guess.name or guess.email
    answer = await scope.ask(f"I couldn't find {who}. Did you mean {named}?", "yes_no", ())
    if answer is not None and answer.kind == "yes":
        return True
    told = f"didn't say whether {named} is who they meant" if answer is None else f"said {named} isn't who they meant"
    return ToolResult(False, f"The owner {told}. Don't email anyone: say no contact is named “{raw}” "
                      "and ask for their full name or address.", expected=True)


def _described(contact: Contact) -> str:
    """Enough to tell two matches apart: "Janet Okafor <janet@uni.ac.uk>, University of X, Supervisor"."""
    return f"{contact.name} <{contact.email}>" + (f", {contact.detail}" if contact.detail else "")


def greeting(recipients: tuple[Contact, ...]) -> str:
    """The greeting line: "Hello Janet,", "Hello Dr Lovelace,", "Hello Janet and Ada,"; "Hello," without a name."""
    names = []
    for contact in recipients:
        words = contact.name.split() if "@" not in contact.name else []
        if len(words) >= 2 and words[0].lower().rstrip(".") in _TITLES:
            names.append(f"{words[0]} {words[-1]}")
        elif words:
            names.append(words[0])
    if not names:
        return "Hello,"
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"Hello {joined},"


def message_only(text: str) -> str:
    """The message without a greeting or sign-off the provider wrote itself (Swift adds its own)."""
    lines = text.replace("\r\n", "\n").strip().split("\n")
    if len(lines) > 1 and _GREETING.match(lines[0].strip()):
        lines = lines[1:]
    filled = [i for i, line in enumerate(lines) if line.strip()]
    for i in filled[1:][-3:]:  # never the message's first line: "Thanks!" alone is the message
        if _SIGN_OFF.match(lines[i].strip()):
            lines = lines[:i]
            break
    return "\n".join(lines).strip()


def compose(recipients: tuple[Contact, ...], message: str, owner: str) -> str:
    """The body as the owner sends it: greeting, their message, and their name."""
    sign_off = f"Regards,\n{owner}" if owner else "Regards,"
    return f"{greeting(recipients)}\n\n{message_only(message)}\n\n{sign_off}"


async def owner_name(host: ToolHost) -> str:
    """Who signs the owner's emails: ``owner_name`` in config.yaml, else their Google account's name."""
    if host.owner_name:
        return host.owner_name
    ask = getattr(host.connector, "owner_name", None)
    if ask is None:
        return ""
    try:
        return str(await ask()).strip()
    except ConnectorError:
        return ""


def _flat(text: str) -> str:
    return " ".join(text.lower().split()).rstrip(".!")


def subject_problem(subject: str, message: str) -> str | None:
    if not subject:
        return "A draft needs a subject of a few words, e.g. “Meeting cancelled”."
    if len(subject) > MAX_SUBJECT or len(subject.split()) > MAX_SUBJECT_WORDS:
        return ("The subject is too long. Make it a few words (e.g. “Meeting cancelled”) and put what to say "
                "in message.")
    if _flat(subject) == _flat(message_only(message)):
        return "The subject repeats the message. Make the subject a few words, and write the message in full."
    if _SPOKEN.match(subject.replace("\u2019", "'")):
        return ("The subject reads like the message. Make it a short summary of what the email is about "
                "(e.g. “Not coming”, “Running late”), and put what to say in message.")
    return None


async def draft_email(host: ToolHost, scope: RunScope, args: dict[str, Any]) -> ToolResult:
    draft_id = str(args.get("draft_id") or "").strip()
    previous = scope.drafts.get(draft_id) if draft_id else None
    if draft_id and previous is None:
        return ToolResult(False, f"There is no draft {draft_id}.")
    to_arg = args.get("to") or ([c.email for c in previous.to] if previous else [])
    addresses = [to_arg] if isinstance(to_arg, str) else [str(a) for a in to_arg or []]
    # A revision keeps its subject unless it gives a new one: a correction changes what is said.
    subject = " ".join(str(args.get("subject") or (previous.subject if previous else "")).split())
    # ``body`` is the older name; either way it's the message, and Swift adds the greeting and sign-off.
    message = str(args.get("message") or args.get("body") or "").strip()
    if not addresses or not message_only(message):
        return ToolResult(False, "A draft needs at least one recipient, a subject and a message.")
    if problem := subject_problem(subject, message):
        return ToolResult(False, problem)
    if len(message) > MAX_BODY:
        return ToolResult(False, f"The message is too long (over {MAX_BODY} characters).")
    recipients = []
    for address in addresses:
        contact = scope.resolved.get(address.strip().lower())
        if contact is None:
            return ToolResult(False, f"{address} isn't a contact Swift has resolved. Use find_contact first; "
                              "never type an address yourself.")
        recipients.append(contact)
    signer = await owner_name(host)
    body = compose(tuple(recipients), message, signer)
    logger.info("draft written", subject_words=len(subject.split()), greeted=greeting(tuple(recipients)) != "Hello,",
                signed=bool(signer), revision=bool(args.get("draft_id")))
    if previous is not None:
        draft = replace(previous, to=tuple(recipients), subject=subject, body=body, version=previous.version + 1)
    else:
        draft = Draft(f"draft-{next(scope.ids)}", tuple(recipients), subject, body)
    scope.drafts[draft.id] = draft
    await scope.publish(draft.id, "email_draft", "drafting", _draft_title(draft), _draft_data(draft))
    return ToolResult(True, "Draft ready, with the owner's greeting and sign-off added. Send it with send_email; "
                      "Swift will ask the owner first.", {"draft_id": draft.id, "version": draft.version})


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
                              "stop and tell the owner it wasn't sent.", expected=True)
        case "revise":
            return ToolResult(False, revise_text(outcome.reason, "draft_email and then send_email", "sent"),
                              expected=True)
        case "denied":
            return ToolResult(False, f"Not sent: {outcome.reason}")
        case "unknown":
            return ToolResult(False, f"It may have been sent: {outcome.reason} Don't send it again or try another "
                              "way; tell the owner to look in their Gmail Sent folder.")
        case _:
            return ToolResult(False, f"Sending failed: {outcome.reason} Don't retry; tell the owner.")


def revise_text(feedback: str, tool: str, done: str) -> str:
    """What a provider is told when the owner asks for a change on a confirm card."""
    return (
        f"The owner wants a change before this goes ahead: “{feedback}”. Nothing was {done}. "
        f"Apply the change, keep everything else as it was, and call {tool} again: Swift shows the owner "
        "the new version to approve."
    )


# ``ask_owner``'s kinds (swift.dialogue.ASK_KINDS) and limits.
ASK_KINDS = ("yes_no", "choice", "free")
MAX_ASK = 300
MAX_ASK_OPTIONS = 8


async def ask_owner(host: ToolHost, scope: RunScope, args: dict[str, Any]) -> ToolResult:
    """Ask the owner one short question and wait for the answer (ADR-016 §5.1). Swift shows it, says it
    for a spoken request and listens for the answer. Never an approval: anything with a side effect
    still goes through its confirm card."""
    question = " ".join(str(args.get("question", "")).split())
    options = [" ".join(str(o).split()) for o in (args.get("options") or []) if str(o).strip()][:MAX_ASK_OPTIONS]
    kind = str(args.get("kind") or ("choice" if options else "free"))
    if not question:
        return ToolResult(False, "Say what to ask, as one short question.")
    if len(question) > MAX_ASK:
        return ToolResult(False, f"That question is too long to say aloud; keep it under {MAX_ASK} characters.")
    if kind not in ASK_KINDS:
        return ToolResult(False, f"kind must be one of {', '.join(ASK_KINDS)}.")
    if kind == "choice" and len(options) < 2:
        return ToolResult(False, "A choice needs at least two options.")
    if scope.ask_fn is None:
        return ToolResult(False, "Swift can't ask the owner right now. Ask in your answer instead.", expected=True)
    answer = await scope.ask(question, kind, tuple(options) if kind == "choice" else ())
    if answer is None:
        return ToolResult(False, "No answer: the owner is away or didn't answer, and the question waits in their "
                          "list. Don't guess. End your turn by asking it in one short sentence.",
                          {"answered": False}, expected=True)
    data = answer.for_run()
    if answer.said:
        scope.answers.append(answer.said)
    if not data.get("answered"):
        return ToolResult(False, str(data.get("reason") or "No answer."), data, expected=True)
    return ToolResult(True, "The owner answered.", data)


WEATHER_URL = "https://wttr.in/?format=j1"
WEATHER_TIMEOUT_S = 10.0


def _fetch_weather() -> dict[str, Any]:
    request = urllib.request.Request(WEATHER_URL, headers={"User-Agent": "swift-assistant"})  # noqa: S310 - a fixed https address
    with urllib.request.urlopen(request, timeout=WEATHER_TIMEOUT_S) as reply:  # noqa: S310
        return json.loads(reply.read(2_000_000))


def _weather_facts(raw: dict[str, Any]) -> dict[str, Any]:
    """Today's weather, cut down to what answers a question about it."""
    now = (raw.get("current_condition") or [{}])[0]
    area = (raw.get("nearest_area") or [{}])[0]
    today = (raw.get("weather") or [{}])[0]
    text = lambda d, key: ((d.get(key) or [{}])[0]).get("value", "")  # noqa: E731
    return {
        "place": text(area, "areaName"), "country": text(area, "country"),
        "now": {"temp_c": now.get("temp_C"), "feels_c": now.get("FeelsLikeC"), "sky": text(now, "weatherDesc")},
        "today": {"max_c": today.get("maxtempC"), "min_c": today.get("mintempC")},
        "hours": [
            {"time": f"{int(h.get('time', 0)) // 100:02d}:00", "chance_of_rain": h.get("chanceofrain"),
             "rain_mm": h.get("precipMM"), "temp_c": h.get("tempC"), "sky": text(h, "weatherDesc")}
            for h in today.get("hourly") or []
        ],
    }


async def weather(host: ToolHost, scope: RunScope, args: dict[str, Any]) -> ToolResult:  # noqa: ARG001
    """Today's weather where the PC is. The address is fixed and nothing goes into it, so no card."""
    try:
        raw = await asyncio.to_thread(_fetch_weather)
        return ToolResult(True, "Today's weather.", _weather_facts(raw))
    except (OSError, ValueError, TimeoutError) as exc:
        # Failed twice on the owner's PC (2026-11-08, 01:19 and 01:20) and never when fetched by hand: the
        # kind of failure is logged so the next one says why. Content-free: a type and a status.
        logger.warning("weather unavailable", error=type(exc).__name__, status=getattr(exc, "code", None))
        return ToolResult(False, "The weather couldn't be read right now.", {"error": type(exc).__name__}, expected=True)


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
            return ToolResult(False, f"{outcome.reason}: “{last.title}” stays as it is. Don't retry; tell the owner.",
                              expected=True)
        case "revise":
            return ToolResult(False, f"The owner wants something else instead: “{outcome.reason}”. Nothing was undone. "
                              "Do what they asked with the workflow's own tools; Swift asks them again before it "
                              "changes anything.", expected=True)
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
        "Swift adds the greeting (\"Hello Janet,\") and the owner's sign-off and name. "
        "Pass draft_id to revise an existing draft: what you leave out (to, subject) stays as it was, so a "
        "correction (\"actually say I'm not coming\") passes only the new message.",
        _obj(
            ["message"],
            to={"type": "array", "items": {"type": "string"},
                "description": "Addresses from find_contact (a new draft needs them)"},
            subject={"type": "string", "description": "A short summary of what it's about, e.g. 'Meeting cancelled'; "
                     "never the message or a sentence to the recipient (a new draft needs it)"},
            message={"type": "string", "description": "What the owner says to the recipient, in the first person "
                     "and their plain voice, in full sentences. Plain text; no greeting, no sign-off."},
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
        "ask_owner",
        "Ask the owner one short question and wait for their answer: Swift shows it, says it aloud for a spoken "
        "request, and listens. Use it when you need a detail you can't safely guess (which file, what time, "
        "which of two people). kind: 'yes_no', 'choice' (with 2-8 short options) or 'free'. Returns the answer, "
        "or answered: false (then don't guess; end your turn by asking). It never approves anything: actions "
        "still show their confirm card.",
        _obj(["question"], question={"type": "string", "description": "One short question, as you'd say it"},
             kind={"type": "string", "enum": list(ASK_KINDS)},
             options={"type": "array", "items": {"type": "string"}, "description": "For 'choice': the options"}),
        "none", ask_owner,
    ),
    ToolSpec(
        "weather",
        "Today's weather where the owner's PC is: now, and hour by hour with the chance of rain. No arguments: "
        "it works out the place itself. Use it for any question about the weather here, and don't ask where.",
        _obj([]),
        "read", weather,
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
        owner_name: str = "",
    ) -> None:
        self.connector = connector
        self.contacts = contacts
        # Signs the emails Swift drafts; "" asks the email connector (the Google account's name).
        self.owner_name = owner_name
        self.gateway = gateway or ActionGateway()
        self.tools = {t.name: t for t in tools}
        self.calendar = calendar
        self.desktop = desktop
        self.opener = opener
        # The system lane (ADR-016 §3), for ``system_action``; set by the backend. None: not offered.
        self.system: Any = None
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
        # Which request wrote it, and what is being written right now and for which request:
        # "show me" during a run brings that app to the front.
        self.last_write_scope: RunScope | None = None
        self.live_write: tuple[RunScope, WriteReceipt] | None = None
        # Titles of the owner's calendar events, from the calendar and from what runs saw, so a
        # request that names one ("cancel Swift check") goes to the calendar workflow.
        self.event_titles: set[str] = set()
        self._titles_at = 0.0
        self._titles_task: asyncio.Task[None] | None = None

    def known_titles(self) -> tuple[str, ...]:
        """The calendar titles Swift knows; asks the calendar again in the background when they're old."""
        stale = time.monotonic() - self._titles_at > TITLES_TTL_S or not self._titles_at
        if self.calendar is not None and stale and (self._titles_task is None or self._titles_task.done()):
            try:
                self._titles_task = asyncio.get_running_loop().create_task(self.refresh_titles())
            except RuntimeError:
                pass  # no loop: what is known will do
        return tuple(self.event_titles)

    async def refresh_titles(self) -> None:
        if self.calendar is None:
            return
        self._titles_at = time.monotonic()
        now = datetime.now().astimezone()
        try:
            events = await self.calendar.list_events(now - timedelta(days=1), now + timedelta(days=TITLES_DAYS), "", 50)
        except (ConnectorError, OSError) as exc:
            logger.info("calendar titles not read", error=type(exc).__name__)
            return
        self.event_titles |= {e.event.title for e in events if e.event.title.strip()}
        logger.info("calendar titles read", count=len(self.event_titles))

    def saw_titles(self, *titles: str) -> None:
        self.event_titles |= {t for t in titles if t.strip()}

    @property
    def scope(self) -> RunScope | None:
        """The newest open scope (one request at a time: the only one)."""
        return self.scopes[-1] if self.scopes else None

    def open(
        self, publish: Publisher, confirm: Confirmer, grant: Grant | None = None, step: Stepper | None = None,
        live: Liver | None = None, ask: Asker | None = None,
    ) -> RunScope:
        scope = RunScope(publish, confirm, grant=grant, step_fn=step, live_fn=live, ask_fn=ask)
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
