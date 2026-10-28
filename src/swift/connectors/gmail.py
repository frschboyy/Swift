"""Gmail and Google contacts for Swift's email workflow (ADR-010 §9).

- Sends with ``drafts.create`` then ``drafts.send`` under ``gmail.compose``, the
  scope spike S4 verified. No ``gmail.readonly``: Swift never reads or searches mail.
- Looks people up with the People API: the owner's contacts (``people.searchContacts``,
  ``contacts.readonly``) and their "other contacts", the people they have emailed
  (``otherContacts.search``, ``contacts.other.readonly``). Both searches need a warm-up
  call with an empty query first; Swift makes it once. Results are kept in memory for
  ``CACHE_S`` so a run that looks the same person up twice asks Google once. No name or
  address is ever logged.
- The owner's own name (``people/me``, ``userinfo.profile``) signs the emails Swift drafts.
- Signing in, the scopes and the stored token are shared with Google Calendar
  (``swift.connectors.google``)::

    uv run --group spikes python -m swift.connectors.gmail signin
    uv run --group spikes python -m swift.connectors.gmail signout
"""

from __future__ import annotations

import base64
import time
from email.message import EmailMessage
from typing import Any

from swift.connectors.base import Contact, ConnectorError, Manifest, OutgoingEmail, SentMessage
from swift.connectors.google import SCOPES, SIGNIN_HINT, GoogleSession, client_secret_path, transient
from swift.connectors.google import main as google_main

__all__ = ["SCOPES", "SIGNIN_HINT", "GmailConnector", "client_secret_path", "main", "mime"]

# How long a search's results are reused, and how many searches are kept.
CACHE_S = 300.0
CACHE_SIZE = 50
SEARCH_SIZE = 10
EMAILED = "you've emailed them"


def mime(email: OutgoingEmail) -> str:
    """The email as Gmail's base64url ``raw`` field. Gmail fills in From."""
    msg = EmailMessage()
    msg["To"] = ", ".join(f"{c.name} <{c.email}>" if c.name else c.email for c in email.to)
    msg["Subject"] = email.subject
    msg.set_content(email.body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def _organization(person: dict[str, Any]) -> str:
    """The first organization a contact has ("Acme Ltd, Supervisor"), or ""."""
    for org in person.get("organizations", []):
        if text := ", ".join(p for p in (org.get("name", ""), org.get("title", "")) if p):
            return text
    return ""


class GmailConnector:
    manifest = Manifest("gmail", "Gmail", auth="oauth")

    def __init__(self) -> None:
        self._google = GoogleSession("Gmail")
        # Lower-cased query -> (when, what it found); which searches have had their warm-up call.
        self._cache: dict[str, tuple[float, tuple[Contact, ...]]] = {}
        self._warm: set[str] = set()
        self._owner: str | None = None

    async def directory(self, query: str) -> list[Contact]:
        key = " ".join(query.lower().split())
        cached = self._cache.get(key)
        if cached is not None and time.monotonic() - cached[0] < CACHE_S:
            return list(cached[1])
        people = await self._google.call(lambda: self._search("contacts", query), retry=True)
        try:
            emailed = await self._google.call(lambda: self._search("other", query), retry=True)
        except ConnectorError:
            if not people:
                raise  # e.g. signed in before contacts.other.readonly: say so rather than "nobody"
            emailed = []
        found = people + [c for c in emailed if c.email.lower() not in {p.email.lower() for p in people}]
        if len(self._cache) >= CACHE_SIZE:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (time.monotonic(), tuple(found))
        return found

    def _search(self, where: str, query: str) -> list[Contact]:
        """One People API search: ``contacts`` (the owner's contacts) or ``other`` (people they've emailed)."""
        service = self._google.service("people", "v1")
        if where == "contacts":
            api, mask, detail = service.people().searchContacts, "names,emailAddresses,organizations", _organization
            source = "gmail"
        else:
            api, mask, detail = service.otherContacts().search, "names,emailAddresses", lambda _: EMAILED
            source = "gmail_emailed"
        if where not in self._warm:
            api(query="", readMask=mask, pageSize=1).execute()  # the search cache fills on this call
            self._warm.add(where)
        found = api(query=query, readMask=mask, pageSize=SEARCH_SIZE).execute()
        out = []
        for result in found.get("results", []):
            person = result.get("person", {})
            name = next((n.get("displayName", "") for n in person.get("names", [])), "")
            for address in person.get("emailAddresses", []):
                if value := address.get("value"):
                    out.append(Contact(name or value, value, source, detail(person)))
        return out

    async def owner_name(self) -> str:
        if self._owner is None:
            def fetch() -> str:
                me = self._google.service("people", "v1").people().get(resourceName="people/me", personFields="names")
                names = me.execute().get("names", [])
                primary = next((n for n in names if n.get("metadata", {}).get("primary")), names[0] if names else {})
                return str(primary.get("displayName", "")).strip()

            try:
                self._owner = await self._google.call(fetch, retry=True)
            except ConnectorError:
                return ""  # not signed in again yet: the draft is signed with the name in config.yaml, if any
        return self._owner

    async def send(self, email: OutgoingEmail) -> SentMessage:
        """A draft, then sending it. If the connection drops while sending, the draft says what
        happened: still in Drafts means not sent (so trying again is safe), gone means sent
        (audit 2026-10, A-06). Never sent twice, never "failed" when it may have gone."""

        def drafts() -> Any:
            return self._google.service("gmail", "v1").users().drafts()

        def create() -> str:
            return str(drafts().create(userId="me", body={"message": {"raw": mime(email)}}).execute()["id"])

        draft_id = await self._google.call(create)  # not repeated: a dropped create sends nothing
        tried = False

        def send() -> SentMessage:
            nonlocal tried
            try:
                sent = drafts().send(userId="me", body={"id": draft_id}).execute()
                return SentMessage(str(sent.get("id", "")))
            except Exception as exc:
                gone = tried and "404" in str(exc)  # the try whose connection dropped did send it
                tried = True
                if not (transient(exc) or gone):
                    raise
                if gone or not self._draft_exists(drafts(), draft_id):
                    return SentMessage(f"draft-{draft_id}")  # sent: Gmail moves a sent draft out of Drafts
                raise  # still a draft: not sent; trying again is safe

        return await self._google.call(send, retry=True, changes=True)

    @staticmethod
    def _draft_exists(drafts: Any, draft_id: str) -> bool:
        try:
            drafts.get(userId="me", id=draft_id, format="minimal").execute()
        except Exception as exc:
            if "404" in str(exc):
                return False
            raise
        return True


def main(argv: list[str] | None = None) -> None:
    google_main(argv, prog="swift.connectors.gmail")


if __name__ == "__main__":
    main()
