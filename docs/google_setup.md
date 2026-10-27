# Google setup (spike S4)

Swift uses **your own** Google Cloud project with an installed-app (desktop) OAuth client. Nothing here is shared with anyone else. Expect this to take about 20 minutes.

> Google's Cloud Console changes its menus often. If a label below doesn't match what you see, look for the closest equivalent and note the difference in `spikes/google/REPORT.md`.

## 1. Create the project
1. Go to <https://console.cloud.google.com/> and sign in with the **personal Gmail account** Swift will act for (ADR-000).
2. Open the project picker, choose **New project**, and name it `swift-personal`. No organisation is needed.

## 2. Enable the APIs
Go to **APIs & Services → Library** and enable each of these:
- **Gmail API**
- **Google Calendar API**
- **People API**

## 3. Configure OAuth consent
Go to **APIs & Services → OAuth consent screen**. Newer consoles call this **Google Auth Platform**.
1. **User type:** External.
2. **App name:** `Swift (personal)`. Use your own email for both the support and developer contact fields.
3. **Scopes / Data access:** add the scopes below. Expect restricted or sensitive warnings; they're normal for personal use.

   | Scope | Purpose | Notes |
   |---|---|---|
   | `https://www.googleapis.com/auth/gmail.compose` | Create, update, and send drafts | Restricted scope |
   | `https://www.googleapis.com/auth/calendar.events` | Read, add, change and remove events, with Google Meet links | Sensitive |
   | `https://www.googleapis.com/auth/calendar.freebusy` | Free/busy for you and attendees | **[verify it's offered]**; if not, use `calendar.readonly` |
   | `https://www.googleapis.com/auth/contacts.readonly` | Contact lookup: your saved Google contacts | Sensitive |
   | `https://www.googleapis.com/auth/contacts.other.readonly` | Contact lookup: "other contacts", the people you've emailed | Sensitive |
   | `https://www.googleapis.com/auth/userinfo.profile` | Your name, to sign the emails Swift drafts | Not sensitive |

   Do **not** add `gmail.readonly`. Email search stays off (§1.4).
4. **Test users / Audience:** add your own Gmail address.

## 4. Choose a publishing status (S4 decision)

| Option | Effect | Trade-off |
|---|---|---|
| **Testing** | Works immediately for listed test users | Refresh tokens **expire after 7 days**, so you sign in again weekly |
| **In production** (unverified) | Tokens don't expire on that schedule | You click through an "unverified app" warning once; restricted scopes may have a user cap |

Record your choice in `spikes/google/REPORT.md`. It becomes part of ADR-004.

## 5. Create the desktop client
1. Go to **Credentials** (or **Clients**), choose **Create credentials → OAuth client ID**, and pick the type **Desktop app**.
2. Download the JSON file.
3. Save it **outside the repo**: `%APPDATA%\Swift\client_secret.json`. The repo's `.gitignore` also blocks `client_secret*.json` as a safety net.

## 6. Test accounts for the calendar checks
- A second account plays the "**supervisor**". A spare Gmail is fine.
- **Shared case:** in that account's Google Calendar, go to **Settings → Share with specific people** and add your main account with "See only free/busy".
- **Unshared case:** you need one more address whose calendar is *not* shared with you. A third spare account, or a friend's address used only for free/busy, works.

## 7. Run the probes
From the repo root:

```powershell
uv sync --group spikes
uv run --group spikes python spikes/google/oauth_probe.py
uv run --group spikes python spikes/google/freebusy_probe.py --shared SUPERVISOR@gmail.com --unshared OTHER@gmail.com
```

Paste the full output into the chat. The probes never print tokens, only their lengths and the scopes granted.

## 8. Signing in again after Swift asks for more (2026-10-27)
Swift now also asks for `contacts.other.readonly` and `userinfo.profile` (the table in step 3). A token from an earlier sign-in doesn't cover them, so **sign in again once**, yourself, in your own browser:

```powershell
uv run --group spikes python -m swift.connectors.gmail signin
```

Add the two scopes on the consent screen first (step 3) if your console lists scopes there. The sign-in prints `granted` or `MISSING` for each scope. Until you sign in again, Swift still finds your saved contacts, but not the people you've only emailed, and it signs emails with `owner_name` from `config.yaml` (or just "Regards,").

## 9. Revoking access later
Go to <https://myaccount.google.com/permissions>, find **Swift (personal)**, and choose **Remove access**. Also delete the `Swift/Google-probe` entry from Windows Credential Manager. The probe deletes it itself, but check.
