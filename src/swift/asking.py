""""Ask me about everything" (the modes study §3, decided 2026-11-14; CLAUDE.md: it raises level 0 to 1, except reads
in the read folders and volume).

One setting, kept in the memory store from the owner's own words (``source="said"``), so it stays on until the owner
turns it off. While it's on: the gateway treats ``reversible`` like ``confirm`` (volume excepted), the system lane asks
before its own reversible changes (volume and reads excepted), and no step card covers a command, so every command
asks. It only ever adds questions, so typed words may turn it on or off. Nothing here approves anything.
"""

from __future__ import annotations

import re
from typing import Any

# The memory record that holds it (not a fact about the owner: "what do you know about me" leaves it out).
KEY = "asking-everything"
NOTE = "Asking because you said: ask me about everything."
# Intents and kinds that never ask because of it: volume (asking about it would make the switch unusable) and reads.
EXEMPT = frozenset({"volume.set", "volume.step", "volume.get", "mute", "info", "list", "timer.left", "radio.get"})

_LEAD = re.compile(r"^\s*(?:(?:hey|ok|okay)\s+)?(?:swift\b[\s,.:!-]*)?(?:please\s+)?", re.I)
_ON = re.compile(r"(?:(?:from now on|for now),? )?(?:always )?ask me (?:about|before) (?:everything|you do anything|anything you do)"
                 r"(?:,? from now on)?", re.I)
_OFF = re.compile(r"(?:you can )?stop asking(?: me)? about everything|(?:you )?(?:don't|do not) (?:need to )?ask(?: me)? about everything"
                  r"|stop asking me before (?:everything|you do anything)", re.I)


def parse(text: str) -> str | None:
    """"ask_all" | "ask_less" for the owner's words, else None."""
    said = _LEAD.sub("", text).strip().rstrip(".!?")
    if _OFF.fullmatch(said):
        return "ask_less"
    if _ON.fullmatch(said):
        return "ask_all"
    return None


def is_on(store: Any) -> bool:
    return store is not None and store.get("memory", KEY) is not None


async def from_tray(session: Any) -> None:
    """The tray's "Stop asking about everything" (``asking`` with on false; a tray never turns it on): off, then the
    tray's status says so (``presence``)."""
    answer(session.memories, "ask_less", "", "tray")
    if session.on_ready is not None:
        await session.on_ready()


def answer(store: Any, action: str, words: str, run: str) -> str:
    """Turn it on or off from the owner's words, and say so."""
    if store is None:
        return "I can't keep that setting here."
    if action == "ask_all":
        if not is_on(store):
            store.write("memory", "ask me about everything", source="said", words="ask me about everything", run=run, key=KEY)
        return "Okay. I'll ask before I do anything, until you say “stop asking about everything”."
    if is_on(store):
        store.forget("memory", KEY, run=run)
        return "Okay. I'll only ask when it matters again."
    return "I'm not asking about everything now."
