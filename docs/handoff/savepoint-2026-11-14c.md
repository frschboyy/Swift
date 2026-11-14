# Save point, 2026-11-14 (evening): moving to the other computer

Read `docs/handoff/README.md`, `docs/handoff/workstreams.md`, `docs/handoff/roadmap.md` and `CLAUDE.md` first. This
replaces `savepoint-2026-11-14b.md`. Each paused session left its own note in `docs/handoff/notes-2026-11-14/` on its
branch (table below).

## `main` now (`a8f12ce`, 28 commits ahead of `origin/main` until the owner pushes)

Merged today with the owner's OK:

- **Halo Step B** (`68519ae`): one card renderer (`overlay/src/card.ts`, `blocks.ts`). The working card's time bar is
  gone on purpose (owner's decision). Halo is still opt-in: `$env:VITE_SWIFT_LOOK = "halo"; npm run tauri dev`.
- **A9** (Gmail's collapsed To row), **A10** (the card moves out from under Task Manager), **C3** (an address said in
  the last 10 minutes opens): merge `c5342ac`. On the merge: Python 2141 passed, 1 flaky failure (below), 35 xfailed;
  overlay tsc clean, 132 pass; cargo 36 pass; routing parity 413/423, 0 harmful.
- **The modes study** (`docs/explorations/modes-study.md`): no code; seven owner decisions with recommendations.
- Docs brought current: the run list, `workstreams.md` (ten stale rows), the handoff branch table, `roadmap.md`.
- **Owner verdict recorded:** 305 FAIL (Read more didn't show the full tea answer, the ellipsis stayed; the answer
  repeated its opening paragraph; results feel plain and hard to scan). The owner's report said 2 FAIL; the second
  wasn't pasted. Ask for it.

## Sessions paused for the move

Each was asked to stop at a clean point, commit (WIP is fine) with a note in `docs/handoff/notes-2026-11-14/`, and not
push. None merges `main`; the orchestrator does, with the owner's OK.

| Session | Branch | What | Next |
|---|---|---|---|
| Unmerged branches | `claude/merge-audit-fixes-google-calendar` (and its session's own branch) | Verdicts on `claude/audit-fixes-google-calendar` (20 commits, checks 222–227), `claude/audit-fixes-recipients` (3), `backup/wake-porcupine-trial-pre-rebase` (25) | Read its note; merge what it says is fine (the owner said: if fine, merge) |
| Check 305 fix | `claude/fervent-tereshkova-435195` | Read more cut off, repeated paragraph; prove the cause, fix, seam scenario | Finish; then merge with the owner's OK. **B4 waits on this** |
| Follow-ups | `claude/festive-colden-b068a2` | A9's repeated "to row opened" log, A10's hotkey-moves-home (`lib.rs:147`) and cursor move, the flaky seam test `test_a_card_counts_down_on_the_backend_s_clock_seen_away_and_back` | Finish; review; merge |
| Split `session.py` | `claude/serene-sanderson-27dd51` | Groundwork: seams out of `session.py` (5,008 lines), kept only if it removes code | Finish step by step; it touches product rules, so a second review |
| B4 build | `claude/objective-ptolemy-8c94e4` | Plan only so far (`b4-build-plan.md` in its notes): four steps, checks 340–351 | Start building in a new `claude/b4-build` worktree once the 305 fix is on `main` |

Session branches with no commits yet only exist here; their notes and WIP commits reach the other PC only once pushed.

## Waiting on the owner

- **Push** `main` and the session branches so the other PC has them (sessions never push).
- **Real-PC checks:** 255 and 252 first, then 306, 310, 320, 330; Halo's 216–221 with `VITE_SWIFT_LOOK=halo`. 305
  waits for its fix.
- **The modes study's seven decisions** (`docs/explorations/modes-study.md`, "Decisions for the owner").
- The second FAIL from the 15:00 report.
- The previous orchestrator chat ("Handoff savepoint restoration") wasn't archived: its Remote Control is live.

## Not finished here

- **The full read of every ADR and exploration**, checked against the code (the owner asked for it). Three read-only
  agents were stopped for the move before reporting. Rerun on the other PC: ADR-000–013, ADR-014–021 with
  `docs/design/halo-system/`, and `docs/explorations/` (including `workflows/` and `modes-study.md`). For each item:
  done, partly, not started, superseded or waiting, with evidence, then what to do next. Known so far:
  - handoff §4 says the groundwork is "not started", but run records, the memory store and `WorkerTask` are built;
  - ADR-018's status line says Step 1 isn't merged (it was, 2026-11-07);
  - B3, B4, B5, B6 and B7 are decided but not built; Halo's ADR-019 §8 items aren't built;
  - the suggested B order is the 305 fix, B4, §8 with B3, B5 with B7, then B6 (they share the card files, so one at a
    time).

## This PC's quirks (Francis-PC)

- `uv run` hangs building a new worktree `.venv`: use `PYTHONPATH=src /c/Users/frchi/Documents/Swift/.venv/Scripts/python.exe`.
- Git has no identity: commit with `git -c user.name=... -c user.email=...` (the identity on `main`'s commits).
- Removing a worktree folder often fails with "Permission denied" while a shell sits in it; `rm -rf` it afterwards.

## Resume (other computer)

After the owner pushes:

```bash
git fetch origin
git checkout main
git merge --ff-only origin/main
```

Then start a session in the main checkout with: *"Resume as the orchestrator from docs/handoff/savepoint-2026-11-14c.md."*
