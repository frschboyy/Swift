"""Spike: can a Swift card feel like it comes from the thing it concerns?

Swift starts every motion here, so it owns the clock. Nothing is tracked: the
source's place is read once, when the action starts, and the spike does no work
at rest. Swift's orb isn't part of this.

    uv run python spikes/desktop/card_origin.py             interactive
    uv run python spikes/desktop/card_origin.py --selftest  hands-off

Each key opens its card; the same key again puts it back.
    Ctrl+Alt+W  a card unfolds from the active window's title bar
    Ctrl+Alt+T  a card rises from the taskbar's notification area
    Ctrl+Alt+P  a card arrives and the active window makes room for it
    Ctrl+Alt+Q  quit

Native windows only: this measures Windows' side of the illusion, not WebView2's.

Result (2026-11-10, owner's PC, judged by eye): all three motions read as coming
from their source, with no lag on the cards or the rest of the screen.

Earlier result (2026-11-10, owner's PC, in git history as window_follow.py): a
window that follows a dragged window per frame trails it, and each move of an
overlay window costs 2-4 ms. Don't chase what the user is moving.
"""

import argparse
import ctypes
import time
from ctypes import wintypes as w

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32")
gdi = ctypes.WinDLL("gdi32")
dwm = ctypes.WinDLL("dwmapi")

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HANDLE),
        ("hCursor", w.HANDLE), ("hbrBackground", w.HANDLE),
        ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR),
    ]


# 64-bit handles get truncated without these.
u32.DefWindowProcW.argtypes = (w.HWND, w.UINT, w.WPARAM, w.LPARAM)
u32.DefWindowProcW.restype = LRESULT
u32.CreateWindowExW.argtypes = (
    w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, w.HWND, w.HANDLE, w.HINSTANCE, w.LPVOID,
)
u32.CreateWindowExW.restype = w.HWND
u32.SetWindowPos.argtypes = (
    w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT
)
u32.GetForegroundWindow.restype = w.HWND
u32.FindWindowW.argtypes = (w.LPCWSTR, w.LPCWSTR)
u32.FindWindowW.restype = w.HWND
u32.FindWindowExW.argtypes = (w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR)
u32.FindWindowExW.restype = w.HWND
u32.GetWindowRect.argtypes = (w.HWND, ctypes.POINTER(w.RECT))
u32.IsZoomed.argtypes = (w.HWND,)
u32.IsWindowVisible.argtypes = (w.HWND,)
u32.ShowWindow.argtypes = (w.HWND, ctypes.c_int)
u32.DestroyWindow.argtypes = (w.HWND,)
u32.SetLayeredWindowAttributes.argtypes = (w.HWND, w.DWORD, ctypes.c_ubyte, w.DWORD)
u32.PeekMessageW.argtypes = (ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT)
u32.DispatchMessageW.argtypes = (ctypes.POINTER(w.MSG),)
u32.MsgWaitForMultipleObjects.argtypes = (w.DWORD, w.LPVOID, w.BOOL, w.DWORD, w.DWORD)
u32.SetProcessDpiAwarenessContext.argtypes = (w.HANDLE,)
k32.GetModuleHandleW.restype = w.HMODULE
gdi.CreateSolidBrush.restype = w.HANDLE
dwm.DwmGetWindowAttribute.argtypes = (w.HWND, w.DWORD, w.LPVOID, w.DWORD)
dwm.DwmSetWindowAttribute.argtypes = (w.HWND, w.DWORD, w.LPVOID, w.DWORD)

WM_HOTKEY = 0x0312
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10
HWND_TOPMOST = w.HWND(-1)
OVERLAY_EX = 0x8 | 0x80 | 0x20 | 0x80000 | 0x08000000  # topmost, tool, click-through, layered, no-activate

CARD_W = 320
GROW_S = 0.26
APPROACH_S, PUSH_S = 0.12, 0.22  # the card closes the gap, then card and window travel together
KEYS = {1: ("W", "window"), 2: ("T", "tray"), 3: ("P", "push"), 4: ("Q", None)}


