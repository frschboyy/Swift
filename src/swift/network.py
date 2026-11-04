"""Whether this PC can reach the internet, and what Swift still does without it.

``online()`` asks Windows (``InternetGetConnectedState``): no network call, no delay. True or
False when Windows knows, None when it can't say (another OS, or the call failed), and then
Swift carries on as if online. With Wi-Fi off and no cable it is False at once, so a request
that needs the agent is answered here instead of waiting on retries (owner checks 2026-11-04:
"Turn it back on" sat 45 s on "Connection hiccup, retrying").

``OFFLINE_ITEMS`` is what still works offline: the system lane, the fast lane and the local
answers, none of which use the network (ADR-016 §3).
"""

from __future__ import annotations

import sys

OFFLINE_SAID = "I'm offline, so I can't do that until the internet is back."
OFFLINE_HELP = "Without the internet I can still do these:"
OFFLINE_ITEMS = (
    "Wi-Fi, Bluetooth and airplane mode: “turn on the Wi-Fi”, “turn it back on”",
    "Timers, alarms and reminders: “set a timer for ten minutes”, “remind me to call Sam at five”",
    "Volume and music: “louder”, “mute”, “next song”, “pause the music”",
    "Brightness and dark mode: “brightness to 60”, “turn on dark mode”",
    "Lock the PC, show the desktop, take a screenshot",
    "Battery, disk space, memory and how long the PC has been on",
    "Windows settings pages: “open Bluetooth settings”",
    "The time and date, and sums: “what day is it a week from today?”, “what's 15% of 80?”",
    "Opening your apps and folders by name",
    "“Undo that” for the last change",
)
OFFLINE_NOT = "Questions, research, writing, email and your calendar need the internet."


def online() -> bool | None:
    """Whether Windows has an internet connection: True, False, or None when it can't tell."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        flags = wintypes.DWORD()
        return bool(ctypes.windll.wininet.InternetGetConnectedState(ctypes.byref(flags), 0))  # type: ignore[attr-defined]
    except Exception:  # an odd Windows: don't stand in the way
        return None
