# S4 report: Google

**Run:** 2026-10-15/16, on the target laptop, personal Gmail `francischianu15@gmail.com`. Status: `PASSED (owner-run on target)` for the technical checks. The publishing-status decision is open.

## Results

| Check | Result |
|---|---|
| OAuth installed-app flow (loopback redirect, `access_type=offline`, `prompt=consent`) | Works |
| `gmail.compose` | Granted. A draft was created and deleted OK |
| `calendar.events` | Granted |
| `calendar.freebusy` | **Granted.** The scope name exists, which settles the spec's [verify] |
| `contacts.readonly` | Granted. People API returned 316 contacts |
| Refresh token length | 103 characters |
| Full credential JSON length | 892 characters |
| Refresh token in Credential Manager (`Swift/Google-probe`) | Stored and read back |
| Full credential JSON in Credential Manager | Also stored and read back (892 < the ~1280 limit) |

Note: the OAuth client JSON in `%APPDATA%\Swift\client_secret.json` is 411 bytes and sits outside the repo.

## Free/busy (7-day window)

| Calendar | `busy_blocks` | `errors` |
|---|---|---|
| Own (`primary`) | 0 | none |
| Shared with free/busy only (`frchianu@gmail.com`) | **2** | none |
| Not shared (`frchianu1@gmail.com`) | 0 | **`[{"domain": "global", "reason": "notFound"}]`** |

Findings:
- A calendar shared as free/busy returns real busy blocks, so the E2 "shared" path works for Gmail-to-Gmail.
- An unshared calendar does **not** fail the request. It returns HTTP 200 with `busy: []` and an `errors` entry whose `reason` is `notFound`. A template that only reads `busy` would see an empty list and wrongly conclude the attendee is free. **The template must check `errors` first**, per §9.1.
- `notFound` also covers an address that doesn't exist, so Swift can't tell "not shared" from "no such account". The spoken message should say "I can't see their calendar" and not claim to know why.
- Not tested: Google Workspace (e.g. university) addresses, where admin policy can change sharing behaviour.

## Still to decide: publishing status

| Option | Effect |
|---|---|
| Testing | Refresh tokens expire after 7 days; weekly re-sign-in |
| In production (unverified) | No 7-day expiry; one "unverified app" warning |

Choice: **not yet recorded.** It becomes part of ADR-004.

## Implications for the spec

- §3: the refresh-token-only rule holds and has headroom. Even the full credential JSON fit in the vault here, but the limit may differ elsewhere, so the rule stays.
- §9.1: scope list confirmed as written; no change.
- Phase 5 templates (P5-4): treat any non-empty `errors` entry for an attendee as "calendar not visible".

## Cleanup

The probe token is still in Credential Manager under `Swift/Google-probe`. Remove it with `uv run --group spikes python spikes/google/oauth_probe.py --cleanup` when S4 is signed off.
