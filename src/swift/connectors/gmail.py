"""Gmail and Google contacts for Swift's email workflow (ADR-010 §9).

- Sends with ``drafts.create`` then ``drafts.send`` under ``gmail.compose``, the
  scope spike S4 verified. No ``gmail.readonly``: Swift never reads or searches mail.
- Looks people up with the People API (``people.searchContacts``) under
  ``contacts.readonly``.
- Signing in, the scopes and the stored token are shared with Google Calendar
  (``swift.connectors.google``)::

    uv run --group spikes python -m swift.connectors.gmail signin
    uv run --group spikes python -m swift.connectors.gmail signout
"""

from __future__ import annotations

import base64
from email.message import EmailMessage

from swift.connectors.base import Contact, Manifest, OutgoingEmail, SentMessage
from swift.connectors.google import SCOPES, SIGNIN_HINT, GoogleSession, client_secret_path, main as google_main

__all__ = ["SCOPES", "SIGNIN_HINT", "GmailConnector", "client_secret_path", "main", "mime"]


def mime(email: OutgoingEmail) -> str:
    """The email as Gmail's base64url ``raw`` field. Gmail fills in From."""
    msg = EmailMessage()
    msg["To"] = ", ".join(f"{c.name} <{c.email}>" if c.name else c.email for c in email.to)
    msg["Subject"] = email.subject
    msg.set_content(email.body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


class GmailConnector:
    manifest = Manifest("gmail", "Gmail", auth="oauth")

    def __init__(self) -> None:
        self._google = GoogleSession("Gmail")

    async def directory(self, query: str) -> list[Contact]:
        def search() -> list[Contact]:
            people = self._google.service("people", "v1").people()
            found = people.searchContacts(query=query, readMask="names,emailAddresses", pageSize=10).execute()
            out = []
            for result in found.get("results", []):
                person = result.get("person", {})
                name = next((n.get("displayName", "") for n in person.get("names", [])), "")
                for address in person.get("emailAddresses", []):
                    if value := address.get("value"):
                        out.append(Contact(name or value, value, "gmail"))
            return out

        return await self._google.call(search)

    async def send(self, email: OutgoingEmail) -> SentMessage:
        def send() -> SentMessage:
            drafts = self._google.service("gmail", "v1").users().drafts()
            draft = drafts.create(userId="me", body={"message": {"raw": mime(email)}}).execute()
            sent = drafts.send(userId="me", body={"id": draft["id"]}).execute()
            return SentMessage(str(sent.get("id", "")))

        return await self._google.call(send)


def main(argv: list[str] | None = None) -> None:
    google_main(argv, prog="swift.connectors.gmail")


if __name__ == "__main__":
    main()
