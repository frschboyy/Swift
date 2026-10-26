"""The owner's Google sign-in, shared by the Gmail and Calendar connectors (ADR-010 §9, ADR-011 W1).

One consent covers every scope Swift uses:

| Scope | For |
|---|---|
| ``gmail.compose`` | sending a draft the owner approved (spike S4) |
| ``contacts.readonly`` | ``find_contact`` |
| ``calendar.events`` | creating an event the owner approved (spike S4) |

No ``gmail.readonly``: Swift never reads or searches mail. ``gmail.metadata`` (ADR-011
§13.4) belongs to the watchers phase and isn't asked for yet.

- Only the refresh token is stored, in Windows Credential Manager under
  ``Swift/Google`` (threat model T9). The OAuth client file stays in
  ``%APPDATA%\\Swift\\client_secret.json`` (docs/google_setup.md).
- A token from before a scope was added still works for the older scopes; the new
  one fails with "insufficient scopes" until the owner signs in again.

Signing in is the owner's job, in their own browser::

    uv run --group spikes python -m swift.connectors.gmail signin
    uv run --group spikes python -m swift.connectors.gmail signout

The Google libraries are imported only when a connector is used, so Swift runs
without them while no Google connector is configured.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from swift.connectors.base import ConnectorError

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]
KEYRING_SERVICE = "Swift/Google"
KEYRING_USER = "refresh_token"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SIGNIN_HINT = "Run `uv run --group spikes python -m swift.connectors.gmail signin` and sign in, then try again."

T = TypeVar("T")


def client_secret_path() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Swift" / "client_secret.json"


def _client() -> dict[str, Any]:
    path = client_secret_path()
    if not path.exists():
        raise ConnectorError(
            "Google isn't set up: the OAuth client file is missing.",
            "Follow docs/google_setup.md to create it, then sign in.",
            code="not_connected",
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("installed") or data["web"]


class GoogleSession:
    """Credentials and API clients for one connector, built on first use."""

    def __init__(self, service_name: str) -> None:
        # What the owner reads in errors: "Gmail", "Google Calendar".
        self.service_name = service_name
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
            raise ConnectorError(f"{self.service_name} isn't connected.", SIGNIN_HINT, code="not_connected")
        client = _client()
        return Credentials(
            token=None, refresh_token=token, token_uri=TOKEN_URI,
            client_id=client["client_id"], client_secret=client["client_secret"], scopes=SCOPES,
        )

    def service(self, name: str, version: str) -> Any:
        if name not in self._services:
            from googleapiclient.discovery import build

            self._services[name] = build(name, version, credentials=self._credentials(), cache_discovery=False)
        return self._services[name]

    async def call(self, fn: Callable[[], T]) -> T:
        try:
            return await asyncio.to_thread(fn)
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001 - Google errors become one readable failure
            text, low = str(exc), str(exc).lower()
            if ("insufficient" in low and "scope" in low) or "insufficientpermissions" in low:
                raise ConnectorError(
                    f"{self.service_name} isn't allowed yet: Swift's Google sign-in is missing a permission.",
                    "Sign in again to grant it: " + SIGNIN_HINT, code="not_connected",
                ) from None
            if "invalid_grant" in text or "401" in text:
                raise ConnectorError(f"{self.service_name} sign-in has expired.", SIGNIN_HINT, code="not_connected") from None
            raise ConnectorError(f"{self.service_name} refused the request: {text[:200]}", "Try again in a moment.") from None


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


def main(argv: list[str] | None = None, prog: str = "swift.connectors.google") -> None:
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("command", choices=["signin", "signout"])
    args = parser.parse_args(argv)
    signin() if args.command == "signin" else signout()


if __name__ == "__main__":
    main()
