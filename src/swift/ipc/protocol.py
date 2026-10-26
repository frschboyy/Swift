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
SCENARIOS = ("happy", "confirm", "error", "long", "email")
RESULT_STATUSES = ("done", "cancelled", "error", "rejected")
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
    # Sent once when the overlay is fully up; ``backend_ms`` is optional.
    "ready": {"startup_ms": (int, None)},
}

OUTBOUND_TYPES = frozenset(
    {"hello.ok", "state", "level", "transcript", "step", "confirm.request", "confirm.voice", "result", "error",
     "artifact", "view", "run.voice", "followup"}
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
    return Message(msg_type, data, now_ms())
