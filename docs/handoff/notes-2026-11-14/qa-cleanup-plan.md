# QA part 2: cleanup plan (2026-11-14, revised 2026-11-15 with the pstack review)

Branch `claude/qa2-pstack-2cefcc` (it carries on from `claude/qa-cleanup-79d6a5`), from `main` at `e18af1b`.
Phase 1 is this plan only, and nothing in the code is changed yet. Phase 2 starts after QA 1 has merged and
the orchestrator says go, with `main` merged in first. Line numbers are at `e18af1b` and will move.

## How the survey was done

### First pass (2026-11-14, without pstack)

- **Python:** a scan of every top-level function, class, method and upper-case constant in `src/swift`,
  counting each name across `src`, `tests`, `spikes`, `eval`, `overlay` and `docs/testing`. Also a scan for
  attributes written and never read, unused imports, commented-out code, repeated 4-line windows, and tiny
  helpers with exactly one caller. Every hit was then read by hand. Some hits were false positives and are
  left alone: dispatch by name (`SystemLane._timer_set` and the others, called through
  `getattr(self, "_" + intent)`), pydantic validators, and the per-run descriptors in `session.py`.
- **Overlay TypeScript:** the same name count over `overlay/src` and `overlay/dev`.
- **Rust:** the same name count over `overlay/src-tauri/src`, plus the repeated-window scan.
- **Tests and spikes:** identical helper bodies across test files, unused helpers and constants, and a static
  check that every `from swift... import` in `spikes`, `eval` and `tests` still resolves (all do).

### Second pass (2026-11-15, with the pstack review skills, applied by hand)

The orchestrator named three skills: `/pstack:thermo-nuclear-code-quality-review`, `/pstack:deslop` and
`/pstack:blast-radius`. None of them can be invoked from a Claude session on this PC:

- `thermo-nuclear-code-quality-review` and `deslop` aren't part of pstack 0.15.36. They ship in the
  `cursor-team-kit` plugin, which isn't installed, as pstack's own README says.
- `blast-radius` is in pstack, but it's marked `disable-model-invocation: true`, so only the owner can start it.

**The owner chose to apply them by hand (2026-11-15).** I read each `SKILL.md` from the marketplace copy
(`~/.claude/plugins/marketplaces/cursor-plugins/cursor-team-kit/skills/{deslop,thermo-nuclear-code-quality-review}`)
and followed it step by step. Phase 2 will do the same with pstack's `blast-radius`. Where a skill and
`CLAUDE.md` disagree, `CLAUDE.md` wins. In particular:

- Both skills are written for a branch diff. Here they were run over the whole of `src/swift`,
  `overlay/src`, `overlay/src-tauri/src`, `tests` and `spikes`.
