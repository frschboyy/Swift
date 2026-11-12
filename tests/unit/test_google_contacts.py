"""Google contacts, the owner's name, and retries for dropped connections (owner checks of 2026-10-27).

No network: the People and Calendar services are fakes put where ``GoogleSession`` keeps its
built clients.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from swift.connectors import google
from swift.connectors.base import CalendarEvent, ConnectorError
from swift.connectors.gmail import EMAILED, GmailConnector
from swift.connectors.google import SCOPES, GoogleSession, transient
from swift.connectors.google_calendar import GoogleCalendarConnector


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(google, "RETRY_DELAYS_S", (0.0, 0.0))


class Call:
    def __init__(self, result: Any) -> None:
        self.result = result

    def execute(self) -> Any:
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result() if callable(self.result) else self.result


def person(name: str, email: str, org: str = "", title: str = "") -> dict[str, Any]:
    found: dict[str, Any] = {"names": [{"displayName": name}], "emailAddresses": [{"value": email}]}
    if org or title:
        found["organizations"] = [{"name": org, "title": title}]
    return {"person": found}


class FakePeople:
    """``people()`` and ``otherContacts()`` of the People API, recording what was asked."""

    def __init__(self, contacts: list[dict[str, Any]], emailed: list[dict[str, Any]], *,
                 other_error: Exception | None = None, me: str = "Francis Chianu") -> None:
        self.contacts, self.emailed, self.other_error, self.me = contacts, emailed, other_error, me
        self.asked: list[tuple[str, str]] = []

    def people(self) -> FakePeople:
        return self

    def otherContacts(self) -> Any:  # noqa: N802 - the API's name
        fake = self

        class Other:
            def search(self, query: str, readMask: str, pageSize: int) -> Call:  # noqa: N803
                fake.asked.append(("other", query))
                if fake.other_error is not None:
                    return Call(fake.other_error)
                return Call({"results": fake.emailed if query else []})

        return Other()

    def searchContacts(self, query: str, readMask: str, pageSize: int) -> Call:  # noqa: N802, N803
        self.asked.append(("contacts", query))
        assert "organizations" in readMask
        return Call({"results": self.contacts if query else []})

    def get(self, resourceName: str, personFields: str) -> Call:  # noqa: N803
        assert resourceName == "people/me"
        return Call({"names": [{"displayName": self.me, "metadata": {"primary": True}}]})


def gmail(people: FakePeople) -> GmailConnector:
    connector = GmailConnector()
    connector._google._services["people"] = people
    return connector


def test_sign_in_asks_for_contacts_other_contacts_and_the_profile() -> None:
    assert "https://www.googleapis.com/auth/contacts.readonly" in SCOPES
    assert "https://www.googleapis.com/auth/contacts.other.readonly" in SCOPES
    assert "https://www.googleapis.com/auth/userinfo.profile" in SCOPES


async def test_someone_the_owner_has_emailed_is_found() -> None:
    """13:44: "email Janet" found nobody. Janet is in the owner's Gmail correspondence."""
    people = FakePeople([], [person("Janet Okafor", "j.okafor@uni.example")])
    found = await gmail(people).directory("janet")
    assert [(c.name, c.email, c.detail) for c in found] == [("Janet Okafor", "j.okafor@uni.example", EMAILED)]
    assert found[0].source == "gmail_emailed"
    # Each search is warmed up once with an empty query, as the People API asks.
    assert people.asked == [("contacts", ""), ("contacts", "janet"), ("other", ""), ("other", "janet")]


async def test_contacts_come_first_with_their_organization_and_are_not_repeated() -> None:
    people = FakePeople(
        [person("Janet Okafor", "j.okafor@uni.example", "University of X", "Supervisor")],
        [person("Janet Okafor", "J.Okafor@uni.example"), person("Janet Bloggs", "jb@shop.example")],
    )
    found = await gmail(people).directory("janet")
    assert [(c.email, c.detail) for c in found] == [
        ("j.okafor@uni.example", "University of X, Supervisor"), ("jb@shop.example", EMAILED),
    ]


async def test_a_search_is_cached_briefly() -> None:
    people = FakePeople([person("Janet Okafor", "j.okafor@uni.example")], [])
    connector = gmail(people)
    await connector.directory("Janet")
    await connector.directory("janet")
    assert [q for where, q in people.asked if where == "contacts" and q] == ["Janet"]


async def test_an_old_sign_in_still_finds_contacts_and_says_so_when_it_finds_none() -> None:
    missing = Exception("insufficientPermissions: Request had insufficient authentication scopes.")
    found = await gmail(FakePeople([person("Ada", "ada@example.edu")], [], other_error=missing)).directory("ada")
    assert [c.email for c in found] == ["ada@example.edu"]
    with pytest.raises(ConnectorError) as raised:
        await gmail(FakePeople([], [], other_error=missing)).directory("janet")
    assert "Sign in again" in raised.value.hint


