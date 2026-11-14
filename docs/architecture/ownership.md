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
| Who may approve what, from where | `intake.approves` | `session._fix_refused` (OWN-01), `restated.restated` (OWN-02), the hands-free fix offer in `session` (OWN-03) |
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
| Settings | `settings` (`config.yaml`) | `memory.Store.setting` with no callers (OWN-07); `overlay.json` (split by design). The unused `config/loader` TOML was removed on 2026-11-15 (HA-CFG-06) |
| The agent executor | `executors/claude_code.ClaudeCodeExecutor` behind `executors/base.Executor`; chosen by `executors/providers` | none found |

## 1. Action approval

### Who may approve, from where

- **Owner:** `src/swift/intake.py` `approves(source, *, named, target) -> Verdict`. Its docstring says "The rules live
  here once; every door calls them."
- **Callers that defer to it:** `session.py:1549` (typed text on a card), `:2464` (hands-free "approve" on a
  card), `:3528` (Swift's own yes/no question).
- **Tests:** `tests/unit/test_intake.py::test_who_may_approve_what`; `tests/unit/test_health_HEAR.py` (HA-HEAR-01's
  strict xfail, the typed "Swift, yes").
- **Second owners** (all three found by the foundation review, D3, and confirmed here):
  - **OWN-01** `session._fix_refused` (`session.py:3916`): decides whether a yes takes the correction offered after
    something couldn't be undone. It checks "typed needs Swift's name" itself and never calls `approves`. Called
    from `:3937` and `:4613`.
  - **OWN-02** `restated.restated` (`restated.py:49`): calls `approves(..., target="reversible")` but adds its own
    `source != "typed"`. So typed "Swift, turn off the Wi-Fi" isn't a yes while typed "Swift, yes" is (D1b).
  - **OWN-03** the hands-free fix offer (`session.py:2471-2472`): `decision.action == "approve" and match is not
    None and self._fix_offer is not None` sends "Swift, yes" to the offer by its own condition.
- **Target, not built:** foundation decision 10 makes `approves` the only decider, with its test checked against
  the table in `CLAUDE.md`.

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
- **Second owners:** none found. Target, not built: an address in the owner's own words (decision 5).

## 6. Web addresses

- **The matcher:** `src/swift/security/web_scope.py` `WebScope` (`note_request`, `note`, `allows`).
- **Two callers with different rules about where an address may come from:**
  - fetching (`executors/claude_code.py:604-697, 851`): the request and context, **plus addresses from earlier
    tool results** (search results, pages, files it read). A read, so no card.
  - opening in the browser (`workflows/desktop_tools._open_url`, `:236`): the owner's words and answers, a recent
    address if `owner_address.points_back` says the request points back, and remembered addresses
    (`owner_address.remembered`). Never a tool result. Then the gateway (`desktop_open`, level 1 or 2 by policy).
- **Tests:** `tests/unit/test_recent_address.py`, `test_audit_2026_10.py`.
- **Second owner, OWN-06:** "which addresses came from the owner" is decided twice, differently. Fetching an
  address a page gave is accepted risk (OCT-03); the point is that a change to one rule doesn't reach the other.
  Target, not built: decision 4 replaces `points_back` with a question.

## 7. Read scope

- **Owner:** `src/swift/executors/read_scope.py` `ReadScope.verdict(path)` (`read`, `ask`, `never`) and
  `ReadScope.in_command(command, cwd)` (X-20's safeguard for Bash and PowerShell). Called only from
  `claude_code.py` (`_ask_read`, `_ask`, `_propose_step`).
- **Separate list, not a second owner:** `desktop/base.py` `NeverRead` (apps and window titles that are never
  read, ADR-012 Q4).
- **Tests:** `tests/unit/test_audit_2026_10.py`, `test_seams_audit_privacy.py`.
- **Known limit:** `in_command` reads the command text; a path built in pieces gets a card (README §2, X-20).

## 8. Memory

- **Owner:** `src/swift/memory.py` `Store` (`write`, `forget`, `get`, `all`, `versions`, `setting`) and `answer`
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
  - **OWN-07** `memory.Store.setting` and `memory/settings/`: "Swift's own settings", with `config.yaml` winning
    (`test_config_yaml_wins_over_a_kept_setting`). No caller in `src/swift` reads it today. A second settings
    store waiting for a first user.
  - **HA-CFG-06** (fixed 2026-11-15): `config/loader.py` and the TOML files, loaded by nothing live, were deleted.

## 15. The agent executor

- **Owner:** `src/swift/executors/claude_code.py` `ClaudeCodeExecutor` behind `executors/base.Executor`
  (`start(WorkerTask)`, `events`, `cancel`, `result`, `reply`). `WorkerTask` carries the request, `ContextPack`,
  `Grant`, `Budget` and `privacy`. Providers chosen in `executors/providers.py`; the light lane's one call in
  `executors/quick.py`; the stream mapped to steps in `claude_mapping.py`.
- **Tests:** `test_claude_executor.py`, `test_executor_contract.py`, `test_providers.py`, `test_claude_mapping.py`,
  `test_worker_task.py`.
- **Second owners:** none for running the agent. Its permission decisions are OWN-05 (§1).
