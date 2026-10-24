"""Gmail and Google contacts for Swift's email workflow (ADR-010 §9).

- Sends with ``drafts.create`` then ``drafts.send`` under ``gmail.compose``, the
  scope spike S4 verified. No ``gmail.readonly``: Swift never reads or searches mail.
- Looks people up with the People API (``people.searchContacts``) under
  ``contacts.readonly``.
- Only the refresh token is stored, in Windows Credential Manager under
  ``Swift/Google`` (threat model T9). The OAuth client file stays in
  ``%APPDATA%\\Swift\\client_secret.json`` (docs/google_setup.md).

Signing in is the owner's job, in their own browser::

    uv run --group spikes python -m swift.connectors.gmail signin
    uv run --group spikes python -m swift.connectors.gmail signout

The Google libraries are imported only when the connector is used, so Swift
runs without them while ``connectors.email`` isn't ``gmail``.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from swift.connectors.base import Contact, ConnectorError, Manifest, OutgoingEmail, SentMessage

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/contacts.readonly",
]
KEYRING_SERVICE = "Swift/Google"
KEYRING_USER = "refresh_token"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SIGNIN_HINT = "Run `uv run --group spikes python -m swift.connectors.gmail signin` and sign in, then try again."


def client_secret_path() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Swift" / "client_secret.json"


def _client() -> dict[str, Any]:
    import json

    path = client_secret_path()
    if not path.exists():
        raise ConnectorError(
            "Gmail isn't set up: the OAuth client file is missing.",
            "Follow docs/google_setup.md to create it, then sign in.",
            code="not_connected",
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("installed") or data["web"]


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
        self._services: dict[str, Any] = {}

    def _credentials(self) -> Any:
        try:
            import keyring
            from google.oauth2.credentials import Credentials
        except ImportError:
            raise ConnectorError(
                "The Google libraries aren't installed.", "Run `uv sync --group spikes`, then restart Swift.",
                code="not_connected",
            ) from None
        token = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        if not token:
            raise ConnectorError("Gmail isn't connected.", SIGNIN_HINT, code="not_connected")
        client = _client()
        return Credentials(
            token=None, refresh_token=token, token_uri=TOKEN_URI,
            client_id=client["client_id"], client_secret=client["client_secret"], scopes=SCOPES,
        )

    def _service(self, name: str, version: str) -> Any:
        if name not in self._services:
            from googleapiclient.discovery import build

            self._services[name] = build(name, version, credentials=self._credentials(), cache_discovery=False)
        return self._services[name]

    async def directory(self, query: str) -> list[Contact]:
        def search() -> list[Contact]:
            people = self._service("people", "v1").people()
            found = people.searchContacts(query=query, readMask="names,emailAddresses", pageSize=10).execute()
            out = []
            for result in found.get("results", []):
                person = result.get("person", {})
                name = next((n.get("displayName", "") for n in person.get("names", [])), "")
                for address in person.get("emailAddresses", []):
                    if value := address.get("value"):
                        out.append(Contact(name or value, value, "gmail"))
            return out

        return await self._call(search)

    async def send(self, email: OutgoingEmail) -> SentMessage:
        def send() -> SentMessage:
            drafts = self._service("gmail", "v1").users().drafts()
            draft = drafts.create(userId="me", body={"message": {"raw": mime(email)}}).execute()
            sent = drafts.send(userId="me", body={"id": draft["id"]}).execute()
            return SentMessage(str(sent.get("id", "")))

        return await self._call(send)

    @staticmethod
    async def _call(fn: Any) -> Any:
        try:
            return await asyncio.to_thread(fn)
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001 - Google errors become one readable failure
            text = str(exc)
            if "invalid_grant" in text or "401" in text:
                raise ConnectorError("Gmail sign-in has expired.", SIGNIN_HINT, code="not_connected") from None
            raise ConnectorError(f"Gmail refused the request: {text[:200]}", "Try again in a moment.") from None


def signin() -> None:
    """Owner-run: consent in the browser, then keep only the refresh token."""
    import keyring
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path()), SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent", open_browser=True)
    if not creds.refresh_token:
        raise SystemExit("Google returned no refresh token; nothing was stored.")
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, creds.refresh_token)
    granted = set(getattr(creds, "granted_scopes", None) or creds.scopes or [])
    for scope in SCOPES:
        print(f"{'granted' if scope in granted else 'MISSING'}  {scope}")
    print("Signed in. The refresh token is in Windows Credential Manager under Swift/Google.")


def signout() -> None:
    import keyring

    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        print("Removed the Swift/Google refresh token. Also remove access at https://myaccount.google.com/permissions")
    except keyring.errors.PasswordDeleteError:
        print("Nothing to remove.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="swift.connectors.gmail")
    parser.add_argument("command", choices=["signin", "signout"])
    args = parser.parse_args(argv)
    signin() if args.command == "signin" else signout()


if __name__ == "__main__":
    main()
