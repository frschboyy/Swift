"""Whether the owner is here (ADR-014 §3): here, idle, or away, and when they come back.

Signals Windows already gives, polled every few seconds (no window, no new permissions):

- **locked**: the session's own lock flag (``WTSQuerySessionInformation``), or the input desktop
  can't be opened (``OpenInputDesktop``: another secure desktop is up). The flag is the one that
  lasts: on the owner's PC the input desktop is closed for only about half a second as the screen
  locks, then opens again behind the lock screen (measured 2026-11-12, owner check 232);
- **asleep**: a poll that comes far later than scheduled means the machine was suspended;
- **idle time**: seconds since the last keyboard or mouse input (``GetLastInputInfo``).

``PresenceMonitor`` turns them into a state and reports each change with its reason. Away
because the screen is locked or the PC slept turns hands-free listening off (threat model
T7); away only because nobody touched the keyboard for a while does not: that's when the
owner may be talking to Swift from across the room.
"""

from __future__ import annotations

import asyncio
import ctypes
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from loguru import logger

State = Literal["here", "idle", "away"]
Reason = Literal["input", "idle", "locked", "asleep", "unlocked", "resumed", "start", "swift"]

IDLE_S = 10 * 60
AWAY_S = 30 * 60
POLL_S = 2.0
# While locked or asleep, poll faster: the unlock is noticed within half a second, not two
# (owner check 13: about 7-10 s from unlocking until Swift heard "hey Swift").
AWAY_POLL_S = 0.5
# A poll this much later than scheduled: the machine was asleep in between.
SLEEP_GAP_S = 15.0


class Probe(Protocol):
    def locked(self) -> bool: ...

    def idle_s(self) -> float: ...


@dataclass(frozen=True)
class Change:
    old: State
    new: State
    reason: Reason
    # True when coming back from away: warm up, reopen the microphone.
    returned: bool

    @property
    def locked_or_asleep(self) -> bool:
        return self.new == "away" and self.reason in ("locked", "asleep")


class PresenceMonitor:
    def __init__(
        self,
        probe: Probe,
        on_change: Callable[[Change], None],
        *,
        idle_s: float = IDLE_S,
        away_s: float = AWAY_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.probe = probe
        self.on_change = on_change
        self.idle_after = idle_s
        self.away_after = away_s
        self.clock = clock
        self.state: State = "here"
        self.reason: Reason = "start"
        # When the current state started (clock time), e.g. how long the owner has been away.
        self.since = clock()
        self._last_poll: float | None = None
        # The last time the owner talked to Swift (hotkey or wake phrase): input, as far as idle goes.
        self._touched: float | None = None

    @property
    def listening_allowed(self) -> bool:
        """Hands-free listening is off while the screen is locked or the PC is asleep (T7)."""
        return not (self.state == "away" and self.reason in ("locked", "asleep"))

    def away_for(self) -> float:
        return self.clock() - self.since if self.state == "away" else 0.0

    def touch(self) -> Change | None:
        """The owner just talked to Swift: they're here, even without touching the keyboard."""
        now = self.clock()
        self._touched = now
        if self.state == "away" and self.reason in ("locked", "asleep"):
            return None  # the next poll says when they're back
        return self._set("here", "swift", now)

    def poll(self) -> Change | None:
        now = self.clock()
        slept = self._last_poll is not None and now - self._last_poll > POLL_S + SLEEP_GAP_S
        self._last_poll = now
        try:
            locked, idle = self.probe.locked(), self.probe.idle_s()
        except Exception as exc:  # noqa: BLE001 - a failed probe keeps the last state
            logger.warning("presence probe failed", error=str(exc))
            return None
        if self._touched is not None:
            idle = min(idle, now - self._touched)
        if slept and self.state != "away":
            # Suspended between two polls: report the time away, then whatever is true now.
            self._set("away", "asleep", now)
        if locked:
            return self._set("away", "locked", now)
        if idle >= self.away_after:
            return self._set("away", "idle", now)
        if idle >= self.idle_after:
            return self._set("idle", "idle", now)
        back: Reason = "unlocked" if self.reason == "locked" else "resumed" if self.reason == "asleep" else "input"
        return self._set("here", back, now)

    def _set(self, state: State, reason: Reason, now: float) -> Change | None:
        if state == self.state and (state != "away" or reason == self.reason or reason == "idle"):
            return None
        change = Change(self.state, state, reason, returned=self.state == "away" and state != "away")
        self.state, self.reason, self.since = state, reason, now
        logger.info("presence", state=state, reason=reason)
        self.on_change(change)
        return change

    async def run(self, every_s: float = POLL_S, away_every_s: float = AWAY_POLL_S) -> None:
        while True:
            self.poll()
            await asyncio.sleep(away_every_s if not self.listening_allowed else every_s)


class WindowsProbe:
    """The real signals, through user32 (Windows only)."""

    DESKTOP_SWITCHDESKTOP = 0x0100

    WTS_CURRENT_SESSION = 0xFFFFFFFF
    WTS_SESSION_INFO_EX = 25
    # WTSINFOEXW: Level (4 bytes, padded to 8), then SessionId, SessionState, SessionFlags (4 bytes each).
    SESSION_FLAGS_AT = 16
    WTS_SESSIONSTATE_LOCK = 0

    def __init__(self) -> None:
        self._user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        self._kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        self._kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        self._wts = ctypes.windll.wtsapi32  # type: ignore[attr-defined]
        self._wts.WTSQuerySessionInformationW.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint),
        ]
        self._wts.WTSQuerySessionInformationW.restype = ctypes.c_int
        self._wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]

    def locked(self) -> bool:
        return self._session_locked() or not self._input_desktop_open()

    def _session_locked(self) -> bool:
        """The session's lock flag: true for as long as the screen is locked. False if Windows won't say."""
        info, size = ctypes.c_void_p(), ctypes.c_uint()
        if not self._wts.WTSQuerySessionInformationW(
            None, self.WTS_CURRENT_SESSION, self.WTS_SESSION_INFO_EX, ctypes.byref(info), ctypes.byref(size)
        ):
            return False
        try:
            if size.value < self.SESSION_FLAGS_AT + 4:
                return False
            return ctypes.c_int32.from_address(info.value + self.SESSION_FLAGS_AT).value == self.WTS_SESSIONSTATE_LOCK
        finally:
            self._wts.WTSFreeMemory(info)

    def _input_desktop_open(self) -> bool:
        desktop = self._user32.OpenInputDesktop(0, False, self.DESKTOP_SWITCHDESKTOP)
        if not desktop:
            return False  # a secure desktop (the lock screen's first moment, a sign-in prompt) isn't ours to open
        self._user32.CloseDesktop(desktop)
        return True

    def idle_s(self) -> float:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not self._user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        # dwTime is the 32-bit tick count of the last input; compare in 32 bits.
        now = self._kernel32.GetTickCount64() & 0xFFFFFFFF
        return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0
