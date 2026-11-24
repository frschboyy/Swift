"""History and pins: finished requests, kept to be reopened (owner, 2026-11-24; it replaces Halo A1's Earlier today).

``found``: "what did you find about …" said or typed shows that earlier answer again, as this request's answer. Only
answers since Swift started: none are kept on disk (run records are content-free), so after a restart it says so.

Requests that ended with an answer, newest first, sent with the stack as ``history``, and the ones the owner pinned
as ``pins``. They never count as waiting. Open brings the request back to the front with its answer, as a click on
its edge would; it is the same run, so nothing runs again, and a reply goes on with it. ``show``: "show my history".
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any

from swift.ipc.protocol import outbound
from swift.stack import StackItem

# Finished requests kept, with their answers, so Earlier today (and pins and History) can reopen them: in memory
# only, gone at a restart (owner, 2026-11-24). The session's own "gone" list keeps only its last few.
MAX_KEPT = 50


class Gone(deque):  # type: ignore[type-arg]
    """``session._gone``: the last few requests that ended and aren't shown ("stop the research one" just after it
    finished), and ``kept``: the last ``MAX_KEPT`` of them, for reopening."""

    def __init__(self, maxlen: int) -> None:
        super().__init__((), maxlen)
        self.kept: deque[Any] = deque(maxlen=MAX_KEPT)
        # Pinned by the owner, newest first: never dropped while pinned, whatever ``kept`` lets go (owner, 2026-11-24).
        self.pins: list[Any] = []

    def append(self, run: Any) -> None:
        super().append(run)
        if run not in self.kept:
            self.kept.append(run)


def _ended(session: Any) -> list[Any]:
    """Requests that ended with an answer and aren't in front, newest first (each once)."""
    seen: set[int] = set()
    runs = [r for r in [*session._runs, *getattr(session._gone, "kept", session._gone)]
            if r.answer is not None and not r.alive and r.ui_id and r is not session._focus and not (id(r) in seen or seen.add(id(r)))]
    return sorted(runs, key=lambda r: r.started_ms, reverse=True)


def _key(run: Any) -> str:
    return str(run.ui_id or run.row()["run_id"])


def _pins(session: Any) -> list[Any]:
    return getattr(session._gone, "pins", [])


def _failed(run: Any) -> bool:
    return bool(run.answer.type == "error" or run.answer.data.get("status") == "error")


def pins(session: Any) -> list[StackItem]:
    """The ``pins`` the shelf shows: the owner's words as the title, and a one-line hint from the answer."""
    out = []
    for run in _pins(session):
        lines = str(run.answer.data.get("summary") or "").strip().splitlines()
        hint = "Failed" if _failed(run) else lines[0] if lines else ""
        out.append(StackItem(f"pinned:{_key(run)}", "pinned", run.title or run.summary or "An answer",
                             hint[:57] + "…" if len(hint) > 60 else hint, run.started_ms, run.thread))
    return out


def extras(session: Any) -> dict[str, list[dict[str, Any]]]:
    """What the ``stack`` frame carries besides what waits: ``history`` and ``pins``, each only when there is one."""
    found = {"history": [i.as_message() for i in history(session)], "pins": [i.as_message() for i in pins(session)]}
    return {k: v for k, v in found.items() if v}


def history(session: Any) -> list[StackItem]:
    """History (owner, 2026-11-24; it replaces A1's Earlier today in the stack): every request that ended and can
    still be reopened, newest first, the reason its outcome. A pinned one is on the shelf instead: one place each."""
    out: list[StackItem] = []
    for run in _ended(session):
        if run in _pins(session):
            continue
        outcome = "failed" if _failed(run) else "stopped" if run.answer.data.get("status") == "cancelled" else "done"
        out.append(StackItem(f"recent:{run.ui_id}", "past", run.title or run.summary or "An answer", outcome,
                             run.started_ms, run.thread))
    return out


# "Show my history", "open history", "Swift, show me my history".
_HISTORY = re.compile(r"^\s*(?:(?:hey|ok|okay)\s+)?(?:swift\b[\s,.:!-]*)?(?:please\s+)?(?:show|open)(?: me)?(?: my)? history"
                      r"(?: please)?[.!?]*\s*$", re.I)


def show(session: Any, text: str) -> tuple[str, None] | None:
    """"Show my history": the History panel opens (Q5, 2026-11-24); what Swift says back, else None."""
    if not _HISTORY.match(text):
        return None
    session._background(session._raw_send(outbound("history", open=True)))
    return "Here's your history.", None


async def open_(session: Any, key: str, action: str) -> None:
    """Open: that request comes back to the front with its answer, the same run, so a reply goes on with it. Pin and
    Unpin: on or off the shelf (the card on screen pins itself this way too). Skip and End do nothing to an answer."""
    runs = [*_pins(session), *_ended(session), *session._runs]
    run = next((r for r in runs if r.ui_id == key or _key(r) == key), None)
    if run is None:
        return
    if action == "open":
        await session._bring(run)
    elif action in ("pin", "unpin") and run.answer is not None and not run.alive:
        if run in _pins(session):
            _pins(session).remove(run)
        if action == "pin":
            _pins(session).insert(0, run)
        await session._send_stack()


# "What did you find about tea?", "what have you found on the trains", "what did you find out about Leeds".
_FIND = re.compile(r"^\s*(?:(?:hey|ok|okay)\s+)?(?:swift\b[\s,.:!-]*)?(?:so,?\s+)?what (?:did|have) you (?:find|found)(?: out)?"
                   r" (?:about|on|for) (?P<q>.+?)[.!?]*\s*$", re.I)
_SMALL = frozenset({"the", "a", "an", "my", "of", "for", "to", "in", "on", "and", "about", "that", "this", "it"})


def found(session: Any, text: str) -> tuple[str, dict[str, Any] | None] | None:
    """A1: "what did you find about …": the earlier answer whose request matches best, again; else what Swift has."""
    m = _FIND.match(text)
    if m is None:
        return None
    asked = m.group("q").strip()
    words = {w for w in re.findall(r"[\w']+", asked.casefold()) if w not in _SMALL and len(w) > 1}
    best, score = None, 0
    for run in _ended(session):
        said = set(re.findall(r"[\w']+", f"{run.title} {run.words} {run.summary}".casefold()))
        hits = len(words & said)
        if hits > score:
            best, score = run, hits
    if best is None or best.answer is None or best.answer.type != "result":
        return f"I haven't found anything about “{asked}” since Swift started.", None
    data = best.answer.data
    return str(data.get("summary") or ""), data.get("details")
