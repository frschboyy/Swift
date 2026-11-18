"""Call / screen-share detector spike (Halo A3). Read only, stdlib only (winreg, ctypes).

    python spikes/calls/probe.py            # one snapshot + poll cost
    python spikes/calls/probe.py --watch 60 # print a line whenever a signal changes
"""
import argparse, ctypes, sys, time, winreg
from ctypes import wintypes as wt

CS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
u32, sh = ctypes.windll.user32, ctypes.windll.shell32
CALL_WORDS = ("meet -", "meet.google", "| microsoft teams", "zoom meeting", "zoom workplace", "discord", "teams meeting")
SHARE_WORDS = ("sharing toolbar", "you're sharing", "is sharing your screen", "stop sharing", "presenting", "slide show")
QUNS = {1: "NOT_PRESENT", 2: "BUSY", 3: "RUNNING_D3D_FULL_SCREEN", 4: "PRESENTATION_MODE", 5: "ACCEPTS_NOTIFICATIONS", 6: "QUIET_TIME", 7: "APP"}


def consent(cap: str) -> dict[str, tuple[int, int]]:
    """app -> (start, stop) FILETIMEs for apps whose capture stream is active (Stop == 0)."""
    out = {}
    def scan(path, prefix=""):
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return
        with k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                name = winreg.EnumKey(k, i)
                if name == "NonPackaged":
                    scan(path + "\\" + name, "np:")
                    continue
                try:
                    with winreg.OpenKey(k, name) as a:
                        s = winreg.QueryValueEx(a, "LastUsedTimeStart")[0]
                        e = winreg.QueryValueEx(a, "LastUsedTimeStop")[0]
                    out[prefix + name.split("#")[-1]] = (s, e)
                except OSError:
                    pass
    scan(CS + "\\" + cap)
    return out


def running() -> set[str]:
    import psutil  # project venv has it; stale keys need a liveness check
    return {(p.info["name"] or "").lower() for p in psutil.process_iter(["name"])}


def mic_active(alive_only: bool = True) -> list[str]:
    """Apps with an open capture stream. Stop==0 is also left behind by killed apps, so filter by process."""
    up = running() if alive_only else None
    return sorted(a for a, (s, e) in consent("microphone").items() if s and e == 0
                  and (up is None or a.split(":")[-1].lower() in up or "_" in a))


def cam_active() -> list[str]:
    return sorted(a for a, (s, e) in consent("webcam").items() if s and e == 0)


def quns() -> str:
    st = ctypes.c_int()
    sh.SHQueryUserNotificationState(ctypes.byref(st))
    return QUNS.get(st.value, str(st.value))


def titles() -> list[str]:
    res = []
    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        if u32.IsWindowVisible(h):
            n = u32.GetWindowTextLengthW(h)
            if n:
                b = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(h, b, n + 1)
                res.append(b.value)
        return True
    u32.EnumWindows(cb, 0)
    return res


def hits(words) -> list[str]:
    return [t for t in titles() if any(w in t.lower() for w in words)]


def snapshot() -> dict:
    return {"mic": mic_active(), "cam": cam_active(), "quns": quns(),
            "call_titles": hits(CALL_WORDS), "share_titles": hits(SHARE_WORDS)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--watch", type=int, default=0)
    n = ap.parse_args().watch
    if n:
        last, end = None, time.time() + n
        while time.time() < end:
            s = snapshot()
            if s != last:
                print(time.strftime("%H:%M:%S"), s, flush=True); last = s
            time.sleep(1)
        sys.exit()
    print(snapshot())
    for name, f in (("mic reg", mic_active), ("quns", quns), ("EnumWindows", titles)):
        t = time.perf_counter()
        for _ in range(50): f()
        print(f"{name}: {(time.perf_counter()-t)/50*1000:.2f} ms/poll")
    print("all mic apps:", {k: v[1] == 0 for k, v in consent("microphone").items()})
