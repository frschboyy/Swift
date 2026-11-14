# Save point, 2026-11-14: resuming on the other computer

Read `docs/handoff/README.md` and `docs/handoff/workstreams.md` first. The owner's decisions of 2026-11-13 and
2026-11-14 are at the end of `workstreams.md`.

## Where things stand

`main` (`cc19d71`) has everything the owner approved on 2026-11-13 and 2026-11-14:

- the workstream fixes A2, A3, A4, A7, A8, A1b, A9, A10/C3 and C1, plus the "Add" → calendar fix (`run-1005-gaps`);
- B1: approval cards lead with the agent's sentence, and the command's first line always shows;
- B2: one approval for a coherent step of a task (`step_grant.py`), with deletes, sends and pushes always asking;
- review item 9: the overlay acknowledges what it drew (`screen`), and countdowns run on the backend only (the owner waived the delete-code bar);
- the groundwork: run records (`runs.py`, N2 `origin`), the `WorkerTask` contract and grant, and the memory store (`memory.py`), which refuses passwords, PINs, card and ID numbers;
- the B4 and B6 design studies (`docs/design/b4-adaptive-results.md`, `docs/design/b6-live-view.md`) with their dev-only prototypes.

The last full run on `main`'s content: Python 2117 passed, 0 failed (on B2's branch after merging `main`); routing parity 413/423, 0 harmful; overlay `tsc` clean, `npm test` 132 pass.

## Not in `main` yet

| Branch | What | Next |
|---|---|---|
| `claude/suspicious-noyce-b32748` | Flaky timing tests moved to virtual time: `6672d28` (seam replay), `5785abc` (`test_s02`), `6bcaa56` (card timing) | Its 50-run check under load and a full suite were running when this was saved. Re-run both, and check that `test_a_plain_answer_on_screen[yes-True]` and `test_a_timer_waits_for_a_question_on_screen` (which fail on `main` about 3 runs in 4) are fixed. Then merge, with the owner's OK. |

`claude/audit-fixes-google-calendar` and `claude/audit-fixes-recipients` are older branches, outside this work.

## Waiting on the owner

- **Halo Step B (one card renderer):** approved to start after item 9, which is now in `main`; the owner hasn't said "start" yet. It is the base for B4, B5, B7 and B3. A brief: one renderer for every card kind, no new features, and it must delete net code; keep B1/B2's approval card, item 9's `countdown` and `screen` as they are; leave clean places for B4's shapes, B5's growth and B7's motion; check both looks, dark and light, in the harness.
- **Owner checks on the real PC:** the run list at the top of `docs/testing/owner-checks.md`. New ones from these two days are 250–257, 259–264, 270–271, 280–281, 290–293 and B2's; re-runs include 197, 204, 205, 206, 208, 218, 219, 49, 242. Check 254 decides A10's fix; 252 proves A9's cause.
- **Not yet:** the Windows Location tool (C1); the credentials vault (C2/C4) needs a decision first.

## After Halo Step B (the order in `workstreams.md`)

B4's shapes, B5, B7 and B3 on Step B; A5 (card lifetimes) and A6 (a stack card points at its live run, via run records); B6 built; memory follow-ups (the agent sees memory through the context pack, "undo that", a memory proposed on a card); then C5, C6, C4, C2. Item 9's steps 2–3 were skipped (no code deleted; step 2 touches a product rule).

Unproven causes, needing the other PC's logs or checks: A7 (204/205), A9 (252), A10 (254), C3 (Blackboard, 15:07).

## Resume (other computer)

```bash
git fetch origin
git checkout main
git merge --ff-only origin/main
git worktree add --track -b claude/suspicious-noyce-b32748 .claude/worktrees/flaky origin/claude/suspicious-noyce-b32748
```

Then start a session in the main checkout with: *"Resume as the orchestrator from docs/handoff/savepoint-2026-11-14.md: finish the flaky-test branch, then start Halo Step B when I say."*

## Not in git, on purpose

Swift's logs, clips and interaction log (`%LOCALAPPDATA%\Swift`), the memory store (`%LOCALAPPDATA%\Swift\memory`), run records, and Claude transcripts stay on this PC. Session notes in the app's side-session folder don't transfer either; what mattered from them is above and in `workstreams.md`.
