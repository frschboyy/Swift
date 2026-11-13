"""Which z-order band Swift's overlay and Task Manager are in (A10, owner check 203): owner-run.

Windows keeps windows in bands, and every ordinary app's windows, always-on-top ones included, are in
the desktop band (1). Swift's ``raise`` puts the overlay at the top of that band (SetWindowPos
HWND_TOPMOST, no focus taken). Task Manager is a system binary that imports ``CreateWindowInBand``;
with **Options > Always on top** ticked it is expected to sit in a higher band (16, "system tools"),
which no ordinary app can go above. This prints the bands, so that's shown, not assumed.

    uv run python spikes/desktop/window_bands.py           # the bands, read-only
    uv run python spikes/desktop/window_bands.py --cover   # also: a plain always-on-top window for 60 s

``--cover`` opens a small always-on-top window (an ordinary app's, band 1) over where Swift sits, to
show that Swift does come in front of one when you say "Hey Swift" (owner check 253).

It only reads window handles, classes and bands (no titles, nothing from inside a window).
"""

from __future__ import annotations

import argparse
import ctypes
import sys
from ctypes import wintypes

BANDS = {0: "default", 1: "desktop (every ordinary app)", 2: "UI access", 3: "immersive IHM", 4: "immersive notification",
         5: "immersive app chrome", 6: "immersive mogo", 7: "immersive edgy", 8: "immersive inactive mobody",
         9: "immersive inactive dock", 10: "immersive active mobody", 11: "immersive active dock",
         12: "immersive background", 13: "immersive search", 14: "genuine windows", 15: "immersive restricted",
         16: "system tools", 17: "lock", 18: "above lock UX"}
WS_EX_TOPMOST = 0x8
GWL_EXSTYLE = -20
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _windows() -> list[tuple[str, str, int, bool, int]]:
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    get_band = getattr(user32, "GetWindowBand", None)
    rows: list[tuple[str, str, int, bool, int]] = []

    def exe_of(hwnd: int) -> str:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return "?"
        try:
            buf, size = ctypes.create_unicode_buffer(520), wintypes.DWORD(520)
            ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
            return buf.value.rsplit("\\", 1)[-1].lower() if ok else "?"
        finally:
            kernel32.CloseHandle(handle)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        exe = exe_of(hwnd)
        if exe not in ("taskmgr.exe", "swift-overlay.exe") and "python" not in exe:
            return True
        cls = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, cls, 128)
        band = wintypes.DWORD(0)
        if get_band is not None:
            get_band(hwnd, ctypes.byref(band))
        topmost = bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)
        rows.append((exe, cls.value, int(band.value), topmost, int(hwnd or 0)))
        return True

    user32.EnumWindows(each, 0)
    return rows


def report() -> None:
    rows = _windows()
    if not any(exe == "taskmgr.exe" for exe, *_ in rows):
        print("Task Manager isn't open: open it and tick Options > Always on top first.")
    for exe, cls, band, topmost, hwnd in rows:
        if cls in ("Tao Thread Event Target",):
            continue
        print(f"{exe:20} {cls:28} band {band} ({BANDS.get(band, '?')}), always on top: {'yes' if topmost else 'no'}")
    manager = [band for exe, _, band, _, _ in rows if exe == "taskmgr.exe"]
    swift = [band for exe, cls, band, top, _ in rows if exe == "swift-overlay.exe" and top]
    if manager and max(manager) == 1 and not any(top for exe, _, _, top, _ in rows if exe == "taskmgr.exe"):
        print("\nTask Manager isn't always on top now: tick Options > Always on top and run this again.")
    elif manager and swift:
        above = max(manager) > max(swift)
        print("\nTask Manager is in a higher band than Swift: no ordinary app can come in front of it."
              if above else "\nTask Manager is in the same band as Swift: Swift's raise should bring it in front.")


def cover() -> None:
    import tkinter as tk

    root = tk.Tk()
    root.title("Always on top (test)")
    root.attributes("-topmost", True)
    width, height = 420, 220
    x = root.winfo_screenwidth() - width - 40
    y = root.winfo_screenheight() - height - 80
    root.geometry(f"{width}x{height}+{x}+{y}")
    tk.Label(root, text="An ordinary always-on-top window.\nDrag it over Swift, click in Notepad,\n"
             "then say \"Hey Swift\".\n\nCloses by itself in 60 seconds.", font=("Segoe UI", 12)).pack(expand=True)
    root.after(60_000, root.destroy)
    root.mainloop()


def main() -> None:
    if sys.platform != "win32":
        sys.exit("Windows only.")
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--cover", action="store_true", help="open a plain always-on-top window for 60 s")
    args = parser.parse_args()
    report()
    if args.cover:
        cover()


if __name__ == "__main__":
    main()
