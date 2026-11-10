"""Spike: can a Swift window ride and push real Windows windows convincingly?

An orb rests on the top edge of the active window and follows it. A card can
slide in and "push" that window aside: the real window moves on the card's curve.

    uv run python spikes/desktop/window_follow.py             interactive
    uv run python spikes/desktop/window_follow.py --selftest  hands-off, prints latency

Interactive keys:  Ctrl+Alt+P push / put back   Ctrl+Alt+S spring / rigid   Ctrl+Alt+Q quit

Native windows only: this measures Windows' side of the illusion, not WebView2's.
"""

import argparse
import ctypes
import statistics
import time
from ctypes import wintypes as w

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32")
gdi = ctypes.WinDLL("gdi32")
dwm = ctypes.WinDLL("dwmapi")

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None, w.HANDLE, w.DWORD, w.HWND, w.LONG, w.LONG, w.DWORD, w.DWORD
)


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
u32.SetWindowRgn.argtypes = (w.HWND, w.HANDLE, w.BOOL)
u32.GetForegroundWindow.restype = w.HWND
u32.GetWindowRect.argtypes = (w.HWND, ctypes.POINTER(w.RECT))
u32.GetWindowThreadProcessId.argtypes = (w.HWND, ctypes.POINTER(w.DWORD))
u32.IsZoomed.argtypes = (w.HWND,)
u32.ShowWindow.argtypes = (w.HWND, ctypes.c_int)
u32.DestroyWindow.argtypes = (w.HWND,)
u32.SetLayeredWindowAttributes.argtypes = (w.HWND, w.DWORD, ctypes.c_ubyte, w.DWORD)
u32.SetWinEventHook.argtypes = (
    w.DWORD, w.DWORD, w.HMODULE, WINEVENTPROC, w.DWORD, w.DWORD, w.DWORD
)
u32.SetWinEventHook.restype = w.HANDLE
u32.UnhookWinEvent.argtypes = (w.HANDLE,)
u32.PeekMessageW.argtypes = (ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT)
u32.DispatchMessageW.argtypes = (ctypes.POINTER(w.MSG),)
u32.SetProcessDpiAwarenessContext.argtypes = (w.HANDLE,)
k32.GetModuleHandleW.restype = w.HMODULE
gdi.CreateSolidBrush.restype = w.HANDLE
gdi.CreateEllipticRgn.restype = w.HANDLE
dwm.DwmGetWindowAttribute.argtypes = (w.HWND, w.DWORD, w.LPVOID, w.DWORD)

EVENT_SYSTEM_FOREGROUND, EVENT_OBJECT_LOCATIONCHANGE = 0x0003, 0x800B
WM_HOTKEY = 0x0312
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10
HWND_TOPMOST = w.HWND(-1)
OVERLAY_EX = 0x8 | 0x80 | 0x20 | 0x80000 | 0x08000000  # topmost, tool, click-through, layered, no-activate

ORB, CARD_W = 28, 320
APPROACH_S, PUSH_S = 0.12, 0.22  # card closes the gap, then card and window travel together


class S:  # spike state
    target = None
    spring = True
    pos = [0.0, 0.0]
    vel = [0.0, 0.0]
    stamps = []     # arrival time of each location event for the target
    latency = []    # selftest: our SetWindowPos -> event arrival
    moved_at = 0.0
    loc_hook = None
    push = None     # dict while a window is pushed or animating
    own = set()


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
    S.own.add(hwnd)
    return hwnd


def frame(hwnd):
    """The rectangle you actually see (GetWindowRect includes invisible resize borders)."""
    r = w.RECT()
    if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        u32.GetWindowRect(hwnd, ctypes.byref(r))
    return r


def follow(hwnd):
    """Listen for moves of this window's process only: a global hook drowns in cursor events."""
    S.target = hwnd
    if S.loc_hook:
        u32.UnhookWinEvent(S.loc_hook)
    pid = w.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    S.loc_hook = u32.SetWinEventHook(EVENT_OBJECT_LOCATIONCHANGE, EVENT_OBJECT_LOCATIONCHANGE,
                                     None, _on_event, pid.value, 0, 0)