async def test_the_owner_name_comes_from_the_google_account() -> None:
    assert await gmail(FakePeople([], [], me="Francis Chianu")).owner_name() == "Francis Chianu"


async def test_no_name_when_google_cant_say() -> None:
    connector = GmailConnector()  # nothing built, no sign-in in tests: the call fails
    connector._google._credentials = lambda: (_ for _ in ()).throw(ConnectorError("Gmail isn't connected."))  # type: ignore[method-assign]
    assert await connector.owner_name() == ""


# ---- retries -------------------------------------------------------------------


def aborted() -> OSError:
    error = ConnectionAbortedError(10053, "An established connection was aborted by the software in your host machine")
    error.winerror = 10053  # type: ignore[attr-defined]
    return error


class Status(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HttpError {status}")
        self.resp = type("Resp", (), {"status": status})()


def test_what_counts_as_a_dropped_connection() -> None:
    assert transient(aborted()) and transient(TimeoutError()) and transient(Status(503))
    assert not transient(Status(400)) and not transient(ValueError("bad"))
    assert transient(OSError(10054, "reset"))


async def test_a_safe_call_is_tried_again_after_a_dropped_connection() -> None:
    tries: list[int] = []

    def flaky() -> str:
        tries.append(1)
        if len(tries) < 3:
            raise aborted()
        return "ok"

    assert await GoogleSession("Google Calendar").call(flaky, retry=True) == "ok"
    assert len(tries) == 3


async def test_an_unsafe_call_is_not_repeated_and_google_is_not_said_to_refuse() -> None:
    tries: list[int] = []

    def send() -> str:
        tries.append(1)
        raise aborted()

    with pytest.raises(ConnectorError) as raised:
        await GoogleSession("Gmail").call(send)
    assert len(tries) == 1
    assert "lost the connection to Gmail" in str(raised.value) and "refused" not in str(raised.value)


async def test_retries_give_up_after_two() -> None:
    tries: list[int] = []

    def down() -> str:
        tries.append(1)
        raise Status(503)

    with pytest.raises(ConnectorError):
        await GoogleSession("Google Calendar").call(down, retry=True)
    assert len(tries) == 3


async def test_a_refusal_is_not_retried_or_called_a_refusal() -> None:
    tries: list[int] = []

    def bad() -> str:
        tries.append(1)
        raise Status(400)

    with pytest.raises(ConnectorError) as raised:
        await GoogleSession("Google Calendar").call(bad, retry=True)
    assert len(tries) == 1 and "Google Calendar couldn't do that" in str(raised.value)


class FakeEvents:
    """Calendar ``events()``: the first delete removes the event but its connection drops (13:40:40)."""

    def __init__(self) -> None:
        self.stored = True
        self.deletes = 0

    def get(self, calendarId: str, eventId: str) -> Call:  # noqa: N803
        if not self.stored:
            return Call(Status(410))
        return Call({"id": eventId, "summary": "Swift check", "status": "confirmed"})

    def delete(self, calendarId: str, eventId: str, sendUpdates: str) -> Call:  # noqa: N803
        self.deletes += 1

        def run() -> dict[str, Any]:
            self.stored = False
            if self.deletes == 1:
                raise aborted()
            return {}

        return Call(run)


class FakeCalendar:
    def __init__(self, events: FakeEvents) -> None:
        self._events = events

    def events(self) -> FakeEvents:
        return self._events


async def test_a_delete_whose_connection_dropped_is_done_on_the_retry() -> None:
    events = FakeEvents()
    connector = GoogleCalendarConnector()
    connector._google._services["calendar"] = FakeCalendar(events)
    assert await connector.delete_event("ev1") == "ev1"
    assert events.deletes == 1 and not events.stored  # the retry saw it gone; nothing removed twice


async def test_a_new_event_whose_connection_keeps_dropping_is_unknown_not_failed() -> None:
    """Every try drops before Google answers: tried again with the same id (never a second event),
    then "can't tell" rather than "failed" (audit 2026-10, A-05)."""

    class Inserts(FakeEvents):
        def __init__(self) -> None:
            super().__init__()
            self.stored = False
            self.ids: list[str] = []

        def insert(self, **kw: Any) -> Call:
            self.ids.append(kw["body"]["id"])
            return Call(aborted())

    events = Inserts()
    connector = GoogleCalendarConnector()
    connector._google._services["calendar"] = FakeCalendar(events)
    start = datetime(2026, 10, 30, 10).astimezone()
    with pytest.raises(ConnectorError) as raised:
        await connector.create_event(CalendarEvent("Lunch", start, start + timedelta(hours=1)))
    assert raised.value.code == "unknown" and "can't tell" in str(raised.value)
    assert len(events.ids) == 3 and len(set(events.ids)) == 1  # one id: Google can't add it twice
