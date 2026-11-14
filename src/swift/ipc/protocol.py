"""Overlay <-> backend WebSocket protocol (PLAN.md §3).

Every frame is a JSON object ``{"v": 1, "type": str, "ts": int, "data": {}}``.
Inbound frames (UI -> backend) are validated strictly: an unknown type, a
missing field or a wrong value raises ``ProtocolError`` and nothing is acted
on. Outbound frames are built by ``outbound()`` so tests and the server share
one encoder.

Run messages (``state``, ``step``, ``confirm.request``, ``result``, ``error``) carry
``agent``: ``{"id", "name"}`` of the provider doing the work, or null when Swift did
it itself. ``step`` also carries a normalized ``activity`` and ``subagent``;
``result`` may carry Swift's own ``note`` (ADR-008). ``error`` carries a ``title``,
``severity``, ``retry`` and the raw ``detail`` (``swift.failures``, ADR-009).

Workflows (ADR-010): ``artifact`` carries a typed, versioned snapshot of what a run is
working on (a draft, a recipient, a send status); ``view`` opens or closes the overlay's
detail view on one; ``run.voice`` is push-to-talk feedback on the working card. Inbound
``view`` is the Show / Back button, ``debug.say`` typed text treated as speech mid-run.
``confirm.request`` may carry ``artifact_id``: the card shows that artifact (the draft).

Several requests at once (ADR-013 phase B): ``runs`` names the request in front (``focus``,
its ``run_id``), the others as one-line ``rows``, and how many confirm cards wait behind the
one on screen. It is sent only while there is more than one. Inbound ``focus`` brings a row
to the front (a click on it, or the overlay's own card fading while others still run).
Inbound ``card.seen`` says a confirm card is drawn and visible, or hidden: its countdown runs
only while it is (ADR-015 §4.2).
The waiting stack (ADR-015 §9): outbound ``stack`` lists what waits for the owner (cards in line or
set aside, held cards, unfinished conversations); inbound ``stack.action`` opens, skips or ends
one. Inbound ``text`` is a request typed into the overlay (source ``typed``): routed like speech,
but it never approves a card.
The Capsule overlay (ADR-017): outbound ``speech`` says when Swift starts and stops talking (the
capsule's Speaking state, the question card's "I'll listen when I'm done"); inbound
``speech.stop`` stops it, inbound ``listen`` pauses or resumes listening (the tray). ``transcript``
carries ``typed`` (the head row's keyboard or mic), ``presence`` carries ``paused``.
The live view (ADR-017 §7): outbound ``live`` is one item of a request's live view (``kind``
"doing", "source", "note", "text" or "hint"), sent for every request, in front or not; outbound
``watch`` opens the view ("show me" while it runs). Inbound ``watch`` says it opened or closed,
``run.stop`` stops that request only, ``live.app`` brings the app it writes in to the front.
The dialogue (ADR-016 §5.1): outbound ``ask`` is Swift's question during a request (``ask_owner``):
open with its ``phase`` ("asking" while Swift says it, "listening" with ``seconds`` once the
microphone is open for the answer, "again" after an answer it couldn't work out), or closed.
Inbound ``ask.reply`` answers it from the card (an option clicked, or typed): never an approval.
Mirrored in overlay/src/protocol.ts.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 64 * 1024

STATES = ("idle", "listening", "transcribing", "working", "confirm", "result", "error")
SCENARIOS = ("happy", "confirm", "error", "long", "email", "research")
RESULT_STATUSES = ("done", "cancelled", "error", "rejected")
# Who started a run (ADR-019 N2), on results and rows: the owner ("asked"), or Swift on its own. Only
# "asked" and the due cards' "reminder" and "away" are sent today; the rest come with watchers and schedules.
ORIGINS = ("asked", "scheduled", "watching", "reminder", "noticed", "learned", "away")
ARTIFACT_KINDS = ("email_draft", "recipient", "send_status", "calendar_event", "text", "list", "table")
PHASES = ("resolving", "drafting", "confirming", "sending", "done", "failed")

# Inbound message types and their required fields: name -> (type, allowed values or None).
_INBOUND: dict[str, dict[str, tuple[type, tuple[str, ...] | None]]] = {
    "hello": {"token": (str, None), "client": (str, None)},
    "ptt": {"state": (str, ("down", "up"))},
    "cancel": {},
    # "Try again" on an error card: re-run the request that failed (ADR-009).
    "retry": {},
    "confirm.reply": {"request_id": (str, None), "decision": (str, ("approve", "reject"))},
    "debug.run": {"scenario": (str, SCENARIOS)},
    # Debug mode only: send typed text through the real executor, skipping mic and STT.
    "debug.ask": {"text": (str, None)},
    # The card's Show / Back button: same as saying "show me" / "hide that" (ADR-010).
    "view": {"action": (str, ("show", "hide"))},
    # Debug mode only: typed text handled as if spoken during a run ("show me").
    "debug.say": {"text": (str, None)},
    # A background request to the front (ADR-013 §3.1).
    "focus": {"run_id": (str, None)},
    # The overlay drew a confirm card and it is visible (or hid it): its countdown runs only then (ADR-015).
    "card.seen": {"request_id": (str, None), "visible": (bool, None)},
    # The waiting stack (ADR-015 §9): open (bring back / resume), skip (back to the stack), end (gone).
    "stack.action": {"id": (str, None), "action": (str, ("open", "skip", "end"))},
    # A request typed into the overlay; optional ``thread_id``: the conversation on screen it follows.
    "text": {"text": (str, None)},
    # Sent once when the overlay is fully up; ``backend_ms`` is optional.
    "ready": {"startup_ms": (int, None)},
    # The capsule's Stop (or Esc while Swift talks): Swift stops talking; nothing else changes (ADR-017).
    "speech.stop": {},
    # The tray's Pause listening / the capsule's Resume: the open microphone off or on (ADR-017).
    "listen": {"on": (bool, None)},
    # The live view of a request (ADR-017 §7): opened or closed (for the log), its Stop (that request
    # only), and its "Show in Word" (the app it writes in, to the front).
    "watch": {"run_id": (str, None), "open": (bool, None)},
    # Optional ``from``: "question" when it is the question card's "Stop request".
    "run.stop": {"run_id": (str, None)},
    "live.app": {"run_id": (str, None)},
    # The answer to Swift's question on the card (ADR-016 §5.1): an option clicked. Never approves a card.
    "ask.reply": {"ask_id": (str, None), "text": (str, None)},
    # The tray's "Clear saved recordings" and "Improve speech recognition" (audit B-06).
    "recordings": {"action": (str, ("clear", "improve"))},
    # The overlay drew a due card (a timer, alarm or reminder): only then is it taken off the schedule
    # (seams audit O-08: an overlay that drops it, behind a request in front, must not lose it).
    "due.shown": {"run_id": (str, None)},
}

OUTBOUND_TYPES = frozenset(
    {"hello.ok", "state", "level", "transcript", "step", "confirm.request", "confirm.voice", "result", "error",
     "artifact", "view", "run.voice", "followup", "presence", "confirm.hold", "resume.offer",
     "runs", "stack", "heard", "speech", "live", "watch", "ask"}
)


class ProtocolError(ValueError):
    """An inbound frame that must be rejected."""


@dataclass(frozen=True)
class Message:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: int = 0


def now_ms() -> int:
    return int(time.time() * 1000)


def decode(raw: str | bytes) -> Message:
    """Parse and validate one inbound frame."""
    if isinstance(raw, bytes):
        raise ProtocolError("binary frames are not accepted")
    if len(raw.encode("utf-8")) > MAX_FRAME_BYTES:
        raise ProtocolError("frame too large")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {exc.msg}") from None
    if not isinstance(obj, dict):
        raise ProtocolError("frame must be a JSON object")
    if obj.get("v") != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version {obj.get('v')!r}")

    kind = obj.get("type")
    if not isinstance(kind, str) or kind not in _INBOUND:
        raise ProtocolError(f"unknown message type {kind!r}")

    data = obj.get("data", {})
    if not isinstance(data, dict):
        raise ProtocolError("data must be a JSON object")
    for name, (typ, allowed) in _INBOUND[kind].items():
        if name not in data:
            raise ProtocolError(f"{kind}: missing field {name!r}")
        value = data[name]
        if not isinstance(value, typ):
            raise ProtocolError(f"{kind}: field {name!r} must be {typ.__name__}")
        if allowed is not None and value not in allowed:
            raise ProtocolError(f"{kind}: field {name!r} must be one of {', '.join(allowed)}")

    ts = obj.get("ts", 0)
    return Message(kind, data, ts if isinstance(ts, int) else 0)


def encode(msg: Message) -> str:
    return json.dumps(
        {"v": PROTOCOL_VERSION, "type": msg.type, "ts": msg.ts or now_ms(), "data": msg.data},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def outbound(msg_type: str, /, **data: Any) -> Message:
    """Build a backend -> UI message. Unknown types are a programming error."""
    if msg_type not in OUTBOUND_TYPES:
        raise ValueError(f"not an outbound message type: {msg_type}")
    if msg_type == "state" and data.get("state") not in STATES:
        raise ValueError(f"unknown state {data.get('state')!r}")
    if msg_type == "artifact" and (data.get("kind") not in ARTIFACT_KINDS or data.get("phase") not in PHASES):
        raise ValueError(f"bad artifact kind or phase: {data.get('kind')!r}, {data.get('phase')!r}")
    if msg_type == "result" and data.get("origin", "asked") not in ORIGINS:
        raise ValueError(f"unknown origin {data.get('origin')!r}")
    return Message(msg_type, data, now_ms())
