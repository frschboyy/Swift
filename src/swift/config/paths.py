"""Filesystem locations (§11, §12).

Config lives in ``%APPDATA%\\Swift``; data, logs and models in
``%LOCALAPPDATA%\\Swift``. ``SWIFT_CONFIG_DIR`` / ``SWIFT_DATA_DIR`` override
them for development and tests only.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "Swift"


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    logs_dir: Path
    models_dir: Path
    db_path: Path
    audit_path: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def permissions_file(self) -> Path:
        return self.config_dir / "permissions.toml"

    @property
    def profiles_file(self) -> Path:
        return self.config_dir / "profiles.toml"

    @property
    def aliases_file(self) -> Path:
        return self.config_dir / "aliases.toml"

    def ensure_dirs(self) -> None:
        for d in (self.config_dir, self.data_dir, self.logs_dir, self.models_dir):
            d.mkdir(parents=True, exist_ok=True)


def _required(env: Mapping[str, str], name: str) -> Path:
    value = env.get(name)
    if not value:
        raise RuntimeError(f"environment variable {name} is not set; Swift requires Windows user profile paths")
    return Path(value)


def app_paths(env: Mapping[str, str] = os.environ) -> AppPaths:
    if override := env.get("SWIFT_CONFIG_DIR"):
        config_dir = Path(override)
    else:
        config_dir = _required(env, "APPDATA") / APP_DIR_NAME

    if override := env.get("SWIFT_DATA_DIR"):
        data_dir = Path(override)
    else:
        data_dir = _required(env, "LOCALAPPDATA") / APP_DIR_NAME

    return AppPaths(
        config_dir=config_dir,
        data_dir=data_dir,
        logs_dir=data_dir / "logs",
        models_dir=data_dir / "models",
        db_path=data_dir / "swift.db",
        audit_path=data_dir / "audit.jsonl",
    )
