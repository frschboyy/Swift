"""A10 "What can I say?" and A11 next-step chips (Halo Explore, off by default): what a card accepts.

The phrases here are not invented: each one is run through the real grammar in ``tests/unit/test_hints.py``
(``rules.route_midrun`` for what a card in front takes, ``rules.route`` for a request). ``ok`` marks a phrase
that ends in an OK card on screen, never in something done by itself. Sent to the overlay in ``hello.ok``
only while ``explore.what_can_i_say`` or ``explore.next_steps`` is on; the overlay learns which verbs the owner
does by hand (3 times) and only then offers them.
"""

from __future__ import annotations

from typing import Any

# What a card in front accepts, by card: (phrase, ok). Checked against ``rules.route_midrun``.
CARD_PHRASES: dict[str, list[tuple[str, bool]]] = {
    "confirm": [("approve", False), ("reject", False), ("show me", False)],
    "done": [("show me again", False), ("undo that", False)],
}

# Swift's own verbs the owner may do by hand first: ``learn`` is the click that counts (the overlay's), ``say``
# the words that do the same, ``ok`` whether they ask for an OK. Checked against ``rules.route``.
VERBS: list[dict[str, Any]] = [
    {"learn": "copy", "label": "Put it in Word", "say": "put that in Word", "ok": True},
    {"learn": "show", "label": "Show me again", "say": "show me again", "ok": False},
]


def for_overlay() -> dict[str, Any]:
    return {"say": {k: [{"text": t, "ok": ok} for t, ok in v] for k, v in CARD_PHRASES.items()}, "verbs": VERBS}
