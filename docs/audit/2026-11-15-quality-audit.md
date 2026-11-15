# Quality audit and skill evaluation (2026-11-15)

**Status:** investigation only, for the owner's review. Nothing was installed, configured or fixed. The brief is the
owner's prompt `docs/handoff/prompts/quality-audit-and-skills.md` (on `handoff/claude/savepoint-2026-11-15`, not on
`main` yet); `CLAUDE.md` wins where they differ.

**Audited:** `main` at `1d6b02b`, in worktree `quality-audit-6f5042`, on Frschboyy-PC. Two foundation branches under
review are not in `main`. Where they fix something, this report names the branch instead of reporting a finding:
`claude/silly-blackburn-367ced` (decisions 1, 3, 10) and `claude/friendly-mestorf-f4f7fb` (decisions 11, 12).

**What was run here:**

| Suite | Result |
|---|---|
| Python, full | 2,184 passed, 1 skipped, 35 expected failures (each names an open finding), 3 warnings, 163 s |
| Overlay `node --test` | 134 tests: 132 pass, 2 todo, 0 fail |
| Overlay `tsc` | not valid here: the worktree has no `node_modules`, and linking it was left out to keep "no configuration changes" |
| Rust `cargo test`, routing parity, speech gate | not run (not touched by a docs-only change; parity and the gate need the owner's data) |
| `test_findings_register.py` after the new entries | 5 passed |

This report builds on the existing records and doesn't repeat them: the 258-entry register `findings.yaml`, the
ownership map (OWN-01 to 07), `privacy.md` §9, `strategy.md`, the health audit, the seams audit and the QA notes of
2026-11-14. When an existing finding is the evidence, it is cited by its ID.

---

## 1. Repository and architecture assessment

### 1.1 What exists

| Part | What it is | Size (2026-11-15) |
|---|---|---|
| Backend | Python 3.12, one asyncio process (`src/swift/backend/__main__.py`), started by the overlay as a child | 24,950 lines in `src/swift`; `session.py` alone is 4,985 (20%) |
| Agent | `claude-agent-sdk` (>=0.1.80) through `executors/claude_code.py` behind `executors/base.Executor`; a mock executor; `WorkerTask` contract | `claude_code.py` 1,046, `claude_mapping.py` 489 |
| Speech | faster-whisper and onnx-asr (parakeet) on CPU, sounddevice capture, text-matched wake (no wake model wired: `wake_acoustic.py` exists, unused), Windows voices | `stt/`, `audio/`, `wake.py` |
| Computer control | pywin32 and comtypes (COM, UI Automation), PowerShell scripts, `SendInput` keys, `os.startfile` | `desktop/windows.py` 924, `system/control.py` 555 |
| Integrations | Google Gmail, Calendar and Contacts (libraries in the `spikes` group, imported lazily), weather over `urllib` | `connectors/`, `workflows/` |
| Overlay | Tauri v2, Rust shell (tray, hotkeys, placement, pane windows, child process) and a **vanilla TypeScript** front end on Vite; no React or other UI framework | 5,380 lines TS (`main.ts` 2,102), 2,861 Rust (`lib.rs` 1,026) |
| IPC | WebSocket on 127.0.0.1 with an OS-chosen port; a per-start token passed by environment, checked with `hmac.compare_digest` in the first `hello` frame; frame size capped (`ipc/server.py`) | `ipc/protocol.py` holds the frame schema |
| Persistence | **No database.** JSON files written atomically (temp file and `os.replace`: memory, parked, scheduler, recordings, word fixes) and JSONL logs appended (run records, interaction log, action journal) under `%LOCALAPPDATA%\Swift`; `config.yaml`; `overlay.json` on the Rust side | readers skip a torn last line (`runs.py:76-79`, `journal.py:57-60`) |
| Tests | pytest with pytest-asyncio and hypothesis; a virtual clock; protocol contract; seam replay through the real presenter; `node --test` for the overlay; `cargo test` | 111 Python test files, 20 overlay test files |
| Evaluation | routing parity (`eval/parity`), speech gate (`eval/stt/gate.py`) | |
| Process | owner checks with a ledger, `plan.py` and `report.py`; findings register with its own test; structure ratchet; ADR-000 to 021; handoff README | |
| CI/CD and lint | **none**: no `.github`, no pre-commit hook, no ruff, mypy or pyright config, no dependency scan (QA15-01) | |

### 1.2 How it fits together

The overlay's Rust process starts the Python backend as a child, reads `SWIFT_BACKEND_READY port=<n>` from its
stdout, and hands the port and token to the web view (`backend_info`). From then on, everything that matters flows
over one WebSocket. The backend decides; the overlay draws and acknowledges (`presenter.ts`, `drawn.Drawn`). The agent
runs inside the backend process through the SDK, and its tool calls come back to Swift for approval
(`claude_code.py` → `confirm_card`).

**Dependency shape:** `session.py` is the hub. It owns question state, card flow, follow-ups, workflow routing and
most of the local lanes. Since 2026-11-01, 42 of the 153 commits whose message says "fix" touched `session.py`. The
next file, `claude_code.py`, has 12. The structure ratchet (`test_structure_ratchet.py`) stops it growing and stops
new package cycles; the split is planned (handoff §4 step 3) and in progress on its own branch.

### 1.3 Strengths, with evidence

- **The rules are written down, with owners.** `CLAUDE.md`'s product rules, `action-authority.md`, the ownership map
  and `reliability.md` §3 are concrete, and each claim names the code that should enforce it. Few projects this size
  have that.
- **The record of findings is honest.** `test_findings_register.py` makes every claimed fix name its evidence, and
  makes every open critical finding name a test or say why not. 35 strict expected failures keep open findings
  visible in the suite.
- **Blocking calls stay off the event loop.** About 50 `asyncio.to_thread` / `run_in_executor` call sites cover COM,
  PowerShell, `psutil`, `os.startfile`, transcription and the SDK import. The `time.sleep` and `subprocess.run` calls
  found are all inside functions that run in a thread (`control.py` `_ps`, `windows.py` pool at 685, `signin.py`).
- **Persistence is crash-tolerant for its size:** atomic replace for state, append-only logs whose readers skip a
  torn line, a corrupt schedule moved aside (`scheduler.py:168`). A database would add nothing at this scale.
- **The IPC boundary is tight:** loopback only, a token of at least 16 characters compared in constant time, never in
  argv, a size cap. The Tauri capability grants only `core:event:default` (no shell, fs or opener plugins). The CSP
  allows no inline script. `open_link` accepts only `http(s)` addresses with a checked host and character set
  (`panes.rs:142`).
- **The tests test behaviour where it counts:** the seam replay drives real backend frames through the real
  presenter, and the intake test checks the approval table itself.

### 1.4 Weaknesses and drift

- **One hub module carries most of the state** (RA-01, II-01, T-09, RV-14, all in the register): a request's state is
  spread over many holders in `session.py`, and frames leave through two doors and fire-and-forget tasks. This is the
  most likely shared cause of the recurring "card stayed", "vanished" and "shown as working" defects (handoff §2).
  The planned fixes (review item 9, the split, run records) address it.
- **Nothing runs by itself** (QA15-01). Every gate depends on the session remembering it. With 673 commits in a
  month, mostly by agent sessions, that is the main process risk.
- **Tests and the real PC differ, by design and in practice.** The handoff says it plainly ("Green tests have
  coexisted with bad days on the real PC"). The seam test stops before the DOM, Tauri and pane windows, so the
  overlay's own refusal of a frame (RA-02) is invisible to it.

### 1.5 Documentation versus code (checked here)

| Document says | Code shows | |
|---|---|---|
| Brief: "pstack is installed" | Installed on this PC too (the owner, relayed by the orchestrator, 2026-11-15); its skills start only when the owner types them, so this audit followed their `SKILL.md` files by hand | Matches |
| Handoff §1: latest measured Python run 1,637 passed | 2,184 passed today | Stale, harmless |
| Handoff §2: "`session.py` is 4,824 lines" | 4,985 (the ratchet's ceiling) | Stale |
| Handoff header "(2026-11-10)" | Content goes to 2026-11-14 | Stale title |
| `capabilities/default.json`: "No shell, fs or opener access" | True of plugins. Every window, panes included, can still call `quit_app`, `restart_backend`, `open_link` (rundll32) and `copy_text` | Accurate in letter. The CSP is what keeps pane content from reaching them; worth one line in the threat model |
| `strategy.md` §3: link `node_modules` to run `tsc` | Needed, and a configuration step this audit wasn't allowed to take | Matches |

The ownership map's claims checked here held: `_background` keeps a task reference (`session.py:1439`), and
`intake.approves` is not yet the only decider (OWN-01 to 03, being fixed on `silly-blackburn-367ced` for OWN-01,
OWN-02 and HA-HEAR-01; OWN-03 isn't named on that branch).

---

## 2. Skill and tooling evaluation

**Read for this evaluation:** the description line of every pstack and cursor-team-kit `SKILL.md` on disk; the
`statechart` skill body; the official plugin manifests and hooks for `security-guidance` and `claude-security`; the
Ponytail manifest and its active rules. External skills (Impeccable, Hallmark, Vercel) are from web listings only,
with no repository code read. Each needs its source read before any install.

| Candidate | Source, maintainer | What it actually does | Kind | Fit for Swift | Security and cost | Verdict |
|---|---|---|---|---|---|---|
| **Ponytail** 5.3.3 | DietrichGebert (`ponytail` marketplace) | Smallest-change rules; `ponytail-audit`, `ponytail-review`, `ponytail-debt` one-shot reports | both | Active here. Covers minimal diffs and deletion; its audit is a generic sweep | Hooks write a per-task CSV to `~/.config/ponytail/band/` (on by default) | **Keep.** No addition |
| **pstack** (poteto, `cursor/plugins`) | Cursor plugin marketplace | Principles (fix root causes, test behaviour, idempotency, separate shared state) and playbooks: `interrogate`, `blast-radius`, `verify-this`, `correct`, `tdd`, `architect`, `how`, `why` | both | **Installed** on this PC (owner-typed only). Matches `reliability.md` closely. Swift already uses `blast-radius` and the QA passes | Text skills. `statechart` downloads Java and TLC through mise | **Keep.** Use by hand, as now |
| pstack `statechart` | same | Model a state machine in TLA+, check it with TLC, draw it in Mermaid, and give the shortest path to each broken rule | audit | **High.** Card lifetimes, question windows, stop and park, and the approval flow are state machines whose defects recur (T-, O-, RA- findings) | Network download of Java and TLC on first run; run in a scratch folder | **Adopt for a trial** (roadmap A3) |
| pstack `create-verification-skill` | same | Makes a project skill that drives the app as a user does | implementation | Medium. The dev harness (port 1431) is a natural target; it can't reach the real PC | Writes a project skill | **Investigate** after the harness config lands (`friendly-mestorf`) |
| pstack `create-formal-verification-skill` | same | A project skill that formally checks the costliest code | audit | Overlaps `statechart` | Tool installs | **Reject for now** |
| cursor-team-kit `thermo-nuclear-code-quality-review` | Cursor | Very strict maintainability review | audit | Duplicates the health audit and Ponytail; `session.py` is already known | none | **Reject** |
| cursor-team-kit `fix-ci`, `loop-on-ci`, `run-smoke-tests`, PR skills | Cursor | GitHub PR and CI loops, Playwright | implementation | No CI, no GitHub PRs (never push), no Playwright | `gh` access | **Reject** |
| **claude-security** | Anthropic (`claude-plugins-official`) | Whole-repo vulnerability scan at a chosen tier; every finding challenged before it's reported; a coverage section listing what was examined | audit | **High.** The executor and read-scope boundary (X-20, B-01, X-07), IPC and Tauri commands are where a security miss costs most | Has hooks and scripts: read them before install. Its README says it reads repo text as data, not instructions | **Adopt** for one scan (roadmap A4) |
| security-guidance | Anthropic | Pattern warnings on every edit; an LLM diff review on **every Stop**; a SessionStart hook that installs the agent SDK | audit | Low marginal value over `claude-security` plus the product-rule reviewer | Per-turn cost and noise; a network install at start | **Reject** |
| code-review, pr-review-toolkit | Anthropic | Multi-agent PR review | audit | Built for PRs; `/code-review` on a branch diff is already available in this app | | **Use what's built in**, no install |
| pyright-lsp, rust-analyzer-lsp, typescript-lsp | Anthropic | Language servers for code intelligence | tool | Helpful for navigating `session.py`; not a gate | Need the language servers installed | **Optional** |
| **Impeccable** | Paul Bakaus, `pbakaus/impeccable`, Apache-2.0 ([source](https://github.com/pbakaus/impeccable)); built on Anthropic's frontend-design skill | `audit` scores accessibility, performance, theming, responsiveness and anti-patterns; a design hook runs its detector on UI edits | both | Medium. The overlay is plain TS and CSS, so its framework-neutral checks apply. Its taste rules may fight Halo (ADR-019) | Large context load; the edit hook should stay off | **Investigate**: audit command only, once, on the Halo screens |
| **Hallmark** | Nutlope, `nutlope/hallmark`, MIT ([source](https://github.com/nutlope/hallmark)) | Anti-"AI slop" design generation with themes; an `audit` mode | mostly implementation | Low. Swift already has a chosen design system (Halo); generative themes conflict with it | `npx` install | **Reject** |
| Anthropic frontend-design | Anthropic | Guidance for building new UI | implementation | Swift needs an audit of existing UI | | **Reject** |
| Vercel React Best Practices | `vercel-labs/agent-skills` ([listing](https://tessl.io/registry/skills/github/vercel-labs/agent-skills/vercel-react-best-practices)) | About 70 React and Next.js performance rules | both | **None.** The overlay has no React | | **Reject** |
| PlanetScale or any database skill | — | Database schema and query tooling | — | **None.** Swift has no database | | **Reject** |
| ruff (lint, including `ASYNC` and `S` rules) | Astral | Static lint; the code already cites its rule codes in 67 `noqa` comments | tool | **High**, cheap: makes existing intent checkable | One dev dependency, no network at run time | **Adopt** (needs the owner's OK) |
| pip-audit, `cargo audit`, `npm audit` | PyPA, RustSec, npm | Check locked dependencies against known vulnerabilities | tool | Medium. `uv.lock`, `Cargo.lock` and `package-lock` exist | Network to read advisories; reports only | **Adopt** as a monthly run |
| pyright (type check) or mypy | Microsoft / Python | Type checking | tool | Medium. The code is annotated but unchecked; a first run will be noisy | Dev dependency | **Investigate**, ratcheted per module |
| py-spy, Windows Performance Recorder | Ben Frederickson / Microsoft | Sampling profiler; system traces | tool | For B-05 (slow first request) and CPU use on a no-GPU PC | Installs a binary | **Optional**, only when a number needs explaining |
| Accessibility checker (axe-core) in the harness | Deque | DOM accessibility rules | tool | Medium for the overlay; runs in the dev harness, not the real PC | npm package | **Optional**, with the Impeccable trial |

---

## 3. Coverage matrix

| Quality dimension | Existing coverage | Identified gap | Recommended capability |
|---|---|---|---|
| Requirements and specification | Product rules, ADRs, `action-authority.md`, foundation decisions, owner checks tied to code by the ledger | Owner checks find defects the spec didn't foresee (2026-11-13 runs); acceptance is decided on the PC only | pstack `interrogate` on new ADRs before build; no new tool |
| Architecture and maintainability | Ownership map, structure ratchet, health audit, Ponytail | Ratchet guards `session.py` only; one hub holds most state | The split already planned; extend the ratchet to `main.ts` and `lib.rs` if they grow (they shrank from 2,236 to 2,102 since 2026-11-08) |
| UI/UX and frontend | Halo design system, seam replay, owner checks 216–221, the harness | No accessibility or contrast check on the drawn DOM; the harness has no pane windows | Impeccable `audit` (trial) and axe-core in the harness |
| Frontend engineering and performance | `node --test`, `tsc` | No measurement of frame-to-paint or memory over a day | Measure first, in the harness (Performance panel); no skill needed |
| Persistence | Atomic writes, tolerant readers | No retention for interaction log, run records, journal (`privacy.md` §9.1); no test of concurrent writers to one JSONL file | Tests, not tools; pstack `principle-make-operations-idempotent` when retention is built |
| Async and concurrency | Virtual clock, seam replay, `cleanup.py` | Fire-and-forget tasks (T-09, RV-14; 8 raw `create_task` calls in `session.py` bypass `_background`, so they hold no reference: Python's docs warn such a task can be garbage collected mid-run); leaked waiter (QA15-02); no model of the state machines | `statechart` (TLA+) on the card and question lifecycle; ruff `ASYNC` and `RUF006` |
| Security and privacy | Threat model, `privacy.md`, read scope, gateway digest, product-rule reviewer | Worker tools have no digest re-check (OWN-05); shell reads by built paths (X-20 safeguard only); no dependency scan; no whole-repo security pass since the health audit | `claude-security` scan; pip-audit, `cargo audit`, `npm audit` |
| Testing and reliability | Layers in `strategy.md`; 2,184 tests; 35 strict xfails; eval gates | Nothing runs automatically (QA15-01); the seam test stops before DOM and Tauri; one known flaky test (`test_parked.py::test_finish_the_named_task`) | A local pre-commit hook running the fast gates; `create-verification-skill` on the harness (later) |
| Runtime performance | `spikes/latency`, `docs/audit/performance.md`, the usage report | B-05 unmeasured since; no resident-memory baseline for a day's use on 24 GB, CPU-only | py-spy, only when a number needs explaining (pstack `principle-explain-the-number`) |
| Process (findings, fixes, checks in step) | Register, ledger, `plan.py`, handoff §6 | Kept in step by sessions remembering; the brief itself lives on an unmerged branch | No new tracker (§7) |

---

## 4. Prioritised findings

New entries added to `findings.yaml` are marked **new**. The rest are existing entries that this audit rechecked
and ranks, so the owner can see one ordered list. Severity is the register's; likelihood and impact are this audit's.

### 4.1 Confirmed

| ID | Area | Finding | Evidence | Severity | Likelihood | Impact | Next step |
|---|---|---|---|---|---|---|---|
| HA-HEAR-01, OWN-01, OWN-02 | approval | Approval decided outside `intake.approves`; typed "Swift, yes" answers Swift's own question | register; ownership map | critical / high | already seen in tests | a typed yes acts (rule 1) | **Fixed on `silly-blackburn-367ced`**, under review; not a new finding |
| OWN-03 | approval | The hands-free fix offer takes "Swift, yes" by its own condition | register | high | medium | rule drift | Check whether `silly-blackburn` covers it; it isn't named there |
| X-20 | security | Shell commands reach never-read places by a built path; only the command's text is checked | register; `ReadScope.in_command` | critical, partial | low (needs the agent to build the path) | secrets to the model | A shell sandbox (the root fix the entry names); include in the security scan |
| OWN-05 | security | A worker's tool runs with the arguments its card showed, with no digest re-check and no journal line | register; `CLAUDE.md` | open | low | the approval-covers-exactly rule is not enforced in one place | Include in the security scan |
| RA-01, RA-02, RV-14, T-09 | concurrency, screen | State spread over many holders; frames refused silently; two send doors; fire-and-forget tasks | register; `presenter.ts:273-277`; `session.py` lines 1218, 1242, 1266, 2763, 3690, 3692, 4341, 4411 | high / medium | **seen**: the 2026-11-13 runs | cards that vanish, stay or show the wrong state | Model the card lifecycle (A3) before building review item 9 |
| **QA15-01** (new) | process | No check runs by itself on any commit; lint rules the code cites can't run; no dependency scan | §1.1; no `.github`, hook or lint config; 78 `noqa` | medium | certain (it is the current state) | regressions land when a session forgets a gate | Owner decides on a local hook and two dev tools (§5) |
| **QA15-02** (new) | concurrency | A confirm card answered while behind another leaves its `shown.wait()` task pending | `session.py:4264` | low | every such card | slow task leak; "pending task destroyed" at exit | Cancel the losing task; a unit test with the virtual clock |
| `test_parked.py::test_finish_the_named_task` | tests | Flaky, about one run in three (handoff §2) | handoff | — | it passed today | trains sessions to ignore red | Not in the register; worth an entry by whoever reproduces it |

### 4.2 Probable risks, to validate

| ID | Area | Risk | Why it's plausible | Validation |
|---|---|---|---|---|
| **QA15-03** (new) | overlay | One panic under a Rust lock poisons it; later commands panic too | 49 `lock().unwrap()`, no recovery | Look for any panic in a guard; only matters if the overlay stops answering after an error |
| RV-15 | presence | The lock rule is checked in about four places | register | The `session.py` split, with one presence step in intake |
| — | concurrency | The 8 raw `create_task` calls could be garbage collected mid-run (Python docs) | They keep no reference; `_background` exists to prevent exactly this | Part of T-09; route them through `_background` when T-09 is fixed |
| — | security | Every pane window may call `quit_app`, `restart_backend`, `open_link` | Tauri v2 app commands are allowed for every window listed in the capability | Only reachable if pane content could run script, which the CSP blocks; record in the threat model |

### 4.3 Unknowns

- **Wake after idle (RA-18), B-05 and the false-wake rate:** no proven cause and no current measurement.
- **Memory over a day's use on 24 GB with two speech models resident:** never measured that this audit found.
- **Whether the overlay type-checks on `main` today:** not checkable here without linking `node_modules`.
- **Whether the external skills do what their listings say:** no repository code read.

**Systemic causes behind the recurring defects:** (1) state held in many places in one module (RA-01, II-01), so each
fix patches one holder; (2) checks that depend on memory, not on automation (QA15-01); (3) tests that stop before the
screen the owner sees (strategy.md §1, RA-02). The first is being addressed by the split, run records and item 9;
the second has no plan yet; the third is accepted, with owner checks as the backstop.

---

## 5. Recommended skill stack

Lean by design: two keep, two adopt, one trial, and tooling. Nothing here is installed. Every addition waits for the
owner's yes.

| Priority | Selection | Why, and which gap | Beyond pstack and Ponytail | Overlap | Install and setup | Drawbacks and security |
|---|---|---|---|---|---|---|
| Essential | **Keep Ponytail and pstack** as now | Implementation discipline, root-cause and verification principles | — | each other, a little | none | Ponytail's ledger CSV is written by default |
| Essential | **A local pre-commit hook plus ruff** (`ASYNC`, `S`, `RUF`, `B` rules the code already cites) and the register, ratchet and owner-plan tests | QA15-01 | Neither runs any check by itself | none | ruff into the dev group; a hook in `.git/hooks` per worktree (or `core.hooksPath`) | One dev dependency; hooks are per PC, so decision 13's bundles don't carry them |
| Essential | **`claude-security`**, one whole-repo scan | Security, at the boundaries where a miss costs most (executor, read scope, IPC, Tauri commands, desktop typing) | Neither does security review | `security-guidance` (rejected) | Plugin install from `claude-plugins-official`; read its hooks and scripts first | Cost of a deep tier; findings need triage into the register |
| Recommended | **pip-audit, `cargo audit`, `npm audit`**, monthly | Dependency vulnerabilities | — | none | pip-audit as a dev dependency; `cargo-audit` binary | Advisory reads need network |
| Recommended | **pstack `statechart`**, trial on one lifecycle | The recurring screen and timing defects | Turns "a card stayed" into a checked model with the shortest failing path | `create-formal-verification-skill` | Installed with pstack; first run downloads Java and TLC | A model is only as good as its match to the code; keep it beside the seam tests |
| Optional | **Impeccable `audit`** (no hook) | Accessibility and responsiveness of the overlay | Neither audits UI | Hallmark, frontend-design (rejected) | Plugin from `pbakaus/impeccable` | Context heavy; taste rules may contradict Halo |
| Optional | pyright, py-spy, axe-core | Types; explaining a slow number; DOM accessibility | | | each a dev install | first type-check run is noisy |

**Alternatives considered:** `security-guidance` instead of `claude-security` (rejected: per-turn LLM reviews and a
SessionStart install); hosted CI (rejected: never push; a local hook does the same job); mypy instead of pyright
(either works, decide when trialled).

---

## 6. Audit roadmap

Each phase ends in something checkable. Phases A1 and A2 need nothing installed.

| Phase | What | Depends on | Done when |
|---|---|---|---|
| **A0. Baseline** (done here) | Suites run on `1d6b02b`; inventory §1; register rechecked for the top items | — | This report |
| **A1. Module and workflow inventory** | Extend `ownership.md` with each critical workflow (voice request, typed request, approval, send, delete, stop, sign-in) and the modules and owner checks each crosses | — | Every workflow names its entry point, owner, tests and owner checks; `test_owner_plan.py` passes |
| **A2. Automatic gates** | The local hook and ruff (QA15-01) | Owner's OK for ruff | A commit that breaks the register, the ratchet or an `ASYNC` rule is refused locally; `noqa` count doesn't grow |
| **A3. Concurrency model** | `statechart` on the card lifecycle (shown, behind, held, stack, run out, stopped, parked), then the question window | Owner's OK for the mise download | Each rule in ADR-013 §5 and ADR-015 is a property TLC checks; every counterexample is a register entry or a seam test |
| **A4. Security pass** | `claude-security` over `executors/`, `security/`, `ipc/`, `desktop/`, `overlay/src-tauri/src`; dependency scans | Owner's OK for the plugin | The report's coverage section lists every folder; each surviving finding is in the register with a test or `untested:` |
| **A5. Root causes before symptoms** | Item 9 (versioned snapshot), the `session.py` split and RV-15, using A1 and A3 | The foundation branches merged | `session.py` below its ceiling, ratchet lowered; RA-01, RA-02, RV-14, T-09 at `fixed` with seam tests |
| **A6. UI and runtime** | Impeccable audit on the Halo screens; a one-day memory and CPU baseline (`psutil` from the backend's own log) | Halo checks 216–221 run | Accessibility findings triaged; a resident-memory number on record in `performance.md` |
| **A7. Living process** | Re-audit an area when a change crosses it (below) | — | Every merged branch's register delta names any area it changed |

**Completion criteria per area:**

| Area | Measurable bar |
|---|---|
| Approval | Every approval path calls `intake.approves` (a test fails on a second decider); OWN-01 to 05 closed |
| Concurrency | Zero raw `create_task` in `session.py` outside `_background` (a ratchet); the card lifecycle model passes |
| Security | A `claude-security` report with full coverage; no open critical security finding without a test |
| Persistence | Retention for the three logs (`privacy.md` §9.1); a test of a torn line in each reader |
| Tests | Fast gates run by hook; the flaky test fixed or quarantined with a register entry |
| UI | No accessibility issue of Impeccable's P0/P1 open on the Halo screens |
| Performance | B-05 measured with a cause; resident memory after one day recorded |

**Reassessment trigger:** a change that adds a dependency, a new process or thread, a new IPC frame type, a new Tauri
command, or a new place that writes to disk re-opens that area's row in the A1 inventory.

---

## 7. Audit tracking proposal

**No new tracker.** The existing pieces already cover it, and they only need two links made explicit:

1. **Findings:** `docs/audit/findings.yaml` stays the one register. Its `status` values already separate identified
   (`open`, `unproven`), investigated (`confidence: confirmed`), fixed (`fixed`, `partial`) and accepted (`wontfix`).
   What it lacks is **verified on the PC**. Proposal: a fixed entry is verified when its owner check passes, recorded
   by naming that check in `note` (`verified: check 242, 2026-11-13`). A small test can then report fixed entries
   with no passed check, from the ledger. That needs a register test change, so it's the owner's call.
2. **Tests:** the `test` field already names the test; `test_named_tests_exist` keeps it honest.
3. **Owner checks:** `owner-checks-ledger.yaml` names the code each check proves; `plan.py` knows what changed since a
   check passed. Linking a finding to its check (point 1) closes the loop.
4. **Roadmap and handoff:** `roadmap.md` and handoff §2 cite register IDs instead of restating findings.
5. **Duplicates:** before adding an entry, search the register by module and keyword, as done here: T-09 already
   covered the raw tasks, so this audit added evidence to the report, not a new entry.
6. **Decisions:** an ADR or foundation decision that changes a rule names the findings it closes or reopens.

---

## 8. Not verified

- The overlay's `tsc` (no `node_modules` here), Rust tests, routing parity and the speech gate.
- Anything on the real PC: no live windows, no port 1420, no real-world actions.
- The external skills' code (Impeccable, Hallmark, Vercel), and the hooks and scripts of `claude-security`. Read
  before any install.
- pstack skills beyond their description lines, except `statechart`.
- QA15-02 and QA15-03 were found by reading; neither is reproduced.
- The shared notes folder for this session group was empty, so no sibling notes were weighed.

Sources for the external skills: [Impeccable](https://github.com/pbakaus/impeccable),
[Hallmark](https://github.com/nutlope/hallmark),
[Vercel React Best Practices listing](https://tessl.io/registry/skills/github/vercel-labs/agent-skills/vercel-react-best-practices).
