"""Load and validate the config files (§12).

Error handling:
- ``permissions.toml``: any problem fails closed (§8.3).
- ``config.toml``: an invalid section falls back to its defaults.
- ``profiles.toml``: an invalid project is dropped.
- ``aliases.toml``: an invalid file yields no seed aliases.
Every problem is returned as a ``ConfigIssue`` for the tray and the log.

``SWIFT_<SECTION>__<KEY>`` environment variables override ``config.toml``
values for development only.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from swift.config import defaults
from swift.config.models import (
    ALIASES_SCHEMA_VERSION,
    CONFIG_SCHEMA_VERSION,
    PERMISSIONS_SCHEMA_VERSION,
    PROFILES_SCHEMA_VERSION,
    AliasesSeed,
    PermissionsConfig,
    ProfilesConfig,
    ProjectProfile,
    SwiftConfig,
)
from swift.config.paths import AppPaths

ENV_PREFIX = "SWIFT_"


@dataclass(frozen=True)
class ConfigIssue:
    file: str
    section: str | None
    message: str


@dataclass
class LoadResult:
    config: SwiftConfig
    permissions: PermissionsConfig
    profiles: ProfilesConfig
    aliases: AliasesSeed
    issues: list[ConfigIssue] = field(default_factory=list)


def _short_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


def _read(path: Path, template: str, write_defaults: bool, issues: list[ConfigIssue]) -> dict[str, Any] | None:
    """Return the parsed TOML table, or None if it is unreadable."""
    if not path.exists():
        if not write_defaults:
            return tomllib.loads(template)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template, encoding="utf-8")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        issues.append(ConfigIssue(path.name, None, f"cannot parse: {exc}"))
        return None


def _check_version(data: dict[str, Any], expected: int, name: str, issues: list[ConfigIssue]) -> bool:
    version = data.pop("schema_version", None)
    if version == expected:
        return True
    issues.append(ConfigIssue(name, "schema_version", f"expected {expected}, found {version!r}"))
    return False


def _env_overrides(env: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, raw in env.items():
        if not name.upper().startswith(ENV_PREFIX) or "__" not in name:
            continue
        section, _, key = name[len(ENV_PREFIX):].lower().partition("__")
        try:
            value: Any = tomllib.loads(f"v = {raw}")["v"]
        except tomllib.TOMLDecodeError:
            value = raw
        out.setdefault(section, {})[key] = value
    return out


def _load_config(paths: AppPaths, write_defaults: bool, env: Mapping[str, str], issues: list[ConfigIssue]) -> SwiftConfig:
    name = paths.config_file.name
    data = _read(paths.config_file, defaults.CONFIG_TOML, write_defaults, issues)
    if data is None:
        return SwiftConfig()
    if not _check_version(data, CONFIG_SCHEMA_VERSION, name, issues):
        return SwiftConfig()

    for section, values in _env_overrides(env).items():
        data.setdefault(section, {})
        if isinstance(data[section], dict):
            data[section].update(values)

    sections: dict[str, BaseModel] = {}
    for key, value in data.items():
        info = SwiftConfig.model_fields.get(key)
        if info is None or key == "schema_version":
            issues.append(ConfigIssue(name, key, "unknown section (ignored)"))
            continue
        model: type[BaseModel] = info.annotation  # type: ignore[assignment]
        try:
            sections[key] = model.model_validate(value)
        except ValidationError as exc:
            issues.append(ConfigIssue(name, key, f"invalid, using defaults: {_short_error(exc)}"))
    return SwiftConfig(**sections)


def _load_permissions(paths: AppPaths, write_defaults: bool, issues: list[ConfigIssue]) -> PermissionsConfig:
    name = paths.permissions_file.name
    data = _read(paths.permissions_file, defaults.PERMISSIONS_TOML, write_defaults, issues)
    if data is None:
        return PermissionsConfig.failed_closed()
    if not _check_version(data, PERMISSIONS_SCHEMA_VERSION, name, issues):
        return PermissionsConfig.failed_closed()
    try:
        return PermissionsConfig.model_validate(data)
    except ValidationError as exc:
        issues.append(ConfigIssue(name, None, f"invalid, failing closed: {_short_error(exc)}"))
        return PermissionsConfig.failed_closed()


def _load_profiles(paths: AppPaths, write_defaults: bool, issues: list[ConfigIssue]) -> ProfilesConfig:
    name = paths.profiles_file.name
    data = _read(paths.profiles_file, defaults.PROFILES_TOML, write_defaults, issues)
    if data is None or not _check_version(data, PROFILES_SCHEMA_VERSION, name, issues):
        return ProfilesConfig()

    for key in data.keys() - {"projects"}:
        issues.append(ConfigIssue(name, key, "unknown section (ignored)"))
    raw_projects = data.get("projects", {})
    if not isinstance(raw_projects, dict):
        issues.append(ConfigIssue(name, "projects", "must be a table; ignoring"))
        return ProfilesConfig()

    projects: dict[str, ProjectProfile] = {}
    for pid, value in raw_projects.items():
        try:
            projects[pid] = ProjectProfile.model_validate(value)
        except ValidationError as exc:
            issues.append(ConfigIssue(name, f"projects.{pid}", f"invalid, ignored: {_short_error(exc)}"))
    try:
        return ProfilesConfig(projects=projects)
    except ValidationError as exc:
        issues.append(ConfigIssue(name, "projects", f"invalid, ignoring all projects: {_short_error(exc)}"))
        return ProfilesConfig()


def _load_aliases(paths: AppPaths, write_defaults: bool, issues: list[ConfigIssue]) -> AliasesSeed:
    name = paths.aliases_file.name
    data = _read(paths.aliases_file, defaults.ALIASES_TOML, write_defaults, issues)
    if data is None or not _check_version(data, ALIASES_SCHEMA_VERSION, name, issues):
        return AliasesSeed()
    try:
        return AliasesSeed.model_validate(data)
    except ValidationError as exc:
        issues.append(ConfigIssue(name, None, f"invalid, ignored: {_short_error(exc)}"))
        return AliasesSeed()


def load_all(paths: AppPaths, *, write_defaults: bool = True, env: Mapping[str, str] = os.environ) -> LoadResult:
    issues: list[ConfigIssue] = []
    return LoadResult(
        config=_load_config(paths, write_defaults, env, issues),
        permissions=_load_permissions(paths, write_defaults, issues),
        profiles=_load_profiles(paths, write_defaults, issues),
        aliases=_load_aliases(paths, write_defaults, issues),
        issues=issues,
    )
