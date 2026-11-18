# Documentation audit and consolidation (2026-11-18)

The owner asked for every document to be checked for redundancy, staleness and conflicts, and reorganised so it is
clear what is current, what is decided, what is outstanding, what is done and what is history, **without losing
anything**. Done on branch `claude/docs-consolidation` from `main` at `da47273`. No product code changed.

**Method.** All ~100 tracked documents (about 20,000 lines) were listed with their last change date. The hubs (handoff,
roadmap, workstreams, README, architecture, CLAUDE.md) were read in full; the rest by status line and structure. Claims
were checked against git (`branch --no-merged`, `merge-base --is-ancestor` for each "on branch X" commit, `log -S`),
the code (grep for each named module, setting or class), and a link checker over every relative link and backticked
repo path. Which documents code and tests read was mapped first, so nothing they depend on moved.

## 1. What was found

### Structure: mostly sound, three hubs drifting

The structure that `CLAUDE.md`'s split set up on 2026-11-15 works: one register of problems (`findings.yaml`, kept
honest by `test_findings_register.py`), one approval model (`action-authority.md`, tested by `test_intake.py`), one
ownership map, one testing strategy. The drift is in the documents every session edits by hand: the handoff, the
roadmap and the workstreams, plus the root README and `architecture.md`, which predate the split.

There was no index of the documents and no single list of decisions. Decisions were spread across the 21 ADRs,
handoff §5 ("Answered", "Running on a default"), two decision sections in `workstreams.md`, the foundation review §7,
the modes study and B4 §7.

### Stale (checked, now fixed)

| Where | It said | The evidence |
|---|---|---|
| `README.md` status | "MVP Milestone 1 (overlay shell driven by a mock executor)" | Swift has run real requests since October |
| `README.md` harness | Open the harness on port 1420 | `CLAUDE.md`: 1420 is the owner's running Swift; the harness uses 1431 (`testing/strategy.md` §3) |
| `README.md` wake | "There is no wake-word model" | `wake_acoustic.py`, `wake.acoustic` in `settings.py` (ADR-021) |
| `architecture.md` first half | Tk overlay, pystray tray, Piper worker pool, a `Local\Swift-<SID>` mutex, `StatusEvent`, availability states | None exist in `src/` or `overlay/` (grep); single instance is `tauri_plugin_single_instance` |
| handoff §6 | `claude/b4-diagram-902ffc` and `claude/byline-no-provider` open | Both merged into `main`; five open branches weren't listed |
| handoff §1 | Next free owner check number 233 | `plan.py --next-id` gives ids now (decision 11) |
| handoff §4 | Halo "design only so far" | Steps A and B are on `main` (the same paragraph says so further on) |
| handoff §2 | `session.py` is 4,824 lines | 4,975 today |
| `roadmap.md` | Three "say whether to merge" steps | `harness-takeaways` merged (`8082af7`); both `audit-fixes-*` branches were deleted on 2026-11-15, their fixes on `main` or superseded |
| `workstreams.md` A1, A7, A9 | "Fixed on `claude/…`, waits on a second review" | `1429e81`, `b4768b3`, `355bc7e`, `20f07e5` are all on `main`; those branches are gone |
| ADR-016 | "Proposed" | Phases A–C approved 2026-10-28 and built |
| ADR-021 | "Decided by: Owner (pending)" | The owner said "start step 1" on 2026-11-11; merged 2026-11-12 |
| Halo `DIRECTION.md`, `SPEC.md` | ADR-019 "(proposed)" | Accepted 2026-11-07 |
| ADR-000 | ADR-001…004 reserved for spike outcomes | Never written; ADR-006 replaced the plan they served |
| `PLAN.md` | "Awaiting owner approval. No code has been written" | Approved and built in October |

### Conflicting (resolved)

- **Handoff §2 against `workstreams.md`.** The handoff's account of the 2026-11-13 runs said "none is fixed yet" for
  items `workstreams.md` marks fixed and merged (A1 wafer, A2, A4, A8, C1). The workstreams are the live tracker, so
  the handoff now points there and the day's diagnosis moved, unchanged, to `archive/2026-11-13-owner-runs.md`.
