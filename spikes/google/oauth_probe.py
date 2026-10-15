"""S4: OAuth installed-app flow, granted scopes, token sizes, Credential Manager limits.

Usage:  uv run --group spikes python spikes/google/oauth_probe.py [--cleanup]

1. Opens the browser for consent (loopback redirect on a random local port).
2. Reports which scopes were actually granted (verifies calendar.freebusy).
3. Reports the length of the refresh token and of the full credential JSON.
4. Stores ONLY the refresh token in Windows Credential Manager under
   "Swift/Google-probe" and reads it back.
5. Tries to store the full credential JSON as well, to find out whether it
   fits in the vault (§3: blob limit is about 1280 UTF-16 characters), then
   deletes that test entry.
Nothing secret is printed. --cleanup deletes the stored refresh token.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _creds import KEYRING_SERVICE, KEYRING_USER, SCOPES, client_secret_path  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cleanup", action="store_true")
    args = ap.parse_args()

    import keyring

    if args.cleanup:
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
            print("deleted Swift/Google-probe refresh token")
        except keyring.errors.PasswordDeleteError:
            print("nothing to delete")
        return

    from google_auth_oauthlib.flow import InstalledAppFlow

    path = client_secret_path()
    if not path.exists():
        raise SystemExit(f"client secret not found at {path}; see docs/google_setup.md step 5")

    flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent", open_browser=True)

    granted = sorted(getattr(creds, "granted_scopes", None) or creds.scopes or [])
    print("requested scopes:")
    for s in SCOPES:
        print(f"  {'GRANTED' if s in granted else 'MISSING'}  {s}")
    extra = [s for s in granted if s not in SCOPES]
    if extra:
        print("extra granted:", extra)

    rt = creds.refresh_token or ""
    full = creds.to_json()
    print(f"refresh_token length: {len(rt)} chars")
    print(f"full credential JSON length: {len(full)} chars")
    print(f"access token expiry: {creds.expiry}")

    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, rt)
    ok = keyring.get_password(KEYRING_SERVICE, KEYRING_USER) == rt
    print(f"refresh token stored in Credential Manager and read back: {ok}")

    try:
        keyring.set_password(KEYRING_SERVICE, "full_json_size_test", full)
        back = keyring.get_password(KEYRING_SERVICE, "full_json_size_test")
        print(f"full JSON stored in vault: {back == full}")
    except Exception as exc:  # noqa: BLE001 - we want the exact failure class
        print(f"full JSON NOT storable in vault: {type(exc).__name__}: {exc}")
    finally:
        try:
            keyring.delete_password(KEYRING_SERVICE, "full_json_size_test")
        except Exception:  # noqa: BLE001
            pass

    print("\nNext: freebusy_probe.py. Run oauth_probe.py --cleanup when S4 is finished.")


if __name__ == "__main__":
    main()
