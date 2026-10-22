"""MVP configuration from ``config.yaml`` (PLAN.md §8, ADR-006).

A missing file gives the defaults. An invalid file is an error: Swift
refuses to start rather than run with settings the owner didn't intend.
``%VAR%`` references in paths are expanded from the environment.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_ENV_REF = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")


def expand(value: str) -> str:
    return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Hotkeys(_Section):
    push_to_talk: str = "Ctrl+Alt+Space"
    debug: str = "Ctrl+Alt+F12"


class SttSettings(_Section):
    model: Literal["base.en", "small.en"] = "base.en"
    cpu_threads: int = Field(4, ge=1, le=32)
    initial_prompt: str = ""


class ExecutorSettings(_Section):
    kind: Literal["mock", "claude_code"] = "mock"
    allowed_tools: list[str] = Field(default_factory=lambda: ["Read", "Glob", "Grep"])
    working_dirs: list[str] = Field(default_factory=list)
    default_dir: int = Field(0, ge=0)
    max_budget_usd: float | None = Field(1.0, gt=0)
    confirm_timeout_s: float = Field(120.0, gt=0)


class LoggingSettings(_Section):
    interactions: str = "%LOCALAPPDATA%/Swift/interactions.jsonl"
    app_log_dir: str = "%LOCALAPPDATA%/Swift/logs"
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("interactions", "app_log_dir")
    @classmethod
    def _expand(cls, v: str) -> str:
        return expand(v)


class Settings(_Section):
    hotkeys: Hotkeys = Field(default_factory=Hotkeys)
    stt: SttSettings = Field(default_factory=SttSettings)
    executor: ExecutorSettings = Field(default_factory=ExecutorSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    debug: bool = False


class SettingsError(ValueError):
    pass


def load_settings(path: Path | None) -> Settings:
    if path is None or not path.exists():
        return Settings()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SettingsError(f"{path.name}: cannot read: {exc}") from None
    if not isinstance(data, dict):
        raise SettingsError(f"{path.name}: top level must be a mapping")
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()
        )
        raise SettingsError(f"{path.name}: {problems}") from None