- **C3, earlier web addresses.** `workstreams.md` described the "pointing" rule as built on a branch awaiting review;
  `action-authority.md` says foundation decision 4 replaced it (`f22f6c0`, `points_back` deleted). The workstream now
  says so.
- **Harness port**, README against `CLAUDE.md` (above).
- **`architecture.md` against `audit/architecture-as-built.md` and `ownership.md`** (above). The as-built page said in
  October that `architecture.md` was wrong; it stayed wrong until now.

### Redundant or finished (archived, not deleted)

Moved to `docs/archive/`, whose README says why each is there and where its current home is: the paused v2.0 spec and
the first MVP plan, the old backlog (its two live ideas joined handoff §4's Deferred list), the Phase C and recordings
briefs and status pages, the Halo A/B brief, the 2026-11-14 status review and session notes (QA 1–3, with their
screenshots), the two adopted `CLAUDE.md` proposals, and the pen.dev brief pack that produced Halo. Every link to them
was rewritten.

### Preserved on purpose

- **Audit documents stay in `docs/audit/`.** About 200 `findings.yaml` entries and eight test files cite them.
  They are dated reasoning; status lives in the register.
- **ADRs are never moved or rewritten.** Only status lines were corrected, with the evidence in the commit.
- **Explorations still open** (interaction layer, UI reach, desktop choreography, assistant UX research, context-aware
  speech, cross-platform readiness, the ADR-011 example workflows) stay in `explorations/`.
- **Design**: `swift-overlay/` is the Capsule spec and still the look that ships; `overlay/src` cites it.

## 2. What changed

| Commit | What |
|---|---|
| 1 | Archive moves, link rewrites, `archive/README.md`, the 2026-11-13 run diagnosis moved out of the handoff, X-20's source pointer |
| 2 | Hub fixes: handoff, roadmap, workstreams, README, `architecture.md`, ADR and Halo status lines, a note in `stt-models.md` that word fixes were removed |
| 3 | New: `docs/README.md` (the map), `decisions/log.md` (every decision by date, pointing at its source), this report |

## 3. Verified, and not

- **Verified:** the Python suite passes on this branch (it reads `findings.yaml`, `CLAUDE.md` and
  `action-authority.md`); no file that code, tests or `plan.py`/`roadmap.py` read was moved; every new link resolves
  (link checker). Each stale claim above was checked as its row says.
- **Not verified:** the body of every ADR and exploration against the code (status lines only); the 2,958-line
  `owner-checks.md` (not touched: three open Halo branches change it); whether the handoff's "In one minute" bullets
  about real-PC results still hold (they depend on owner checks).

## 4. Left for later, and why

- **Handoff §1's test counts** are from 2026-11-06/07. They should be replaced by a fresh full run of all four suites
  (Python, overlay, Rust, parity) rather than one.
- **The handoff is still long (~370 lines).** §2's X-17 leftovers and "not understood yet", and §5's "Answered" list
  (now indexed in the decisions log), could move out once the owner confirms which are still live.
- **`ROADMAP.md`** was last generated 2026-11-14. Run `uv run python spikes/owner_checks/roadmap.py` in the main checkout.
- **`docs/stt-*.md` could move into a `docs/speech/` folder**, but `session.py`, `settings.py`, `transcriber.py` and two
  tests cite the paths; not worth a code change.
- **Dead references in dated documents** (removed `learn_fixes.py`, `fixes.py`, `boost.py`; a prompt file in the quality
  audit that never reached `main`) are left as written: they record what existed then.
- **Merged worktrees** under `.claude/worktrees/` (answer-heard-feedback, b-ui-review, keep-detector-misses,
  mic-echo-trial, noise-voice-gate, stt-corrections, and others) can be removed with the owner's OK.
- **Untracked files in the main checkout** (`docs/handoff/halo-b8/`, `docs/testing/live-ui-loop.md`, new Halo boards,
  `.claude/stale-wip/`) belong to other work and weren't touched.

## 5. Merging this branch

It touches files that open branches also change: one line of `owner-checks.md` (the three `claude/halo-b8*` branches)
and the handoff and workstreams (`claude/a12-c9-followup`, 8 lines). Expect small conflicts in whichever merges second.
Merging this after the Halo B8 work is the cheaper order.
