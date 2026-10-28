"""The device, as the system lane sees it (ADR-016 §3): volume, media keys, theme, brightness,
lock, windows, information. One base class, a recording ``FakeSystem`` for tests and debug mode,
and ``WindowsSystem`` for the real thing.

Every method is async and may raise ``SystemUnavailable`` with a sentence the owner can read;
the lane turns that into a short spoken-style failure ("This display doesn't let Windows change
its brightness."). Nothing here decides *whether* to act: that is the lane's job, with the
gateway classes of ADR-016 §3.1 (everything in this file is read-only or reversible; power
actions are not offered).

``WindowsSystem`` uses only what ships with Windows plus ``comtypes`` and ``psutil`` (already
dependencies): Core Audio for volume, mute and "is anything playing", the registry for the app
theme, WMI for brightness, ``keybd_event`` for media keys and Win-key shortcuts, ``ShowWindow``
on the foreground window.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Literal

import psutil

WindowAction = Literal["minimize", "maximize", "restore", "desktop", "snap_left", "snap_right"]
MediaKey = Literal["play_pause", "next", "prev"]
Radio = Literal["wifi", "bluetooth"]


class SystemUnavailable(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Battery:
    percent: int
    plugged: bool
    minutes_left: int | None = None


@dataclass(frozen=True)
class Disk:
    free_gb: float
    total_gb: float
    drive: str = "C:"


class SystemControl:
    """Every method a system intent can reach. The base class says no to all of them."""

    async def get_volume(self) -> int:
        raise SystemUnavailable("I can't read the volume here.")

    async def set_volume(self, level: int) -> int:
        raise SystemUnavailable("I can't change the volume here.")

    async def get_mute(self) -> bool:
        raise SystemUnavailable("I can't read the mute state here.")

    async def set_mute(self, muted: bool) -> None:
        raise SystemUnavailable("I can't mute here.")

    async def audio_playing(self) -> bool:
        raise SystemUnavailable("I can't tell whether anything is playing.")

    async def media_key(self, key: MediaKey) -> None:
        raise SystemUnavailable("I can't control media here.")

    async def get_dark_mode(self) -> bool:
        raise SystemUnavailable("I can't read the theme here.")

    async def set_dark_mode(self, dark: bool) -> None:
        raise SystemUnavailable("I can't change the theme here.")

    async def get_brightness(self) -> int:
        raise SystemUnavailable("I can't read the brightness here.")

    async def set_brightness(self, level: int) -> int:
        raise SystemUnavailable("I can't change the brightness here.")

    async def lock(self) -> None:
        raise SystemUnavailable("I can't lock the computer here.")

    async def battery(self) -> Battery | None:
        return None

    async def disk(self) -> Disk:
        raise SystemUnavailable("I can't read the disk here.")

    async def cpu_percent(self) -> float:
        raise SystemUnavailable("I can't read the processor load here.")

    async def memory(self) -> tuple[float, float]:
        """(used GB, total GB)."""
        raise SystemUnavailable("I can't read the memory here.")

    async def uptime_s(self) -> float:
        raise SystemUnavailable("I can't read the uptime here.")

    async def open_uri(self, uri: str) -> None:
        raise SystemUnavailable("I can't open that here.")

    async def window(self, action: WindowAction) -> None:
        raise SystemUnavailable("I can't move windows here.")

    async def screenshot(self) -> None:
        raise SystemUnavailable("I can't take a screenshot here.")

    async def radios(self) -> dict[Radio, bool]:
        """Each radio this PC has, and whether it is on ("wifi", "bluetooth")."""
        raise SystemUnavailable("I can't read the radios here.")

    async def set_radio(self, kind: Radio, on: bool) -> None:
        raise SystemUnavailable("I can't switch radios here.")

    async def chime(self, repeat: int = 3) -> None:
        """A short sound for a timer, alarm or reminder that is due."""


# ---- the stand-in ---------------------------------------------------------------------------


@dataclass
class FakeSystem(SystemControl):
    volume: int = 40
    muted: bool = False
    playing: bool = True
    dark: bool = False
    brightness: int | None = 60
    battery_state: Battery | None = field(default_factory=lambda: Battery(76, False, 190))
    free_gb: float = 212.4
    total_gb: float = 476.0
    cpu: float = 14.0
    ram_used: float = 9.1
    ram_total: float = 16.0
    uptime: float = 3 * 3600 + 25 * 60
    radio_state: dict[Radio, bool] = field(default_factory=lambda: {"wifi": True, "bluetooth": True})
    calls: list[tuple[str, tuple]] = field(default_factory=list)

    def _log(self, name: str, *args: object) -> None:
        self.calls.append((name, args))

    async def get_volume(self) -> int:
        return self.volume

    async def set_volume(self, level: int) -> int:
        self._log("set_volume", level)
        self.volume = max(0, min(100, level))
        if self.volume and self.muted:
            self.muted = False
        return self.volume

    async def get_mute(self) -> bool:
        return self.muted

    async def set_mute(self, muted: bool) -> None:
        self._log("set_mute", muted)
        self.muted = muted

    async def audio_playing(self) -> bool:
        return self.playing

    async def media_key(self, key: MediaKey) -> None:
        self._log("media_key", key)
        if key == "play_pause":
            self.playing = not self.playing

    async def get_dark_mode(self) -> bool:
        return self.dark

    async def set_dark_mode(self, dark: bool) -> None:
        self._log("set_dark_mode", dark)
        self.dark = dark

    async def get_brightness(self) -> int:
        if self.brightness is None:
            raise SystemUnavailable("This display doesn't let Windows change its brightness.")
        return self.brightness

    async def set_brightness(self, level: int) -> int:
        self._log("set_brightness", level)
        if self.brightness is None:
            raise SystemUnavailable("This display doesn't let Windows change its brightness.")
        self.brightness = max(0, min(100, level))
        return self.brightness

    async def lock(self) -> None:
        self._log("lock")

    async def battery(self) -> Battery | None:
        return self.battery_state

    async def disk(self) -> Disk:
        return Disk(self.free_gb, self.total_gb)

    async def cpu_percent(self) -> float:
        return self.cpu

    async def memory(self) -> tuple[float, float]:
        return self.ram_used, self.ram_total

    async def uptime_s(self) -> float:
        return self.uptime

    async def open_uri(self, uri: str) -> None:
        self._log("open_uri", uri)

    async def window(self, action: WindowAction) -> None:
        self._log("window", action)

    async def screenshot(self) -> None:
        self._log("screenshot")

    async def radios(self) -> dict[Radio, bool]:
        return dict(self.radio_state)

    async def set_radio(self, kind: Radio, on: bool) -> None:
        self._log("set_radio", kind, on)
        if kind not in self.radio_state:
            raise SystemUnavailable(f"This PC has no {'Wi-Fi' if kind == 'wifi' else 'Bluetooth'}.")
        self.radio_state[kind] = on

    async def chime(self, repeat: int = 3) -> None:
        self._log("chime", repeat)


# ---- Windows --------------------------------------------------------------------------------

_VK = {"play_pause": 0xB3, "next": 0xB0, "prev": 0xB1}
_VK_WIN, _VK_SHIFT, _VK_D, _VK_S, _VK_LEFT, _VK_RIGHT = 0x5B, 0x10, 0x44, 0x53, 0x25, 0x27
_SW = {"minimize": 6, "maximize": 3, "restore": 9}
_NO_WINDOW = 0x08000000


def _keys(*codes: int, extended: bool = False) -> None:
    """Press the keys together, then release them in reverse."""
    user32 = ctypes.windll.user32
    ext = 1 if extended else 0
    for code in codes:
        user32.keybd_event(code, 0, ext, 0)
    for code in reversed(codes):
        user32.keybd_event(code, 0, ext | 2, 0)


def _com():
    """The Core Audio interfaces, defined once (comtypes, no extra package)."""
    from ctypes import HRESULT, POINTER, c_float, c_int, c_uint
    from ctypes.wintypes import DWORD

    from comtypes import COMMETHOD, GUID, IUnknown

    class IAudioEndpointVolume(IUnknown):
        _iid_ = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
        _methods_ = (
            COMMETHOD([], HRESULT, "RegisterControlChangeNotify", (["in"], POINTER(IUnknown), "pNotify")),
            COMMETHOD([], HRESULT, "UnregisterControlChangeNotify", (["in"], POINTER(IUnknown), "pNotify")),
            COMMETHOD([], HRESULT, "GetChannelCount", (["out"], POINTER(c_uint), "pnChannelCount")),
            COMMETHOD([], HRESULT, "SetMasterVolumeLevel", (["in"], c_float, "fLevelDB"), (["in"], POINTER(GUID), "ctx")),
            COMMETHOD([], HRESULT, "SetMasterVolumeLevelScalar", (["in"], c_float, "fLevel"), (["in"], POINTER(GUID), "ctx")),
            COMMETHOD([], HRESULT, "GetMasterVolumeLevel", (["out"], POINTER(c_float), "pfLevelDB")),
            COMMETHOD([], HRESULT, "GetMasterVolumeLevelScalar", (["out"], POINTER(c_float), "pfLevel")),
            COMMETHOD([], HRESULT, "SetChannelVolumeLevel", (["in"], c_uint, "nChannel"), (["in"], c_float, "fLevelDB"), (["in"], POINTER(GUID), "ctx")),
            COMMETHOD([], HRESULT, "SetChannelVolumeLevelScalar", (["in"], c_uint, "nChannel"), (["in"], c_float, "fLevel"), (["in"], POINTER(GUID), "ctx")),
            COMMETHOD([], HRESULT, "GetChannelVolumeLevel", (["in"], c_uint, "nChannel"), (["out"], POINTER(c_float), "pfLevelDB")),
            COMMETHOD([], HRESULT, "GetChannelVolumeLevelScalar", (["in"], c_uint, "nChannel"), (["out"], POINTER(c_float), "pfLevel")),
            COMMETHOD([], HRESULT, "SetMute", (["in"], c_int, "bMute"), (["in"], POINTER(GUID), "ctx")),
            COMMETHOD([], HRESULT, "GetMute", (["out"], POINTER(c_int), "pbMute")),
        )

    class IAudioMeterInformation(IUnknown):
        _iid_ = GUID("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")
        _methods_ = (
            COMMETHOD([], HRESULT, "GetPeakValue", (["out"], POINTER(c_float), "pfPeak")),
        )

    class IMMDevice(IUnknown):
        _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
        _methods_ = (
            COMMETHOD([], HRESULT, "Activate", (["in"], POINTER(GUID), "iid"), (["in"], DWORD, "dwClsCtx"),
                      (["in"], POINTER(DWORD), "pActivationParams"), (["out"], POINTER(POINTER(IUnknown)), "ppInterface")),
        )

    class IMMDeviceEnumerator(IUnknown):
        _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        _methods_ = (
            COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], DWORD, "dataFlow"), (["in"], DWORD, "dwStateMask"),
                      (["out"], POINTER(POINTER(IUnknown)), "ppDevices")),
            COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], DWORD, "dataFlow"), (["in"], DWORD, "role"),
                      (["out"], POINTER(POINTER(IMMDevice)), "ppDevice")),
        )

    return IAudioEndpointVolume, IAudioMeterInformation, IMMDeviceEnumerator, GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")


@contextlib.contextmanager
def _endpoint(kind: str):
    """The default speakers' ``kind`` interface ("volume" or "meter"); COM set up and torn down on this thread."""
    import comtypes
    from comtypes import CLSCTX_ALL, CoCreateInstance

    volume_t, meter_t, enum_t, clsid = _com()
    comtypes.CoInitialize()
    try:
        try:
            enumerator = CoCreateInstance(clsid, enum_t, CLSCTX_ALL)
            device = enumerator.GetDefaultAudioEndpoint(0, 1)  # eRender, eMultimedia
            wanted = volume_t if kind == "volume" else meter_t
            raw = device.Activate(wanted._iid_, CLSCTX_ALL, None)
            yield ctypes.cast(raw, ctypes.POINTER(wanted))
        except OSError as exc:  # COMError is an OSError; no output device, or the service is down
            raise SystemUnavailable("I can't reach the sound device.") from exc
    finally:
        comtypes.CoUninitialize()


