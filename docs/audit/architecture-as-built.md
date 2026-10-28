# Swift as built (October 2026)

What runs, checked in code at `9b2d934` plus this branch. `docs/architecture.md` still describes the Phase 0 plan in places (a Tk overlay, Piper, Ollama); this page is what is actually there.

## Processes

| Process | What it is | Started by |
|---|---|---|
| Overlay | Tauri v2 (`overlay/src-tauri`, Rust) with a TypeScript UI (`overlay/src`). Windows: the main card, a pane per other request, the stack, and the text box. Click-through outside cards (`win.rs`, `hit.rs`); positions in `overlay.json` | The owner (`npm run tauri dev`) |
| Backend | `python -m swift.backend` (`backend/__main__.py`): one asyncio loop (`Session`, executors, gateway, scheduler, IPC server on a loopback WebSocket with a per-launch token) | The overlay (`backend.rs`), inside a kill-on-close Job Object. **Not restarted if it dies** (B-04) |
| Claude Code CLIs | One `claude.exe` per run, plus a warm spare, plus a warm one for the light lane (`quick.py`). Each is killed after its run | The backend, through claude-agent-sdk 0.2.172 |
| Speech | SAPI (`speech.py`) on its own thread | The backend |

## The paths a request takes

```
hotkey ─┐
        ├─ capture (recorder, pre-roll) ─ speech gate ─ STT (parakeet, local) ─┐
wake  ──┘   (open mic: wake.py matches "hey Swift" in the transcript)          │
typed ──────────────────────────────────────────────────────────────────────────┤
                                                                                ▼
Session._interaction: thread, desktop context (if "this/here"), router (rules.route)
   ├─ "stop the research one" etc. → another request (route_target)
   ├─ control (stop, cancel, repeat, approve…) ─────────────────────────► answered here
   ├─ local: fast lane (time, maths…), open <name>, system lane ───────────► answered here, journaled for system
   ├─ quick (light.kind) → QuickModel (one tool-free Claude call) ──────► card; agent on Haiku if nothing came back
   ├─ workflow (library.match) → Claude Code with the playbook and a Grant ─┐
   └─ agent → Claude Code (demand: Haiku/Sonnet/Opus, escalation) ─────────┤
                                                                            ▼
                ClaudeCodeExecutor: spare CLI, `swift` MCP server, can_use_tool = _ask
                   ├─ Read/Glob/Grep: no card in the read folders; a card elsewhere; secrets never (B-01)
                   ├─ WebSearch: no card; WebFetch: no card, given addresses only (A-03)
                   ├─ Edit/Write/Bash: a card (whole command shown, A-12); refused in workflow runs
                   └─ mcp__swift__* → ToolHost.call(run) → RunScope (Grant limits tools)
                          └─ side effects → ActionGateway.execute:
                             validate → resolve (contacts only) → policy → card → journal PENDING
                             → digest check → perform → verify id → journal DONE/FAILED/UNKNOWN
                ▼
result card, spoken reply (auto: voice in → voice out), reply window (8 s, or 25 s after a question)
```

What can go wrong on each path, and where it is handled, is in [day-scenarios.md](day-scenarios.md). The failures this audit fixed are A-01 to A-12 in [2026-10-audit.md](2026-10-audit.md).

## Where each product rule is enforced

| Rule | Enforced in | Checked by |
|---|---|---|
| Recipients come only from contacts or `find_contact` | `ActionGateway.execute` step 2 (`scope.resolved`); calendar `_attendees`; `fill_in_email` targets | `test_workflows`, `test_calendar` |
| Approving hands-free needs Swift's name | `Session._hear_busy` (cards); `_system_answer` (Wi-Fi question, A-04) | `test_hands_free`, `test_audit_2026_10` |
| No hands-free listening while locked | `Lifecycle.handle` pauses the mic and sets `listening_paused`; `hear_wake` checks it before and after transcription (A-09) | `test_presence`, `test_audit_2026_10` |
| Logs content-free | `logging_setup.make_patcher` (content keys → length; secrets masked); the interaction log is the owner's local file | `test_redaction`; the real log has 0 addresses and transcripts redacted |
| Status labels generic | `overlay/src/agents.ts` ("Swift · via …"); `steps_for` drops "Starting Claude Code" | `test_providers` |
| Typing never approves | `_start_typed` (cards); `_system_answer` (A-04) | `test_stack`, `test_audit_2026_10` |
| Audio never leaves the machine | STT is local onnx (`HF_HUB_OFFLINE` forced at import); clips go only to `%LOCALAPPDATA%\Swift\audio` when `save_audio` is on | `test_offline_env` |
| Every side effect goes through the gateway | `ToolHost` tools → `gateway.execute`; the system lane is the one documented exception (journaled, local, reversible) | `test_architecture` (AST scan) |

## State, and where it lives

| State | File | Survives a restart |
|---|---|---|
| Timers, alarms, reminders | `%LOCALAPPDATA%\Swift\schedule.json` | yes. A due item is removed before it is shown (B-03) |
| Parked conversations | `parked.json` | yes |
| Overlay and pane positions | `overlay.json` | yes |
| Action journal | `journal.jsonl` | yes. `PENDING` at start is reported, never resumed |
| Interaction log (transcripts, the owner's own) | `interactions.jsonl` | yes |
| Threads, cards, runs, the warm CLIs | memory | no: a restart ends runs, and their cards go |

## Current state

| Area | State | Evidence |
|---|---|---|
| Wake, hotkey, STT, reply window, room-noise filters | works | report checks 1–3, 43, 45, 46 PASS |
| Fast and system lanes | works | parity 100% in every system family; checked in code |
| Light lane | works; A-10 fixed one swallow | probe, tests |
| Calendar workflow (read, add, change, cancel, Meet, undo) | works | checks 29–36 on 2026-10-27 |
| Email drafts, send, fill-in | works; the subject fix is unverified live | checks 41, 49 not yet re-run |
| Several requests at once | partly: A-07 and A-08 were real failures, now fixed | log 2026-10-28 01:42, 01:52 |
| Presence, held cards, the stack | works | checks 12, 13, 16 PASS; 14 and 22 not re-run |
| Spoken replies (Phase B) | unverified live | no owner check existed (now 59) |
| Overlay panes, drag, Read more | partly verified (checks 18–20 PASS by eye) | 150% scaling not checked |
| Backend crash recovery | missing (B-04) | `backend.rs` |
| Web answers (weather, news) | not built (Phase I); the agent answers in 10–17 s | parity `web` 0/10 |
