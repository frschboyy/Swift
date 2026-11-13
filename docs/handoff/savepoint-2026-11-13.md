# Save point, refreshed 2026-11-13: resuming on the other computer

Read `docs/handoff/README.md` and `docs/handoff/workstreams.md` first (both on this branch, which is built on `claude/workstreams`).

The Claude status text pasted by the owner identifies seven sessions: the `Roadmap and owner checks` orchestrator
and six workers. This refresh records their Git branches and the context in that pasted report; the repository cannot
confirm whether the Claude processes are still running. Treat them as tasks to resume, not live sessions that will
transfer.

## The seven sessions

The six worker branches were based on `claude/workstreams` (`5bd9e61`). Their `savepoint/<name>` refs reflect the
worktree state checked at 16:37: dirty worktrees have a WIP commit on their current branch tip; clean worktrees
point to that branch tip so an older snapshot cannot overwrite later commits. WIP is unreviewed and may fail.

| Session/task | Branch | Snapshot | State checked at 16:37; next action |
|---|---|---|---|
| Main orchestrator: "Roadmap and owner checks" | `claude/workstreams` (`71e7163`) | None; branch is clean | Committed A8 music fix (`41a1773`), A1b refusal-text fix (`1429e81`), owner check 262 and its report/ledger/handoff updates. The owner-pasted report says the new A8 regression test passed and failed with the fix undone; full suite passed except one Windows drive-path test that also fails without these changes; routing parity stayed 413/423, 0 harmful. These results were reported by Claude, not rerun in this savepoint session. Nothing is merged; the branch waits for the owner's OK. Resume by reviewing the six worker results independently, keeping the A8/A1b work on this branch, and not merging without approval. |
| A2/A3: a question shown as "Working on it"; spinner doesn't turn | `claude/a2-question-state-42bf6d` (`5aa1aa1`) | `savepoint/a2-question-state-42bf6d` (clean) | The A2 front-state and A3 spinner commits are present; no WIP remains. Replay the lunch question in the harness; whether A2 is refused or mis-drawn is still unproven, and A3 has not been checked. |
| A4–A6: cards vanish unseen; stack restore | `claude/a4-card-lifecycle-f50a7b` (`5bd9e61`) | `savepoint/a4-card-lifecycle-f50a7b` | WIP is `session.py` plus a seam scenario. Its A4 assertions passed, but one test request did not wind down during cleanup. Diagnose that, then replay unseen-card and stack restoration scenarios. |
| A7: one ask becomes two requests | `claude/a7-duplicates-54bd6a` (`bf71860`) | `savepoint/a7-duplicates-54bd6a` | Commit `bf71860` addresses an utterance begun before Swift asked; the WIP adds `same_request.py` and its test. Run focused tests and finish the duplicate cases; checks 204/205 remain uninvestigated. |
| A9: Gmail writes only with the cursor in the body | `claude/a9-gmail-focus-03dda1` (`c8bff02`) | `savepoint/a9-gmail-focus-03dda1` (clean) | Three commits now cover failure logging, retrying focus, and bringing a compose window forward. The earlier 14 tests passed; the real failure cause is still unproven. Retest the Gmail path and checks 242/49/215. |
| A10 + C3: Swift behind Task Manager; opening a website | `claude/a10-front-and-web-9f8dcd` (`6bd3666`) | `savepoint/a10-front-and-web-9f8dcd` | Two commits cover invalid ports and spoken web addresses; WIP adds window-band handling, tests and a report line. Finish the topmost-window investigation (A10) and reproduce the Blackboard failure (C3). |
| C1: never answer with a location Swift doesn't have | `claude/c1-grounded-facts-556f60` (`5bd9e61`) | `savepoint/c1-grounded-facts-556f60` | WIP adds a location instruction, weather-area separation, tests and owner checks 259–261. Run focused tests; the owner checks still need real-PC evidence. |

The six workers own checks 244–261; C1's current WIP adds 259–261, and `plan.py` prints the next free number. The
orchestrator owns check 262. The full roadmap context—not just failed checks—is in `docs/handoff/workstreams.md`:
three themes (task orchestration/state, adaptive UI/UX, agent autonomy), each item mapped to checks, evidence, kind,
and next steps. It includes the remaining fixes, design decisions and capabilities, with A8/A1b marked fixed on
`claude/workstreams`. Local `main` is 7 commits ahead of `origin/main`.

## Other local branch, not one of the seven sessions

`claude/run-1005-gaps` (`ce92b76`) is clean and not merged into `main`; its commit is the "Add" → calendar routing fix.
The prior savepoint mistakenly listed a misheard-clips labelling card as the seventh session. The owner's latest
session list identifies the seventh as the orchestrator above, and no separate labelling-card worktree or WIP is
present. Do not treat `claude/run-1005-gaps` as that labelling-card work.

## Publish refs for the other computer

The refreshed WIP refs and handoff are local only. At the last remote check, `origin` had `main` but none of these
session/savepoint branches. After reviewing what should be published, run `bash docs/handoff/savepoint.sh` again
from this worktree to refresh snapshots and print the branch list. The minimum refs for these tasks are:

```bash
git push origin main claude/workstreams claude/savepoint-2026-11-13 claude/a2-question-state-42bf6d claude/a4-card-lifecycle-f50a7b claude/a7-duplicates-54bd6a claude/a9-gmail-focus-03dda1 claude/a10-front-and-web-9f8dcd claude/c1-grounded-facts-556f60 claude/run-1005-gaps savepoint/a2-question-state-42bf6d savepoint/a4-card-lifecycle-f50a7b savepoint/a7-duplicates-54bd6a savepoint/a9-gmail-focus-03dda1 savepoint/a10-front-and-web-9f8dcd savepoint/c1-grounded-facts-556f60
```

`main` includes seven local commits that are not on `origin/main`; review them before publishing. Do not push secrets,
local logs or audio.

## Resume (other computer)

```bash
git fetch origin
git checkout main
git merge --ff-only origin/main
```

For each of the six named workstreams, create its local branch from the fetched remote and restore its snapshot:

```bash
git worktree add --track -b claude/<name> .claude/worktrees/<name> origin/claude/<name>
git -C .claude/worktrees/<name> restore --source=origin/savepoint/<name> -- .
```

For A2 and A9, the snapshot is clean and matches the branch tip, so the restore makes no changes. For A4, A7, A10
and C1, it restores the saved WIP as uncommitted work. Then start a session in each worktree with: *"Resume task
<task> from docs/handoff/savepoint-2026-11-13.md and docs/handoff/workstreams.md. Re-run the focused tests, finish
the item, and commit following CLAUDE.md."* For the separate clean `claude/run-1005-gaps` branch:

```bash
git worktree add --track -b claude/run-1005-gaps .claude/worktrees/run-1005-gaps origin/claude/run-1005-gaps
```

## Not in git, on purpose

- **Swift's logs, clips and interaction log** (`%LOCALAPPDATA%\Swift`). They may contain transcripts or audio and must stay on the originating PC; never put them on GitHub or copy them to the other computer. Use the redacted owner-check report and the summaries above to carry findings across.
- **Claude transcripts** (`~/.claude/projects/...`). They are private and cannot be resumed under another account. The task summaries above are the portable context; the actual Claude processes do not transfer.
- `dt_scripts/` and `dt_src/` in the main checkout are an unrelated project (agriculture digital twin), not part of this save point.
