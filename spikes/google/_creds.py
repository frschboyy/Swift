"""Shared credential handling for the S4 probes. Prints lengths, never values."""

from __future__ import annotations

import json
import os
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/contacts.readonly",
]
KEYRING_SERVICE = "Swift/Google-probe"
KEYRING_USER = "refresh_token"
TOKEN_URI = "https://oauth2.googleapis.com/token"


def client_secret_path() -> Path:
    return Path(os.environ["APPDATA"]) / "Swift" / "client_secret.json"


def load_client() -> dict:
    data = json.loads(client_secret_path().read_text(encoding="utf-8"))
    return data.get("installed") or data["web"]


def credentials_from_keyring(scopes: list[str] | None = None):
    import keyring
    from google.oauth2.credentials import Credentials

    rt = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    if not rt:
        raise SystemExit("no refresh token in Credential Manager; run oauth_probe.py first")
    c = load_client()
    return Credentials(
        token=None,
        refresh_token=rt,
        token_uri=TOKEN_URI,
        client_id=c["client_id"],
        client_secret=c["client_secret"],
        scopes=scopes or SCOPES,
    )