def _ps(script: str, timeout: float = 8.0) -> str:
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW, check=False,
    )
    if done.returncode != 0:
        raise SystemUnavailable("Windows didn't accept that.")
    return done.stdout.strip()


# Windows.Devices.Radios through PowerShell's WinRT bridge: no extra package. About 1 s a call.
_RADIO_PRELUDE = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
$access = Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus])
if ($access -ne 'Allowed') { Write-Output "denied"; exit 0 }
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
"""
_RADIO_LIST = _RADIO_PRELUDE + r"""
foreach ($r in $radios) { Write-Output "$($r.Kind)|$($r.State)" }
"""
_RADIO_SET = _RADIO_PRELUDE + r"""
$done = 0
foreach ($r in $radios) {
  if ($r.Kind -eq '__KIND__') {
    $res = Await ($r.SetStateAsync([Windows.Devices.Radios.RadioState]::__STATE__)) ([Windows.Devices.Radios.RadioAccessStatus])
    Write-Output "set|$res"; $done = 1
  }
}
if ($done -eq 0) { Write-Output "none" }
"""
_RADIO_KIND = {"wifi": "WiFi", "bluetooth": "Bluetooth"}


def _ps_script(script: str, timeout: float = 15.0) -> str:
    """Run a longer PowerShell script (passed encoded, so quoting can't break it)."""
    import base64

    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW, check=False,
    )
    if done.returncode != 0:
        raise SystemUnavailable("Windows didn't accept that.")
    return done.stdout.strip()