class S:  # spike state
    anim = None   # the one open or moving card
    fg = None     # selftest: stands in for the foreground window
    own = []


_wndproc = WNDPROC(lambda h, m, wp, lp: u32.DefWindowProcW(h, m, wp, lp))


def make_window(name, rgb, width, height, ex, style=0x80000000):
    cls = WNDCLASS(lpfnWndProc=_wndproc, hInstance=k32.GetModuleHandleW(None),
                   hbrBackground=gdi.CreateSolidBrush(rgb), lpszClassName=name)
    u32.RegisterClassW(ctypes.byref(cls))
    hwnd = u32.CreateWindowExW(ex, name, name, style, 200, 200, width, height,
                               None, None, cls.hInstance, None)
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    if ex & 0x80000:
        u32.SetLayeredWindowAttributes(hwnd, 0, 255, 2)
    S.own.append(hwnd)
    return hwnd


def frame(hwnd):
    """The rectangle you actually see (GetWindowRect includes invisible resize borders)."""
    r = w.RECT()
    if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        u32.GetWindowRect(hwnd, ctypes.byref(r))
    return r


def tray():
    # shortcut: the whole notification area, not one icon; a single icon's rect needs UI Automation
    bar = u32.FindWindowW("Shell_TrayWnd", None)
    r = w.RECT()
    u32.GetWindowRect(u32.FindWindowExW(bar, None, "TrayNotifyWnd", None) or bar, ctypes.byref(r))
    return r


def start(kind):
    """Read where the source is, once, and return the animation for a card from it."""
    if kind == "tray":
        r = tray()
        cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
        return dict(src=(cx - 12, cy - 12, 24, 24),
                    dst=(max(0, r.right - 352), r.top - 172, 340, 160))
    hwnd = S.fg or u32.GetForegroundWindow()
    if not hwnd:  # the card never takes focus, so the active window is never the card
        return print("no active window")
    f = frame(hwnd)
    if kind == "window":
        cx = (f.left + f.right) // 2
        return dict(src=(cx - 30, f.top, 60, 6), dst=(cx - 180, f.top + 44, 360, 180))
    if u32.IsZoomed(hwnd):
        return print("a maximised window has nowhere to move to")
    r = w.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    return dict(hwnd=hwnd, x0=r.left, y0=r.top, left0=f.left, top=f.top, h=f.bottom - f.top)


def toggle(kind):
    a = S.anim
    if a:
        if a["kind"] != kind:
            print("put the open card back first (same key again)")
        elif a["done"]:
            a.update(back=True, done=False, t0=time.perf_counter())
        return
    a = start(kind)
    if a:
        S.anim = dict(a, kind=kind, back=False, done=False, t0=time.perf_counter())


