"""S4: free/busy visibility and the exact error format for unshared calendars.

Usage:
  uv run --group spikes python spikes/google/freebusy_probe.py --shared SUPERVISOR@gmail.com --unshared OTHER@gmail.com [--gmail-draft-test]

Prints the raw freebusy response for: your primary calendar, a calendar
shared with you, and one that is not. Also checks the People API scope by
counting contacts (count only), and with --gmail-draft-test creates and then
immediately deletes an empty draft to prove gmail.compose works.
Uses the refresh token stored by oauth_probe.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _creds import credentials_from_keyring  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shared", required=True, help="address whose calendar IS shared with you")
    ap.add_argument("--unshared", required=True, help="address whose calendar is NOT shared with you")
    ap.add_argument("--gmail-draft-test", action="store_true")
    args = ap.parse_args()

    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    creds = credentials_from_keyring()
    creds.refresh(Request())

    cal = build("calendar", "v3", credentials=creds, cache_discovery=False)
    now = datetime.now(timezone.utc)
    body = {
        "timeMin": now.isoformat(),
        "timeMax": (now + timedelta(days=7)).isoformat(),
        "items": [{"id": "primary"}, {"id": args.shared}, {"id": args.unshared}],
    }
    try:
        resp = cal.freebusy().query(body=body).execute()
        print("freebusy response (busy blocks summarized as counts):")
        for cid, entry in resp.get("calendars", {}).items():
            summary = {"busy_blocks": len(entry.get("busy", [])), "errors": entry.get("errors")}
            print(f"  {cid}: {json.dumps(summary)}")
    except HttpError as exc:
        print(f"freebusy HttpError {exc.status_code}: {exc.reason}")

    people = build("people", "v1", credentials=creds, cache_discovery=False)
    try:
        r = people.people().connections().list(resourceName="people/me", pageSize=100, personFields="names").execute()
        print(f"people API: {r.get('totalPeople', len(r.get('connections', [])))} contacts visible")
    except HttpError as exc:
        print(f"people API HttpError {exc.status_code}: {exc.reason}")

    if args.gmail_draft_test:
        gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
        import base64

        raw = base64.urlsafe_b64encode(b"Subject: Swift S4 probe (auto-deleted)\r\n\r\n").decode()
        try:
            d = gmail.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
            gmail.users().drafts().delete(userId="me", id=d["id"]).execute()
            print("gmail.compose: draft created and deleted OK")
        except HttpError as exc:
            print(f"gmail HttpError {exc.status_code}: {exc.reason}")


if __name__ == "__main__":
    main()
