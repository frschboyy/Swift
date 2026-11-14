# Save point, 2026-11-14 (afternoon): moving back to the other computer

Read `docs/handoff/README.md`, `docs/handoff/workstreams.md` and `CLAUDE.md` first. This replaces
`savepoint-2026-11-14.md` (the morning one).

## `main` now (`c9f3b2e`)

What was merged today on this PC, all with the owner's OK:

- **The flaky-test fix** (`84df075`). It was checked under load here: 50 of 50 passed on the branch, against 3 of 10 failing on `main`.
- **A7, check 204** (`dc549f9`): two causes, proven from this PC's logs.
  - The false start "can you set, can you turn off the Wi-Fi" now stays with Swift.
  - The owner's **A+B decision**: while Swift's own question is open, saying the same request again aloud is the yes. A near match asks again, a typed one never approves, and the opposite request is a request of its own.
  - `fbdaed2`'s premise (a greeting ending in a comma) was wrong.
- **A7 guard** (`d08f217`): the suspected "a request said while a question is open goes to the agent" gap was disproven. A replay now guards it.
- **Read scope** (`96520bc`): a never-read folder written as a volume ID is refused (it used to get a card), and a volume path that can't be resolved is refused instead of raising. The full suite on this PC is **2133 passed, 0 failed**.
- **The owner's verdicts:** 252 FAIL, 254 PASS (band data), 255 FAIL, recorded.

## Open branches (local to this PC until pushed)

| Branch | What | State | Next |
|---|---|---|---|
| `claude/halo-step-b-c7b584` | Halo Step B: one card renderer, net −35 lines, default look pixel-identical | Built and reviewed by its session | It must merge `main` and renumber its checks 303–304 to **305–306** (A7 took 303–304), then re-run overlay `tsc`/`npm test` and the full suite. Then the orchestrator reviews it and asks the owner to merge. Hand-over note: `docs/handoff/halo-step-b.md` on the branch, if it was copied before the switch |
| `claude/a10-uncovered-anchor-9b3922` | A10: when a higher-band window (Task Manager, band 16) covers the orb, the card shows at the nearest uncovered anchor | `cargo test` 36 pass; Python was running | Finish, merge `main`, checks **320–329**, then review |
| `claude/c3-recent-address-83f24a` | C3: an address the owner said or typed in the last 10 minutes of the conversation may open | Stopped at `b6830ea` (WIP), with `main` (`c9f3b2e`) merged in. Fix and tests in `27bcdbe`, docs in `52a5df9`. Check renumbered to **330**. 38 targeted tests pass | Run the full suite and routing parity on the branch, then the orchestrator's second review (product rule). Review notes: `notes-2026-11-14/c3-recent-address-review.md` |
| `claude/a9-gmail-252-e5d21c` | A9: Gmail compose not filled | Stopped at `a18e1fe`, clean, with `main` (`c9f3b2e`) merged in. Full suite 2137 passed, 0 failed. **Proven and fixed** (`f060c8b`, root): a compose that opens without the cursor in it shows To as a "Recipients" line with no To box. Swift now focuses that line (only when the subject is empty), which opens the To box; confirmed against the live window. Read-only probe: `spikes/desktop/gmail_fields.py`. Check **310** written | Orchestrator review, then merge with the owner's OK. Restart Swift and the owner runs check 310. **Not proven:** 12:24 (nothing found with Chrome in front) and 12:26 (behind; `SetForegroundWindow` failed). If 310 fails, run `uv run python spikes/desktop/gmail_fields.py` while the compose is open and paste it with the `gmail compose not filled` log line. For `gmail_behind`, try UIA `SetFocus` as a fallback in `bring_forward` |

The next free check number after these blocks is **340**.

## Proven today from this PC's logs

- **A9 (252):** in the 12:24, 12:26 and 12:30 runs, Swift gave up after about 20 s.
  - `not_loaded` twice: Chrome in front, and Gmail's fields found as none in one run and Subject + Body but no To in the other.
  - `gmail_behind` once: all three fields found, compose behind another window.
  - The fill worked 3 of 3 on 2026-10-27 and has failed every time since 2026-11-05.
  - Unproven guess: a compose opened without the cursor in it collapses the To row, so the "To recipients" box isn't there.
- **A10 (254):** `taskmgr.exe` is in band 16 (system tools) and Swift is in band 1. No ordinary app can come in front. The owner chose "move out from under it" (no signed UI-access install).
- **C3 (255):** step 1 opened usiu.ac.ke. In step 2 the agent offered that address, the owner said yes, and `_open_url` refused it, because it wasn't in that request. The owner chose "your recent words count" (above).

## The owner's decisions today (to record in `workstreams.md` if a branch hasn't)

- **A7:** A+B (above).
- **A10:** move out from under higher-band windows.
- **C3:** an address the owner said or typed in the last 10 minutes of the conversation may open. A yes to an address the agent made up never counts, and the agent asks for an address rather than offering one.
- **Halo Step B:**
  - ADR-019 §8's six look items come as the next branch, after Step B merges;
  - Halo becomes the default (deleting the old look) only after the owner has seen it on the real PC (checks 216–221);
  - deck edges and stack rows stay out of the renderer until B5.
- **Modes (a question, not decided):** the owner asked whether Swift should have modes like Claude's. The orchestrator's view:
  - no bypass, because the product rules forbid it;
  - instead, trust learned per kind of reversible action, offered on a card and undoable;
  - a plan card for long tasks, using B2's step approval;
  - one "ask me about everything" switch.
  - Suggested as a design study after Halo Step B, beside the memory follow-ups.

## Waiting on the owner

- The Gmail compose window for A9 (above).
- **Re-runs on the real PC, once their branches merge:** 252 (A9), the A10 check, 255 or C3's new check, 303/304 (A7), 305/306 (Halo).
- **Checks 216–221:** Halo on the real PC. They decide whether Halo becomes the default.

Session notes from today, which aren't in git otherwise, are copied to `docs/handoff/notes-2026-11-14/` on this branch. Halo's screenshots stayed on this PC.

## This PC's quirks (Francis-PC)

- `uv run` hangs building a new worktree `.venv`. Use the main checkout's venv: `PYTHONPATH=src /c/Users/frchi/Documents/Swift/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
- Git has no identity configured. Commits used `git -c user.name=... -c user.email=...` with the identity on `main`'s commits.
- Old worktree folders `.claude/worktrees/main-baseline` and `review-a7` may be left as empty folders that Windows wouldn't delete; git no longer tracks them.
- `.claude/stale-wip/`: patches of uncommitted edits from four archived 2026-11-13 worktrees. `main` has newer versions of all of them.

## Resume (other computer)

After the owner pushes the branches from this PC (they decide that; sessions never push):

```bash
git fetch origin
git checkout main
git merge --ff-only origin/main
```

Then start a session in the main checkout with: *"Resume as the orchestrator from docs/handoff/savepoint-2026-11-14b.md."*
