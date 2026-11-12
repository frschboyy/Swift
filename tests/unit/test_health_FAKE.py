"""Health audit 2026-11-12, group FAKE: where a fake is kinder than the real thing.

Each test is a strict xfail that reproduces a failure the fakes hide; it flips to XPASS when fixed.
No network, no real app: Google's services and the desktop are stand-ins that behave like the real
ones in the one way that matters here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from test_google_contacts import Call, aborted

from swift.connectors import google
from swift.connectors.base import ConnectorError, Contact, OutgoingEmail
from swift.connectors.gmail import GmailConnector
from swift.connectors.google import GoogleSession
from swift.connectors.google_calendar import GoogleCalendarConnector


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(google, "RETRY_DELAYS_S", (0.0, 0.0))


class HttpErrorLike(Exception):
    """What googleapiclient's ``HttpError`` says when printed: its status, the address it asked and
    Google's reason (``HttpError.__repr__``, which is also its ``__str__``). The suite's own fakes
    say only "<HttpError 404 Not Found>", without the address."""

    def __init__(self, status: int, uri: str, reason: str) -> None:
        self.resp = type("Resp", (), {"status": status})()
        super().__init__(f'<HttpError {status} when requesting {uri} returned "{reason}">')


# ---- HA-FAKE-01: "404" / "401" looked for in the whole error text, address included ----------


DRAFT = "r-5214043378190865123"  # Gmail draft ids are long numbers: "404" turns up in some


class Drafts:
    """Gmail ``drafts()``: the first send drops before Gmail does anything; Gmail is then briefly down."""

    def __init__(self) -> None:
        self.sends = 0
        self.sent: list[str] = []

    def create(self, userId: str, body: dict[str, Any]) -> Call:  # noqa: N803
        return Call({"id": DRAFT})

    def send(self, userId: str, body: dict[str, Any]) -> Call:  # noqa: N803
        def run() -> dict[str, Any]:
            self.sends += 1
            if self.sends == 1:
                raise aborted()  # dropped before Gmail sent it: still in Drafts
            self.sent.append(body["id"])
            return {"id": "m1"}

        return Call(run)

    def get(self, userId: str, id: str, format: str) -> Call:  # noqa: A002, N803
        uri = f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{id}?format=minimal&alt=json"
        return Call(HttpErrorLike(503, uri, "Backend Error"))


async def test_an_email_not_sent_is_never_reported_sent() -> None:
    drafts = Drafts()
    connector = GmailConnector()
    users = type("Users", (), {"drafts": lambda self: drafts})()
    connector._google._services["gmail"] = type("Gmail", (), {"users": lambda self: users})()
    email = OutgoingEmail((Contact("Ada", "ada@example.edu"),), "Lunch", "Hello Ada,\n\nLunch?")
    try:
        sent = await connector.send(email)
    except ConnectorError:
        sent = None
    # Reported sent only if Gmail sent it. Today: SentMessage("draft-r-…") with nothing sent.
    assert sent is None or drafts.sent == [DRAFT]


EVENT = "fa3404c1e2b04d7b9d6e0b8c1a2f3e4d"  # Swift's own event ids are uuid hex: "404" turns up in some


class Events:
    """Calendar ``events()``: the delete drops before Google removes it; Google is then briefly down."""

    def __init__(self) -> None:
        self.deletes = 0
        self.stored = True

    def get(self, calendarId: str, eventId: str) -> Call:  # noqa: N803
        if self.deletes:
            uri = f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{eventId}?alt=json"
            return Call(HttpErrorLike(503, uri, "Backend Error"))
        return Call({"id": eventId, "summary": "Lunch", "status": "confirmed"})

    def delete(self, calendarId: str, eventId: str, sendUpdates: str) -> Call:  # noqa: N803
        def run() -> dict[str, Any]:
            self.deletes += 1
            raise aborted()  # dropped before Google removed it

        return Call(run)


async def test_an_event_still_there_is_never_reported_removed() -> None:
    events = Events()
    connector = GoogleCalendarConnector()
    connector._google._services["calendar"] = type("Cal", (), {"events": lambda self: events})()
    with pytest.raises(ConnectorError):  # can't tell, or failed; never "removed"
        await connector.delete_event(EVENT)
    assert events.stored


async def test_a_refusal_is_not_an_expired_sign_in(monkeypatch: pytest.MonkeyPatch) -> None:
    fired: list[int] = []
    monkeypatch.setattr(google, "expired_listeners", [lambda: fired.append(1)])
    uri = "https://www.googleapis.com/calendar/v3/calendars/primary/events?q=401k+review&alt=json"

    def search() -> None:
        raise HttpErrorLike(403, uri, "Rate Limit Exceeded")

    with pytest.raises(ConnectorError) as raised:
        await GoogleSession("Google Calendar").call(search, retry=True)
    assert raised.value.code != "not_connected" and not fired  # no "sign in again" offer


# ---- HA-FAKE-02: Google's raw error text, address and query included, on the owner's card --------


@pytest.mark.xfail(strict=True, reason="HA-FAKE-02: a Google refusal reaches the card as raw HttpError text")
async def test_a_google_refusal_reads_as_a_sentence() -> None:
    uri = "https://people.googleapis.com/v1/people:searchContacts?query=Ada+Lovelace&readMask=names&alt=json"

    def search() -> None:
        raise HttpErrorLike(429, uri, "Quota exceeded for quota metric 'Read requests'")

    with pytest.raises(ConnectorError) as raised:
        await GoogleSession("Gmail").call(search, retry=True)
    assert "googleapis.com" not in str(raised.value) and "Ada" not in str(raised.value)


# ---- HA-FAKE-03: Esc while a request waits for the warm CLI is swallowed ----------------------------


class SlowClient:
    """A ClaudeSDKClient whose CLI takes a long time to connect (5-13 s on the owner's laptop)."""

    def __init__(self, options: Any) -> None:
        self.options = options

    async def connect(self) -> None:
        await asyncio.sleep(30)

    async def set_model(self, model: str | None) -> None: ...

    async def query(self, prompt: str) -> None: ...

    async def receive_response(self):  # type: ignore[no-untyped-def]
        return
        yield

    async def disconnect(self) -> None: ...


async def test_cancel_while_waiting_for_the_warm_cli_stops_the_start(tmp_path: Path) -> None:
    from swift.executors.claude_code import ClaudeCodeExecutor

    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", client_factory=SlowClient)
    ex.prepare()  # the spare starts connecting
    await asyncio.sleep(0.05)
    starting = asyncio.create_task(ex.start("what's on my calendar"))
    await asyncio.sleep(0.05)
    starting.cancel()  # Esc: Session.cancel() cancels the interaction task
    try:
        await asyncio.wait_for(starting, 2)
        cancelled = False
    except asyncio.CancelledError:
        cancelled = True
    started = list(ex._runs)
    for run_id in started:
        await ex.cancel(run_id)
    await ex.close()
    assert cancelled and not started


# ---- HA-FAKE-04: Gmail filled in part-way: the owner isn't told a compose window is open --------------


@pytest.mark.xfail(strict=True, reason="HA-FAKE-04: the fake fills all or nothing; the real one stops part-way")
async def test_a_part_filled_gmail_window_is_said() -> None:
    from test_desktop import make

    from swift.desktop.base import DesktopError

    host, desktop, _, _ = make(said="email my lecturer that I'll miss Thursday")

    async def part_way(app: str, to: list[str], subject: str, body: str) -> str:
        # Like WindowsDesktop._fill_gmail: "To" is set (Value pattern), then the body needs the focus.
        desktop.filled.append((app, to, "", ""))
        raise DesktopError("Swift couldn't put the cursor in Gmail's body, so it stopped there.",
                           "Finish the email yourself, or try again.")

    desktop.fill_in_email = part_way  # type: ignore[method-assign]
    found = await host.call("find_contact", {"query": "lecturer"})
    draft = await host.call("draft_email", {"to": [found.data["candidates"][0]["email"]], "subject": "Thursday",
                                            "message": "I'll miss Thursday's lecture."})
    result = await host.call("fill_in_email", {"draft_id": draft.data["draft_id"]})
    assert not result.ok
    # The owner and the provider learn a half-filled compose window is open (not to fill in another).
    assert "Finish the email yourself" in result.text or "open" in result.text.lower()
