"""Local "open ..." handlers (ADR-007): narrow patterns, config-only targets, launcher mocked."""

from __future__ import annotations

from pathlib import Path

import pytest

from swift.routing import route
from swift.routing.local import LocalOpener, OpenTarget
from swift.settings import Settings
from tests.unit.test_routing import SpyExecutor, ask  # noqa: F401
from swift.executors.mock import MockExecutor
from swift.ipc.protocol import Message  # noqa: F401
from swift.session import Session

from tests.unit.test_routing import Recorder


class FakeOpener(LocalOpener):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.launched: list[OpenTarget] = []
        self.fail = False

    def launch(self, target: OpenTarget) -> None:
        if self.fail:
            raise OSError("nope")
        self.launched.append(target)


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for d in ("Downloads", "Documents", "proj/Swift", "Lectures"):
        (tmp_path / d).mkdir(parents=True)
    return Settings.model_validate(
        {
            "executor": {"working_dirs": [str(tmp_path / "proj" / "Swift")]},
            "local": {"folders": {"lecture notes": str(tmp_path / "Lectures")}},
        }
    )


def resolve(settings: Settings, text: str) -> OpenTarget | None:
    return LocalOpener(settings).resolve(route(text))


@pytest.mark.parametrize(
    "text",
    [
        "Open my downloads folder.",
        "launch chrome",
        "Hey Swift open the swift project in VS Code",
        "Bring up VS Code for my project.",
        "open notepad",
    ],
)
def test_open_requests_route_local(text: str) -> None:
    r = route(text)
    assert r.route == "local" and r.action == "open" and r.target


@pytest.mark.parametrize(
    "text",
    [
        "Open the Trading project and run the backtest",
        "open the file and fix the typo in it",
        "launch the tests then tell me what failed",
        "open the folder to see what is in it",
        "Open",
    ],
)
def test_compound_requests_stay_with_claude(text: str) -> None:
    assert route(text).route == "agent"


def test_targets_resolve_from_config(settings: Settings, tmp_path: Path) -> None:
    t = resolve(settings, "open my downloads folder")
    assert (t.kind, t.path) == ("folder", str(tmp_path / "Downloads"))
    assert resolve(settings, "open the lecture notes folder").path == str(tmp_path / "Lectures")
    assert resolve(settings, "launch Chrome").kind == "app"
    p = resolve(settings, "open the swift project")
    assert (p.kind, p.app) == ("project", "code")
    assert resolve(settings, "open the Swift project in Chrome").app == "chrome"
    assert resolve(settings, "bring up VS Code for the swift project").app == "code"


@pytest.mark.parametrize(
    "text",
    ["open the thesis project", "launch my IDE", "open regedit", "open the pictures folder", "open notepad in chrome", "open cmd", "open a pull request for this branch"],
)
def test_unknown_targets_resolve_to_nothing(settings: Settings, text: str) -> None:
    assert resolve(settings, text) is None


def test_missing_folder_does_not_resolve(settings: Settings, tmp_path: Path) -> None:
    (tmp_path / "Downloads").rmdir()
    assert resolve(settings, "open downloads") is None


def test_disabled(settings: Settings) -> None:
    off = Settings.model_validate({"local": {"enabled": False}})
    assert LocalOpener(off).resolve(route("launch chrome")) is None


def make_session(opener: LocalOpener | None):
    rec, records, spy = Recorder(), [], SpyExecutor()
    session = Session(rec, spy, debug_executor=MockExecutor(speed=0), on_finish=records.append, opener=opener)
    session._test = (rec, spy, records)  # type: ignore[attr-defined]
    return session, rec, spy, records


async def test_open_runs_locally_and_is_logged(settings: Settings) -> None:
    opener = FakeOpener(settings)
    session, rec, spy, records = make_session(opener)
    await ask("Open my downloads folder.", session)
    assert spy.calls == [] and [t.name for t in opener.launched] == ["downloads"]
    assert rec.last("result")["summary"] == "Opened Downloads."
    assert (records[0]["route"], records[0]["action"], records[0]["target"]) == ("local", "open", "downloads")


async def test_unknown_target_falls_through_to_claude(settings: Settings) -> None:
    opener = FakeOpener(settings)
    session, _, spy, records = make_session(opener)
    await ask("Hey Swift open the thesis project.", session)
    assert opener.launched == [] and spy.calls and spy.calls[0][0] == "open the thesis project."
    assert records[0]["route"] == "agent" and "target" not in records[0]


async def test_no_opener_falls_through(settings: Settings) -> None:
    session, _, spy, _ = make_session(None)
    await ask("launch chrome", session)
    assert len(spy.calls) == 1


async def test_launch_failure_shows_an_error(settings: Settings) -> None:
    opener = FakeOpener(settings)
    opener.fail = True
    session, rec, spy, records = make_session(opener)
    await ask("launch chrome", session)
    assert spy.calls == [] and rec.last("error")["code"] == "open_failed" and records[0]["status"] == "error"

