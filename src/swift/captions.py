"""Captions (Halo A6, 2026-11-18): the words Swift is saying, on the speaking pill.

The owner's own words turn them on or off ("captions on", "turn captions off"), kept in the memory store so they stay
as set across restarts. Until the owner has said either, they follow the PC: on while the sound is muted or Windows
Live captions is running (``refresh``, each lifecycle tick and on each overlay), else off. While on, the ``speech``
frame carries what is being said (``spoken``).
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from typing import Any

from swift.system.control import SystemUnavailable

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


# What the PC said last (``refresh``): muted, or Windows Live captions running. Used only while the owner hasn't chosen.
_auto = False


def setting(store: Any) -> str | None:
    """"on" or "off" as the owner said it, or None: they haven't (the PC decides)."""
    record = store.get("memory", KEY) if store is not None else None
    if record is None:
        return None
    return "off" if "off" in record.text else "on"


def is_on(store: Any) -> bool:
    chosen = setting(store)
    return chosen == "on" or (chosen is None and _auto)


async def refresh(control: Any, live_captions: Any = None) -> None:
    """Read the PC: the output muted (``control.get_mute``), or Windows Live captions running. Never raises."""
    global _auto
    muted = False
    if control is not None:
        try:
            muted = bool(await control.get_mute())
        except (SystemUnavailable, OSError):  # a PC Swift can't read: as if not muted
            muted = False
    # No system lane (a test, a fake): nothing to read on the PC.
    running = await asyncio.to_thread(live_captions or _live_captions_running) if control is not None or live_captions else False
    _auto = muted or running


def _live_captions_running() -> bool:
    """Windows 11 Live captions (LiveCaptions.exe) is running. Read only; False when it can't be told."""
    if sys.platform != "win32":
        return False
    try:
        tasklist = os.path.join(os.environ.get("SystemRoot", "C:/Windows"), "System32", "tasklist.exe")
        out = subprocess.run([tasklist, "/FI", "IMAGENAME eq LiveCaptions.exe", "/NH", "/FO", "CSV"],
                             capture_output=True, text=True, timeout=5, creationflags=0x08000000)  # CREATE_NO_WINDOW
    except (OSError, subprocess.SubprocessError):
        return False
    return "livecaptions.exe" in out.stdout.casefold()


def spoken(store: Any, said: str) -> dict[str, str]:
    """The ``speech`` frame's caption: what is being said, only while captions are on."""
    return {"text": said} if said and is_on(store) else {}


def answer(store: Any, action: str, run: str) -> str:
    if store is None:
        return "I can't keep that setting here."
    if action == "captions_on":
        if setting(store) != "on":
            store.write("memory", "captions on", source="said", words="captions on", run=run, key=KEY)
        return "Captions are on: what I say shows by the orb. Say “captions off” to hide them."
    if setting(store) != "off":  # kept as said, so a muted PC doesn't turn them back on
        store.write("memory", "captions off", source="said", words="captions off", run=run, key=KEY)
    return "Captions are off."