@WINEVENTPROC
def _on_event(_hook, event, hwnd, id_object, _child, _thread, _ms):
    if id_object != 0 or not hwnd:  # 0 = the window itself, not its caret or cursor
        return
    if event == EVENT_SYSTEM_FOREGROUND:
        if hwnd not in S.own and not S.push:
            follow(hwnd)
    elif hwnd == S.target:
        now = time.perf_counter()
        S.stamps.append(now)
        if S.moved_at:
            S.latency.append(now - S.moved_at)
            S.moved_at = 0.0


def goal():
    r = frame(S.target)
    return (r.left + r.right) / 2 - ORB / 2, max(0, r.top - ORB / 2)


def step(orb, card, dt):
    if S.target:
        g = goal()
        for i in (0, 1):
            if S.spring:
                k, c = 320.0, 28.0  # a little under critical damping: one small overshoot
                S.vel[i] += (k * (g[i] - S.pos[i]) - c * S.vel[i]) * dt
                S.pos[i] += S.vel[i] * dt
            else:
                S.pos[i], S.vel[i] = g[i], 0.0
        u32.SetWindowPos(orb, HWND_TOPMOST, round(S.pos[0]), round(S.pos[1]), 0, 0,
                         SWP_NOSIZE | SWP_NOACTIVATE)
    p = S.push
    if not p or p["done"]:
        return
    t = time.perf_counter() - p["t0"]
    if p["back"]:
        u = min(1.0, t / PUSH_S)
        e, alpha, gap = (1 - u) ** 2, 255 * (1 - u), 0.0
    elif t < APPROACH_S:  # accelerate into contact: the "impact" is the frame the gap closes
        a = (t / APPROACH_S) ** 2
        e, alpha, gap = 0.0, 255 * a, 0.5 * CARD_W * (1 - a)
    else:
        u = min(1.0, (t - APPROACH_S) / PUSH_S)
        e, alpha, gap = 1 - (1 - u) ** 2, 255, 0.0
    dx = round(CARD_W * e)
    ok = u32.SetWindowPos(p["hwnd"], None, p["x0"] + dx, p["y0"], 0, 0,
                          SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
    if not ok and not p["warned"]:
        p["warned"] = True
        print("can't move that window (elevated app?):", ctypes.WinError(ctypes.get_last_error()))
    S.moved_at = S.moved_at or time.perf_counter()
    u32.SetLayeredWindowAttributes(card, 0, int(alpha), 2)
    u32.SetWindowPos(card, HWND_TOPMOST, round(p["left0"] - CARD_W + dx - gap), p["top"],
                     CARD_W, p["h"], SWP_NOACTIVATE)
    if (p["back"] or t >= APPROACH_S) and u >= 1.0:
        p["done"] = True
        if p["back"]:
            u32.ShowWindow(card, 0)
            S.push = None


def toggle_push(card):
    p = S.push
    if p:
        if p["done"]:
            p.update(back=True, done=False, t0=time.perf_counter())
        return
    if not S.target or u32.IsZoomed(S.target):
        print("push skipped: no window, or it's maximised")
        return
    r, f = w.RECT(), frame(S.target)
    u32.GetWindowRect(S.target, ctypes.byref(r))
    S.push = dict(hwnd=S.target, x0=r.left, y0=r.top, left0=f.left, top=f.top,
                  h=f.bottom - f.top, t0=time.perf_counter(), back=False, done=False,
                  warned=False)
    u32.SetLayeredWindowAttributes(card, 0, 0, 2)
    u32.ShowWindow(card, 4)  # show without activating


def pump(card):
    msg = w.MSG()
    while u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
        if msg.message == WM_HOTKEY:
            if msg.wParam == 1:
                toggle_push(card)
            elif msg.wParam == 2:
                S.spring = not S.spring
                print("follow:", "spring" if S.spring else "rigid")
            else:
                return False
        u32.DispatchMessageW(ctypes.byref(msg))
    return True


def frames(orb, card, until):
    """Run one step per composed frame (DwmFlush waits for the compositor)."""
    last, n, t0 = time.perf_counter(), 0, time.perf_counter()
    while True:
        dwm.DwmFlush()  # wait first, so each frame is placed from the freshest events
        if not pump(card) or until():
            break
        now = time.perf_counter()
        step(orb, card, min(0.05, now - last))
        last, n = now, n + 1
    return n / max(1e-9, time.perf_counter() - t0)


def report(fps):
    gaps = [b - a for a, b in zip(S.stamps, S.stamps[1:]) if b - a < 0.1]  # within one drag
    print(f"frames/s {fps:.0f}   location events {len(S.stamps)}")
    if gaps:
        print(f"gap between move events: median {statistics.median(gaps) * 1000:.1f} ms, "
              f"p95 {sorted(gaps)[int(len(gaps) * 0.95)] * 1000:.1f} ms")
    if S.latency:
        print(f"our move -> event arrives: median {statistics.median(S.latency) * 1000:.2f} ms, "
              f"max {max(S.latency) * 1000:.2f} ms  (n={len(S.latency)})")


def selftest(orb, card):
    dummy = make_window("SwiftSpikeDummy", 0x00603020, 420, 300, 0, style=0x00CF0000)
    u32.ShowWindow(dummy, 4)
    follow(dummy)
    S.spring, n = False, [0]

    def sweep():  # move our own window 4 px a frame, as a drag would
        n[0] += 1
        S.moved_at = time.perf_counter()
        u32.SetWindowPos(dummy, None, 200 + 4 * n[0], 200, 0, 0,
                         SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        pump(card)  # so the latency number isn't just the wait for the next frame
        return n[0] > 120

    fps = frames(orb, card, sweep)
    frames(orb, card, lambda: (n.__setitem__(0, n[0] + 1), n[0] > 125)[1])  # drain last events
    g, events = goal(), len(S.stamps)
    assert events >= 100, f"only {events} location events for 120 moves"
    assert abs(S.pos[0] - g[0]) <= 1 and abs(S.pos[1] - g[1]) <= 1, "rigid orb is off its anchor"

    before = frame(dummy).left
    toggle_push(card)
    frames(orb, card, lambda: S.push["done"])
    assert frame(dummy).left - before == CARD_W, "push didn't move the window by the card's width"
    toggle_push(card)
    frames(orb, card, lambda: S.push is None)
    assert frame(dummy).left == before, "put-back didn't restore the window"
    report(fps)
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    u32.SetProcessDpiAwarenessContext(w.HANDLE(-4))  # per-monitor v2: real pixels
    orb = make_window("SwiftSpikeOrb", 0x00FFB060, ORB, ORB, OVERLAY_EX)
    u32.SetWindowRgn(orb, gdi.CreateEllipticRgn(0, 0, ORB, ORB), True)
    card = make_window("SwiftSpikeCard", 0x00302820, CARD_W, 200, OVERLAY_EX)
    u32.ShowWindow(orb, 4)
    try:
        if args.selftest:
            return selftest(orb, card)
        fg = u32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
                                 None, _on_event, 0, 0, 0)
        for hot_id, key in ((1, "P"), (2, "S"), (3, "Q")):
            if not u32.RegisterHotKey(None, hot_id, 0x1 | 0x2, ord(key)):
                print(f"Ctrl+Alt+{key} is taken by another app")
        if u32.GetForegroundWindow():
            follow(u32.GetForegroundWindow())
        print("Drag a window. Ctrl+Alt+P push, Ctrl+Alt+S spring/rigid, Ctrl+Alt+Q quit.")
        fps = 0.0
        try:
            fps = frames(orb, card, lambda: False)
        except KeyboardInterrupt:
            pass
        u32.UnhookWinEvent(fg)
        report(fps)
    finally:
        if S.push:  # never leave the owner's window where the spike put it
            u32.SetWindowPos(S.push["hwnd"], None, S.push["x0"], S.push["y0"], 0, 0,
                             SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        for hwnd in S.own:
            u32.DestroyWindow(hwnd)


if __name__ == "__main__":
    main()