class WindowsSystem(SystemControl):
    """The real device. Blocking calls run in a worker thread so the core loop never waits on them."""

    async def get_volume(self) -> int:
        def read() -> int:
            with _endpoint("volume") as v:
                return round(v.GetMasterVolumeLevelScalar() * 100)
        return await asyncio.to_thread(read)

    async def set_volume(self, level: int) -> int:
        level = max(0, min(100, level))

        def write() -> int:
            with _endpoint("volume") as v:
                v.SetMasterVolumeLevelScalar(level / 100.0, None)
                if level and v.GetMute():
                    v.SetMute(0, None)
                return round(v.GetMasterVolumeLevelScalar() * 100)
        return await asyncio.to_thread(write)

    async def get_mute(self) -> bool:
        def read() -> bool:
            with _endpoint("volume") as v:
                return bool(v.GetMute())
        return await asyncio.to_thread(read)

    async def set_mute(self, muted: bool) -> None:
        def write() -> None:
            with _endpoint("volume") as v:
                v.SetMute(1 if muted else 0, None)
        await asyncio.to_thread(write)

    async def audio_playing(self) -> bool:
        def peak() -> bool:
            with _endpoint("meter") as m:
                best = 0.0
                for _ in range(6):
                    best = max(best, m.GetPeakValue())
                    time.sleep(0.04)
                return best > 0.0005
        return await asyncio.to_thread(peak)

    async def media_key(self, key: MediaKey) -> None:
        await asyncio.to_thread(_keys, _VK[key], extended=True)

    async def get_dark_mode(self) -> bool:
        import winreg

        def read() -> bool:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        try:
            return await asyncio.to_thread(read)
        except OSError as exc:
            raise SystemUnavailable("I can't read the theme.") from exc

    async def set_dark_mode(self, dark: bool) -> None:
        import winreg

        def write() -> None:
            path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as k:
                for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
                    winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 0 if dark else 1)
            ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "ImmersiveColorSet", 2, 3000, None)
        try:
            await asyncio.to_thread(write)
        except OSError as exc:
            raise SystemUnavailable("Windows wouldn't switch the theme.") from exc

    async def get_brightness(self) -> int:
        script = "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Select-Object -First 1).CurrentBrightness"
        try:
            out = await asyncio.to_thread(_ps, script)
            return int(out)
        except (ValueError, subprocess.SubprocessError, SystemUnavailable) as exc:
            raise SystemUnavailable("This display doesn't let Windows change its brightness.") from exc

    async def set_brightness(self, level: int) -> int:
        level = max(0, min(100, level))
        script = (
            "Invoke-CimMethod -InputObject (Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods"
            f" | Select-Object -First 1) -MethodName WmiSetBrightness -Arguments @{{Timeout=1;Brightness={level}}} | Out-Null"
        )
        try:
            await asyncio.to_thread(_ps, script)
        except (subprocess.SubprocessError, SystemUnavailable) as exc:
            raise SystemUnavailable("This display doesn't let Windows change its brightness.") from exc
        return level

    async def lock(self) -> None:
        if not await asyncio.to_thread(ctypes.windll.user32.LockWorkStation):
            raise SystemUnavailable("Windows wouldn't lock.")

    async def battery(self) -> Battery | None:
        b = await asyncio.to_thread(psutil.sensors_battery)
        if b is None:
            return None
        left = None if b.secsleft in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) else int(b.secsleft // 60)
        return Battery(round(b.percent), bool(b.power_plugged), left)

    async def disk(self) -> Disk:
        drive = os.environ.get("SystemDrive", "C:")
        usage = await asyncio.to_thread(psutil.disk_usage, drive + "\\")
        return Disk(usage.free / 1e9, usage.total / 1e9, drive)

    async def cpu_percent(self) -> float:
        return await asyncio.to_thread(psutil.cpu_percent, 0.4)

    async def memory(self) -> tuple[float, float]:
        m = await asyncio.to_thread(psutil.virtual_memory)
        return (m.total - m.available) / 1e9, m.total / 1e9

    async def uptime_s(self) -> float:
        return time.time() - psutil.boot_time()

    async def open_uri(self, uri: str) -> None:
        if not uri.startswith(("ms-settings:", "https://")):
            raise SystemUnavailable("I only open Windows settings and web searches this way.")
        try:
            await asyncio.to_thread(os.startfile, uri)  # type: ignore[attr-defined]
        except OSError as exc:
            raise SystemUnavailable("Windows couldn't open that.") from exc

    async def window(self, action: WindowAction) -> None:
        def run() -> None:
            user32 = ctypes.windll.user32
            if action == "desktop":
                _keys(_VK_WIN, _VK_D)
            elif action in ("snap_left", "snap_right"):
                _keys(_VK_WIN, _VK_LEFT if action == "snap_left" else _VK_RIGHT, extended=True)
            else:
                hwnd = user32.GetForegroundWindow()
                if not hwnd:
                    raise SystemUnavailable("There's no window in front.")
                user32.ShowWindow(hwnd, _SW[action])
        await asyncio.to_thread(run)

    async def screenshot(self) -> None:
        await asyncio.to_thread(_keys, _VK_WIN, _VK_SHIFT, _VK_S)

    async def radios(self) -> dict[Radio, bool]:
        try:
            out = await asyncio.to_thread(_ps_script, _RADIO_LIST)
        except subprocess.SubprocessError as exc:
            raise SystemUnavailable("Windows didn't answer about the radios.") from exc
        if out == "denied":
            raise SystemUnavailable("Windows doesn't let Swift control the radios. Check Settings, Privacy, Radios.")
        found: dict[Radio, bool] = {}
        for line in out.splitlines():
            kind, _, state = line.partition("|")
            for name, winrt in _RADIO_KIND.items():
                if kind.strip() == winrt:
                    found[name] = found.get(name, False) or state.strip() == "On"  # type: ignore[index]
        return found

    async def set_radio(self, kind: Radio, on: bool) -> None:
        script = _RADIO_SET.replace("__KIND__", _RADIO_KIND[kind]).replace("__STATE__", "On" if on else "Off")
        try:
            out = await asyncio.to_thread(_ps_script, script)
        except subprocess.SubprocessError as exc:
            raise SystemUnavailable("Windows didn't answer about the radios.") from exc
        name = "Wi-Fi" if kind == "wifi" else "Bluetooth"
        if out == "none":
            raise SystemUnavailable(f"This PC has no {name}.")
        if out == "denied" or "Allowed" not in out:
            raise SystemUnavailable(f"Windows didn't let Swift switch {name}. Check Settings, Privacy, Radios.")

    async def chime(self, repeat: int = 3) -> None:
        if sys.platform != "win32":
            return

        def ring() -> None:
            import winsound

            for _ in range(repeat):
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
                time.sleep(0.5)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(ring)
