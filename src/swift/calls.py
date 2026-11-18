"""Hold during calls (Halo A3, ``explore.hold_during_calls``).

While the owner is on a call or presenting, Swift holds what it would show or say: the same hold as when the owner is
away (``Session.hold_cards``: confirm cards hidden and their countdowns stopped, speech and due notices kept back). It
never answers for the owner and loosens nothing: a held card can't be approved, because it isn't on screen. After the
call it is released, and what came due meanwhile is shown (``notify_due``).

The detector follows the spike (``spikes/calls/REPORT.md``; measured idle only, owner check pending):

- **a call**: a call app (Teams, Zoom, a browser...) that is running has the microphone open
  (ConsentStore ``LastUsedTimeStop == 0``); Swift's own microphone and apps that aren't call apps don't count, and a
  key left behind by an app that isn't running doesn't either;
- **presenting**: Windows' own state (``SHQueryUserNotificationState``) says busy, full screen or presentation mode.

Holding is safe, showing is not, so a doubtful reading holds. Plain window shares are not detected on their own.
"""

from __future__ import annotations

import asyncio
import ctypes
import sys
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol

from loguru import logger

from swift.ipc.protocol import outbound

POLL_S = 2.0
# The key closes between an app's prompts: a call is over only after this long without it.
OUT_S = 5.0
# A key opened longer ago than this is left behind by a crash, not a call (review 7ab2b70 finding 3).
STALE_S = 4 * 3600
_EPOCH_1601 = 11644473600  # seconds from FILETIME's 1601 to Unix time
CALL_APPS = ("teams", "zoom", "discord", "slack", "whatsapp", "skype", "webex", "chrome", "msedge", "firefox", "brave")
# SHQueryUserNotificationState: BUSY, RUNNING_D3D_FULL_SCREEN, PRESENTATION_MODE.
_PRESENTING = {2, 3, 4}
_CS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


async def hold_new(session: Any, request_id: str) -> bool:
    """A card that came to the front while the hold is on (a call, or away) is hidden at once, like the one on
    screen when the hold began (``Session.hold_cards``), and waits in the stack. True: held, so not read aloud."""
    attention = session.attention
    if attention is None or not attention.held:
        return False
    await session._send_stack()
    await session._send(outbound("confirm.hold", request_id=request_id, held=True))
    return True


def opened_recently(start: int, now: float) -> bool:
    """Was the microphone opened (ConsentStore ``LastUsedTimeStart``, a FILETIME) within ``STALE_S``?"""
    return now - (start / 10_000_000 - _EPOCH_1601) < STALE_S


async def open_held(session: Any) -> None:
    """The owner opened the held card from the stack: they're here, and on a call they chose to show it, so the
    call hold is lifted until the next call (``Lifecycle.lift_call``; review 7ab2b70 finding 4)."""
    session._owner_here()
    if session.on_open_held is not None:
        await session.on_open_held()


class Probe(Protocol):
    def in_call(self) -> bool: ...


def mic_call(mic_apps: Iterable[str], alive: set[str], paths: Iterable[str] = ()) -> bool:
    """Is a running call app holding the microphone? ``mic_apps`` are the ConsentStore names with the stream open:
    ``np:<exe>`` for a desktop app, the package family (``MSTeams_8wekyb3d8bbwe``) for a Store app, which is running
    when a process runs from its folder (``WindowsApps\\MSTeams_<version>_<arch>__8wekyb3d8bbwe``). ``paths``: the
    running processes' exe paths."""
    folders = {p.lower().replace("/", "\\").split("\\windowsapps\\", 1)[1].split("\\")[0] for p in paths
               if "\\windowsapps\\" in p.lower().replace("/", "\\")}
    for app in mic_apps:
        if app.startswith("np:"):
            exe = app[3:].lower()
            running = exe in alive
        else:
            name, _, publisher = app.lower().rpartition("_")
            exe = name
            running = any(f.startswith(name + "_") and f.endswith("__" + publisher) for f in folders)
        if running and any(word in exe for word in CALL_APPS):
            return True
    return False


class WindowsProbe:
    """Reads the registry, the process list and the shell's notification state. Read only; no admin."""

    def in_call(self) -> bool:
        if sys.platform != "win32":
            return False
        import psutil  # in the project's environment; the process check drops stale keys

        procs = [p.info for p in psutil.process_iter(["name", "exe"])]  # exe: None where access is denied
        alive = {(p["name"] or "").lower() for p in procs}
        return mic_call(self._mic_open(), alive, [p["exe"] for p in procs if p["exe"]]) or self._presenting()

    @staticmethod
    def _presenting() -> bool:
        state = ctypes.c_int()
        ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))  # type: ignore[attr-defined]
        return state.value in _PRESENTING

    @staticmethod
    def _mic_open() -> list[str]:
        import winreg  # type: ignore[import-not-found,unused-ignore]

        found: list[str] = []

        def scan(path: str, prefix: str = "") -> None:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
            except OSError:
                return
            with key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    name = winreg.EnumKey(key, i)
                    if name == "NonPackaged":
                        scan(path + "\\" + name, "np:")
                        continue
                    try:
                        with winreg.OpenKey(key, name) as app:
                            start = winreg.QueryValueEx(app, "LastUsedTimeStart")[0]
                            stop = winreg.QueryValueEx(app, "LastUsedTimeStop")[0]
                    except OSError:
                        continue
                    if start and stop == 0 and opened_recently(start, time.time()):
                        found.append(prefix + name.split("#")[-1])

        scan(_CS)
        return found


class CallWatch:
    """Polls the probe; tells ``on_change(in_call, seconds)`` when a call starts (0) and when it ends (how long)."""

    def __init__(self, probe: Probe, on_change: Callable[[bool, float], Awaitable[None]], *,
                 clock: Callable[[], float] = time.time, out_s: float = OUT_S) -> None:
        self.probe = probe
        self.on_change = on_change
        self.clock = clock
        self.out_s = out_s
        self.in_call = False
        self._since = 0.0
        self._quiet: float | None = None

    async def poll(self) -> None:
        try:
            now_on = self.probe.in_call()
        except Exception as exc:  # a failed probe keeps the last state
            logger.warning("call probe failed", error=type(exc).__name__)
            return
        now = self.clock()
        if now_on:
            self._quiet = None
            if not self.in_call:
                self.in_call, self._since = True, now
                await self.on_change(True, 0.0)
        elif self.in_call:
            self._quiet = now if self._quiet is None else self._quiet
            if now - self._quiet >= self.out_s:
                self.in_call = False
                await self.on_change(False, self._quiet - self._since)

    async def run(self, every_s: float = POLL_S) -> None:
        while True:
            try:
                await self.poll()
            except Exception as exc:  # a failed hold must not end call detection (review 7ab2b70 finding 5)
                logger.error("call hold change failed", error=type(exc).__name__)
            await asyncio.sleep(every_s)
