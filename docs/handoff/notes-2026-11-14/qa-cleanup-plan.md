# QA part 2: cleanup plan (2026-11-14)

Branch `claude/qa-cleanup-79d6a5`, from `main` at `e18af1b`. Phase 1 is this plan only: nothing in the code
is changed yet. Phase 2 starts after QA 1 has merged, with `main` merged in first. Line numbers below are
at `e18af1b` and will move.

## How the survey was done

- **Python:** a scan of every top-level function, class, method and upper-case constant in `src/swift`,
  counting each name across `src`, `tests`, `spikes`, `eval`, `overlay` and `docs/testing`. Also a scan for
  attributes written and never read, unused imports, commented-out code, repeated 4-line windows, and tiny
  helpers with exactly one caller. Every hit was then read by hand. Dispatch by name (`SystemLane._timer_set`
  and friends via `getattr(self, "_" + intent)`), pydantic validators and the per-run descriptors in
  `session.py` were false positives and are left alone.
- **Overlay TypeScript:** the same name count over `overlay/src` and `overlay/dev`. Only
  `EVERY_INBOUND_TYPE`/`EVERY_OUTBOUND_TYPE` (`protocol.examples.ts`) and `mindMapText` (`dev/b4/shapes.ts`)
  are used by tests alone, which is their purpose. Nothing to remove.
- **Rust:** the same name count over `overlay/src-tauri/src`, plus the repeated-window scan.
- **Tests and spikes:** identical helper bodies across test files, unused helpers and constants, and a static
  check that every `from swift... import` in `spikes`, `eval` and `tests` still resolves (all do).

### What the survey found overall

The codebase is already lean. There is no commented-out code, almost no literal duplication, and the
comments mostly carry reasons, dates, check numbers or ADR references (kept by rule). The tiny one-caller
helpers (`_is_retry`, `_drop_questions`, `_away_questions`, `_approval_doubt`, `_to_c`/`_from_c`, ...) are named
predicates with a docstring; inlining them saves 1-2 lines each and makes the callers harder to read, so
they stay. So the safe default steps are small: **about −55 lines** in steps 1-5. The one large cut is the
unwired config scaffold (step 7, about −690 lines), which needs the owner's decision.

## Steps

Each step is one commit labelled `cleanup (symptom-free): ...`, with its line delta (src + tests) in the
message. A step is kept only if it deletes more than it adds. After each step: the full Python suite
(`PYTHONPATH=src .venv python -m pytest -q -p no:cacheprovider`); overlay `tsc` + `npm test` only if
`overlay/src` is touched (no step plans to); `cargo test` for step 5.

### Step 1: dead definitions in `src/swift` (≈ −21)

| File | What goes | Why it's safe | Δ |
|---|---|---|---|
| `dialogue.py:44-45` | `MAX_OPTIONS`, `MAX_QUESTION` | Not referenced anywhere (src, tests, spikes, overlay) | −2 |
| `stack.py:26` | `CARD_KINDS` | Never read; the comment above it keeps the three kinds in words | −1 |
| `executors/claude_code.py:99` | `ESCALATE_TOOL` | Never read; the tool name lives where the tool is defined | −1 |
| `ipc/protocol.py:62` | `RESULT_STATUSES` | Never read in Python; the overlay's own protocol types are the contract | −1 |
| `system/intents.py:486` | `_SEARCH_START` | Private regex, never used | −1 |
| `routing/rules.py:346-349` | `route_for_eval` | Its docstring names `spikes/routing/eval_routes.py`, which no longer calls it; `findings.yaml` only quotes it as past evidence | −6 |
| `audio/recorder.py` | `Recorder.capped` (Protocol property), its three writes in `MicRecorder`, and the `self.capped = False` in three test fakes (`test_dialogue.py`, `test_voice.py`, `test_wake.py`) | Written since Milestone 2, read nowhere; the `return` after the cap stays, so the cap itself is unchanged | −9 |

Kept on purpose: `stt/transcriber.py` `PARAKEET_REPO` (unused, but it records where the model files come from;
turning it into a comment is 0 lines).

**Proves it:** full Python suite; `eval/parity/score.py` unchanged (413/423, 0 harmful), since `rules.py`
is touched. `test_dialogue.py`, `test_stack.py`, `test_routing.py`, `test_voice.py`, `test_wake.py` cover the
modules directly.

### Step 2: unused imports (≈ −10)

- `session.py:158` `REASKS`, `session.py:199` `CLOSE` (names on shared import lines: 0 lines, but no
  test imports them through `swift.session`).
- Tests: `test_audit_2026_10.py:181` `Transcription`, `test_playbooks.py:15` `pytest`, `test_routing.py:7`
  `asyncio`, `test_screen_state.py:99` `Transcription`, `test_seams_audit_ipc.py:9` `pytest`,
  `test_seams_audit_routing.py:9` `pytest`, `test_seams_audit_state.py:246` `until_d`,
  `test_voice_fixes_1027.py:26,45` `WriteReceipt`, `LOUD`, `QUIET`, `test_workflows.py:5` `asyncio`.
- Spikes: `spikes/hermes/probe_hook.py:6` `json`, `sys`; `spikes/stt/learn_fixes.py:34` `np`.

**Why it's safe:** each name has no use in its module, in an annotation string or in a `TYPE_CHECKING`
block. **Proves it:** full Python suite (collection fails on a wrong removal); each spike file still
compiles (`python -m py_compile`).

