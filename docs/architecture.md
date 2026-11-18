# Architecture

How Swift is put together today. **Rewritten 2026-11-18:** the earlier first half described the Phase 0 plan
(a Tk overlay, pystray, Ollama, Piper workers, a named mutex, availability states); none of that was built, and that
text is in `docs/archive/2026-10-mvp-plan/SWIFT_BUILD_PROMPT.md` §4. Who owns each responsibility, module by module,
is [`architecture/ownership.md`](architecture/ownership.md); a request's full path as audited in October is
[`audit/architecture-as-built.md`](audit/architecture-as-built.md).

## Processes

| Process | What it is | Started by |
|---|---|---|
| Overlay | Tauri v2 (`overlay/src-tauri`, Rust) with a TypeScript UI (`overlay/src`). One main window draws the card in front and the requests behind it (the Deck, ADR-018), plus pane windows for the stack and the reader, and the text box. Click-through outside cards; never takes focus. One copy at a time (`tauri_plugin_single_instance`) | The owner (`npm run tauri dev`) |
| Backend | `python -m swift.backend` (`backend/__main__.py`): one asyncio loop holding the session, executors, gateway, scheduler, and the IPC server on a loopback WebSocket with a per-launch token | The overlay (`backend.rs`), inside a kill-on-close Job Object |
| Claude Code CLIs | One `claude` process per run, plus a warm spare, through claude-agent-sdk | The backend (`executors/claude_code.py`) |
| Speech in and out | Local speech-to-text (Parakeet, `stt/`), wake listening (`wake.py`, `wake_acoustic.py`), Windows voices through SAPI (`speech.py`) on their own threads | The backend |

Rules that hold across them: all state changes happen on the backend's loop; the overlay draws what the backend
sends (`ipc/protocol.py`, `overlay/src/protocol.ts`) and owns no request state of its own; user-facing apps Swift
opens are outside the Job Object, so they outlive it.

## Trust boundary

Every side effect that leaves this PC or acts for the owner elsewhere (email, calendar, files, programs) goes through `security/gateway.py` (built in ADR-010 for email; more workflows reuse it). Swift's own device changes are the one exception, below. The full sequence is:

1. validate
2. resolve targets
3. evaluate policy
4. confirm
5. journal `PENDING`
6. execute
7. verify
8. journal `DONE`/`FAILED`
9. audit

What exists today (ADR-010):

- `ActionGateway.execute` runs those steps for `send_email`. Policy is a fixed table: external side effects always need the confirm card; there is no "auto". The approval is bound to the draft's digest, used once, and voided if the draft changes.
- The journal (`%LOCALAPPDATA%\Swift\journal.jsonl`) holds metadata only; an action still `PENDING` at startup is logged and never resumed.
- `tests/unit/test_architecture.py` checks by AST scan that a connector's `send` is reached only through the gateway's `Action.perform`.

### Swift's own device changes (ADR-016 §3, Phases A1 and A2)

The system lane (`swift/system/`) changes this PC directly, without a confirm card: volume, mute, media keys, dark mode, brightness, lock, window moves, a screenshot, opening a Windows settings page, and a web search in the default browser. The exception is deliberate and bounded:

- **Local and low-stakes.** Each change stays on this PC and is reversible ("undo that", for 10 minutes: volume, mute, theme, brightness, timers and reminders) or harmless (lock, a window move, a settings page). Nothing here sends, deletes, buys or shuts down. Sleep, restart, shut down and sign out are not in the lane; they go to the agent and its confirm card.
- **What the owner said, nothing else.** The lane runs only on the owner's own words, routed by the rules (`routing/rules.py`); no model, page or connector output can reach it. Targets are fixed: settings pages from a built-in table, web searches only to `google.com` with the spoken query, and `WindowsSystem.open_uri` refuses anything that isn't `ms-settings:` or `https://`.
- **Journaled.** Each change is written to the same action journal as the gateway (`PENDING`, then `DONE`/`FAILED`, tool `system.<intent>`), metadata only: never a search query or a reminder's words. Reads (battery, volume) and Swift's own timers and reminders (`schedule.json`) are not journaled.

