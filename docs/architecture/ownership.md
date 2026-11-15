# Who owns what (component ownership map)

**Read from the code on `main` at `55a4886` (2026-11-15).** Each row names the one module that owns a
responsibility, its interface, the tests that pin it, and every **second owner** found: another place that
decides the same thing. Second owners are findings (`OWN-*` in [`docs/audit/findings.yaml`](../audit/findings.yaml));
this document doesn't fix them.

How to use it: before adding logic, find the row and change the owner (`CLAUDE.md`, "Respect the owners"). If the
thing you need isn't here, find its owner in the code and add a row.

Line numbers are as of `55a4886` and will drift; the function names won't, as often.

**Limits.** Found with grep and excerpts, not a full read of `session.py` (4,989 lines). A second owner hidden in
`session.py` under a name not searched for may be missing. Where a row says "not checked", it wasn't.

## Summary

| Responsibility | Owner | Second owners found |
|---|---|---|
| Who may approve what, from where | `intake.approves` | none since foundation decision 10 (OWN-01, OWN-02, OWN-03 fixed) |
| An approved Swift action runs as shown | `security/gateway.ActionGateway.execute` | Worker tool cards decided in `executors/claude_code` (OWN-05) |
| Conversation and question state | `session` (questions), `dialogue.Dialogue` (parsing an answer), `answer_window.AnswerWindow` (its clock) | none found; split by design |
| What's on screen | overlay `presenter.ts`; backend view in `drawn.Drawn` | `session._on_screen` decides from backend state, not the overlay's `screen` ack (OWN-04) |
| Card countdowns | `attention.Attention` (confirm cards), `answer_window` (questions) | none: the overlay only draws (`presenter.ts` header, T-08) |
| Run records | `runs.RunRecords` | interaction log, journal, `parked`, `exchange` each keep a part (by design, see below) |
| Contacts and recipients | `workflows/tools.find_contact` writes `RunScope.resolved`; the gateway checks it | none found |
| Web addresses | `security/web_scope.WebScope` (the matcher) | two callers with different source rules: `claude_code` (WebFetch) and `desktop_tools._open_url` (OWN-06) |
| Read scope | `executors/read_scope.ReadScope` | none found (`desktop/base.NeverRead` is the separate list for apps and window titles) |
| Memory | `memory.Store` | none found |
| Speech recognition | `stt/transcriber` | none found |
| Wake | `wake` (words); `wake_acoustic` not wired in | none found |
| Speech output | `speech.Speaker` | none found |
| Connectors | `connectors/*` behind `connectors/base` | none found |
| Recovery after a connector failure | sign-ins: `signin.SigninWatch`; other failures: the gateway's `_failed` reports to the agent | none found; no reason codes yet (decision 8) |
| Windows automation (other apps) | `desktop/windows.WindowsDesktop` (reading, writing, focus); `system/control.WindowsSystem` (window actions, device) | split by job, not a second owner |
| Swift's own window placement | overlay Rust `placement.rs`, `prefs.rs` | none found |
| Presence (locked, away, paused) | `presence` + `intake` step 1 | about four checks in `session` (existing RV-15) |
| Logging (`swift.log`) | `logging_setup` (redaction on every record) | none found |
| Interaction log | `runlog.InteractionLog` | none found |
| Settings | `settings` (`config.yaml`) | `overlay.json` (split by design). The unused `config/loader` TOML was removed on 2026-11-15 (HA-CFG-06) |
| The agent executor | `executors/claude_code.ClaudeCodeExecutor` behind `executors/base.Executor`; chosen by `executors/providers` | none found |

## 1. Action approval

### Who may approve, from where

- **Owner:** `src/swift/intake.py` `approves(source, *, named, level, paying=False) -> Verdict`. `channel()` maps the
  source to gesture (a click, or the hotkey held: decision 3), named voice, plain voice or typed; `APPROVES` is the
  "What approves" column of `CLAUDE.md`'s table, level by level (foundation decision 10).