def step(card):
    a = S.anim
    t = time.perf_counter() - a["t0"]
    if a["kind"] != "push":
        u = min(1.0, t / GROW_S)
        e = (1 - u) ** 2 if a["back"] else 1 - (1 - u) ** 3
        x, y, cw, ch = (round(s + (d - s) * e) for s, d in zip(a["src"], a["dst"]))
        alpha = 255 * min(1.0, 2 * e)
    else:
        if a["back"]:
            u = min(1.0, t / PUSH_S)
            e, alpha, gap = (1 - u) ** 2, 255 * (1 - u), 0.0
        elif t < APPROACH_S:  # accelerate into contact: the "impact" is the frame the gap closes
            u, near = 0.0, (t / APPROACH_S) ** 2
            e, alpha, gap = 0.0, 255 * near, 0.5 * CARD_W * (1 - near)
        else:
            u = min(1.0, (t - APPROACH_S) / PUSH_S)
            e, alpha, gap = 1 - (1 - u) ** 2, 255, 0.0
        dx = round(CARD_W * e)
        ok = u32.SetWindowPos(a["hwnd"], None, a["x0"] + dx, a["y0"], 0, 0,
                              SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        if not ok and not a.get("warned"):
            a["warned"] = True
            print("can't move that window (elevated app?):",
                  ctypes.WinError(ctypes.get_last_error()))
        x, y, cw, ch = round(a["left0"] - CARD_W + dx - gap), a["top"], CARD_W, a["h"]
    u32.SetLayeredWindowAttributes(card, 0, int(alpha), 2)
    u32.SetWindowPos(card, HWND_TOPMOST, x, y, cw, ch, SWP_NOACTIVATE)
    u32.ShowWindow(card, 4)  # show without activating
    if u >= 1.0:
        a["done"] = True
        if a["back"]:
            u32.ShowWindow(card, 0)
            S.anim = None


def animate(card):
    """Run the open animation to its end, one step per composed frame, and say how it went."""
    a = S.anim
    if not a or a["done"]:
        return
    place, late, last = [], 0, None
    while not a["done"]:
        dwm.DwmFlush()  # wait for the compositor, so each step lands on its own frame
        now = time.perf_counter()
        late += last is not None and now - last > 0.025
        last = now
        step(card)
        place.append((time.perf_counter() - now) * 1000)
    place.sort()
    print(f"{a['kind']:>6} {'back' if a['back'] else 'out ':4}: {len(place)} frames, {late} late, "
          f"placing median {place[len(place) // 2]:.1f} ms, max {place[-1]:.1f} ms")


def rect(hwnd):
    r = w.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def selftest(card):
    S.fg = make_window("SwiftSpikeDummy", 0x00603020, 420, 300, 0, style=0x00CF0000)
    u32.ShowWindow(S.fg, 4)
    for kind in ("window", "tray"):
        toggle(kind)
        dst = S.anim["dst"]
        animate(card)
        assert rect(card) == dst and u32.IsWindowVisible(card), f"{kind}: card isn't at its place"
        toggle(kind)
        animate(card)
        assert S.anim is None and not u32.IsWindowVisible(card), f"{kind}: card didn't go back"
    t = tray()
    assert dst[1] + dst[3] <= t.top and dst[0] >= 0, "tray card covers the taskbar or leaves the screen"

    before = frame(S.fg).left
    toggle("push")
    animate(card)
    assert frame(S.fg).left - before == CARD_W, "push didn't move the window by the card's width"
    toggle("push")
    animate(card)
    assert frame(S.fg).left == before, "put-back didn't restore the window"
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    u32.SetProcessDpiAwarenessContext(w.HANDLE(-4))  # per-monitor v2: real pixels
    card = make_window("SwiftSpikeCard", 0x00302820, CARD_W, 200, OVERLAY_EX)
    dwm.DwmSetWindowAttribute(card, 33, ctypes.byref(ctypes.c_int(2)), 4)  # rounded corners
    try:
        if args.selftest:
            return selftest(card)
        for hot_id, (key, _) in KEYS.items():
            if not u32.RegisterHotKey(None, hot_id, 0x1 | 0x2, ord(key)):
                print(f"Ctrl+Alt+{key} is taken by another app")
        print(__doc__.split("\n\n")[3])
        msg = w.MSG()
        while True:
            u32.MsgWaitForMultipleObjects(0, None, False, 500, 0x04FF)  # asleep until a key; Ctrl+C still works
            while u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == WM_HOTKEY:
                    kind = KEYS[msg.wParam][1]
                    if not kind:
                        return
                    toggle(kind)
                    animate(card)
                u32.DispatchMessageW(ctypes.byref(msg))
    except KeyboardInterrupt:
        pass
    finally:
        a = S.anim
        if a and a["kind"] == "push":  # never leave the owner's window where the spike put it
            u32.SetWindowPos(a["hwnd"], None, a["x0"], a["y0"], 0, 0,
                             SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        for hwnd in S.own:
            u32.DestroyWindow(hwnd)


if __name__ == "__main__":
    main()
