"""The dev harness never touches the owner's data (QA 3, finding 1).

The debug backend started from ``overlay/dev/harness-config.yaml`` once swept the owner's real recordings
folder and deleted 10 clips: the config moved the logs to ``%TEMP%`` but left ``stt.audio_dir`` at its
default. These tests resolve every path setting the harness loads, found from the settings model itself so
a new one can't be missed, and fail if any lands in ``%LOCALAPPDATA%\\Swift`` or ``%APPDATA%\\Swift``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic import AfterValidator, BaseModel

from swift.settings import Settings, _env_value, expand, load_settings

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "overlay" / "dev" / "harness-config.yaml"
LAUNCH = ROOT / ".claude" / "launch.json"


def _owner_folders() -> list[str]:
    return [os.path.normcase(os.path.realpath(Path(_env_value(v)) / "Swift")) for v in ("LOCALAPPDATA", "APPDATA")]


def _path_settings(model: BaseModel, prefix: str = "") -> dict[str, str]:
    """Every ``Expanded`` setting (a path), by dotted name, in a settings model and its sections."""
    out: dict[str, str] = {}
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            out |= _path_settings(value, f"{prefix}{name}.")
        elif any(isinstance(m, AfterValidator) and m.func is expand for m in field.metadata):
            out[f"{prefix}{name}"] = value
    return out


def _inside(path: str, folder: str) -> bool:
    p = os.path.normcase(os.path.realpath(path))
    return p == folder or p.startswith(folder.rstrip("\\/") + os.sep)


def test_the_walk_finds_the_path_settings() -> None:
    found = _path_settings(Settings())
    for name in ("stt.audio_dir", "stt.test_set_dir", "logging.runs", "memory_dir", "system.schedule_file"):
        assert name in found


# Settings Swift only reads from, never writes: the harness keeps their defaults, so it routes as the app does.
READ_ONLY = {"demand_classifier.model_dir"}


def test_no_harness_path_is_in_the_owner_s_data() -> None:
    settings = load_settings(HARNESS)
    owner = _owner_folders()
    leaks = {name: p for name, p in _path_settings(settings).items()
             if name not in READ_ONLY and any(_inside(p, f) for f in owner)}
    assert not leaks, f"harness-config.yaml leaves these in the owner's Swift folders: {sorted(leaks)}"


def test_the_read_only_settings_are_only_models() -> None:
    # The exception covers model folders only: one that held the owner's data would need its own %TEMP% path.
    # As written, not realpath: an app sandbox redirects real folders, so realpath can land in its own copy.
    models = Path(os.path.normcase(os.path.normpath(Path(_env_value("LOCALAPPDATA")) / "Swift" / "models")))
    paths = _path_settings(load_settings(HARNESS))
    inside = {name: models in Path(os.path.normcase(os.path.normpath(paths[name]))).parents for name in READ_ONLY}
    assert all(inside.values()), {name: paths[name] for name in READ_ONLY}


def test_the_backend_harness_launch_entry_loads_that_config() -> None:
    entry = next(c for c in json.loads(LAUNCH.read_text(encoding="utf-8"))["configurations"] if c["name"] == "backend-harness")
    args = " ".join(entry.get("runtimeArgs", []))
    config = re.search(r"'--config',\s*'([^']+)'", args)
    assert config and (ROOT / config.group(1)).resolve() == HARNESS.resolve(), "backend-harness must load harness-config.yaml"
    owner = _owner_folders()
    for key, value in (entry.get("env") or {}).items():
        assert not any(_inside(expand(value), f) for f in owner), f"backend-harness env {key} points into the owner's data"