- **Callers, every approval door:** `session._answer_text` (an "approve" on a confirm card: typed, hands-free, the
  hotkey, debug; level 2), `session._take_answer` (a yes to Swift's own question; level 1), `session._fix_refused`
  (the correction offer, from `_midrun_text` and `_answer_fix`; level 1), `restated.restated` (the request said
  again; level 1). Each passes its real source (`_midrun_text` takes it as a required keyword) and whether Swift's
  name was said. A click on a confirm card (`confirm.reply`) is the gesture itself and doesn't ask.
- **Tests:** `tests/unit/test_intake.py::test_approves_is_the_table_cell_by_cell` (reads the table in `CLAUDE.md` and
  `action-authority.md`); `tests/unit/test_one_decider.py` (patches `approves` both ways and drives the doors: a door
  with a rule of its own fails it); `tests/unit/test_health_HEAR.py` (HA-HEAR-01).
- **Second owners:** none left. OWN-01 (`_fix_refused`'s own typed rule), OWN-02 (`restated`'s extra
  `source != "typed"`) and OWN-03 (the hands-free fix offer's `match is not None`) are fixed.
- **Gap, not a second owner:** speech with the hotkey held can't answer Swift's own question at all (FD-01).

### An approved action runs exactly as shown

- **Owner, for Swift's own tools** (email, calendar, desktop, system actions): `src/swift/security/gateway.py`
  `ActionGateway.execute(scope, action)`. In order: validate, refuse an already-sent digest (`scope.sent`), check
  recipients against `scope.resolved`, look up `POLICY`, confirm, write `PENDING` to the journal, **recompute
  `action.digest()` and refuse on a mismatch** (`changed_after_approval`), perform. Each tool supplies its own
  `digest` lambda (`workflows/calendar.py:_digest`, `desktop_tools.py`, `scope.Draft.digest`, `system_tools.py`).
- **Tests:** `tests/unit/test_audit_2026_10.py`, `tests/unit/test_calendar_lifecycle.py`,
  `tests/unit/test_email_as_owner.py`, `tests/unit/test_desktop.py`.
- **Second owner, OWN-05:** the agent's own tools (Bash, PowerShell, Edit, Write, reads outside the read folders)
  are decided in `executors/claude_code.py` `can_use_tool` → `_ask` / `_ask_read` → `_decide`, not the gateway.
  On approval it returns `PermissionResultAllow(updated_input=args)`: the same arguments the card was made from,
  so no swap is visible in this code. But there is no digest recomputed before execution and no journal line, and
  the step grant (`executors/step_grant.reversible`, `base.Grant.covers`) is a second place that decides "approved
  ahead". `CLAUDE.md` says "The gateway binds it to the action's digest"; for worker tools that is not what the
  code does. Whether the SDK can change the arguments between `can_use_tool` and the call is unproven.

## 2. Conversation and question state

- **Owners (split by design):**
  - `session.py` holds the questions (`Question` objects, their `owner` request, `_drop_questions`,
    `_away_questions`, `_follow_screen`) and the requests (`Run`, `_focus`, `_cards`).
  - `src/swift/dialogue.py` `Dialogue`: asking, and working out what an answer means (`_choose`, `pending`).
  - `src/swift/answer_window.py` `AnswerWindow`: one question's window and deadline (`idle`, `asking`,
    `listening`, `closed`), on `clock.now()`.
  - `exchange.py` keeps the last exchange for follow-ups; `parked.py` keeps stopped conversations
    (`%LOCALAPPDATA%\Swift`, `KEEP_S`).
- **Tests:** `tests/unit/test_dialogue.py`, `test_dialogue_model.py`, `test_answer_window.py`,
  `test_question_on_screen.py`, `test_followup.py`, `test_parked.py`.
- **Second owners:** none found. Not checked: whether `Dialogue.pending` and the session's question list can
  disagree.

## 3. Cards and what's on screen

- **What the overlay shows:** `overlay/src/presenter.ts` (pure; deadlines in state, no `setTimeout` for card
  lifetimes). `main.ts` draws what it says. Tests: `tests/unit/test_overlay_presenter.py`, overlay `npm test`.
- **What the overlay drew:** `src/swift/drawn.py` `Drawn`. Every frame goes out through `Drawn.send`, numbered;
  the overlay's `screen` acknowledgement comes back through `Drawn.ack` (review item 9). `session.py:3778` feeds
  it to `attention.set_seen`. Tests: `tests/unit/test_screen_state.py`, `test_seam_replay.py`.
- **Countdowns, backend only:**
  - confirm cards: `src/swift/attention.py` `Attention.wait`, `set_seen`, `set_queued`, `on_change`, `on_expire`
    (held while away, counts only once drawn). Tests: `test_attention.py`, `test_card_timing.py`,
    `test_held_cards.py`, `test_capsule_backend.py`.
  - questions: `answer_window.AnswerWindow` (above).
  - The overlay only draws the countdown it's sent (`presenter.ts` header: "the backend is its one clock").
- **The waiting stack:** `src/swift/stack.py`; whether an answer was seen: `src/swift/seen.py`.
- **Second owner, OWN-04:** `session._on_screen(q)` (`session.py:3387`) decides whether a question is on screen
  from the backend's own state (`not self._cards and q.owner is self._focus`), not from what the overlay said it
  drew. Confirm cards count down from the `screen` ack; questions listen from the backend's belief. The two can
  differ while a frame is in flight or refused. Whether that has caused a wrong answer is unproven.

## 4. Run records

- **Owner:** `src/swift/runs.py` `RunRecords`: one append-only `runs/<id>.jsonl` per run, content-free
  (`started`, `worker`, `step`, `asked`, `artifact`, `ended`). Tests: `tests/unit/test_runs.py`,
  `test_run_records.py`.
- **The other records, each with its own job:** `runlog.InteractionLog` (the owner's words, local),
  `security/journal.Journal` (side effects, `PENDING` before each; names its run), `parked.Parked` (unfinished
  conversations), `exchange` (the last exchange, in memory).
- **Second owners:** none deciding the same thing. Not checked: ADR-020's "one record per conversation" against
  these five. `runs.py`'s docstring says steps and approvals are "written here only", while `runlog.FIELD_ORDER`
  still has `steps` and `approvals`; whether both are written is not checked.

## 5. Contacts and recipients

- **Owner:** `src/swift/workflows/tools.py` `find_contact` (`:156`) and `_which` (`:259`), with
  `workflows/names.py` choosing among several matches. Only these write `RunScope.resolved` (`tools.py:202, 219,
  225`).
- **Checked by:** the gateway (`gateway.py:172`, `not_a_contact`), `draft_email` (`tools.py:382`), calendar
  attendees (`calendar.py:118`).
- **Tests:** `tests/unit/test_google_contacts.py`, `test_email_as_owner.py`, `test_audit_2026_10.py`.
- **Also, in the same module:** `draft_email` writes an address from the owner's own words (`said_addresses` over
  `RunScope.said` and answers) into `RunScope.resolved` with source `said`; the send card marks it
  (`overlay/src/cardtext.recipientText`). Foundation decision 5; `tests/unit/test_recipient_from_words.py`.
- **Second owners:** none found.

## 6. Web addresses

- **The matcher:** `src/swift/security/web_scope.py` `WebScope` (`note_request`, `note`, `allows`).
- **Two callers with different rules about where an address may come from:**
  - fetching (`executors/claude_code.py:604-697, 851`): the request and context, **plus addresses from earlier
    tool results** (search results, pages, files it read). A read, so no card.
  - opening in the browser (`workflows/desktop_tools._open_url`): an address in the owner's words and answers for
    this request opens; otherwise `_offer` asks "Open usiu.ac.ke?" (a level 1 question: `RunScope.ask(approval=True)`,
    decided by `intake.approves`) about the owner's own earlier addresses (`RunScope.earlier`, 10 minutes) and
    remembered ones (`owner_address.remembered`), and opens the owner's address as given. Never a tool result or
    the agent's url. Then the gateway (`desktop_open`, reversible). `points_back` is gone (foundation decision 4).
- **Tests:** `tests/unit/test_recent_address.py`, `test_desktop.py`, `test_audit_2026_10.py`, and the seam scenario
  `test_seam_replay.py::test_swift_s_question_about_an_earlier_address_is_on_screen_and_a_plain_yes_opens_it`.
- **OWN-06, accepted (owner, 2026-11-15):** opening has one rule with no word pattern, and both callers read the
  owner's words through `WebScope.note_request`. Fetching keeps its wider sources (the context Swift adds and
  tool-result addresses, OCT-03), on purpose: a fetch only reads.

