"""T0-04 (§12, §8.3): config defaults, per-section fallback, fail-closed permissions."""

from __future__ import annotations

import tomllib

import pytest

from swift.config import defaults
from swift.config.loader import load_all
from swift.config.models import AliasesSeed, PermissionsConfig, ProfilesConfig, SwiftConfig
from swift.config.paths import AppPaths

NO_ENV: dict[str, str] = {}


@pytest.mark.parametrize(
    ("template", "model"),
    [
        (defaults.CONFIG_TOML, SwiftConfig),
        (defaults.PERMISSIONS_TOML, PermissionsConfig),
        (defaults.PROFILES_TOML, ProfilesConfig),
        (defaults.ALIASES_TOML, AliasesSeed),
    ],
)
def test_templates_match_model_defaults(template: str, model: type) -> None:
    assert model.model_validate(tomllib.loads(template)) == model()


def test_first_run_writes_commented_defaults(paths: AppPaths) -> None:
    result = load_all(paths, env=NO_ENV)
    assert result.issues == []
    assert result.config == SwiftConfig()
    assert result.permissions == PermissionsConfig()
    assert not result.permissions.fail_closed
    for f in (paths.config_file, paths.permissions_file, paths.profiles_file, paths.aliases_file):
        assert f.exists()
        assert f.read_text(encoding="utf-8").startswith("#")


def test_existing_files_are_not_overwritten(paths: AppPaths) -> None:
    paths.config_dir.mkdir(parents=True)
    paths.config_file.write_text("schema_version = 1\n[wake]\nthreshold = 0.7\n", encoding="utf-8")
    result = load_all(paths, env=NO_ENV)
    assert result.config.wake.threshold == 0.7
    assert "threshold = 0.7" in paths.config_file.read_text(encoding="utf-8")


def test_invalid_section_falls_back_alone(paths: AppPaths) -> None:
    paths.config_dir.mkdir(parents=True)
    paths.config_file.write_text(
        "schema_version = 1\n[wake]\nthreshold = 7\n[vad]\nend_silence_s = 1.2\n", encoding="utf-8"
    )
    result = load_all(paths, env=NO_ENV)
    assert result.config.wake == SwiftConfig().wake
    assert result.config.vad.end_silence_s == 1.2
    assert [(i.file, i.section) for i in result.issues] == [("config.toml", "wake")]


def test_unknown_key_is_reported(paths: AppPaths) -> None:
    paths.config_dir.mkdir(parents=True)
    paths.config_file.write_text("schema_version = 1\n[wake]\nthreshhold = 0.6\n[bogus]\nx = 1\n", encoding="utf-8")
    result = load_all(paths, env=NO_ENV)
    sections = {i.section for i in result.issues}
    assert sections == {"wake", "bogus"}


def test_unparseable_config_uses_defaults(paths: AppPaths) -> None:
    paths.config_dir.mkdir(parents=True)
    paths.config_file.write_text("this is = = not toml", encoding="utf-8")
    result = load_all(paths, env=NO_ENV)
    assert result.config == SwiftConfig()
    assert result.issues and result.issues[0].file == "config.toml"


def test_cloud_llm_only_off(paths: AppPaths) -> None:
    paths.config_dir.mkdir(parents=True)
    paths.config_file.write_text('schema_version = 1\n[privacy]\ncloud_llm = "on"\n', encoding="utf-8")
    result = load_all(paths, env=NO_ENV)
    assert result.config.privacy.cloud_llm == "off"
    assert result.issues[0].section == "privacy"


@pytest.mark.parametrize(
    "content",
    [
        "not = = toml",
        "[files]\nmax_file_mb = 5\n",  # missing schema_version
        "schema_version = 99\n",
        'schema_version = 1\n[confirm]\nhigh_risk_mode = "always_yes"\n',
        "schema_version = 1\n[files]\nunknown = 1\n",
        "schema_version = 1\nfail_closed = false\n",
    ],
)
def test_bad_permissions_fail_closed(paths: AppPaths, content: str) -> None:
    paths.config_dir.mkdir(parents=True)
    paths.permissions_file.write_text(content, encoding="utf-8")
    result = load_all(paths, env=NO_ENV)
    assert result.permissions.fail_closed
    assert any(i.file == "permissions.toml" for i in result.issues)


def test_fail_closed_is_not_serialized() -> None:
    assert "fail_closed" not in PermissionsConfig.failed_closed().model_dump()


def test_invalid_project_dropped(paths: AppPaths) -> None:
    paths.config_dir.mkdir(parents=True)
    paths.profiles_file.write_text(
        "schema_version = 1\n"
        '[projects.good]\npath = "C:/p"\ndefault = true\n'
        '[projects.good.tasks.tests]\nargv = ["C:/p/python.exe", "-m", "pytest"]\n'
        '[projects.bad.tasks.tests]\nargv = []\n',
        encoding="utf-8",
    )
    result = load_all(paths, env=NO_ENV)
    assert set(result.profiles.projects) == {"good"}
    assert result.profiles.projects["good"].tasks["tests"].timeout_s == 600
    assert result.issues[0].section == "projects.bad"


def test_two_default_projects_rejected(paths: AppPaths) -> None:
    paths.config_dir.mkdir(parents=True)
    paths.profiles_file.write_text(
        'schema_version = 1\n[projects.a]\npath = "C:/a"\ndefault = true\n'
        '[projects.b]\npath = "C:/b"\ndefault = true\n',
        encoding="utf-8",
    )
    result = load_all(paths, env=NO_ENV)
    assert result.profiles.projects == {}
    assert result.issues


def test_env_override(paths: AppPaths) -> None:
    env = {"SWIFT_WAKE__THRESHOLD": "0.65", "SWIFT_STT__MODEL": "small.en", "SWIFT_CONFIG_DIR": "ignored"}
    result = load_all(paths, env=env)
    assert result.config.wake.threshold == 0.65
    assert result.config.stt.model == "small.en"
    assert result.issues == []


def test_write_defaults_false_leaves_disk_untouched(paths: AppPaths) -> None:
    result = load_all(paths, write_defaults=False, env=NO_ENV)
    assert result.config == SwiftConfig()
    assert not paths.config_dir.exists()
