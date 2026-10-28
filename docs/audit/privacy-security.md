# Privacy and security, as verified (October 2026)

## Data flows

| Data | Where it goes | Scope check against the threat model |
|---|---|---|
| Microphone audio | RAM, then the local STT (parakeet onnx, offline forced at import). Saved as WAV only when `stt.save_audio` is on | ok. **The owner has it on:** 148 clips, 27 MB, no retention (B-06). T14 says RAM-only; it should say "RAM, unless saving is on" |
| Transcripts | The local interaction log (`interactions.jsonl`, the owner's own). Redacted in `swift.log`. Sent to Claude Code as the request | ok |
| Speech out | SAPI, local | ok |
| The request, thread context, the desktop context line, the selected text (only when asked) | Anthropic, through Claude Code | ok, as decided (ADR-007; ADR-016 Q16 asks to state it plainly) |
| Files Claude Code reads | Anthropic | No card in the working folders, Documents and Downloads; a card elsewhere; secrets never (B-01, fixed) |
| Web pages fetched and search queries | Anthropic's tools; the page's server sees the fetch | Fetches are now limited to given addresses (A-03) |
| Email (drafts, send), calendar (list, create, update, delete), People search | Google, under the owner's OAuth; the refresh token is in Credential Manager (`keyring`) | ok: T9 checked in code (`google.py`: `keyring.get_password`; no token written to a file) |
| Calendar titles (a cache for matching) | Memory, refreshed every 10 min | ok |
| Timers and reminders (labels) | `schedule.json`, local | ok; not journaled |
| Overlay positions | `overlay.json` | ok |
| The action journal | `journal.jsonl`: tool, digest prefix, recipient domains, receipt ids; `reason` on failure | ok (metadata). A failure reason holds the connector's error text, cut at 200 characters |

## Can untrusted content steer a run into a side effect without its card?

Every path that reaches a side effect, checked:

| Path | Gate | Result |
|---|---|---|
| Agent → Swift tool (`mcp__swift__*`) | `ToolHost.call` → gateway; workflow runs are limited by their `Grant` | ok. Confirm-policy tools always show a card; contacts only |
| Agent → `desktop_write` / `fill_in_email` / `desktop_open` | Reversible: no card, journaled | **Gap B-02:** no owner-words gate outside workflows. Since A-01 and A-02 it can no longer send (no bare Enter) or run commands (no terminals); it can still type text into the app in front |
| Agent → `system_action` | The intent must be in the owner's words (`RunScope.said`); disruptive changes need a card | ok (`test_system_phase_a2`) |
| Agent → Bash, Edit, Write | A card per call; refused in workflow runs | ok; the card now shows the whole command (A-12) |
| Agent → WebFetch | Given addresses only (A-03) | fixed |
| Agent → Read, Glob, Grep | By path (`read_scope.py`): read folders free, elsewhere a card, secrets never | fixed (B-01) |
| "Undo that" | `gateway.undo_last` with its own card | ok |
| A change of mind ("actually…") | Goes to the same run as a new turn; `scope.said` is not widened by it | ok (safe direction) |
| A resumed parked conversation | A new run; `said` is the new words ("go on"), so `system_action` can't act on the old text | ok (safe direction) |
| The system lane | Only the owner's own words, routed by rules; `open_uri` takes `ms-settings:` and `https://` only | ok |
| Hands-free and typed approvals | The name is needed (cards; the Wi-Fi question since A-04); typing never approves | fixed |

## Do confirm cards describe what will happen?

| Card | Shows | Verdict |
|---|---|---|
| Email send | The recipients by name, the subject, and the draft as an artifact; bound to the digest of recipients, subject and body | accurate |
| Calendar add, change, remove | Title, when, before → after, attendees, "Google emails them", Meet | accurate |
| Bash, PowerShell | The whole command, its lines kept (A-12) | fixed |
| Write | The path, the line count, the first line | the content isn't shown; the path is (enough to spot a Startup-folder write) |
| Edit | The path, and 70 characters of the old and new text | partial; working-folder files, reversible with git |
| System "Turn off Wi-Fi?" | The question | accurate |

## Tokens

- **Google:** only the refresh token is stored, in Credential Manager (`Swift/Google`). The client secret file is `%APPDATA%\Swift\client_secret.json`, by design (an installed-app client).
- **Claude:** the Claude Code CLI keeps its own sign-in (`~\.claude`). Swift never reads or stores it, but Claude Code's own Read could (B-01).
- No tokens in `swift.log`: the patterns mask bearer, `ya29.`, `1//`, `GOCSPX-`, `AIza` and JWTs, and secret-named keys.

## Logs

- **The real `swift.log`:** transcripts appear only as `[REDACTED:n chars]`, with 0 email addresses in 2160 lines.
- **Free-text fields:**
  - `reason` and `detail` are not content keys.
  - A denied action's reason can include an address the model gave (B-07, suspected, never seen).
  - Claude Code's error `detail` comes from the CLI's own messages.
- **The interaction log:** it holds transcripts, as intended; it is the owner's local file, and `report.py` reads it.

## The overlay and the text box

- **Capture-excluded windows:** the overlay sets them (`win.rs`), so screenshots and screen sharing don't show cards.
- **The text box:**
  - It sends typed text over the loopback WebSocket with the per-launch token.
  - Text is capped at 2000 characters (`MAX_TYPED`).
  - It is routed like speech, and can't approve.
  - Nothing typed is logged except its length.

## Remaining risks

1. **B-01 (fixed):** a Grep over a read folder can still search a secret-looking file inside it.
2. **B-02:** the agent typing into the app in front without the owner asking for writing.
3. **The A-03 slow channel:** a page listing many links lets a run leak a few bits per fetch.
4. **Bystander audio** in saved clips (B-06).
5. **Prompt injection through the selection text or an email body**: the same gates apply. A card is still needed for anything external, and recipients come only from contacts.
