"""Sign-ins checked and offered again (``swift.signin``, ``swift.executors.signin``)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import types
from datetime import UTC, datetime, timedelta

import pytest

from swift.executors.base import WorkerTask
from swift.connectors import google
from swift.connectors.base import ConnectorError
from swift.executors.signin import SigninExecutor
from swift.failures import Failure
from swift.signin import SigninWatch, judge_claude
from test_session import answer_confirm, make

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _iso(delta: timedelta) -> str:
    return (NOW + delta).isoformat().replace("+00:00", "Z")


@pytest.mark.parametrize(
    ("data", "status"),
    [
        ({"loggedIn": True, "loginExpiresAt": _iso(timedelta(days=28))}, "ok"),
        ({"loggedIn": True, "loginExpiresAt": _iso(timedelta(days=2))}, "expiring"),
        ({"loggedIn": True, "loginExpiresAt": _iso(-timedelta(minutes=1))}, "expired"),
        ({"loggedIn": False}, "expired"),
        ({"loggedIn": True}, "ok"),
        ({"loggedIn": True, "loginExpiresAt": "soon"}, "ok"),
        ({}, "unknown"),
    ],
)
def test_claude_status_read(data: dict[str, object], status: str) -> None:
    assert judge_claude(data, NOW) == status


async def test_check_offers_only_what_needs_the_owner() -> None:
    offered: list[set[str]] = []
    watch = SigninWatch(offered.append, google=lambda: "expired", claude=lambda: "ok")
    assert await watch.check() == {"google"}
    assert offered == [{"google"}]

    offered.clear()
    watch = SigninWatch(offered.append, google=lambda: "unknown", claude=lambda: "expiring")
    assert await watch.check() == {"claude"}
    assert offered == [{"claude"}]

    offered.clear()
    watch = SigninWatch(offered.append, google=lambda: "absent", claude=None)
    assert await watch.check() == set()
    assert offered == []  # never signed in, or offline: no card


async def test_refused_offers_at_most_every_ten_minutes() -> None:
    offered: list[set[str]] = []
    watch = SigninWatch(offered.append, google=None, claude=None)
    watch.refused("claude")
    watch.refused("claude")
    assert offered == [{"claude"}]


async def test_run_waits_while_busy() -> None:
    checks: list[int] = []
    busy = [True]
    watch = SigninWatch(lambda s: None, google=lambda: checks.append(1) or "ok", claude=None, busy=lambda: busy[0])
    task = asyncio.create_task(watch.run(every_s=100, first_after_s=0, retry_s=0.01))
    await asyncio.sleep(0.05)
    assert checks == []
    busy[0] = False
    await asyncio.sleep(0.1)
    task.cancel()
    assert checks == [1]


# --- the run: one card per sign-in -------------------------------------------


class _Proc:
    def __init__(self, timeout: bool = False) -> None:
        self.timeout = timeout

    def wait(self, timeout: float) -> int:
        if self.timeout:
            raise subprocess.TimeoutExpired("claude", timeout)
        return 0


def _executor(**kw: object) -> tuple[SigninExecutor, dict[str, list[object]]]:
    calls: dict[str, list[object]] = {"google": [], "claude": [], "back": []}

    async def back() -> None:
        calls["back"].append(1)

    args: dict[str, object] = {
        "google_signin": lambda t: calls["google"].append(t),
        "claude": lambda: "claude.exe",
        "claude_check": lambda: "ok",
        "open_claude": lambda path: calls["claude"].append(path) or _Proc(),
        "on_claude_back": back,
        "answer_s": 1.0,
        "signin_s": 1.0,
    } | kw
    return SigninExecutor(**args), calls  # type: ignore[arg-type]


async def _drive(ex: SigninExecutor, answers: dict[str, bool | None]) -> tuple[list[str], str]:
    run_id = await ex.start(WorkerTask("Sign in again"))
    cards: list[str] = []
    async for event in ex.events(run_id):
        if event.type == "confirm":
            cards.append(event.text)
            assert event.request_id is not None
            answer = answers[event.request_id.split(":")[1]]
            if answer is not None:
                await ex.reply(event.request_id, answer)
    return cards, (await ex.result(run_id)).summary


async def test_approved_google_opens_the_consent_page() -> None:
    ex, calls = _executor()
    assert ex.want({"google"})
    cards, text = await _drive(ex, {"google": True})
    assert cards == ["Sign in to Google again?"]
    assert calls["google"] == [1.0]
    assert text == "Google: signed in again."


async def test_rejected_opens_nothing() -> None:
    ex, calls = _executor()
    ex.want({"google", "claude"})
    cards, text = await _drive(ex, {"google": False, "claude": False})
    assert cards == ["Sign in to Claude again?", "Sign in to Google again?"]
    assert calls["google"] == [] and calls["claude"] == []
    assert "not signed in" in text


async def test_unanswered_card_opens_nothing() -> None:
    ex, calls = _executor(answer_s=0.01)
    ex.want({"claude"})
    _, text = await _drive(ex, {"claude": None})
    assert calls["claude"] == []
    assert "ask again" in text


async def test_claude_login_window_then_warmed_again() -> None:
    ex, calls = _executor()
    ex.want({"claude"})
    _, text = await _drive(ex, {"claude": True})
    assert calls["claude"] == ["claude.exe"]
    assert calls["back"] == [1]
    assert text == "Claude: signed in again."


async def test_claude_still_signed_out_after_the_window() -> None:
    ex, calls = _executor(claude_check=lambda: "expired", open_claude=lambda p: _Proc(timeout=True))
    ex.want({"claude"})
    _, text = await _drive(ex, {"claude": True})
    assert calls["back"] == []
    assert "didn't finish" in text


async def test_google_flow_failing_ends_in_a_line() -> None:
    def fail(t: float) -> None:
        raise ConnectorError("no", "x")

    ex, _ = _executor(google_signin=fail)
    ex.want({"google"})
    _, text = await _drive(ex, {"google": True})
    assert "didn't finish" in text


async def test_want_while_running_starts_nothing_new() -> None:
    ex, _ = _executor()
    assert ex.want({"google"})
    await ex.start(WorkerTask("Sign in again"))
    assert not ex.want({"google"})


# --- Google: a new sign-in replaces the clients built on the old one ---------
# The Google libraries are in the spikes group, so the tests give them small stand-ins.


class RefreshError(Exception):
    pass


@pytest.fixture
def google_libs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    built: list[str] = []
    mods = {
        "googleapiclient": types.ModuleType("googleapiclient"),
        "googleapiclient.discovery": types.ModuleType("googleapiclient.discovery"),
        "google.auth": types.ModuleType("google.auth"),
        "google.auth.exceptions": types.ModuleType("google.auth.exceptions"),
        "google.auth.transport": types.ModuleType("google.auth.transport"),
        "google.auth.transport.requests": types.ModuleType("google.auth.transport.requests"),
    }
    mods["googleapiclient.discovery"].build = lambda name, *a, **k: built.append(name) or "new client"  # type: ignore[attr-defined]
    mods["google.auth.exceptions"].RefreshError = RefreshError  # type: ignore[attr-defined]
    mods["google.auth.transport.requests"].Request = object  # type: ignore[attr-defined]
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return built


def test_google_clients_rebuilt_after_signing_in_again(
    monkeypatch: pytest.MonkeyPatch, google_libs: list[str]
) -> None:
    monkeypatch.setattr(google.GoogleSession, "_credentials", lambda self: object())
    session = google.GoogleSession("Google Calendar")
    session._services["calendar"] = "old client"
    assert session.service("calendar", "v3") == "old client"
    monkeypatch.setattr(google, "_generation", google._generation + 1)
    assert session.service("calendar", "v3") == "new client"
    assert google_libs == ["calendar"]


def test_google_refusal_tells_the_listeners(monkeypatch: pytest.MonkeyPatch) -> None:
    heard: list[int] = []
    monkeypatch.setattr(google, "expired_listeners", [lambda: heard.append(1)])
    err = google.GoogleSession("Gmail")._failure(Exception("invalid_grant: Token has been expired or revoked."))
    assert err.code == "not_connected" and "expired" in str(err)
    assert heard == [1]


def test_google_check_reads_the_refusal(monkeypatch: pytest.MonkeyPatch, google_libs: list[str]) -> None:
    class Creds:
        def __init__(self, exc: Exception | None) -> None:
            self.exc = exc

        def refresh(self, request: object) -> None:
            if self.exc:
                raise self.exc

    for exc, status in [
        (None, "ok"),
        (RefreshError("invalid_grant: Token has been expired or revoked."), "expired"),
        (OSError("offline"), "unknown"),
    ]:
        monkeypatch.setattr(google, "_stored_credentials", lambda e=exc: Creds(e))
        assert google.check() == status
    monkeypatch.setattr(google, "_stored_credentials", lambda: None)
    assert google.check() == "absent"


# --- through the session: Swift's own run with a confirm card ----------------


async def test_session_shows_the_card_and_signs_in_on_approve() -> None:
    session, rec, records = make()
    ex, calls = _executor()
    ex.want({"google"})
    session.start_own(ex, "Sign in again", "signin")
    await answer_confirm(session, rec, "approve")
    for _ in range(100):
        if records:
            break
        await asyncio.sleep(0.02)
    assert calls["google"] == [1.0]
    assert records[0]["source"] == "signin" and records[0]["status"] == "done"
    assert records[0]["approvals"][0]["decision"] == "approve"
    assert any(m.type == "result" and "signed in again" in str(m.data) for m in rec.messages)


async def test_session_refused_sign_in_is_reported() -> None:
    session, _, _ = make()
    refused: list[str] = []
    session.on_signin_refused = refused.append
    await session._send_failure(Failure("auth", "Claude Code isn't signed in", "m", "h", detail="run /login"), None)
    await session._send_failure(Failure("offline", "Can't reach", "m", "h"), None)
    assert refused == ["claude"]
