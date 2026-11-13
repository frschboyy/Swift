# Save point, 2026-11-13 16:27: resuming on the other computer

Read `docs/handoff/README.md` and `docs/handoff/workstreams.md` first (both on this branch, which is built on `claude/workstreams`).

## What was running

Seven sessions were still running when the credits ran out. They were all started from the session "Roadmap and owner checks", and each one has its own branch from `claude/workstreams` (`5bd9e61`). Uncommitted work is on `savepoint/<name>`: one WIP commit on top of the session's branch, unreviewed and possibly failing.

| Session (rerun it) | Branch | WIP | State at 16:27 |
|---|---|---|---|
| A2: a question shown as "Working on it" (also A3, the spinner that doesn't turn) | `claude/a2-question-state-42bf6d` | `savepoint/a2-question-state-42bf6d` | Replaying the lunch question in the dev harness; `session.py` and a seam scenario edited. **Revert its `.claude/launch.json` edit** (a temporary harness entry) |
| A4–A6: cards vanish unseen; stack restore | `claude/a4-card-lifecycle-f50a7b` | `savepoint/a4-card-lifecycle-f50a7b` | The A4 seam scenario's assertions pass; one test request doesn't wind down at cleanup, which it was debugging |
| A7: one ask becomes two requests | `claude/a7-duplicates-54bd6a` | `savepoint/a7-duplicates-54bd6a` | Edits under way; it was writing the seam scenario |
| A9: Gmail writes only with the cursor in the body | `claude/a9-gmail-focus-03dda1` | `savepoint/a9-gmail-focus-03dda1` | New `desktop/gmail_fill.py` plus its tests (14 pass); it was splitting the work into one-finding commits, starting with the logging |
| A10 + C3: Swift behind Task Manager; opening a website | `claude/a10-front-and-web-9f8dcd` | `savepoint/a10-front-and-web-9f8dcd` | Two commits (`c5a3cad`, `6bd3666`: web addresses) plus uncommitted `desktop_tools.py` edits; A10 not known to be done |
| C1: never answer with a location Swift doesn't have | `claude/c1-grounded-facts-556f60` | `savepoint/c1-grounded-facts-556f60` | Agent instruction and tests edited, owner check added to `owner-checks.md`, the ledger and `report.py` |
| Labelling card for misheard clips (worked from the main checkout; also looking at the 10:05 run's gaps) | none yet (`claude/run-1005-gaps` is merged and clean) | none | Was reproducing the 10:05 run's issues from the code. **The 10:05 run's logs are on the other computer** |

Owner check numbers 244–261 were split between the six A/C sessions. `plan.py` prints the next free number.

Not finished in "Roadmap and owner checks": merging `claude/workstreams` (A8 music fix `41a1773`, A1b `1429e81`, check 262) waits for the owner's OK. `main` was 7 commits ahead of `origin/main`.

## Push (this computer)

Run `bash docs/handoff/savepoint.sh` again just before pushing, so the WIP is current. It prints the full push command. At 16:27 it was:

```bash
git push origin main claude/workstreams claude/savepoint-2026-11-13 claude/a2-question-state-42bf6d claude/a4-card-lifecycle-f50a7b claude/a7-duplicates-54bd6a claude/a9-gmail-focus-03dda1 claude/a10-front-and-web-9f8dcd claude/c1-grounded-facts-556f60 savepoint/a2-question-state-42bf6d savepoint/a4-card-lifecycle-f50a7b savepoint/a7-duplicates-54bd6a savepoint/a9-gmail-focus-03dda1 savepoint/a10-front-and-web-9f8dcd savepoint/c1-grounded-facts-556f60
```

## Resume (other computer)

```bash
git fetch origin && git checkout main && git merge --ff-only origin/main
```

For each row, recreate the worktree and put the WIP back as uncommitted changes:

```bash
git worktree add .claude/worktrees/<name> claude/<name>
git -C .claude/worktrees/<name> restore --source=origin/savepoint/<name> -- .
```

Then start a session in that worktree with: *"Resume the session '<title>' from docs/handoff/savepoint-2026-11-13.md. Its uncommitted changes are restored here. Re-run the tests, finish the item as described in workstreams.md, and commit following CLAUDE.md."*

## Not in git, on purpose

- **Swift's logs, clips and interaction log** (`%LOCALAPPDATA%\Swift`). They hold transcripts and audio, which must stay off GitHub (product rule: audio never leaves the PC). Each computer keeps its own. Copy them by USB if a session needs the other computer's run.
- **Claude transcripts** (`~/.claude/projects/...`). They're private and can't be resumed under another account. The table above is the summary to resume from.
- `dt_scripts/` and `dt_src/` in the main checkout are an unrelated project (agriculture digital twin), not part of this save point.
