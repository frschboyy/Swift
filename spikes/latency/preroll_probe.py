"""Pre-roll options: key-down to first audio, idle CPU/RAM, and the mic indicator.

Usage: uv run --group spikes python spikes/latency/preroll_probe.py [--reps 8] [--idle-s 10]

Measures, on one audio thread (WASAPI needs that):
  cold      open + start a stream, time to its first block (what MicRecorder does today)
  restart   stream already open, stop() then start(), time to the first block (option B)
  running   stream running all the time; key-down to the next block is at most one block (option A)
For each state it reads Windows' own mic-in-use record (the source of the tray indicator) for
this python.exe, and for the idle states it samples this process' CPU and RAM.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import psutil

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "src"))
from swift.audio.recorder import BLOCK, SAMPLE_RATE, _input_device  # noqa: E402

# sounddevice is imported on the audio thread (in run()): importing it here would initialize
# PortAudio on the main thread and WASAPI then fails with -9999 on the worker.
sd = None


def mic_in_use() -> bool | None:
    """True while Windows counts the mic as in use by this process' app (the tray indicator's source).

    Reads ConsentStore/microphone: LastUsedTimeStop is 0 while a capture stream is active. A
    plain python.exe is listed under NonPackaged by its path; started from the Claude desktop
    app it is attributed to the packaged app's key instead (override with --consent-key).
    """
    import winreg

    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
    for sub in (CONSENT_KEY or sys.executable.replace("\\", "#"),):
        for root in (base + "\\NonPackaged\\" + sub, base + "\\" + sub):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root) as k:
                    return winreg.QueryValueEx(k, "LastUsedTimeStop")[0] == 0
            except OSError:
                continue
    return None


CONSENT_KEY = ""


class Probe:
    def __init__(self) -> None:
        self.first = threading.Event()
        self.t0 = 0.0
        self.first_ms = 0.0
        self.blocks = 0

    def cb(self, indata: np.ndarray, frames: int, t: object, status: object) -> None:
        self.blocks += 1
        if not self.first.is_set():
            self.first_ms = (time.perf_counter() - self.t0) * 1000
            self.first.set()

    def make(self):
        dev, extra = _input_device()
        return sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=BLOCK,
                              device=dev, extra_settings=extra, callback=self.cb)

    def arm(self) -> None:
        self.first.clear()
        self.t0 = time.perf_counter()


def summary(xs: list[float]) -> str:
    return f"median {statistics.median(xs):.0f} ms  min {min(xs):.0f}  max {max(xs):.0f}  (n={len(xs)})"


def idle_cost(seconds: float) -> str:
    p = psutil.Process()
    p.cpu_percent(None)
    time.sleep(seconds)
    return f"CPU {p.cpu_percent(None):.2f}% of one core, RSS {p.memory_info().rss / 2**20:.0f} MB"


def run(reps: int, idle_s: float) -> None:
    global sd
    import sounddevice as sd

    pr = Probe()
    sd.query_devices()
    print(f"idle in-use before: {mic_in_use()}")

    cold = []
    for _ in range(reps):
        pr.arm()
        s = pr.make()
        s.start()
        pr.first.wait(3)
        cold.append(pr.first_ms)
        if len(cold) == 1:
            print(f"cold, mic in use while recording: {mic_in_use()}")
        s.stop()
        s.close()
        time.sleep(0.3)
    print(f"cold open+start  : {summary(cold)}")
    time.sleep(0.5)
    print(f"cold, after close, in use: {mic_in_use()}")

    s = pr.make()
    restart = []
    s.start()
    pr.first.wait(3)
    s.stop()
    print(f"opened, stopped, in use: {mic_in_use()}")
    print(f"stopped-stream idle : {idle_cost(idle_s)}")
    for _ in range(reps):
        time.sleep(0.3)
        pr.arm()
        s.start()
        pr.first.wait(3)
        restart.append(pr.first_ms)
        s.stop()
    print(f"restart start()  : {summary(restart)}")
    time.sleep(0.5)
    print(f"after restart test (stopped), in use: {mic_in_use()}")
    s.close()

    s = pr.make()
    s.start()
    time.sleep(0.5)
    print(f"running, in use: {mic_in_use()}")
    gaps = []
    for _ in range(reps * 4):
        time.sleep(0.137)
        pr.arm()
        pr.first.wait(1)
        gaps.append(pr.first_ms)
    print(f"running: key-down to next block: {summary(gaps)}")
    print(f"running-stream idle : {idle_cost(idle_s)}")
    s.stop()
    s.close()
    print(f"baseline idle (no stream): {idle_cost(3)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=8)
    ap.add_argument("--idle-s", type=float, default=10.0)
    ap.add_argument("--consent-key", default="", help="registry key name under ConsentStore\microphone")
    a = ap.parse_args()
    globals()["CONSENT_KEY"] = a.consent_key
    with ThreadPoolExecutor(1, thread_name_prefix="audio") as ex:
        ex.submit(run, a.reps, a.idle_s).result()
