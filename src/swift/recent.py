"""Earlier today in the stack (Halo A1, D12: with the stack list, 2026-11-18).

``found``: "what did you find about …" said or typed shows that earlier answer again, as this request's answer. Only
answers since Swift started: none are kept on disk (run records are content-free), so after a restart it says so.

Requests that ended today with an answer, newest first, listed under the waiting ones as ``recent`` items. They
never count as waiting (the overlay leaves them out of the pile and its badge). Open brings the request back to the
front with its answer, as a click on its edge would; it is the same run, so nothing runs again.
"""

from __future__ import annotations

import re
import time
from collections import deque
from typing import Any

from swift.stack import StackItem

MAX_RECENT = 6
# Finished requests kept, with their answers, so Earlier today (and pins and History) can reopen them: in memory
# only, gone at a restart (owner, 2026-11-24). The session's own "gone" list keeps only its last few.
MAX_KEPT = 50


class Gone(deque):  # type: ignore[type-arg]
    """``session._gone``: the last few requests that ended and aren't shown ("stop the research one" just after it
    finished), and ``kept``: the last ``MAX_KEPT`` of them, for reopening."""

    def __init__(self, maxlen: int) -> None:
        super().__init__((), maxlen)
        self.kept: deque[Any] = deque(maxlen=MAX_KEPT)

    def append(self, run: Any) -> None:
        super().append(run)
        if run not in self.kept:
            self.kept.append(run)


def _today_ms() -> int:
    t = time.localtime()
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000)


def _ended(session: Any) -> list[Any]:
    """Requests that ended with an answer and aren't in front, newest first (each once)."""
    seen: set[int] = set()
    runs = [r for r in [*session._runs, *getattr(session._gone, "kept", session._gone)]
            if r.answer is not None and not r.alive and r.ui_id and r is not session._focus and not (id(r) in seen or seen.add(id(r)))]
    return sorted(runs, key=lambda r: r.started_ms, reverse=True)


def items(session: Any) -> list[StackItem]:
    """The ``recent`` stack items: today's answers, newest first, at most MAX_RECENT."""
    today = _today_ms()
    out: list[StackItem] = []
    for run in _ended(session):
        if run.started_ms < today or len(out) >= MAX_RECENT:
            continue
        failed = run.answer.type == "error" or run.answer.data.get("status") == "error"
        out.append(StackItem(f"recent:{run.ui_id}", "recent", run.title or run.summary or "An answer",
                             "failed" if failed else "done", run.started_ms, run.thread))
    return out


async def open_(session: Any, key: str, action: str) -> None:
    """Open: that request comes back to the front with its answer. Skip and End do nothing to an answer."""
    run = next((r for r in _ended(session) if r.ui_id == key), None)
    if action == "open" and run is not None:
        await session._bring(run)


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
