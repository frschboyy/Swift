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


def test_contacts_and_email_connector(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from swift.backend.__main__ import _make_tools
    from swift.connectors.fake import FakeCalendarConnector, FakeMailConnector
    from swift.routing.local import LocalOpener

    f = tmp_path / "c.yaml"
    f.write_text(
        "connectors:\n  email: none\n"
        "contacts:\n  - name: Dr Ada Lovelace\n    email: ada@example.edu\n    aliases: [lecturer]\n"
        f"logging:\n  journal: '{(tmp_path / 'j.jsonl').as_posix()}'\n",
        encoding="utf-8",
    )
    s = load_settings(f)
    assert s.contacts[0].aliases == ["lecturer"]
    opener = LocalOpener(s)
    tools = _make_tools(s, None, opener)
    assert tools.connector is None and tools.calendar is None and tools.opener is opener
    assert "create_calendar_event" in tools.tools and "desktop_write" in tools.tools
    # Debug mode always uses the fake connectors, so a demo never reaches Google.
    debug = s.model_copy(update={"debug": True})
    assert isinstance(_make_tools(debug, None, opener).connector, FakeMailConnector)
    assert isinstance(_make_tools(debug, None, opener).calendar, FakeCalendarConnector)
    bad = tmp_path / "bad.yaml"
    bad.write_text("contacts:\n  - name: X\n    email: not-an-address\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="contacts.0.email"):
        load_settings(bad)


def test_workflow_and_desktop_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from swift.backend.__main__ import _make_library

    monkeypatch.setenv("APPDATA", str(tmp_path))
    s = Settings()
    assert s.workflows.dir == f"{tmp_path}/Swift/workflows" and s.desktop.enabled
    assert s.connectors.calendar == "none"
    library = _make_library(s)
    assert library is not None and "email-draft" in library.packages
    assert _make_library(s.model_copy(update={"workflows": s.workflows.model_copy(update={"enabled": False})})) is None
    f = tmp_path / "c.yaml"
    f.write_text("desktop:\n  never_read_titles: [payroll]\nconnectors:\n  calendar: google\n", encoding="utf-8")
    loaded = load_settings(f)
    assert loaded.desktop.never_read_titles == ["payroll"] and loaded.connectors.calendar == "google"
