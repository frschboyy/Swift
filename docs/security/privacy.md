# Privacy policy: what Swift keeps, sends and deletes

**What Swift does today**, read from the code on `main` at `55a4886` (2026-11-15) and the threat model
([`docs/threat_model.md`](../threat_model.md)). It is not a statement of intent. Each line is marked:

- **Implemented**: the code does it, with the evidence named.
- **Partly**: some of it is built; what isn't is said.
- **Not built**: the policy wants it and the code doesn't do it.

"Implemented" means specified and in code, with a test where one is named. It doesn't mean verified on the real
PC: that needs an owner check (`CLAUDE.md`, "How to work").

Paths: `%APPDATA%\Swift` holds config; `%LOCALAPPDATA%\Swift` holds data (`config/paths.py`). Settings can move
some of them (`settings.py` `LoggingSettings`, `SttSettings`, `SystemSettings`).

## 1. What stays on the PC

| Data | Where | Status | Evidence |
|---|---|---|---|
| Live audio | RAM only | Implemented | `audio/recorder.py`; transcribed locally by `stt/transcriber.py` (Parakeet or faster-whisper). No cloud speech-to-text exists in `src/swift`. Offline environment forced at import (`swift/__init__.py`: `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`); threat model T11, test `tests/unit/test_offline_env.py` |
| Saved recordings | `%LOCALAPPDATA%\Swift\audio`, test set `stt_testset` | Implemented | `stt/recordings.py` (B-06): kept only when they can improve transcription; no network import, a test runs the loop with sockets cut (threat model, *Privacy of saved recordings*); `tests/unit/test_recordings.py` |
| Open-microphone speech not acted on | RAM, 6 s | Implemented | threat model T14; saved only if the owner addresses Swift right after |
| Interaction log (the owner's words, routes, approvals, `error_detail`) | `%LOCALAPPDATA%\Swift\interactions.jsonl` | Implemented | `runlog.py` docstring: "never leaves the machine"; transcripts in full by design (decision 8) |
| Run records (content-free events per request) | `%LOCALAPPDATA%\Swift\runs\<id>.jsonl` | Implemented | `runs.py` |
| Action journal (side effects, recipient domains) | `%LOCALAPPDATA%\Swift\journal.jsonl` | Implemented | `security/journal.py`; gateway writes `domains` here, never in `swift.log` (`gateway.py` "a domain can identify a person: the journal only") |
| Memory (facts, every version) | `%LOCALAPPDATA%\Swift\memory` | Implemented | `memory.py`; plain files, one writer, logs kinds only; `tests/unit/test_memory.py` |
| Parked conversations | `%LOCALAPPDATA%\Swift\parked.json` | Implemented | `parked.py`, `backend/__main__.py:419` |
| Timers and reminders | `%LOCALAPPDATA%\Swift\schedule.json` | Implemented | `system/scheduler.py`, `settings.SystemSettings.schedule_file` |
| Routing examples | config and data dirs | Implemented | `settings.demand_classifier.examples_file` |
| App log | `%LOCALAPPDATA%\Swift\logs\swift.log` | Implemented | `logging_setup.py`; see §4 |
| Overlay position | `%LOCALAPPDATA%\Swift\overlay.json` | Implemented | `overlay/src-tauri/src/prefs.rs` |
| Desktop context (app in front, selection) | not stored | Implemented | `desktop/windows.py`: "Nothing read here is logged; titles are used only to check the never-read list"; `desktop/base.py` `NeverRead` skips banking titles and private windows |

**A worker can't read Swift's own data.** `backend/__main__.py` `_swift_s_own` adds the config and data dirs, the
logs, interaction log, journal, run records, recordings and test set to the never-read list
(`executors/read_scope.py`). **Implemented** for Read, Glob and Grep; **partly** for Bash and PowerShell
(`ReadScope.in_command` reads the command's text, so a path built in pieces gets a card instead of a refusal;
X-20, README §2).

## 2. What goes to the answering model

The answering model is Claude Code in the cloud, through the Agent SDK (`executors/claude_code.py`), and the light
lane's one tool-free call (`executors/quick.py`) through the same sign-in. Threat model T11.

| What | Status | Evidence |
|---|---|---|
| The request's words (transcript or typed text) | Implemented, by design | `executors/base.WorkerTask.prompt` |
| The context pack: the previous exchange or the resumed parked task, where the owner is (app in front; no window text or title), words speech recognition was unsure of, the workflow catalogue, a change of mind | Implemented | `executors/base.ContextPack`; built at `session.py:2922-2932` (`_desktop_note`, `_unclear_note`, `_thread_context`, `library.catalogue()`); `desktop/base.py`: "Where the owner is … No text, no title" |
| The selection or selected files | Implemented, only when the request is about them | `desktop/base.py`: "read only when a request is about them" |
| Tool results: Swift's tools (contacts found, calendar events, drafts) and the agent's (command output, search results, pages) | Implemented, by design | the SDK returns them to the model |
| File contents the agent reads | Implemented: inside the read folders without a card, outside on a card, never in the never-read places | `read_scope.ReadScope.verdict` |
| Audio | Never | no audio path to the executor |
| Credentials | Never entered by Swift | `CLAUDE.md` hard limit; sign-in is owner-run (`signin.py`) |
| Claude Code's own session transcripts on disk | Not kept | `extra_args={"no-session-persistence": None}` and `setting_sources=[]` in `claude_code.py:568-573` and `quick.py:74-79` |
| A "local only" privacy class | Partly | `WorkerTask.privacy`; Claude Code refuses `"local"` (`claude_code.py:595`), and no local worker exists |

What the provider keeps on its side is the provider's policy, not Swift's; Swift can't delete it.

## 3. What goes to connectors (Google)

| What | Status | Evidence |
|---|---|---|
| Gmail: a draft created and sent, after its own card | Implemented | `connectors/gmail.py` (`drafts.create`, `drafts.send`); gateway `POLICY` |
| Gmail: reading or searching mail | Never | no `gmail.readonly` scope (`connectors/google.py` docstring) |
| Contacts: searched by name | Implemented | `contacts.readonly`, `contacts.other.readonly`; `find_contact` |
| Calendar: events listed, added, changed, removed on the primary calendar (changes after a card) | Implemented | `connectors/google_calendar.py`, `workflows/calendar.py` |
| Web pages: fetched only at addresses the run was given | Implemented, with an accepted leak of a few bits per fetch (OCT-03) | `security/web_scope.py`; A-03 |
| Search queries | Go to the search provider | OCT-03 |

### Connector scopes

`connectors/google.py` `SCOPES`, one consent for all: `gmail.compose`, `contacts.readonly`,
`contacts.other.readonly`, `userinfo.profile`, `calendar.events`. **Implemented.** `gmail.metadata` is for a later
phase and not asked for.

## 4. Logs

| Rule | Status | Evidence |
|---|---|---|
| `swift.log` holds no content: secrets and content fields redacted on every record | Implemented | `logging_setup._patch`, `redact`, content keys replaced by their length; `tests/unit/test_redaction.py` |
| The interaction line in `swift.log` is an allow-list | Implemented | `runlog.summary`, X-03/X-04/X-05/X-19 |
| Tracebacks carry exception types, not messages | Implemented | `test_redaction.py::test_an_exception_s_message_stays_out_of_a_traceback` |
| `swift.log` holds structure: reason codes, error classes, field roles, timings | Partly | timings and codes in many lines; connector failures log `connector_failed` with no cause (decision 8, **not built**) |
| Lines written before the X-fixes are unchanged | Known | README §1, "Older lines in `swift.log` are unchanged" |
| X-05's leftovers: `workflow skipped` can quote a workflow file, a bare `sk-ant-…` key isn't recognised, the backend's stderr is unchecked | Not built | README §2, X-05 entry |

## 5. Retention and sweeping

| Data | Kept for | Status | Evidence |
|---|---|---|---|
| Recordings with no flag | until the repeat window passes (`HOLD_S`), seconds | Implemented | `stt/recordings.py` |
| Flagged recordings | `audio.keep_days` (7; 0 keeps nothing), swept at start-up and daily | Implemented | `recordings.sweep`, `backend/__main__.py:143, 410` |
| Test set clips | at most 200, oldest dropped | Implemented | threat model T14 |
| `swift.log` | 5 files of 10 MB, rotated | Implemented | `logging_setup.py:171-172`, `logging.rotation_mb`, `retention_files` |
| Parked conversations | 24 h (questions 10 min) | Implemented | `parked.py` `KEEP_S`, `QUESTION_KEEP_S` |
| Interaction log | for ever | **Not built**: no rotation or sweep found | `runlog.py` has none |
| Run records | for ever | **Not built** | `runs.py` has none |
| Journal | for ever | **Not built** | `security/journal.py` has none |
| Memory | for ever, every version, the forgotten ones too | Implemented by design; **no way to erase** a version | `memory.py`: "every version, the forgotten ones too" |

A retention period for the interaction log, run records and journal is the owner's to choose; this policy doesn't
set one.

## 6. How the owner deletes each

| Data | How | Status |
|---|---|---|
| Recordings, index, test set | Tray: **Clear saved recordings** | Implemented (`backend/__main__.py:163-171`, `recordings.clear`) |
| A memory | "forget …" hides it; the versions stay | Partly: no erase. Deleting `%LOCALAPPDATA%\Swift\memory\versions\<key>` by hand erases it |
| Interaction log, run records, journal, parked, schedule, `swift.log` | Delete the file or folder by hand, with Swift stopped | Not built in Swift: no menu item or command |
| Google refresh token | Windows Credential Manager, entry `Swift/Google`; or revoke at the Google account's third-party access page | By hand; Swift has no sign-out |
| Claude Code sign-in | The CLI's own sign-out | Outside Swift |
| Everything | Delete `%LOCALAPPDATA%\Swift` and `%APPDATA%\Swift` | By hand |

## 7. Tokens and sign-ins

| Rule | Status | Evidence |
|---|---|---|
| Only Google's refresh token is stored, in Windows Credential Manager (`Swift/Google`) | Implemented | `connectors/google.py` (`keyring`), threat model T9 |
| The OAuth client file is `%APPDATA%\Swift\client_secret.json`; `.gitignore` blocks `client_secret*.json` and `.env` | Implemented | `google.py`, T9 |
| Sign-in is owner-run in the browser; Swift never sees or enters a password | Implemented | `google.py` `InstalledAppFlow`; `signin.py`; `CLAUDE.md` |
| Claude Code's sign-in is the CLI's own; Swift adds no credentials | Implemented | `executors/quick.py` docstring |
| Sign-in checks log the service and status only | Implemented | `signin.py` docstring |
| A worker can't read secret places (`.ssh`, `.env`, credential stores) | Partly | `read_scope.py` never-read list; Bash by command text only (X-20) |

## 8. What may appear in a pasted owner-check report

`spikes/owner_checks/report.py` reads `swift.log` and the interaction log and prints a report the owner pastes into a
chat (which sends it to the model that answers there).

| What | Status | Evidence |
|---|---|---|
| Check results, counts, reason codes, timings | Implemented, by design | the check rows |
| **The first 60 characters of each request's words** (or what was heard, if unclear), one row per request | Implemented: **the report carries the owner's words** | `report.py:98` |
| Contact names, addresses, email bodies, file contents | Not printed by any line found; not proven absent | no line found prints them; a transcript can contain a name ("email Ada …") |
| A warning on the report that it holds words | Not built | — |

So a pasted report is **not** content-free: it has the start of every request. The owner should know that before
pasting one into a chat. Whether to drop or mask that column is the owner's decision.

## 9. Gaps, in one list

1. No retention for the interaction log, run records and journal (§5).
2. No way to erase a memory version from Swift (§6).
3. No in-app deletion for anything but recordings (§6).
4. Connector failures have no reason in `swift.log` (decision 8).
5. X-05's leftovers in logs (§4).
6. Bash and PowerShell reach never-read places by a built path (X-20 is a safeguard).
7. A pasted owner-check report carries the start of each request (§8).
8. Bystander audio can be in a kept clip for up to 7 days (threat model T14, accepted).
