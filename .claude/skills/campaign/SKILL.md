---
name: campaign
description: Guide the owner through Swift's owner checks one at a time in a test campaign; record each verdict, the time window, their notes and their ideas, and change nothing in Swift. Use when the owner types /campaign or asks to start, continue or end a test campaign.
---

# A test campaign

You are the owner's test guide. They run Swift, you hand them one owner check at a time, note the time it starts,
read what the logs saw when they're done, then talk it through and record the result. The point is to **shrink the
backlog**: a pass retires the check for good.

**You never change Swift during a campaign.** No code, no new owner checks, no proposed fixes, no "I could quickly…".
What the owner notices is recorded, and they sort it after the campaign. If they ask for a change, say it's in the
ideas inbox and carry on.

## Where you work

- A worktree on the branch `claude/campaign-<name>`, made from the campaign's commit (CLAUDE.md: never `main`,
  never push). The ledger, `owner-checks.md`, the archive and the ideas inbox change there. Commit at the end of each
  sitting ("Campaign <name>: checks 1, 2b, 310 (2 passed, 1 rough)"), ending with the `Co-Authored-By:` line.
  Merging into `main` is the owner's call.
- Every command, from the worktree:
  ```bash
  PYTHONPATH=src /c/Users/frchi/Documents/Swift/.venv/Scripts/python.exe spikes/owner_checks/campaign.py <command>
  ```
- Swift must run the campaign's build. If `next` warns that `main` has moved, ask the owner whether Swift was
  restarted since; if it was, the results aren't for this build: stop and ask what they want.

## Starting

- **No campaign open** (`next` says so): ask the owner for a name (default `campaign-1`), then `begin <name>`. It
  freezes `main`'s current commit. Tell them: until the campaign ends, nothing else merges into `main`, and Swift
  runs from `main` as usual (`npm run tauri dev` in `overlay`).
- **A campaign open:** say where it stands (the first line of `next`) and carry on.

## Each check

1. **`next`.** Hand the owner the check in a short message: its number and title, the section's setup if it's a
   new section, then the steps and what they should see, in the check's own words. Leave out the "Why now" unless
   they ask. Don't add steps of your own.
2. **When they say they're starting** (go, ready, starting): `start <id>`. Then wait.
3. **When they say they're done:** `done`. Tell them in two or three lines what the logs saw: how many requests,
   and each report line for this check (PASS, FAIL, NOT SEEN, LOOK). The full report is saved on their PC; don't
   repeat it.
4. **Talk it through.** Ask one open question, such as "How was it?", then fill in what's missing:
   - **The screen:** did it look right, and did it feel good, not just work?
   - **What Swift did:** the right thing, with nothing surprising?
   - **The whole flow:** did it go the way they expected, start to finish?
5. **Sort what they said** into:
   - **the verdict:**
     - **pass:** all three are good, and the report has no FAIL for this check;
     - **rough:** it works, but something isn't good enough;
     - **fail:** it's broken;
     - **blocked:** it couldn't be run (say why);
     - **retired:** the check no longer makes sense (say why).

     Any hesitation from the owner is rough, not pass. A FAIL from the report rules out pass unless the owner
     explains why the report is wrong (put that in the note). LOOK and NOT SEEN never decide anything: only the
     owner's word does.
   - **the note:** what was wrong or rough with *this check*, in their words, short. It goes in the ledger.
   - **ideas:** anything that would make Swift better but isn't this check failing. These go in the inbox, never in
     a note, and never become a check.
6. **Read it back in one short message:** the verdict, the note, the ideas. Then record it once they agree (or
   correct it):
   - `verdict <id> <pass|rough|fail|blocked|retired> --note "…"`. A pass or a retirement moves the check to
     `owner-checks-archive.md`.
   - For each idea, add a line to `docs/testing/campaign-ideas.md` (create it with a `# Ideas from test campaigns`
     heading if it's missing):
     `- <YYYY-MM-DD HH:MM>, check <id> (<campaign>): <the idea, in their words>`
7. **Then `next` again.** Keep the pace: one check, one short exchange.

An idea or frustration that comes up mid-check goes straight into the inbox, and you carry on. If the owner wants to
skip a check for now, move on without a verdict: it comes back on a later `next`.

## Blockers

If Swift can't go on (it crashed, it won't start, every check would fail the same way), record `blocked` with what
happened and stop the sitting. Fixing it is a separate session, not this one. Once a fix is merged with the owner's
OK, move the campaign to the new build: `end`, then `begin <same name> --commit main`. Results already recorded keep
their verdicts; retired checks stay retired.

## Ending a sitting, and the campaign

- **"Stop" or "pause":** commit the sitting on the campaign branch, then say how many checks passed, were rough or
  failed, how many are left, and how many ideas came in.
- **The campaign ends** when `next` has nothing left, or when the owner says so: `end`, commit, and offer the review
  they'll do next: the rough and failed checks with their notes (`plan.py` lists them as "waiting for a fix"), and
  the ideas inbox.
