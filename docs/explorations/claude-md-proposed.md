# Proposed rewrite of `CLAUDE.md`'s rules (for the owner to decide)

This replaces the **Rules** section of `CLAUDE.md` only, if the owner agrees. It assumes the recommendations in
[`foundation-rules-review.md`](foundation-rules-review.md) §7; a line that depends on one names it as *(decision N)*.
"Fixing things" stays as it is. "Commands" changes only where decision 14 says. `CLAUDE.md` itself isn't edited.

---

## Rules

- **Git:**
  - Work on a branch in a worktree; commit there only. If git has no identity on this PC, commit with
    `git -c user.name="Francis Chianu" -c user.email=<the email on main's recent commits>` *(decision 14)*.
  - **Never push.** To move work to another PC, make a `git bundle` of the named branches when the owner asks
    *(decision 13)*. Merge into `main` only when the owner says so.
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
| 3. Its own card | irreversible (deleting permanently, sending, publishing, pushing, running code, typing into a terminal), reaching anyone else, or the owner's accounts | its own card, never covered by a step card, a plan, a learned trust or a setting | a gesture, or Swift's name; **paying: a gesture only** *(decision 9)* |

- **A gesture** is a click on Swift's own button, the same button pressed from the keyboard *(decision 2)*, or speech
  with the hotkey held *(decision 3)*.
- **Typed words never approve**, at any level, with or without Swift's name *(decision 1)*.
- **Nothing approves unless the owner is present** (unlocked, not away, listening not paused) **and the thing is on
  screen and in front**, and nothing heard over Swift's own voice is a yes. A click needs no check: it was on the thing.
- **What a worker read never acts by itself.** The agent's text, a page, a tool's output or an option the agent wrote
  never chooses a recipient, a web address, a path to delete, a memory or a trust. Shown on a card, marked as the
  worker's, and approved by the owner, it may be used.
  - Recipients come from contacts, `find_contact`, or an address in the owner's own words, marked on the send card
    *(decision 5)*.
  - A web address comes from the owner's words in this request, or Swift asks "Open (their earlier address)?"
    *(decision 4)*.
  - Memory is written only from the owner's words or an approved card.
- **Deleting a file always asks.** A move to the Recycle Bin is level 2; a permanent delete, emptying the bin, or a
  recycle Swift can't confirm is level 3 (ADR-019) *(decision 7)*.
- **Learned trust** lowers one kind from level 1 to 0 (only kinds on its table, never level 3). **"Ask me about
  everything"** raises level 0 to 1, except reads in the read folders and volume.
- **`intake.approves` is the one place approval is decided**, and its test checks it against the table above
  *(decision 10)*. Change both together.
- **No hands-free listening while locked, away or paused.**
- **Logs:** `swift.log` holds no content (the owner's words, names, addresses, file contents) but does hold
  structure (reason codes, error classes, field roles, timings). The owner's local interaction log keeps their words
  and answers *(decision 8)*.
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
  `main` *(decision 11)*;
- when the owner pastes a report, save it to a file and record it with `--record FILE`; what they tell you they saw
  goes in with `--set 216=pass 217=fail --note "…"`;
- after recording, and after every merge, run it with `--write`. The status file is generated and never merged by
  hand (`merge=ours`) *(decision 12)*.

### The live roadmap

Unchanged: `docs/handoff/roadmap.md`, written to `ROADMAP.md` by `spikes/owner_checks/roadmap.py`.

---

**Commands, from a worktree on this PC** *(decision 14)*: run Python as
`PYTHONPATH=src /c/Users/frchi/Documents/Swift/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` (and the
same interpreter for `eval/parity/score.py` and `eval/stt/gate.py`), since `uv run` hangs in worktrees here. The
other commands stay as they are.