- **Asking first (A2).** A change that takes something away the owner may be relying on (Wi-Fi or Bluetooth off, airplane mode on) is not done on the request: Swift asks ("Turn off Wi-Fi?") and does it only on a yes within 45 s. A short "yes" heard hands-free is not taken, the same rule as confirm cards.
- **The agent's `system_action` (A2).** For a mixed request ("turn the volume down and write a haiku") the agent can do the system part, but only what the owner asked for: each intent must also be found in the owner's own words for that request (`RunScope.said`). This tool goes through the gateway like any other (`system_action` reversible, `system_action_disruptive` behind the confirm card), so model output, web pages or files can never trigger a system change by themselves.

## Swift's voice (ADR-016 §4, Phase B)

- `swift/speech.py`: `WindowsSpeaker` says the spoken form of an answer (`spoken`: a sentence or two, no markdown) through SAPI on its own thread; `FakeSpeaker` in tests and debug mode.
- The session decides when (`_speak_reply`): spoken requests get spoken answers, typed ones don't; never while the owner is away. The hotkey, Esc and typing stop it.
- Half-duplex: while Swift talks, and 0.6 s after, the open microphone's utterances are dropped (`own_voice`), and the reply window reopens when the voice ends.

## Workflows and "show me" (ADR-010)

- **Swift's tools** (`swift/workflows/tools.py`): `find_contact`, `draft_email`, `send_email`, `present`, one `ToolHost` with one open `RunScope` per run. Claude Code gets them in its in-process `swift` MCP server; Codex and Hermes will get them over a loopback HTTP MCP server (phase B).
- **Recipients** come only from `contacts` in config or the connector's directory, through `find_contact`; an address from the model or from speech alone is refused.
- **Artifacts**: the tools publish typed, versioned snapshots (`email_draft`, `recipient`, `send_status`, `text`, `list`, `table`) as `artifact` messages. The session keeps the latest of each for the current run.
- **Voice mid-run**: push-to-talk while working goes to `rules.route_midrun` ("show me", "show the draft", "hide that", "stop"). Swift answers in milliseconds, without a model or a new run.
- **"Show me"**: the session picks the artifact for the run's phase (`ArtifactStore.pick`) and sends `view`; the overlay swaps the working card's body for it in place.

## Connectors (ADR-005)

Integrations sit behind a connector boundary:
- A connector contributes `ToolSpec`s to the registry.
- **Swift's own code or config** assigns each tool's capability, side-effect class, and target extraction. A connector's self-description is never trusted.
- Connector output is `UNTRUSTED_EXTERNAL`.
- Connector tools execute only through the gateway, like every other tool.

Built so far: `connectors/fake.py` (tests, debug mode) and `connectors/gmail.py` (`drafts.create` + `drafts.send` under `gmail.compose`; People search of contacts and the people the owner has emailed, under `contacts.readonly` and `contacts.other.readonly`, cached briefly in memory; the owner's name from `userinfo.profile` signs drafts; safe calls retried after a dropped connection; refresh token only, in Credential Manager). A plugin/MCP host for third-party connectors is Phase 7.

## Configuration and logging (Phase 0)

- `config/paths.py` places config in `%APPDATA%\Swift`, and data, logs, and models in `%LOCALAPPDATA%\Swift`.
- `settings.py` reads the owner's `config.yaml`: typed sections, unknown keys refused, `%VAR%` paths expanded. Phase 0's
  TOML loader (`config.toml`, `permissions.toml`, `profiles.toml`, `aliases.toml`) was never wired in and was removed
  on 2026-11-15 (HA-CFG-06).
- `logging_setup.py` runs every record through a redaction patcher before any sink sees it. Tracebacks are formatted and redacted by the patcher, and loguru's `diagnose`/`backtrace` are off, so local variables are never rendered.
- Importing `swift` forces `HF_HUB_OFFLINE=1` and the related offline/telemetry switches.

## Swift and its providers (ADR-008)

- **Swift** owns the conversation: routing, approvals, follow-up context, presenting results, and its own name.
- **Providers** are executors that work for Swift. Today that is Claude Code; the demo executor appears as "Demo agent".
- Each provider declares a `ProviderInfo` and reports normalized `activity` steps.
- The session attaches `agent` to every run message.
- The overlay turns that normalized data into words in `overlay/src/agents.ts`. Status labels never name the provider ("Reading", "Working on it"; owner, 2026-10-26); only the byline on a result does ("Swift · via Claude Code").
- When the owner calls Swift "Claude" or "Codex", Swift says who it is, at most once an hour.