- Thermo-nuclear's "be ambitious, restructure" is limited by `CLAUDE.md`'s "Structural steps delete code" and
  by "Never remove" (the project's memory comments and product-rule paths).

What was run for each skill's criteria:

- **Thermo-nuclear:** files over 1,000 lines; thin wrappers and one-caller helpers (348 Python hits and
  165 overlay hits, each skimmed); duplicated 5-line windows in `src` and 6-line windows across `tests`;
  modules nothing in `src` imports; silent `getattr(x, "name", None)` fallbacks at boundaries; near-duplicate
  helpers.
- **Deslop:**
  - comments that restate the next line (a word-overlap scan of every standalone comment, then a read of
    every short comment);
  - `try/except: pass` blocks (17, each read);
  - casts to `any` or `as unknown as` in the overlay (one, the dev hook `window.__overlay`, kept);
  - unused imports and dead names (a fresh AST scan, scripts kept outside the repo).

### What both passes found overall

The codebase is already lean, and thermo-nuclear's ambition mostly runs into two walls:

- The big files are big because of one-off logic, not duplication. Splitting them moves code and fails the
  "must delete" rule (see "Thermo-nuclear findings not planned").
- The comments nearly all carry a reason, a date, a check number or an ADR reference.
  - The restating-comment scan found two hits: a field comment in `capsule.ts` and the numbered pipeline
    stages in `security/gateway.py`. Both are kept.
  - One stale comment turned up, and it goes in step 1.

The second pass added three steps (6, 7, 8), a few items to steps 1 and 2, and the doc corrections for the
config scaffold step (now step 9, approved by the owner).

## Steps

Each step is one commit, labelled `cleanup (symptom-free): ...` with its line delta (src + tests) in the
message. A step is kept only if it deletes more than it adds. After each step:

- the full Python suite (`PYTHONPATH=src /c/Users/frchi/Documents/Swift/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`);
- overlay `tsc` and `npm test` only if `overlay/src` is touched (no step plans to);
- `cargo test` for step 5;
- `eval/parity/score.py` when `routing/` is touched (step 1).

### Step 1: dead definitions in `src/swift` (≈ −21)

| File | What goes | Why it's safe | Δ |
|---|---|---|---|
| `dialogue.py:44-45` | `MAX_OPTIONS`, `MAX_QUESTION` | Not referenced anywhere (src, tests, spikes, overlay) | −2 |
| `stack.py:26` | `CARD_KINDS` | Never read; the comment above it keeps the three kinds in words | −1 |
| `executors/claude_code.py:99` | `ESCALATE_TOOL` | Never read; the tool name lives where the tool is defined | −1 |
| `ipc/protocol.py:62` | `RESULT_STATUSES` | Never read in Python; the overlay's own protocol types are the contract | −1 |
| `system/intents.py:486` | `_SEARCH_START` | Private regex, never used | −1 |
| `routing/rules.py:346-349` | `route_for_eval` | Its docstring names `spikes/routing/eval_routes.py`, which no longer calls it; `findings.yaml` only quotes it as past evidence | −6 |
| `audio/recorder.py` | `Recorder.capped` (a Protocol property), its three writes in `MicRecorder`, and `self.capped = False` in three test fakes (`test_dialogue.py`, `test_voice.py`, `test_wake.py`) | Written since Milestone 2, read nowhere. The `return` after the cap stays, so the cap itself is unchanged | −9 |
| `__main__.py:20` (new, 2nd pass) | The stale comment "The agent runtime arrives in Phase 1." becomes "The backend is `python -m swift.backend`." | The runtime has existed for months; the comment misleads | 0 |

Kept on purpose:

- `stt/transcriber.py` `PARAKEET_REPO`: unused, but it records where the model files come from.
- `runlog.unclassified`: tests only, but it's the privacy guard behind `conftest.py`'s "every log field is
  classified" check (product rule: logs content-free).
- `desktop/fake.py`: tests only, by design (the fakes).

**Proves it:**

- the full Python suite;
- `eval/parity/score.py` unchanged (413/423, 0 harmful), since `rules.py` is touched.

`test_dialogue.py`, `test_stack.py`, `test_routing.py`, `test_voice.py`, `test_wake.py` and `test_version.py`
cover the modules directly.

### Step 2: unused imports (≈ −11)

- **`src`:** `session.py:158` `REASKS` and `session.py:199` `CLOSE`. These are names on shared import lines
  (0 lines), and no test imports them through `swift.session`.
- **Tests:**
  - `test_audit_2026_10.py:148` and `:181` `Transcription` (the 2nd pass found the one at line 148);
  - `test_playbooks.py:15` `pytest`;
  - `test_routing.py:7` `asyncio`;
  - `test_screen_state.py:99` `Transcription`;
  - `test_seams_audit_ipc.py:9` `pytest`;
  - `test_seams_audit_routing.py:9` `pytest`;
  - `test_seams_audit_state.py:246` `until_d`;
  - `test_voice_fixes_1027.py:26,45` `WriteReceipt`, `LOUD`, `QUIET`;
  - `test_workflows.py:5` `asyncio`.
- **Spikes:**
  - `spikes/hermes/probe_hook.py:6` `json` and `sys`;
  - `spikes/stt/learn_fixes.py:34` `np`;
  - `spikes/stt/real_noise.py:32` `SAMPLE_RATE` (2nd pass; a name on a shared line).

Not unused, so kept:

- pytest fixtures imported from `tests/fixtures`: `event_loop_policy`, `one_clock`, `fake_sd`, `make_recorder`.
  They are used by name as parameters.
- `spikes/latency/claude_startup.py:92` `claude_agent_sdk`: imported on purpose, so its cost is paid before
  timing.

**Why it's safe:** none of these names is used in its module, in an annotation string or in a
`TYPE_CHECKING` block.
**Proves it:** the full Python suite (a wrong removal fails collection); each spike file still compiles
(`python -m py_compile`).

### Step 3: `Session._question_timer`, called by tests only (≈ −4; `session.py` −4)

`session.py:3200` `_question_timer(q, seconds)` is one line, `self._window(q).listen(seconds)`, and nothing
in `src` calls it.

- Its two callers in `test_seams_audit_speech.py:279,286` call `session._window(q).listen(0.1)` instead
  (the same number of lines).
- The docstring mention in `test_seams_audit_state.py:26` is reworded to `_window`.
- Lower `SESSION_MAX_LINES` in `test_structure_ratchet.py` to the new length.

**For the second review:** it sits beside the question window (a plain "yes" answers only the question on
screen). The change is mechanical: the method is removed, and no production path changes.
**Proves it:** the full Python suite, in particular `test_seams_audit_speech.py::test_s14_...`,
`test_question_on_screen.py`, `test_seam_replay.py` and `test_structure_ratchet.py`.

### Step 4: local executors share their run plumbing (≈ −15)

`executors/improve.py:106-130` and `executors/signin.py:145-168` carry the same `cancel`, `reply` and `_get`
word for word (`_results: dict[str, ExecResult | None]`, `_answers: dict[str, Future[bool]]`). Their
`result` differs only by a warning log in `improve.py`.

- Move them into one small base class, `LocalRuns`, in `executors/base.py` (beside `UnknownRun`).
- `improve.py` keeps a `result` override for its log line.
- `echo.py` has a different shape (no answers, never `None`) and is left alone.

Estimate: −2 × 22 lines, +~25 for the base with its docstring, so net about −15. Dropped if it isn't net negative.

**For the second review:** `reply` is how a click on these executors' own cards (word-fix approval, the
sign-in card) reaches them. The move is mechanical: the same code, in one place.
**Proves it:** `test_recordings.py` (ImproveExecutor), `test_signin.py`, `test_worker_task.py`, then the full suite.

