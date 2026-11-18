# Swift: notes for Claude Code

Swift is a voice-first Windows assistant: a Python asyncio backend in `src/swift`, Claude Code through claude-agent-sdk, and a Tauri v2 overlay in `overlay/` (Rust in `src-tauri`, TypeScript in `src`). The owner is Francis.

**Start with [`docs/handoff/README.md`](docs/handoff/README.md).** It has the current state, work in progress, the owner checks to run, the agreed order, and the open decisions. The map of every other document is [`docs/README.md`](docs/README.md).

Owner's principle: **"Swift adapts to the user, not the user to Swift."**

## Hard limits

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
- **Edits in the owner's main checkout:** an edit hook blocks the Edit tool there. Make changes in a worktree, then fast-forward `main` (`git merge --ff-only`) when the owner approves a merge.

## Product rules

A path that breaks one is a critical bug, and a fix to one is reviewed by someone other than its author.
The full model, with where the code enforces each rule: [`docs/product/action-authority.md`](docs/product/action-authority.md).

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
- **An approval covers exactly what its card showed.** For Swift's own actions the gateway binds it to the action's
  digest and recomputes it before running: a changed recipient, path, command or payload voids it, and an approval
  is never reused for another action (ADR-010, threat model T3). A worker's tool card is bound the same way
  (`ActionGateway.bind` / `allow`, OWN-05): the digest is recomputed from the arguments handed back to run, one
  approval covers one call, and each is journalled; a step card binds each command it lists.
  Enforcement lives in the backend, never in the agent or the overlay.
- **No hands-free listening while locked, away or paused.**
- **Logs:** `swift.log` holds no content (the owner's words, names, addresses, file contents) but does hold
  structure (reason codes, error classes, field roles, timings). The owner's local interaction log keeps their words
  and answers *(foundation decision 8)*.
- **Swift speaks as itself.** Status, cards and speech never name the provider ("Claude Code is…"); setup errors and
  the settings that choose one may.
- **Audio never leaves the PC.** A request's words go to the model that answers it; recordings don't. What else is
  kept and sent: [`docs/security/privacy.md`](docs/security/privacy.md).

**While the foundation decisions are being built (2026-11-15):** The owner accepted all 14 decisions in
`docs/explorations/foundation-rules-review.md` §7 on 2026-11-15. The rules above are the target; until each
decision's code is merged, the code may differ. A change must move the code toward these rules, never away. What
isn't built yet: [`docs/product/action-authority.md`](docs/product/action-authority.md) §5 (decisions 7 and 9;
1-6, 8 and 10 are built, owner checks pending).
Owner checks (decisions 11-12, built): a new check on a branch gets `plan.py --next-id`'s `<branch>-<n>` id;
at merge, `plan.py --renumber` then `--write` ([`docs/testing/strategy.md`](docs/testing/strategy.md) §4).

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
  there; two owners of one thing is a bug. The map: [`docs/architecture/ownership.md`](docs/architecture/ownership.md).
- **Fixing things** follows [`docs/engineering/reliability.md`](docs/engineering/reliability.md) §3: prove the cause
  first; one finding per commit; label the fix (root, partial, safeguard, workaround or symptom); screen fixes need a
  seam scenario; another author reviews a product-rule fix; big claims need a test; structural steps delete code;
  confidence bars are scored on the owner's saved clips.
- **Testing** follows [`docs/testing/strategy.md`](docs/testing/strategy.md): which layers a change needs (a speech
  change needs the speech gate, a screen change a seam scenario, a routing change parity), the commands, and owner
  checks for new behaviour.
- `session.py` is large: add small modules with narrow interfaces. No new dependencies without a clear need.

## Where to look

- **Python tests** from a worktree on this PC (`uv run` hangs building a worktree venv):
  ```bash
  PYTHONPATH=src /c/Users/frchi/Documents/Swift/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
  ```
  Every other command (parity, speech gate, overlay, Rust, dev harness, the owner's logs): [`docs/testing/strategy.md`](docs/testing/strategy.md) §3.
- **State and plan:** [`docs/handoff/README.md`](docs/handoff/README.md); the live roadmap `docs/handoff/roadmap.md`, written to `ROADMAP.md` by `spikes/owner_checks/roadmap.py`.
- **Findings:** `docs/audit/findings.yaml`. **Threat model:** `docs/threat_model.md`. **Decisions:** `docs/decisions/`.
