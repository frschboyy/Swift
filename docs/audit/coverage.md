# Audit coverage (October 2026)

What this audit read, traced, ran, or left out. **Read in full** means every line. **Traced** means the paths were followed through the code. **Skimmed** means the structure and the risky parts only.

## Backend (`src/swift`, about 17.7k lines)

| Area | Files | Depth |
|---|---|---|
| Action gateway and journal | `security/gateway.py`, `security/journal.py` | read in full |
| Claude Code executor and permission bridge | `executors/claude_code.py`, `claude_mapping.py`, `quick.py` | read in full (quick: connect and spare) |
| Workflow tools | `workflows/tools.py` (send, draft), `desktop_tools.py`, `system_tools.py`, `scope.py`, `calendar.py` (outcomes, attendees) | traced; `desktop_tools`, `system_tools` and `scope` read in full |
| Desktop on Windows | `desktop/base.py`, `desktop/windows.py` (writers, context, keys) | traced |
| Google connectors | `connectors/google.py`, `google_calendar.py`, `gmail.py` (send, retries) | traced |
| Session | `session.py` (3.5k lines): `_interaction`, `_hear_busy`, `hear_wake`, `_start_typed`, `_start_beside`, `_system_answer`, `_swift_confirm`, `_ask_card`/`_card_done`, `_close_scope`, `_finish`, `_speak_reply`, `notify_due` | traced; not read line by line |
| Attention and presence | `attention.py` (full), `lifecycle.py` (`handle`), `presence.py` (skimmed) | traced |
| Routing | `routing/rules.py` (via the probe), `light.py` (full), `fast.py` (skimmed); `workflows/library.py` (`match`, loading) | traced |
| System lane | `system/scheduler.py` (full), `system/lane.py`, `intents.py`, `control.py` (skimmed) | traced |
| Logging and redaction | `logging_setup.py` | read in full |
| Speech, STT, wake, recorder | `speech.py`, `stt/transcriber.py`, `wake.py`, `audio/recorder.py` | skimmed (timeouts, priming, pause and resume) |
| Not covered | `config/*`, `settings.py` (only the defaults used), `runlog.py`, `parked.py`, `stack.py`, `routing/classifier.py`, `identity.py`, `failures.py` | names and defaults only |

## Overlay

| Area | Depth |
|---|---|
| `src/agents.ts` (labels), `ipc.ts` (reconnect), `styles.css` (card detail), `main.ts` (card detail rendering) | traced |
| `src-tauri/src/backend.rs` (start, exit) | read the start and exit paths |
| `presenter.ts`, `panes.ts`, `pane.ts`, `stack.ts`, `win.rs`, `hit.rs`, `placement.rs`, `prefs.rs`, `lib.rs` | not reviewed beyond their tests: `npm test` 47 and `cargo test` 22, all passing |

## Docs read

- `docs/architecture.md`, `threat_model.md`, `backlog.md`;
- ADR-016: §1, §10–15;
- ADR-015: the typing rule;
- the sibling hand-over notes for ADR-010 to ADR-015 work;
- `docs/testing/owner-checks.md`;
- `spikes/owner_checks/report.py` (run on the real logs).

ADR-005 to ADR-014 were read only through those notes and the code.

## Evidence used

- **The owner's `swift.log`:** 2160 lines, 2026-10-23 to 2026-10-28.
- **`interactions.jsonl`:** 327 rows.
- **`journal.jsonl`:** existence only.

Transcripts were not quoted.

## Ran

| What | Result |
|---|---|
| Python tests | 1052 at the start, 1080 at the end, all passing |
| Overlay | `tsc --noEmit` clean; `npm test` 47 passing (a temporary `node_modules` junction, removed afterwards) |
| Rust | `cargo test` 22 passing, in the worktree's own `target` |
| Parity | 365/375 before and after |
| Owner report | `report.py` on the real logs, 2026-10-27 17:00 and 2026-10-28 00:00 |
| Route probe | 28 everyday requests through `rules.route` and `library.match` (see [day-scenarios.md](day-scenarios.md)) |

## Not done, and why

- **Nothing was run on the real microphone, screen, Google account or apps:** the ground rules.
- **No dev server on port 1420.** No harness session was needed: the only overlay change is one CSS property.
- **Idle CPU and memory over a long session:** the owner's Swift wasn't running.
- **The A-03 exploit was not tried against the real CLI:** that would mean making real model calls to a real attacker URL.