## 7. Read scope

- **Owner:** `src/swift/executors/read_scope.py` `ReadScope.verdict(path)` (`read`, `ask`, `never`) and
  `ReadScope.in_command(command, cwd)` (X-20's safeguard for Bash and PowerShell). Called only from
  `claude_code.py` (`_ask_read`, `_ask`, `_propose_step`).
- **Separate list, not a second owner:** `desktop/base.py` `NeverRead` (apps and window titles that are never
  read, ADR-012 Q4).
- **Tests:** `tests/unit/test_audit_2026_10.py`, `test_seams_audit_privacy.py`.
- **Known limit:** `in_command` reads the command text; a path built in pieces gets a card (README §2, X-20).

## 8. Memory

- **Owner:** `src/swift/memory.py` `Store` (`write`, `forget`, `get`, `all`, `versions`) and `answer`
  for "remember / forget / what do you know". Only the backend imports it.
- **Tests:** `tests/unit/test_memory.py`, including
  `test_one_writer_only_swifts_backend_imports_the_store` and the `test_worker_text_*` cases.
- **Second owners:** none found. `stt/fixes.py` (word fixes) is a separate store of a different kind.

## 9. Speech

- **Recognition:** `src/swift/stt/transcriber.py` (Parakeet or faster-whisper, local); end of speech
  `endpoint.py`; word fixes `stt/fixes.py`; saved recordings `stt/recordings.py`; improvement pass
  `stt/improve.py`. Gate: `eval/stt/gate.py`. Tests: `test_stt.py`, `test_stt_gate.py`, `test_recordings.py`,
  `test_seams_audit_stt.py`.
- **Wake:** `src/swift/wake.py` (words matched on transcripts). `wake_acoustic.py` is "not wired in yet"
  (ADR-021). Tests: `test_wake.py`, `test_wake_acoustic.py`, `test_hands_free.py`.
- **Capture:** `audio/recorder.py`. **Speech output:** `src/swift/speech.py` `Speaker` (`speak`, `stop`,
  `speaking`, `recently`), Windows voices. Tests: `test_speech.py`.
- **Second owners:** none found.

## 10. Connectors and recovery

- **Owner:** `src/swift/connectors/base.py` (the boundary, `ConnectorError` with `code`); `gmail.py`,
  `google_calendar.py`, `google.py` (one sign-in for both); `fake.py` for tests and debug mode.
- **Recovery:**
  - sign-ins: `src/swift/signin.py` `SigninWatch` (checked at start-up, daily, and on `refused`; Google's expiry
    listener and the agent's refusal both reach it, `backend/__main__.py:218`, `session.on_signin_refused`); the
    card that opens the page is `executors/signin.py`.
  - any other failure: `gateway._failed` writes `FAILED` with the code to the journal and returns the reason to
    the agent; `unknown` becomes `UNKNOWN`, never "failed". Retrying is the agent's turn. `failures.py` turns a
    failure into the owner's card.
- **Tests:** `test_signin.py`, `test_failures.py`, `test_google_contacts.py`, `test_calendar.py`.
- **Second owners:** none found. Gap (decision 8, not built): `swift.log` gets `connector_failed` with no cause,
  so check 215's failures can't be explained from the log.

## 11. Windows automation and window placement

- **Other apps, by job:**
  - `src/swift/desktop/windows.py` `WindowsDesktop`: the app in front, focus, the selection, writing (Word,
    UI Automation, paste, keys), Gmail's compose fields, `bring_forward`. Tests use `desktop/fake.py`
    (`test_desktop.py`, `test_gmail_fill.py`).
  - `src/swift/system/control.py` `WindowsSystem`: volume, media, theme, brightness, lock, and window actions on
    the front window (minimize, maximize, snap). Tests: `test_system_lane.py`, `test_health_SYS.py`.
  - Both call `ShowWindow` and read the foreground window; they don't decide the same thing, so this is recorded
    as a split, not a finding.
- **Swift's own windows:** `overlay/src-tauri/src/placement.rs` (anchors, smart placement), `prefs.rs`
  (`overlay.json`), `panes.rs`. Tests: `cargo test`.

## 12. Presence

- **Owner:** `src/swift/presence.py` (here, idle, away) and `intake` step 1.
- **Second owners, already recorded:** RV-15, about four lock checks in `session.py` (`_deaf()` and others).
  Not repeated here.

## 13. Logging and the interaction log

- **`swift.log`:** `src/swift/logging_setup.py`: `_patch` on every record (`redact`, content fields replaced by
  their length), rotation `rotation_mb` 10, `retention_files` 5. Tests: `tests/unit/test_redaction.py`,
  `test_seams_audit_privacy.py`.
- **Interaction log:** `src/swift/runlog.py` `InteractionLog` (`interactions.jsonl`, the owner's words in full);
  `summary` is the allow-listed line that goes to `swift.log`. Tests: `test_runlog.py`.
- **Second owners:** none found.

## 14. Settings

- **Owner:** `src/swift/settings.py` (`config.yaml`, pydantic, invalid file refuses to start). Tests:
  `test_settings.py`, `test_health_CFG.py`.
- **Split by design:** the overlay's position and smart placement in `overlay.json` (`prefs.rs`: "config.yaml is
  the owner's file, which Swift never writes").
- **Second owners:**
  - **OWN-07** (fixed 2026-11-15): `memory.Store.setting` and `memory/settings/`, an unused second settings store, were
    deleted. `config.yaml` (`settings.py`) is the one owner of settings; the memory store holds only the owner's records.
  - **HA-CFG-06** (fixed 2026-11-15): `config/loader.py` and the TOML files, loaded by nothing live, were deleted.

## 15. The agent executor

- **Owner:** `src/swift/executors/claude_code.py` `ClaudeCodeExecutor` behind `executors/base.Executor`
  (`start(WorkerTask)`, `events`, `cancel`, `result`, `reply`). `WorkerTask` carries the request, `ContextPack`,
  `Grant`, `Budget` and `privacy`. Providers chosen in `executors/providers.py`; the light lane's one call in
  `executors/quick.py`; the stream mapped to steps in `claude_mapping.py`.
- **Tests:** `test_claude_executor.py`, `test_executor_contract.py`, `test_providers.py`, `test_claude_mapping.py`,
  `test_worker_task.py`.
- **Second owners:** none for running the agent. Its permission decisions are OWN-05 (§1).
