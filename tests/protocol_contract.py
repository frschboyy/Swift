"""The overlay <-> backend contract (seams audit 2026-11, layer A).

``tests/fixtures/protocol/frames.json`` holds examples of every frame each side sends. From them:

- ``check_frame``: does a frame the backend sends fit the examples (no field the examples lack, no
  value of a kind they never have, nothing missing that every example has)? ``tests/conftest.py``
  runs it on every frame every ``Session`` sends in the test suite.
- ``render_ts``: the same examples as TypeScript (``overlay/src/protocol.examples.ts``), so ``tsc``
  checks each against ``protocol.ts``, excess fields included, and that every type has one.
- ``Dialogue``: invariants over a sequence of frames in both directions (one card per request at a
  time; every question opened is closed).

So a field the backend adds must be added to an example, and then to the overlay's types, or a test fails.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "tests" / "fixtures" / "protocol" / "frames.json"
TS_EXAMPLES = ROOT / "overlay" / "src" / "protocol.examples.ts"

# Values whose inside the examples don't pin down: a workflow artifact's data (one shape per kind,
# typed in protocol.ts), an answer's details, the hotkeys from settings.
OPEN = frozenset({"artifact.data", "result.details", "hello.ok.hotkeys"})


def load() -> dict[str, list[dict[str, Any]]]:
    return json.loads(FRAMES.read_text(encoding="utf-8"))


def kind_of(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "str"
    if isinstance(v, (list, tuple)):
        return "list"
    if isinstance(v, dict):
        return "dict"
    return type(v).__name__  # not JSON: always a violation


@dataclass
class _Node:
    kinds: set[str] = field(default_factory=set)
    keys: dict[str, _Node] = field(default_factory=dict)
    required: set[str] | None = None
    item: _Node | None = None


def _learn(node: _Node, value: Any, path: str) -> None:
    node.kinds.add(kind_of(value))
    if path in OPEN:
        return
    if isinstance(value, dict):
        node.required = set(value) if node.required is None else node.required & set(value)
        for k, v in value.items():
            _learn(node.keys.setdefault(k, _Node()), v, f"{path}.{k}")
    elif isinstance(value, list):
        for v in value:
            node.item = node.item or _Node()
            _learn(node.item, v, f"{path}[]")


def _check(node: _Node, value: Any, path: str, out: list[str]) -> None:
    kind = kind_of(value)
    if kind not in node.kinds:
        out.append(f"{path}: a {kind}, but the examples have {'/'.join(sorted(node.kinds))}")
        return
    if path in OPEN:
        return
    if isinstance(value, dict):
        for k in sorted((node.required or set()) - set(value)):
            out.append(f"{path}.{k}: missing (every example has it)")
        for k, v in value.items():
            if k not in node.keys:
                out.append(f"{path}.{k}: not in any example (add it there, then to protocol.ts)")
            else:
                _check(node.keys[k], v, f"{path}.{k}", out)
    elif isinstance(value, (list, tuple)) and node.item is not None:
        for v in value:
            _check(node.item, v, f"{path}[]", out)


_shapes: dict[str, dict[str, _Node]] | None = None


def shapes() -> dict[str, dict[str, _Node]]:
    global _shapes
    if _shapes is None:
        _shapes = {}
        for direction, frames in load().items():
            if direction.startswith("_"):
                continue
            by_type = _shapes.setdefault(direction, {})
            for f in frames:
                _learn(by_type.setdefault(f["type"], _Node()), f["data"], f["type"])
    return _shapes


def check_frame(msg_type: str, data: dict[str, Any], direction: str = "to_overlay") -> list[str]:
    """What is wrong with this frame, against the examples (empty: it fits)."""
    node = shapes()[direction].get(msg_type)
    if node is None:
        return [f"{msg_type}: no example of this type in {FRAMES.name}"]
    out: list[str] = []
    _check(node, data, msg_type, out)
    return out


def render_ts() -> str:
    frames = load()

    def block(name: str, kind: str) -> str:
        body = ",\n".join("  " + json.dumps(f, ensure_ascii=False) for f in frames[name])
        return f"export const {name.upper()} = [\n{body},\n] satisfies {kind}[];\n"

    return (
        "// Generated from tests/fixtures/protocol/frames.json (seams audit 2026-11, layer A). Don't edit:\n"
        "// change the JSON, then run `uv run python tests/protocol_contract.py`. tsc checks every example\n"
        "// against protocol.ts, and that every message type has one. Never imported by the app.\n"
        'import type { Inbound, Outbound } from "./protocol";\n\n'
        + block("to_overlay", "Inbound") + "\n" + block("to_backend", "Outbound") + "\n"
        "type Missing<All extends { type: string }, Given extends { type: string }> = Exclude<All[\"type\"], Given[\"type\"]>;\n"
        "// A type here means a message type with no example: add one to frames.json.\n"
        "export const EVERY_INBOUND_TYPE: [Missing<Inbound, (typeof TO_OVERLAY)[number]>] extends [never] ? true : never = true;\n"
        "export const EVERY_OUTBOUND_TYPE: [Missing<Outbound, (typeof TO_BACKEND)[number]>] extends [never] ? true : never = true;\n"
    )


@dataclass
class Dialogue:
    """Invariants over one session's frames, both ways (seams audit layer A):

    - a request has at most one confirm card open at a time (O-07): a second ``confirm.request`` for
      the same request before the first is answered, expired or the request ended;
    - every question opened (``ask`` open) is closed (``ask`` not open) by the end (T-03).
    """

    open_cards: dict[str, str] = field(default_factory=dict)  # run_id -> request_id
    open_asks: dict[str, str] = field(default_factory=dict)  # ask_id -> run_id
    problems: list[str] = field(default_factory=list)

    def sent(self, msg_type: str, data: dict[str, Any]) -> None:
        """A frame to the overlay."""
        if msg_type == "confirm.request":
            run, req = str(data.get("run_id")), str(data.get("request_id"))
            if (other := self.open_cards.get(run)) not in (None, req):
                self.problems.append(f"two cards open for {run}: {other} and {req}")
            self.open_cards[run] = req
        elif msg_type == "result":
            self.open_cards.pop(str(data.get("run_id")), None)
        elif msg_type == "state" and data.get("state") != "confirm":
            self.open_cards.clear()  # the overlay drops its card on any other stage (presenter.ts setStage)
        elif msg_type == "ask":
            if data.get("open"):
                self.open_asks[str(data["ask_id"])] = str(data.get("run_id"))
            else:
                self.open_asks.pop(str(data["ask_id"]), None)

    def received(self, msg_type: str, data: dict[str, Any]) -> None:
        """A frame from the overlay."""
        if msg_type == "confirm.reply":
            req = data.get("request_id")
            for run, open_req in list(self.open_cards.items()):
                if open_req == req:
                    del self.open_cards[run]

    def card_done(self, request_id: str) -> None:
        """A card answered by voice, or expired into the stack (seen from the session, not the wire)."""
        self.received("confirm.reply", {"request_id": request_id})

    def finished(self) -> list[str]:
        """The problems, once the session is done: also every question still open."""
        return self.problems + [f"question {a} (request {r}) opened and never closed"
                                for a, r in self.open_asks.items()]


if __name__ == "__main__":
    TS_EXAMPLES.write_text(render_ts(), encoding="utf-8", newline="\n")
    print(f"wrote {TS_EXAMPLES.relative_to(ROOT)}")
