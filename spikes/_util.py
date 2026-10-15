"""Shared helpers for Phase 0 spikes. Throwaway code: never imported by src/swift."""

from __future__ import annotations

import json
import math
import os
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

SPIKES_DIR = Path(__file__).resolve().parent


def models_dir() -> Path:
    """Model store per §11: %LOCALAPPDATA%\\Swift\\models."""
    d = Path(os.environ["LOCALAPPDATA"]) / "Swift" / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pct(values: list[float], q: float) -> float:
    """Nearest-rank percentile (no interpolation; honest for small n)."""
    s = sorted(values)
    k = max(1, math.ceil(q / 100 * len(s)))
    return s[k - 1]


def summarize(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "p50": round(pct(values, 50), 4),
        "p90": round(pct(values, 90), 4),
        "mean": round(statistics.fmean(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def machine_info() -> dict[str, Any]:
    batt = psutil.sensors_battery()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "available_ram_gb": round(psutil.virtual_memory().available / 2**30, 1),
        "power": None if batt is None else ("AC" if batt.power_plugged else "battery"),
        "battery_percent": None if batt is None else batt.percent,
        "python": platform.python_version(),
    }


def private_mb(proc: psutil.Process | None = None) -> float:
    """Private bytes (Windows) of a process, in MiB."""
    proc = proc or psutil.Process()
    mi = proc.memory_info()
    return round(getattr(mi, "private", mi.rss) / 2**20, 1)


def write_result(spike: str, name: str, data: dict[str, Any]) -> Path:
    out_dir = SPIKES_DIR / spike / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{name}-{stamp}.json"
    payload = {"machine": machine_info(), **data}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {path}")
    return path


class Timer:
    def __enter__(self) -> Timer:
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed = time.perf_counter() - self.start
