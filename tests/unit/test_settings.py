from __future__ import annotations

from pathlib import Path

import pytest

from swift.settings import Settings, SettingsError, load_settings

EXAMPLE = Path(__file__).resolve().parents[2] / "config.example.yaml"


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    s = load_settings(tmp_path / "nope.yaml")
    assert s == Settings()
    assert s.executor.allowed_tools == ["Read", "Glob", "Grep"]
    assert s.hotkeys.push_to_talk == "Ctrl+Shift+Space"


def test_example_file_is_valid() -> None:
    s = load_settings(EXAMPLE)
    assert s.stt.model == "small.en"


def test_env_refs_expand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWIFT_TEST_DIR", "C:/x")
    f = tmp_path / "c.yaml"
    f.write_text("logging:\n  interactions: '%SWIFT_TEST_DIR%/i.jsonl'\n", encoding="utf-8")
    assert load_settings(f).logging.interactions == "C:/x/i.jsonl"


def test_default_paths_are_expanded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", "C:/la")
    s = load_settings(None)
    assert s.logging.interactions == "C:/la/Swift/interactions.jsonl"
    assert s.stt.audio_dir == "C:/la/Swift/audio"
    assert s.demand_classifier.model_dir == "C:/la/Swift/models/bge-small-en-v1.5"


def test_unset_localappdata_falls_back_to_the_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    s = load_settings(None)
    assert s.logging.interactions == str(Path.home() / "AppData" / "Local") + "/Swift/interactions.jsonl"
    assert "%" not in s.logging.app_log_dir


def test_unset_other_variable_is_a_settings_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWIFT_TEST_MISSING", raising=False)
    f = tmp_path / "c.yaml"
    f.write_text("logging:\n  interactions: '%SWIFT_TEST_MISSING%/i.jsonl'\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="SWIFT_TEST_MISSING"):
        load_settings(f)


@pytest.mark.parametrize(
    "text",
    [
        "stt:\n  model: large-v3\n",
        "hotkeys:\n  push_to_talk: Ctrl+Space\n  surprise: 1\n",
        "unknown_section: {}\n",
        "- a list\n",
        "stt: [unclosed\n",
    ],
)
def test_invalid_file_refuses_to_start(tmp_path: Path, text: str) -> None:
    f = tmp_path / "c.yaml"
    f.write_text(text, encoding="utf-8")
    with pytest.raises(SettingsError):
        load_settings(f)


def test_audio_preroll_defaults_off_and_is_bounded(tmp_path: Path) -> None:
    assert Settings().audio.preroll_s == 0.0
    f = tmp_path / "config.yaml"
    f.write_text("audio:\n  preroll_s: 0.5\n", encoding="utf-8")
    assert load_settings(f).audio.preroll_s == 0.5
    f.write_text("audio:\n  preroll_s: 30\n", encoding="utf-8")
    with pytest.raises(SettingsError):
        load_settings(f)