### Step 3: `Session._question_timer`, called by tests only (≈ −4; `session.py` −4)

`session.py:3200` `_question_timer(q, seconds)` is one line, `self._window(q).listen(seconds)`, and nothing
in `src` calls it. Its two callers in `test_seams_audit_speech.py:279,286` call `session._window(q).listen(0.1)`
instead (same lines). The docstring mention in `test_seams_audit_state.py:26` is reworded to `_window`.
Lower `SESSION_MAX_LINES` in `test_structure_ratchet.py` to the new length.

**For the second review:** it sits beside the question window (a plain "yes" answers only the question on
screen). The change is mechanical: the method is removed, no production path changes.
**Proves it:** full Python suite, in particular `test_seams_audit_speech.py::test_s14_...`,
`test_question_on_screen.py`, `test_seam_replay.py`, `test_structure_ratchet.py`.

### Step 4: local executors share their run plumbing (≈ −15)

`executors/improve.py:106-130` and `executors/signin.py:145-168` carry the same `cancel`, `reply` and `_get`
word for word (`_results: dict[str, ExecResult | None]`, `_answers: dict[str, Future[bool]]`), and `result`
differs only by a warning log in `improve.py`. Move them into one small base class, `LocalRuns`, in
`executors/base.py` (beside `UnknownRun`); `improve.py` keeps a `result` override for its log line.
`echo.py` has a different shape (no answers, never `None`) and is left alone.

Estimate: −2 × 22 lines, +~25 for the base with its docstring: net about −15. Dropped if it isn't net negative.

**For the second review:** `reply` is how a click on these executors' own cards (word-fix approval, the
sign-in card) reaches them. The move is mechanical: same code, one place.
**Proves it:** `test_recordings.py` (ImproveExecutor), `test_signin.py`, `test_worker_task.py`, then the full suite.

### Step 5: Rust, one `to_fraction` (≈ −8)

`overlay/src-tauri/src/panes.rs:140-146` and `placement.rs:159-165` define the same `to_fraction(area, (x, y))`.
Drop the `panes.rs` copy; `lib.rs:612` calls `placement::to_fraction`, and the `panes.rs` test at line 210
imports it from `placement`.

**Proves it:** `cargo test` in `overlay/src-tauri` (worktree's own `target`), including
`panes::tests::remembered_places_round_trip_and_stay_on_screen` and `placement::tests::a_dropped_overlay_*`.

### Step 6: considered, not planned

- **The two drag loops in `lib.rs`** (~370 and ~580): the same "4-pixel threshold, follow the cursor" loop,
  but one runs on `std::thread::spawn` and updates hit-test state and emits `drag`; the other runs on
  `spawn_blocking` and returns whether it moved. A shared helper with a callback saves ~6 lines and couples
  two threading models. Not worth the risk without a desktop test.
- **The fakes' `_Run` in `executors/mock.py`** shares 4 fields and `events`/`result` with `claude_code.py`'s
  `_Run`. Sharing a dataclass across the real executor and the mock would tie the mock to the CLI's state;
  the saving is ~10 lines. Left.
- **Test helpers:** the only identical bodies across test files are four tiny helpers (`_executor`,
  `finish`, `ask`; 19 lines in all). Moving them into a shared module adds imports for nearly as many lines.
  Left.
- **Comments that restate the code:** a read of `session.py`, `workflows/tools.py`, `executors/` and
  `overlay/src/main.ts` found very few; nearly all carry a reason or a reference. No sweep is planned; any
  restating comment met in steps 1-5 goes in that step.

### Step 7: the unwired config scaffold (≈ −690), owner decision first

`config/loader.py` (189 lines), `config/models.py` (212) and `config/defaults.py` (126) are the Phase 0
scaffold (`43cfa3a`): `config.toml`, `permissions.toml` (fails closed), `profiles.toml`, `aliases.toml`.
Nothing in `src` imports `config.loader`, `config.models` or `config.defaults`; only `tests/unit/test_config.py`
(145) does. Swift's live settings are `settings.py`. `AppPaths.config_file`, `permissions_file`,
`profiles_file`, `aliases_file` and `ensure_dirs` exist only for the loader (and `test_paths.py`).
`pydantic` stays (`settings.py` uses it).

Removing it is behaviour-free today, but `docs/architecture.md` ("Configuration and logging (Phase 0)")
describes it as built, and `permissions.toml` failing closed may be meant for later. So this is the owner's
call: delete it (and update `architecture.md`), or keep it as planned work. Not done without that answer.
**Proves it:** full suite minus `test_config.py`; `backend/__main__.py` imports only `config.paths.app_paths`.

## Product-rule touch list (for the orchestrator's second review)

- Step 3 (`_question_timer`, beside the question window): mechanical.
- Step 4 (`reply` of the improve and sign-in executors): mechanical.
- None of the steps touches `intake.approves`, `_on_screen`, `restated.py`, `owner_address.py`, `step_grant.py`,
  read scope or recipients.

## Totals (estimates)

| Step | Area | Δ |
|---|---|---|
| 1 | Dead definitions | ≈ −21 |
| 2 | Unused imports | ≈ −10 |
| 3 | `_question_timer` | ≈ −4 |
| 4 | Local executors | ≈ −15 |
| 5 | Rust `to_fraction` | ≈ −8 |
| **1-5** | | **≈ −58** |
| 7 | Config scaffold (if the owner agrees) | ≈ −690 |
