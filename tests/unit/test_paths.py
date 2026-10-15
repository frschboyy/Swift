"""T0-05 (§12): config and data locations."""

from __future__ import annotations

from pathlib import Path

import pytest

from swift.config.paths import app_paths

WIN_ENV = {"APPDATA": r"C:\Users\u\AppData\Roaming", "LOCALAPPDATA": r"C:\Users\u\AppData\Local"}


def test_default_locations() -> None:
    p = app_paths(WIN_ENV)
    assert p.config_dir == Path(WIN_ENV["APPDATA"]) / "Swift"
    assert p.data_dir == Path(WIN_ENV["LOCALAPPDATA"]) / "Swift"
    assert p.logs_dir == p.data_dir / "logs"
    assert p.models_dir == p.data_dir / "models"
    assert p.db_path == p.data_dir / "swift.db"
    assert p.audit_path == p.data_dir / "audit.jsonl"
    assert p.permissions_file == p.config_dir / "permissions.toml"


def test_dev_overrides(tmp_path: Path) -> None:
    env = dict(WIN_ENV, SWIFT_CONFIG_DIR=str(tmp_path / "c"), SWIFT_DATA_DIR=str(tmp_path / "d"))
    p = app_paths(env)
    assert p.config_dir == tmp_path / "c"
    assert p.data_dir == tmp_path / "d"


def test_missing_profile_env_is_an_error() -> None:
    with pytest.raises(RuntimeError, match="APPDATA"):
        app_paths({})


def test_ensure_dirs(tmp_path: Path) -> None:
    p = app_paths({"SWIFT_CONFIG_DIR": str(tmp_path / "c"), "SWIFT_DATA_DIR": str(tmp_path / "d")})
    p.ensure_dirs()
    assert p.config_dir.is_dir() and p.logs_dir.is_dir() and p.models_dir.is_dir()
