"""ADR-019 §8.3: "Try again from step N" on a request's Failed card (Halo B8, 2026-11-18).

The overlay's Failed card keeps what the run did before it failed (its steps) and offers "Try again from step N",
N the step it failed on. The retry is the same request in the same thread, as before; ``note`` adds Swift's own
line to the worker's context (never to the owner's words on the card) saying where to pick up. Nothing is skipped
by Swift: the worker still asks for every card it needs.
"""

from __future__ import annotations

from typing import Any

# The most steps a Failed card shows (the overlay keeps the last MAX_STEPS too): a larger N is not believed.
MAX_STEP = 50


def resume_from(data: dict[str, Any]) -> int | None:
    """The ``retry`` frame's ``from_step``, when it's a step past the first; else None (a plain "Try again")."""
    n = data.get("from_step")
    return n if isinstance(n, int) and not isinstance(n, bool) and 1 < n <= MAX_STEP else None


def note(record: dict[str, Any]) -> str:
    """Swift's line in the worker's context for a retry from step N; "" for any other request."""
    n = record.get("resume_from")
    if not isinstance(n, int) or record.get("source") != "retry":
        return ""
    done = "Step 1" if n == 2 else f"Steps 1 to {n - 1}"
    return (f"Swift's note: the owner is trying this again from step {n}. {done} of the last attempt finished before "
            f"it failed; pick up from step {n}, and redo an earlier step only if it has to be.")
