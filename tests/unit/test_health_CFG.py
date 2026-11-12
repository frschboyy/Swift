"""Health audit 2026-11-12, group CFG: repros. Each is a strict xfail that flips when fixed."""

from __future__ import annotations

from pathlib import Path

import pytest

from swift.config.paths import app_paths
from swift.executors.claude_code import ClaudeCodeExecutor, _Run
from swift.routing.light import kind
from swift.routing.local import LocalOpener
from swift.routing.rules import route
from swift.settings import Settings, expand


def test_allowed_tools_setting_cannot_pre_approve_writing_tools(tmp_path: Path) -> None:
    cfg = Settings.model_validate({"executor": {"allowed_tools": ["Read", "Glob", "Grep", "Bash", "Write"]}}).executor
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), allowed_tools=cfg.allowed_tools, confirm_tools=cfg.confirm_tools,
                            claude="claude.exe")
    opts = ex.options(_Run(), "cc-1")
    # Pre-approved tools never reach can_use_tool, so "rm file" in Bash would run without a card.
    assert "Bash" not in opts.allowed_tools and "Write" not in opts.allowed_tools
    assert {"Bash", "Write"} <= set(ex.confirm_tools)  # still usable, each call on a card


def test_a_web_tool_in_the_setting_is_still_checked_per_call(tmp_path: Path) -> None:
    # Pre-approved, WebFetch skipped _ask's checks: an address the owner didn't give, a workflow's manifest.
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), allowed_tools=["Read", "WebFetch", "WebSearch"], claude="claude.exe")
    opts = ex.options(_Run(), "cc-1")
    assert not {"WebFetch", "WebSearch"} & set(opts.allowed_tools) and "WebFetch" in opts.tools


@pytest.mark.xfail(strict=True, reason="HA-CFG-02: 'is it X or Y' sends weather/date questions to the tool-free lane")
@pytest.mark.parametrize("text", ["is it raining or sunny today", "is it cold or warm in london", "is it monday or tuesday"])
def test_now_questions_do_not_take_the_quick_lane(text: str) -> None:
    assert kind(text) is None and route(text).action != "quick"


@pytest.mark.xfail(strict=True, reason="HA-CFG-03: a partial executor.models drops 'light'; startup indexes it directly")
def test_partial_models_setting_keeps_light() -> None:
    models = Settings.model_validate({"executor": {"models": {"standard": "claude-sonnet-5-5"}}}).executor.models
    models["light"]  # backend/__main__.py: QuickModel(settings.executor.models["light"], ...)


@pytest.mark.xfail(strict=True, reason="HA-CFG-04: 'open this' on a selected .py script resolves to os.startfile")
def test_open_selected_script_is_refused(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text("print(1)\n")
    assert LocalOpener(Settings()).resolve_files([str(script)]) is None


@pytest.mark.xfail(strict=True, reason="HA-CFG-05: app_paths raises on a bare environment that settings.expand handles")
def test_app_paths_and_settings_agree_on_a_bare_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    expand("%LOCALAPPDATA%/Swift")  # settings: falls back under the profile
    app_paths({})  # main() calls this right after load_settings, outside any SWIFT_BACKEND_ERROR handler