### Step 5: Rust, one `to_fraction` (≈ −8)

`overlay/src-tauri/src/panes.rs:140-146` and `placement.rs:159-165` define the same `to_fraction(area, (x, y))`.
Drop the `panes.rs` copy. `lib.rs:612` then calls `placement::to_fraction`, and the `panes.rs` test at
line 210 imports it from `placement`.

**Proves it:** `cargo test` in `overlay/src-tauri` (with the worktree's own `target`), including
`panes::tests::remembered_places_round_trip_and_stay_on_screen` and `placement::tests::a_dropped_overlay_*`.

### Step 6 (new, thermo-nuclear "copy-pasted logic"): one `%VAR%`-expanding path type in `settings.py` (≈ −26)

Six settings classes repeat the same 4-line validator, then a blank line:
`@field_validator(...)`, `@classmethod`, `def _expand(cls, v: str) -> str:`, `return expand(v)`. They are
`SttSettings:80`, `DemandClassifierSettings:227`, `WorkflowSettings:256`, `SystemSettings:286`,
`LoggingSettings:322` and `Settings:359`.

The change:

- Define one type, `Expanded = Annotated[str, AfterValidator(expand)]`, with a 1-line comment.
- Annotate the 12 fields with it: `audio_dir`, `word_fixes_file`, `test_set_dir`, `model_dir`,
  `examples_file`, `dir`, `schedule_file`, `interactions`, `app_log_dir`, `journal`, `runs` and `memory_dir`.
- Drop the six validators.

**Why it's safe:**

- `_Section` sets `validate_default=True`, and that applies to `Annotated` validators just as it does to
  `field_validator`, so the default `%LOCALAPPDATA%` paths are still expanded.
- Both run after the `str` check, in "after" mode.
- A `ValueError` from `expand` still reports at the field's own `loc`, so `SettingsError`'s text
  (`settings.py:382`) is unchanged.
- `AfterValidator` and `Annotated` come from pydantic ≥ 2.9 and `typing`, which are already in use.

**Left as is:** `LocalSettings._expand` (`folders`, `projects`: `dict[str, str]`). Moving it to
`dict[str, Expanded]` would report errors one level deeper (`local.folders.work: ...` instead of
`local.folders: ...`), which is a visible change.
**Proves it:** `test_settings*.py` (defaults expand, an unset `%VAR%` is a `SettingsError`, a bare
environment falls back), `test_health_CFG.py`, then the full suite.

### Step 7 (new, deslop "patterns inconsistent with the codebase"): `try/except X: pass` becomes `contextlib.suppress(X)` (≈ −16)

`contextlib.suppress` is already the house idiom (37 uses in `claude_code.py`, `quick.py`, `session.py`,
`speech.py`, `control.py` and `scheduler.py`). Sixteen sites still spell it as a 4-line `try/except/pass`.

**The orchestrator's rule (2026-11-15):** a site changes only where `suppress` names exactly the types the
old `except` caught *and* it is provably the same. One commit.

**The one real difference, found while checking:** on Python 3.12 (this project's version), `suppress(X)`
also swallows an `ExceptionGroup` whose members are all `X`, and `except X:` doesn't.

- For `X = Exception` the two are identical, because an `ExceptionGroup` is itself an `Exception`. So the
  `except Exception` sites are provably the same and stay in.
- For a narrow `X`, a site stays in only if its body can't raise an exception group. That means its body
  awaits no task, `TaskGroup`, handler or callback.

Kept (11 sites). Each becomes a 2-line `with`, and each reason comment moves to the `with` line:

| File | Sites | Why provably the same | Δ |
|---|---|---|---|
| `desktop/windows.py` | 439, 600, 723, 735, 778, 805 | `except Exception` → `suppress(Exception)`: identical | −12 +1 import |
| `ipc/server.py` | 74 | the body is one `client.send` | −2 +1 |
| `executors/claude_mapping.py:159` | 1 | the body is `PureWindowsPath.relative_to` (`ValueError`) | −2 +1 |
| `executors/signin.py:136` | 1 | the body is two `asyncio.to_thread` calls on a subprocess (`TimeoutExpired`) | −2 +1 |
| `lifecycle.py:189` | 1 | the body is sleeps and a flag poll (`TimeoutError`) | −2 +1 |
| `workflows/tools.py:770` | 1 | the body is `get_running_loop().create_task(...)` (`RuntimeError`) | −2 +1 |

Left as they are (an exception group can't be ruled out, or the area is excluded):

- `ipc/server.py:112`: its body awaits `self._handler(msg)`, which runs the session.
- `session.py:1703` and `executors/mock.py:229`: they `await` a task, which re-raises whatever the task raised.
- `backend/__main__.py:592`: its body is `asyncio.run(_serve(...))`, the whole backend.
- `system/lane.py:165`: it awaits arbitrary undo steps.
- `security/gateway.py:238`: the security pipeline's late-stop wait (product-rule area).
- Any site whose `except` body is more than `pass`.

**Also safe:**

- A `return` inside the block behaves the same.
- No site has an `else` or a `finally`.

**For the second review:** `lifecycle.py:189` is in the presence loop: it waits for speech before freeing
the spare. Mechanical.
**Proves it:** the full suite, in particular `test_desktop.py`, `test_ipc*.py`, `test_presence.py`,
`test_held_cards.py`, `test_signin.py`, `test_workflows.py` and `test_claude_mapping*.py`.

### Step 8 (new): dead `AppPaths` fields `db_path`, `audit_path` (≈ −4), approved by the orchestrator on 2026-11-15

`config/paths.py`: `db_path` (`swift.db`) and `audit_path` (`audit.jsonl`) are Phase 0 fields that nothing
reads, not even the loader. The only reader is `test_paths.py:20-21`. The live journal and audit paths come
from `settings.py`. Dead fields are ordinary cleanup (orchestrator, 2026-11-15), so this is its own commit,
before step 9.
**Proves it:** `test_paths.py` (two asserts go), `test_redaction.py`, `test_health_CFG.py`, then the full suite.

### Step 9: the unwired Phase 0 config scaffold (≈ −698), approved by the owner on 2026-11-15

These files are the Phase 0 scaffold (`43cfa3a`): `config/loader.py` (189 lines), `config/models.py` (212)
and `config/defaults.py` (126). They describe `config.toml`, `permissions.toml` (fails closed),
`profiles.toml` and `aliases.toml`.

Nothing in `src` imports them; only `tests/unit/test_config.py` (145) does. Swift's live settings are
`settings.py`, and `docs/threat_model.md` T12 already says "the TOML loader is unused, HA-CFG-06".

| What goes | Δ |
|---|---|
| `config/loader.py`, `config/models.py`, `config/defaults.py` | −527 |
| `tests/unit/test_config.py` | −145 |
| `config/paths.py`: `config_file`, `permissions_file`, `profiles_file`, `aliases_file`, `ensure_dirs` (only the loader and `test_paths.py` use them) | −19 |
| `tests/unit/test_paths.py`: the `permissions_file` assert, and `test_ensure_dirs` | −7 |

Kept: `config/paths.py` itself with `app_paths`, `config_dir`, `data_dir`, `logs_dir` and `models_dir`.
`backend/__main__.py`, `logging_setup.py`, `eval/stt/gate.py`, two spikes and `conftest.py` use them.
`pydantic` stays (`settings.py`), and no dependency is freed (the loader used only the standard library's
`tomllib`).

**Docs in the same commit** (they describe the scaffold as built):

- `docs/architecture.md:91-99`, "Configuration and logging (Phase 0)": drop the `config/loader.py` bullet
  and say that settings come from `config.yaml` (`settings.py`).
- `docs/threat_model.md:28` (T4): "argv only from `profiles.toml`" is about a file Swift never reads. Reword
  it to the live mitigation (no shell tool, `shell=False`), or mark it as the planned design. **Flagged for
  the orchestrator:** it's a threat-model line, so it gets the second review.
- `docs/threat_model.md:36` (T12) keeps its HA-CFG-06 reference; "(the TOML loader is unused …)" becomes
  "(the Phase 0 TOML loader was removed on 2026-11-…)".
- `docs/decisions/ADR-010-workflows-and-show-me.md:126` lists "`permissions.toml` policy" as future work.
  It's an ADR, so it is left as written.

**Proves it:**

- the full suite minus `test_config.py`;
- `backend/__main__.py` imports only `config.paths.app_paths`;
- `test_owner_plan.py`: the ledger doesn't cite `config/loader.py`, which was checked.

### Step 10 (new, docs only): stale status-label sentence in `architecture.md`, approved by the orchestrator on 2026-11-15

`docs/architecture.md`, "Swift and its providers", says the overlay renders "Claude Code is reading" and
"Swift · via Claude Code". `overlay/src/agents.ts` doesn't: it says "Reading" and "Working on it", per the
owner's decision of 2026-10-26 (product rule: status labels generic). The code is right and the doc is stale.
The fix rewords that sentence to say the working card's labels are generic ("Reading", "Working on it")
and that only the result's byline names the provider. It's done on this branch.

## Thermo-nuclear findings not planned (and why)

Thermo-nuclear treats these as presumptive blockers. None of them is a cleanup this branch can make,
because the fix either moves code (and fails "Structural steps delete code") or touches a product-rule path:

1. **`session.py`, 4,989 lines (5× the 1k bar).** `split-session-py` already took the literal duplication
   (−22) and found that moving a cohesive area into its own module adds lines: one try was +69 net.
   - The "code judo" move is a design change, not a move: the question flow owning its own window and
     capture state in `dialogue.py`, so that `Session` stops mirroring it.
   - I also checked the repeated "bring a run to the front" sequence (`_bring` at 1158 and `_show_card`
     at 1280). A helper nets 0 lines, so it's dropped.
2. **`overlay/src/main.ts`, 2,102 lines:** about 40 `render*`/`on*` functions in one module. The helpers are
   short and named, and there is no duplication. A split into `cards/` modules moves code. It's left for a
   design step.
3. **`executors/claude_code.py` (1,047) and `overlay/src-tauri/src/lib.rs` (1,026)** are just over the bar.
   - Nothing dead was found in either beyond `ESCALATE_TOOL` (step 1).
   - The two drag loops in `lib.rs` (~370 and ~580) run on different threading models. A shared helper saves
     ~6 lines and couples them, without a desktop test to prove it. Not planned.
4. **`lifecycle.py` takes `session: Any`** (line 49) and reaches it through `getattr(self.session, "...", None)`
   (lines 107-231). That's a silent-fallback boundary, there so tests can pass small fakes.
   - The cleaner contract would be a `Protocol`, but the fakes would have to grow to implement it, which
     adds lines.
   - This is also the lock and presence path (product rule: no hands-free listening while locked). Not
     planned. It's worth a design note.
5. **`system/control.py` `_ps` and `_ps_script` (326 and 360)** are near-duplicate PowerShell runners. One
   could do both, but the merge changes how real Windows commands are invoked (`-Command` against
   `-EncodedCommand -ExecutionPolicy Bypass`). It can't be proved without real-world actions, so it's not planned.
6. **The fakes' `_Run` in `executors/mock.py`** shares 4 fields and `events`/`result` with `claude_code.py`'s
   `_Run`. Sharing a dataclass would tie the mock to the CLI's state, for ~10 lines. Left.
7. **Test helpers:** the 6-line duplicate scan across `tests` found only in-file setup repeats
   (`test_owner_checks_1700.py`, `test_front_rules.py`, `test_voice_fixes_1700.py`) and four tiny helpers
   across files (19 lines in all). Moving them adds about as many import lines. Left.
8. **Spikes:** eight scripts aren't referenced by any doc or test:
   - `latency/piper_bench.py`, `latency/thread_probe.py`;
   - `b4_previews/ooxml_excerpt.py`, `b4_previews/thumb_spike.py`;
   - `hermes/probe_hook.py`, which is cited in `docs/spikes/hermes-agent.md`;
   - `wake/piper_sample_generator/generate_samples.py`;
   - `_util.py` and `google/_creds.py`, which are imported by other spikes.

   Spikes are the evidence behind past decisions, and deleting them changes no behaviour, but it is the
   owner's call. Not in this plan.
9. **Unused `_agent` parameters** in `overlay/src/agents.ts` (`activityLabel`, `handoffLabel`). Dropping them
   changes signatures at every caller for 0 lines. Left.

## Product-rule touch list (for the orchestrator's second review)

- Step 3 (`_question_timer`, beside the question window): mechanical.
- Step 4 (`reply` of the improve and sign-in executors): mechanical.
- Step 7 (`lifecycle.py:189` presence loop): mechanical. `system/lane.py` and `security/gateway.py` are left
  as they are.
- Step 9's `docs/threat_model.md` T4 wording.
- No step touches `intake.approves`, `_on_screen`, `restated.py`, `owner_address.py`, `step_grant.py`, read
  scope or recipients.

## Totals (estimates; src + tests)

| Step | Area | Δ |
|---|---|---|
| 1 | Dead definitions | ≈ −21 |
| 2 | Unused imports | ≈ −11 |
| 3 | `_question_timer` (`session.py` −4) | ≈ −4 |
| 4 | Local executors | ≈ −15 |
| 5 | Rust `to_fraction` | ≈ −8 |
| 6 | `settings.py` `Expanded` path type | ≈ −26 |
| 7 | `contextlib.suppress` (11 sites) | ≈ −16 |
| 8 | Dead `AppPaths` fields | ≈ −4 |
| 9 | Config scaffold (owner approved) | ≈ −698 |
| 10 | `architecture.md` status labels (docs) | 0 |
| **All** | | **≈ −803** |

Phase 2 ends with pstack's `blast-radius` applied by hand on the finished branch, with its result recorded
here before reporting.
