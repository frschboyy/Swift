# Swift: notes for Claude Code

Swift is a voice-first Windows assistant: a Python asyncio backend in `src/swift`, Claude Code through claude-agent-sdk, and a Tauri v2 overlay in `overlay/` (Rust in `src-tauri`, TypeScript in `src`). The owner is Francis.

**Start with [`docs/handoff/README.md`](docs/handoff/README.md).** It has the current state, work in progress, the owner checks to run, the agreed order, and the open decisions.

Owner's principle: **"Swift adapts to the user, not the user to Swift."**

## Rules

- **Git:**
  - Work on a branch in a worktree; commit there only. If git has no identity on this PC, commit with
    `git -c user.name=... -c user.email=...` with the identity from `git log -1 --format="%an <%ae>" main` (never guessed) *(foundation decision 14)*.
  - **Never push.** To move work to another PC, make a `git bundle` of the named branches when the owner asks
    *(foundation decision 13)*. Merge into `main` only when the owner says so.
  - End commit messages with a `Co-Authored-By:` line.
- **Never enter credentials or sign in for the owner.** Google sign-in is owner-run:
  ```bash
  uv run --group spikes python -m swift.connectors.gmail signin
  ```
- **No real-world actions to test** (emails, calendar, Wi-Fi, locking, deleting). Use the fakes, debug mode and the dev harness.
- **Port 1420 is the owner's running Swift.** Never start a dev server on it; the harness uses 1431.

### Product rules

A path that breaks one is a critical bug, and a fix to one is reviewed by someone other than its author.

**What an action needs** follows from four things Swift knows: how reversible it is, who it reaches, how the owner
answered, and whether the owner is there. Swift decides reversibility and reach, never the agent.

| Level | When | What Swift does | What approves |
|---|---|---|---|
| 0. Do it | a read; or reversible, on the owner's PC only, and the owner's words asked | acts; "undo that" works | nothing needed |
| 1. Ask once | disruptive on the owner's PC only (Wi-Fi off); or the owner's words don't clearly ask (an address they gave earlier, writing into an app); or Swift's own question about the owner's request | one short question on screen | a gesture, Swift's name, or a plain spoken "yes" while it's on screen; saying the same request again, spoken |
| 2. Card | what a worker chose to do on the owner's PC (commands, file edits, reads outside the read folders); moving a file to the Recycle Bin | a card saying what and why; one step or plan card may cover several | a gesture, or Swift's name |
| 3. Its own card | irreversible (deleting permanently, sending, publishing, pushing, running code, typing into a terminal), reaching anyone else, or the owner's accounts | its own card, never covered by a step card, a plan, a learned trust or a setting | a gesture, or Swift's name; **paying: a gesture only** *(foundation decision 9)* |

- **A gesture** is a click on Swift's own button, the same button pressed from the keyboard *(foundation decision 2)*, or speech
  with the hotkey held *(foundation decision 3)*.
- **Typed words never approve**, at any level, with or without Swift's name *(foundation decision 1)*.
- **Nothing approves unless the owner is present** (unlocked, not away, listening not paused) **and the thing is on
  screen and in front**, and nothing heard over Swift's own voice is a yes. A click needs no check: it was on the thing.
- **What a worker read never acts by itself.** The agent's text, a page, a tool's output or an option the agent wrote
  never chooses a recipient, a web address, a path to delete, a memory or a trust. Shown on a card, marked as the
  worker's, and approved by the owner, it may be used.
  - Recipients come from contacts, `find_contact`, or an address in the owner's own words, marked on the send card
    *(foundation decision 5)*.
  - A web address comes from the owner's words in this request, or Swift asks "Open (their earlier address)?"
    *(foundation decision 4)*.
  - Memory is written only from the owner's words or an approved card.
- **Deleting a file always asks.** A move to the Recycle Bin is level 2; a permanent delete, emptying the bin, or a
  recycle Swift can't confirm is level 3 (ADR-019) *(foundation decision 7)*.
- **Learned trust** lowers one kind from level 1 to 0 (only kinds on its table, never level 3). **"Ask me about
  everything"** raises level 0 to 1, except reads in the read folders and volume.
- **`intake.approves` is the one place approval is decided**, and its test checks it against the table above
  *(foundation decision 10)*. Change both together.
- **An approval covers exactly what its card showed.** The gateway binds it to the action's digest and recomputes it
  before running: a changed recipient, path, command or payload voids it, and an approval is never reused for
  another action (ADR-010, threat model T3). Enforcement lives in the backend, never in the agent or the overlay.
