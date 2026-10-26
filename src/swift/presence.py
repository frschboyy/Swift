"""Whether the owner is here (ADR-014 §3): here, idle, or away, and when they come back.

Signals Windows already gives, polled every few seconds (no window, no new permissions):

- **locked**: the input desktop can't be opened while the lock screen (or another secure
  desktop) is up (``OpenInputDesktop``);
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
Reason = Literal["input", "idle", "locked", "asleep", "unlocked", "resumed", "start"]

IDLE_S = 10 * 60
AWAY_S = 30 * 60
POLL_S = 2.0
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

    @property
    def listening_allowed(self) -> bool:
        """Hands-free listening is off while the screen is locked or the PC is asleep (T7)."""
        return not (self.state == "away" and self.reason in ("locked", "asleep"))

    def away_for(self) -> float:
        return self.clock() - self.since if self.state == "away" else 0.0

    def poll(self) -> Change | None:
        now = self.clock()
        slept = self._last_poll is not None and now - self._last_poll > POLL_S + SLEEP_GAP_S
        self._last_poll = now
        try:
            locked, idle = self.probe.locked(), self.probe.idle_s()
        except Exception as exc:  # noqa: BLE001 - a failed probe keeps the last state
            logger.warning("presence probe failed", error=str(exc))
            return None
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

    async def run(self, every_s: float = POLL_S) -> None:
        while True:
            self.poll()
            await asyncio.sleep(every_s)


class WindowsProbe:
    """The real signals, through user32 (Windows only)."""

    DESKTOP_SWITCHDESKTOP = 0x0100

    def __init__(self) -> None:
        self._user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        self._kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        self._kernel32.GetTickCount64.restype = ctypes.c_ulonglong

    def locked(self) -> bool:
        desktop = self._user32.OpenInputDesktop(0, False, self.DESKTOP_SWITCHDESKTOP)
        if not desktop:
            return True  # the lock screen's desktop isn't ours to open
        self._user32.CloseDesktop(desktop)
        return False

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
