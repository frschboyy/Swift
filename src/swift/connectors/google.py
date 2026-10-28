"""The owner's Google sign-in, shared by the Gmail and Calendar connectors (ADR-010 §9, ADR-011 W1).

One consent covers every scope Swift uses:

| Scope | For |
|---|---|
| ``gmail.compose`` | sending a draft the owner approved (spike S4) |
| ``contacts.readonly`` | ``find_contact``: the owner's Google contacts |
| ``contacts.other.readonly`` | ``find_contact``: "other contacts", the people the owner has emailed |
| ``userinfo.profile`` | the owner's name, to sign the emails Swift drafts |
| ``calendar.events`` | creating an event the owner approved (spike S4) |

No ``gmail.readonly``: Swift never reads or searches mail. ``gmail.metadata`` (ADR-011
§13.4) belongs to the watchers phase and isn't asked for yet.

- Only the refresh token is stored, in Windows Credential Manager under
  ``Swift/Google`` (threat model T9). The OAuth client file stays in
  ``%APPDATA%\\Swift\\client_secret.json`` (docs/google_setup.md).
- A token from before a scope was added still works for the older scopes; the new
  one fails with "insufficient scopes" until the owner signs in again.
- A dropped connection (WinError 10053/10054, a timeout) or a 5xx is retried, at most
  twice with a short backoff, but only for calls that are safe to repeat (``retry=True``:
  reads, a patch, a delete). Sending an email or adding an event is never repeated.

Signing in is the owner's job, in their own browser::

    uv run --group spikes python -m swift.connectors.gmail signin
    uv run --group spikes python -m swift.connectors.gmail signout

The Google libraries are imported only when a connector is used, so Swift runs
without them while no Google connector is configured.
"""

from __future__ import annotations

import argparse
import asyncio
import errno
import json
import os
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from loguru import logger

from swift.connectors.base import ConnectorError

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/contacts.other.readonly",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar.events",
]
KEYRING_SERVICE = "Swift/Google"
KEYRING_USER = "refresh_token"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SIGNIN_HINT = "Run `uv run --group spikes python -m swift.connectors.gmail signin` and sign in, then try again."

# Waits before the second and third try of a call that is safe to repeat.
RETRY_DELAYS_S = (0.5, 1.5)
# Windows' WSAECONNABORTED / WSAECONNRESET / WSAETIMEDOUT, and their POSIX names.
_DROPPED = {10053, 10054, 10060, errno.ECONNABORTED, errno.ECONNRESET, errno.ETIMEDOUT, errno.EPIPE}

T = TypeVar("T")


def transient(exc: BaseException) -> bool:
    """A failure worth one more try: the connection dropped or timed out, or Google had a 5xx."""
    if isinstance(exc, (ConnectionError, TimeoutError, socket.timeout)):
        return True
    if isinstance(exc, OSError) and (exc.errno in _DROPPED or getattr(exc, "winerror", None) in _DROPPED):
        return True
    status = getattr(getattr(exc, "resp", None), "status", None)
    try:
        return status is not None and 500 <= int(status) < 600
    except (TypeError, ValueError):
        return False


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

    async def call(self, fn: Callable[[], T], *, retry: bool = False, changes: bool = False) -> T:
        """Run ``fn`` on a thread. ``retry``: it is safe to repeat, so a dropped connection is tried again.
        ``changes``: it changes something, so a connection that stays dropped means Swift can't tell
        whether it was done (``code="unknown"``), not that it failed."""
        delays = RETRY_DELAYS_S if retry else ()
        for attempt in range(len(delays) + 1):
            try:
                return await asyncio.to_thread(fn)
            except ConnectorError:
                raise
            except Exception as exc:  # noqa: BLE001 - Google errors become one readable failure
                if attempt < len(delays) and transient(exc):
                    logger.info("google call retried", service=self.service_name, attempt=attempt + 1,
                                error=type(exc).__name__)
                    await asyncio.sleep(delays[attempt])
                    continue
                if changes and transient(exc):
                    raise ConnectorError(
                        f"Swift lost the connection to {self.service_name} before it answered, so it can't tell "
                        "whether that was done.", f"Check {self.service_name} before trying again.", code="unknown",
                    ) from None
                raise self._failure(exc) from None
        raise AssertionError("unreachable")

    def _failure(self, exc: Exception) -> ConnectorError:
        if transient(exc):
            return ConnectorError(f"Swift lost the connection to {self.service_name}, so it couldn't finish.",
                                  "Try again in a moment.")
        text, low = str(exc), str(exc).lower()
        if ("insufficient" in low and "scope" in low) or "insufficientpermissions" in low:
            return ConnectorError(
                f"{self.service_name} isn't allowed yet: Swift's Google sign-in is missing a permission.",
                "Sign in again to grant it: " + SIGNIN_HINT, code="not_connected",
            )
        if "invalid_grant" in text or "401" in text:
            return ConnectorError(f"{self.service_name} sign-in has expired.", SIGNIN_HINT, code="not_connected")
        return ConnectorError(f"{self.service_name} couldn't do that: {text[:200]}", "Try again in a moment.")


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
