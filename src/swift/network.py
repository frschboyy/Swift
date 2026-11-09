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
import threading

# Calm and short (owner, 2026-11-09: the offline list was too intrusive). A request that needs the internet
# gets one sentence; the list comes only when asked ("what works offline"), five lines, no examples.
OFFLINE_SAID = "I'm offline, so this waits for the internet. Quick commands like timers, volume and Wi-Fi still work."
OFFLINE_HELP = "Without the internet I can still do these:"
OFFLINE_ITEMS = (
    "Wi-Fi, Bluetooth and airplane mode",
    "Timers, alarms and reminders",
    "Volume, music, brightness and dark mode",
    "Lock, screenshots, settings pages and your apps",
    "The time, the date and sums",
)
OFFLINE_NOT = "Research, writing, email and your calendar wait for the internet."


# Windows' Network List Manager (its CLSID): what Windows' own connectivity check found, kept by Windows.
_NLM = "{DCB00C01-570F-4A9B-8D69-199FDBA5723B}"
_local = threading.local()


def online() -> bool | None:
    """Whether this PC reaches the internet: True, False, or None when it can't tell.

    ``InternetGetConnectedState`` first: False there is certain (no adapter up). True only means "has a
    connection", also for a LAN without internet, a captive portal or a virtual adapter, so then the
    Network List Manager is asked, which reports what Windows' own connectivity check found. Both are
    local: no network call (seams audit R-02)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        flags = wintypes.DWORD()
        connected = bool(ctypes.windll.wininet.InternetGetConnectedState(ctypes.byref(flags), 0))  # type: ignore[attr-defined]
    except Exception:  # an odd Windows: don't stand in the way
        return None
    if not connected:
        return False
    reaches = _internet_by_nlm()
    return connected if reaches is None else reaches


def _internet_by_nlm() -> bool | None:
    """The Network List Manager's ``IsConnectedToInternet`` (one COM object per thread), or None."""
    try:
        manager = getattr(_local, "nlm", None)
        if manager is None:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            manager = _local.nlm = win32com.client.Dispatch(_NLM)
        return bool(manager.IsConnectedToInternet)
    except Exception:  # no pywin32, COM refused: the fast answer stands
        return None
