from __future__ import annotations

from pathlib import Path

import pytest

from swift.settings import Settings, SettingsError, load_settings

EXAMPLE = Path(__file__).resolve().parents[2] / "config.example.yaml"


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    s = load_settings(tmp_path / "nope.yaml")
    assert s == Settings()
    assert s.executor.allowed_tools == ["Read", "Glob", "Grep"]
    assert s.hotkeys.push_to_talk == "Ctrl+Alt+Space"


def test_example_file_is_valid() -> None:
    s = load_settings(EXAMPLE)
    assert s.stt.model == "base.en"


def test_env_refs_expand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWIFT_TEST_DIR", "C:/x")
    f = tmp_path / "c.yaml"
    f.write_text("logging:\n  interactions: '%SWIFT_TEST_DIR%/i.jsonl'\n", encoding="utf-8")
    assert load_settings(f).logging.interactions == "C:/x/i.jsonl"


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
