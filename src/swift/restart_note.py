"""The note a request carries when the owner's change of mind starts it again (session._run, ADR-014 §7)."""

from __future__ import annotations

from swift.parked import _clip

ANSWER_CLIP = 300


def restart_note(change: str, status: str, summary: str) -> str:
    head = f"[The user changed their mind while this was running: “{change}”. Do the request with that change. "
    if status == "done":  # it had finished while closing: its answer is discarded, not part-way work (EX-01)
        return head + f"A previous attempt finished with: “{_clip(summary, ANSWER_CLIP)}”. Change it to match; don't redo what is already done.]"
    return head + "A previous attempt was stopped part-way; check before redoing anything.]"
