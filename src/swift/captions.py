"""Captions (Halo A6, 2026-11-18): the words Swift is saying, on the speaking pill.

Off by default; the owner's own words turn them on or off ("captions on", "turn captions off"), kept in the memory
store so they stay as set across restarts. While on, the ``speech`` frame carries what is being said (``spoken``).
Not built: turning them on by themselves when the sound is muted or Windows captions are on (Swift reads neither yet).
"""

from __future__ import annotations

import re
from typing import Any

KEY = "captions-on"
_LEAD = re.compile(r"^\s*(?:(?:hey|ok|okay)\s+)?(?:swift\b[\s,.:!-]*)?(?:please\s+)?", re.I)
_ON = re.compile(r"(?:turn |switch |show )?(?:the )?captions on|(?:turn on|switch on|show) (?:the )?captions", re.I)
_OFF = re.compile(r"(?:turn |switch )?(?:the )?captions off|(?:turn off|switch off|hide) (?:the )?captions|no (?:more )?captions", re.I)


def parse(text: str) -> str | None:
    """"captions_on" | "captions_off" for the owner's words, else None."""
    said = _LEAD.sub("", text).strip().rstrip(".!?")
    if _OFF.fullmatch(said):
        return "captions_off"
    if _ON.fullmatch(said):
        return "captions_on"
    return None


def is_on(store: Any) -> bool:
    return store is not None and store.get("memory", KEY) is not None


def spoken(store: Any, said: str) -> dict[str, str]:
    """The ``speech`` frame's caption: what is being said, only while captions are on."""
    return {"text": said} if said and is_on(store) else {}


def answer(store: Any, action: str, run: str) -> str:
    if store is None:
        return "I can't keep that setting here."
    if action == "captions_on":
        if not is_on(store):
            store.write("memory", "captions on", source="said", words="captions on", run=run, key=KEY)
        return "Captions are on: what I say shows by the orb. Say “captions off” to hide them."
    if is_on(store):
        store.forget("memory", KEY, run=run)
    return "Captions are off."
