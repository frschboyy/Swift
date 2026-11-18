# Proposal: a slimmer `CLAUDE.md`, with its detail in its own documents (for the owner to decide)

**Proposed 2026-11-15, after an outside review of `CLAUDE.md`.** `CLAUDE.md` itself isn't edited. If the owner
agrees, the new text in §3 replaces it and the drafts below lose their "draft" line.

## 1. Why

The outside review said `CLAUDE.md` does too many jobs, needs a component ownership map, needs a privacy policy and
a testing hierarchy, and must keep specified, implemented and verified apart. Today the one file is the entry point,
the full approval model, the work-in-progress list, the owner-check procedure, the fixing rules and the command
reference, at 161 lines. Detail that changes weekly (what's not built, commands) sits beside rules that must never
weaken.

## 2. What goes where

| Document | Holds | Status |
|---|---|---|
| `CLAUDE.md` | the principle, the hard limits, the product rules and the approval table (all kept word for word), how to work, where to look | proposed in §3 |
| [`docs/product/action-authority.md`](../../product/action-authority.md) | the full approval model: inputs, levels, rules across levels, where code enforces each, what isn't built | drafted |
| [`docs/engineering/reliability.md`](../../engineering/reliability.md) | specified vs implemented vs verified, how to fix, scope and ownership, the findings register | drafted |
| [`docs/testing/strategy.md`](../../testing/strategy.md) | the layers (unit, integration, seam, overlay and Rust, evaluation gates, owner acceptance, structure), which layers each change needs, the commands, owner checks | drafted |
| [`docs/security/privacy.md`](../../security/privacy.md) | what stays, what's sent, retention, deletion, tokens, scopes, reports | drafted (part 2) |
| [`docs/architecture/ownership.md`](../../architecture/ownership.md) | the one owner of each responsibility, and the second owners found | drafted (part 1) |

**What stays in `CLAUDE.md` and why:** anything whose breaking is a critical bug stays word for word, because
`CLAUDE.md` is the one file every session is sure to load. Only explanation, procedure and fast-changing lists move.
Moving the product rules out would make them easier to miss, which is a weakening.

## 3. The proposed `CLAUDE.md`, in full

```markdown
# Swift: notes for Claude Code

Swift is a voice-first Windows assistant: a Python asyncio backend in `src/swift`, Claude Code through claude-agent-sdk, and a Tauri v2 overlay in `overlay/` (Rust in `src-tauri`, TypeScript in `src`). The owner is Francis.

**Start with [`docs/handoff/README.md`](docs/handoff/README.md).** It has the current state, work in progress, the owner checks to run, the agreed order, and the open decisions.

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
- **An approval covers exactly what its card showed.** The gateway binds it to the action's digest and recomputes it
  before running: a changed recipient, path, command or payload voids it, and an approval is never reused for
  another action (ADR-010, threat model T3). Enforcement lives in the backend, never in the agent or the overlay.
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
isn't built yet: [`docs/product/action-authority.md`](docs/product/action-authority.md) §5 (decisions 1-10) and
[`docs/testing/strategy.md`](docs/testing/strategy.md) §4 (decisions 11-12).

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
```

That is 107 lines against 161, and every product-rule and hard-limit line is still there.

## 4. Line-by-line map, old to new

Line numbers are `CLAUDE.md` at `55a4886`. "Verbatim" means the same words; "moved" means the same words in the
named document, checked by the script in §5.

| Old lines | What | New place | Change |
|---|---|---|---|
| 1-7 | title, what Swift is, start with the handoff, principle | `CLAUDE.md` top | verbatim |
| 9 | `## Rules` | `## Hard limits` | heading renamed |
| 11-16 | Git | `CLAUDE.md` Hard limits | verbatim |
| 17-20 | credentials, sign-in command | `CLAUDE.md` Hard limits | verbatim |
| 21 | no real-world actions to test | `CLAUDE.md` Hard limits; also `strategy.md` §3 | verbatim |
| 22 | port 1420 | `CLAUDE.md` Hard limits; also `strategy.md` §3 | verbatim |
| 24 | `### Product rules` | `## Product rules` | heading level |
| 26 | critical bug, other-author review | `CLAUDE.md` Product rules; also `action-authority.md` intro | verbatim; a pointer line added after it |
| 28-29 | what an action needs | `CLAUDE.md`; also `action-authority.md` §1 | verbatim |
| 31-36 | the level table | `CLAUDE.md`; also `action-authority.md` §2 | verbatim |
| 38-60 | gesture, typed, presence, worker reading, recipients, addresses, memory, delete, trust, `intake.approves`, digest binding, locked | `CLAUDE.md`; also `action-authority.md` §3 | verbatim |
| 61-63 | logs | `CLAUDE.md`; also `privacy.md` §4 | verbatim |
| 64-65 | Swift speaks as itself | `CLAUDE.md` | verbatim |
| 66 | audio never leaves the PC | `CLAUDE.md` | verbatim; a pointer to `privacy.md` appended |
| 68-71 | Code | `CLAUDE.md` How to work (one line); also `reliability.md` §4 | same words joined in one bullet |
| 73-84 | owner checks procedure | `strategy.md` §4 | moved verbatim; `CLAUDE.md` keeps "owner checks for new behaviour" under Testing |
| 86-88 | live roadmap | `CLAUDE.md` Where to look; also `strategy.md` §4 | verbatim, "Unchanged:" dropped |
| 90-94 | foundation decisions being built, "move toward, never away" | `CLAUDE.md` Product rules, last paragraph | verbatim, with pointers to where the list now is |
| 96-102, 105 | not built: decisions 1-10 | `action-authority.md` §5 | moved verbatim |
| 103-104 | not built: decisions 11-12 | `strategy.md` §4 | moved verbatim |
| 107-119 | How to work | `CLAUDE.md` How to work; also `reliability.md` §1, §2, §4 | verbatim; ownership-map pointer appended to line 118-119 |
| 121-123 | Fixing things, sources | `reliability.md` header | moved |
| 125-132 | the eight fixing rules | `reliability.md` §3 | moved verbatim; `CLAUDE.md` keeps each by name in one bullet |
| 134-141 | Python tests command | `CLAUDE.md` Where to look (command); `strategy.md` §3 (all of it) | command verbatim |
| 142-159 | parity, speech gate, overlay, Rust, dev harness | `strategy.md` §3 | moved verbatim |
| 160 | owner's logs | `strategy.md` §3 | moved verbatim |
| 161 | edits in the main checkout | `CLAUDE.md` Hard limits | verbatim, moved up (it limits what a session may do) |

**Nothing weakened, checked rule by rule:** every line in 11-66 (hard limits and product rules) is word for word in
the new `CLAUDE.md`. The only product-rule-adjacent text that leaves `CLAUDE.md` is the not-built list (96-105),
which isn't a rule but the code's distance from one; the rule that governs it ("A change must move the code toward
these rules, never away", 93-94) stays.

**What's lost from `CLAUDE.md`'s own text:** the eight fixing rules become names in one line, so their one-sentence
explanations need the click to `reliability.md`. The commands other than Python tests need the click to
`strategy.md`. If the owner wants the fixing rules whole in `CLAUDE.md`, that adds 8 lines and changes nothing else.

## 5. How the move was checked

Every non-empty line of `CLAUDE.md` at `55a4886` was looked for, whitespace-normalised, in the proposed `CLAUDE.md`
(§3) and the drafted documents. Script (run from the worktree root):

```bash
PYTHONPATH=src /c/Users/frchi/Documents/Swift/.venv/Scripts/python.exe - <<'EOF'
import re, pathlib
norm = lambda s: re.sub(r"\s+", " ", s).strip()
old = [l for l in pathlib.Path("CLAUDE.md").read_text(encoding="utf-8").splitlines() if norm(l)]
new = " ".join(norm(pathlib.Path(p).read_text(encoding="utf-8")) for p in [
    "docs/explorations/claude-md-split.md", "docs/product/action-authority.md",
    "docs/engineering/reliability.md", "docs/testing/strategy.md"])
missing = [l for l in old if norm(l) not in new]
print(len(old), "lines,", len(missing), "not found word for word:")
print("\n".join(missing))
EOF
```

Result at `55a4886`: 134 lines, 6 not found word for word, all of them changes the map names: two headings
(`### While the foundation decisions are being built`, `## Commands`), the fixing rules' source line (now
`reliability.md`'s header), "Unchanged:" before the roadmap line, "Not built yet:" (now pointers), and "No new
dependencies" (joined into one bullet with the `session.py` line). Other old headings are found only because this
file quotes them. A second check looks for old lines 11-66 (hard limits and product rules) in the proposed
`CLAUDE.md` block alone: all are there except the heading `### Product rules`, now `## Product rules`.

## 6. For the owner

1. Accept the split as proposed, or keep the fixing rules whole in `CLAUDE.md` (§4, last paragraph).
2. On acceptance: replace `CLAUDE.md` with §3, drop the "draft" line from the four documents, and from then on a
   change to the approval model edits `action-authority.md` and, if the table or a hard line changes, `CLAUDE.md` in
   the same commit.
