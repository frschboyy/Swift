"""Earlier today in the stack (Halo A1, D12: with the stack list, 2026-11-18).

Requests that ended today with an answer, newest first, listed under the waiting ones as ``recent`` items. They
never count as waiting (the overlay leaves them out of the pile and its badge). Open brings the request back to the
front with its answer, as a click on its edge would; it is the same run, so nothing runs again.
"""

from __future__ import annotations

import time
from typing import Any

from swift.stack import StackItem

MAX_RECENT = 6


def _today_ms() -> int:
    t = time.localtime()
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000)


def _ended(session: Any) -> list[Any]:
    """Requests that ended with an answer and aren't in front, newest first (each once)."""
    seen: set[int] = set()
    runs = [r for r in [*session._runs, *session._gone]
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