- **No hands-free listening while locked, away or paused.**
- **Logs:** `swift.log` holds no content (the owner's words, names, addresses, file contents) but does hold
  structure (reason codes, error classes, field roles, timings). The owner's local interaction log keeps their words
  and answers *(foundation decision 8)*.
- **Swift speaks as itself.** Status, cards and speech never name the provider ("Claude Code is…"); setup errors and
  the settings that choose one may.
- **Audio never leaves the PC.** A request's words go to the model that answers it; recordings don't.

### Code

- `session.py` is large: add small modules with narrow interfaces.
- No new dependencies without a clear need.

### Owner checks

New behaviour gets checks in `docs/testing/owner-checks.md`, report lines in `spikes/owner_checks/report.py`, and the
code each check proves in `docs/testing/owner-checks-ledger.yaml` (`test_owner_plan.py` fails without it).
`spikes/owner_checks/plan.py` keeps the run list and status in `owner-checks-status.md`:

- on a branch, give a new check a provisional id, `<branch>-<n>`; `plan.py --renumber` numbers it when it merges into
  `main` *(foundation decision 11)*;
- when the owner pastes a report, save it to a file and record it with `--record FILE`; what they tell you they saw
  goes in with `--set 216=pass 217=fail --note "…"`;
- after recording, and after every merge, run it with `--write`. The status file is generated and never merged by
  hand (`merge=ours`) *(foundation decision 12)*.

### The live roadmap

Unchanged: `docs/handoff/roadmap.md`, written to `ROADMAP.md` by `spikes/owner_checks/roadmap.py`.

### While the foundation decisions are being built (2026-11-15)

The owner accepted all 14 decisions in `docs/explorations/foundation-rules-review.md` §7 on 2026-11-15. The rules
above are the target; until each decision's code is merged, the code may differ. A change must move the code toward
these rules, never away. Not built yet:

- **1, 3, 10:** `intake.approves` still lets a typed "Swift, yes" answer Swift's reversible question (HA-HEAR-01's
  strict xfail), and three places still decide approval outside it (`_fix_refused`, `restated.py`, the hands-free fix
  offer).
- **2:** no keyboard Tab and Enter on the card's own button yet.
- **4, 5, 6:** web addresses still go through `owner_address.points_back`; recipients still only from contacts and
  `find_contact`; an unclear write into an app is still refused, not asked about.
- **8:** `swift.log` has no reason codes for connector failures yet.
- **11, 12:** check numbers are still whole numbers taken from "Next free check number", and the run list is still
  generated between markers in `docs/testing/owner-checks.md` (by `plan.py --write`).
- **7, 9:** apply when the W2 file tools and paying (C2) are built.

## How to work

- **Specified, implemented, verified are three different claims.** A rule in this file is specified; it's
  implemented only when the code and a test show it; it's verified only when its owner check has passed on the real
  PC. Never describe behaviour from this file alone: read the code and its tests. Never change a rule to fit what the
  code happens to do; say where they differ.
- **Understand, then prove, then change:** read the handoff and the code a change touches, reproduce the problem,
  name the cause (or say "unproven"), make the smallest change that fixes it, verify the original case, and report
  what was and wasn't verified.
- **Stay in scope.** A problem found on the way is recorded (in `docs/audit/findings.yaml` or the report) and fixed
  separately, unless it blocks the task.
- **Respect the owners.** Before adding logic, find the code that already owns that responsibility and change it
  there; two owners of one thing is a bug.

## Fixing things

Rules from the reliability audit and its review (`docs/audit/2026-11-reliability-audit.md`, `docs/audit/2026-11-reliability-audit-review.md`):

- **Prove the cause first.** Reproduce it where it happens before naming a cause. Say "unproven" when it is.
- **One finding per commit.**
- **Label the fix in its commit message:** root, partial, safeguard, workaround or symptom. A workaround names what would replace it.
- **Screen fixes need the seam.** A fix to what's on screen isn't done until it has a scenario in `tests/unit/test_seam_replay.py`, which fails with the fix undone.
- **Product rules:** someone other than the author reviews a fix to one, unless the owner waives it.
- **Big claims need a test.** A commit that claims "one owner of X" names the test that would fail if there were two.
- **Structural steps delete code.** Prototype on a branch and keep it only if it removes more than it adds.
- **Confidence bars:** score any change to one on the owner's saved clips.

## Commands (Windows; from a worktree)

- **Python tests:** from a worktree on this PC (`uv run` hangs building a worktree venv), use the main checkout's
  interpreter; where `uv` works, `uv run --frozen pytest -q -p no:cacheprovider` is the same:
  ```bash
  PYTHONPATH=src /c/Users/frchi/Documents/Swift/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
  ```
  Use the same interpreter (`PYTHONPATH=src … python.exe`) for `eval/parity/score.py` and `eval/stt/gate.py` below.
- **Routing parity** (must not drop):
  ```bash
  uv run python eval/parity/score.py
  ```
- **Speech gate** (before and after any change to speech recognition; no sentence that was right may go wrong):
  ```bash
  uv run python eval/stt/gate.py --data //localhost/c$/Users/frchi/AppData/Local/Swift
  ```
- **Overlay:** in `overlay/`, run `npx --no-install tsc --noEmit` and `npm test`. A worktree has no `node_modules`; link it temporarily and remove the link afterwards:
  ```powershell
  New-Item -ItemType Junction -Path <worktree>\overlay\node_modules -Target C:\Users\frchi\Documents\Swift\overlay\node_modules
  ```
- **Rust:** `cargo test` in `overlay/src-tauri`, using the worktree's own `target` (a long target path breaks Windows linking).
- **Dev harness:**
  - Add a temporary `.claude/launch.json` entry running `npm --prefix overlay exec -- vite overlay --port 1431 --strictPort`, plus the existing `backend-harness` entry (debug backend on 8765).
  - Open `http://localhost:1431/dev/harness.html?port=8765&token=devharness-token-0123456789abcdef`.
  - Drive states with `window.__shim.inject(type, data)`; the `Agent` shape is `{id, name}`.
  - Revert `launch.json` afterwards.
- **Owner's logs:** `C:\Users\frchi\AppData\Local\Swift\logs\swift.log`. From a worktree, read them at `//localhost/c$/Users/frchi/AppData/Local/Swift/logs/swift.log`.
- **Edits in the owner's main checkout:** an edit hook blocks the Edit tool there. Make changes in a worktree, then fast-forward `main` (`git merge --ff-only`) when the owner approves a merge.
