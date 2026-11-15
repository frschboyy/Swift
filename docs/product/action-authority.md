# Action authority: what an action needs before Swift does it

**Status:** adopted 2026-11-15 (the owner accepted the split); `CLAUDE.md` links here.

The model the owner accepted on 2026-11-15 ([`foundation-rules-review.md`](../explorations/foundation-rules-review.md)
§4 and §7, decisions 1 to 14). This file is the full statement; `CLAUDE.md` keeps the table and the hard lines.

A path that breaks one of these rules is a critical bug, and a fix to one is reviewed by someone other than its
author.

## 1. The inputs

What an action needs follows from four things Swift knows: how reversible it is, who it reaches, how the owner
answered, and whether the owner is there. Swift decides reversibility and reach, never the agent. A fifth input,
origin, decides what an action may use.

1. **Channel**, how the approval or request arrived:
   - **gesture**: a click on Swift's own button, the same button pressed from the keyboard *(foundation decision 2)*, or speech
     with the hotkey held *(foundation decision 3)*;
   - **named voice**: the open microphone with Swift's name ("Swift, yes");
   - **plain voice**: the open microphone without the name;
   - **typed words**: text in the box, with or without the name. The name adds nothing for typing.
2. **Presence**: the owner is here (unlocked, not away, listening not paused), the thing is on screen and in front,
   and it wasn't heard over Swift's own voice. A click needs no on-screen check: it was on the thing.
3. **Reversibility**, decided by Swift: read; reversible (has an undo); disruptive (the owner loses something until
   they put it back: Wi-Fi off); irreversible (deleting permanently, sending, paying, publishing, pushing, running
   code, typing into a terminal).
4. **Reach**: only the owner's PC; someone else (send, invite, publish, share); money; the owner's accounts.
5. **Origin** of what the action uses (a recipient, an address, a path, a fact): the owner's words, an approved
   card, or a worker's reading (the agent's text, a page, a tool's output, an option the agent wrote).

## 2. The levels

| Level | When | What Swift does | What approves |
|---|---|---|---|
| 0. Do it | a read; or reversible, on the owner's PC only, and the owner's words asked | acts; "undo that" works | nothing needed |
| 1. Ask once | disruptive on the owner's PC only (Wi-Fi off); or the owner's words don't clearly ask (an address they gave earlier, writing into an app); or Swift's own question about the owner's request | one short question on screen | a gesture, Swift's name, or a plain spoken "yes" while it's on screen; saying the same request again, spoken |
| 2. Card | what a worker chose to do on the owner's PC (commands, file edits, reads outside the read folders); moving a file to the Recycle Bin | a card saying what and why; one step or plan card may cover several | a gesture, or Swift's name |
| 3. Its own card | irreversible (deleting permanently, sending, publishing, pushing, running code, typing into a terminal), reaching anyone else, or the owner's accounts | its own card, never covered by a step card, a plan, a learned trust or a setting | a gesture, or Swift's name; **paying: a gesture only** *(foundation decision 9)* |

## 3. The rules across every level

- **A gesture** is a click on Swift's own button, the same button pressed from the keyboard *(foundation decision 2)*, or speech
  with the hotkey held *(foundation decision 3)*.
- **Typed words never approve**, at any level, with or without Swift's name *(foundation decision 1)*.
- **Nothing approves unless the owner is present** (unlocked, not away, listening not paused) **and the thing is on
  screen and in front**, and nothing heard over Swift's own voice is a yes. A click needs no check: it was on the
  thing.
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
- **An approval covers exactly what its card showed.** For Swift's own actions the gateway binds it to the action's digest and recomputes it
  before running: a changed recipient, path, command or payload voids it, and an approval is never reused for
  another action (ADR-010, threat model T3). Enforcement lives in the backend, never in the agent or the overlay.
- **No hands-free listening while locked, away or paused.**

## 4. Where the code enforces it

From [`docs/architecture/ownership.md`](../architecture/ownership.md) §1, §5 to §8 and §12.

| Rule | Owner in code | Second owners (findings) |
|---|---|---|
| Who approves, from where | `intake.approves` (`APPROVES` is the table in §2; `test_intake.py` and `test_one_decider.py`) | none (OWN-01 to OWN-03 fixed); the hotkey can't answer Swift's question (FD-01) |
| On screen and in front | `drawn.Drawn` (what the overlay drew), `attention.set_seen` | `session._on_screen` for questions (OWN-04) |
| An approval covers what its card showed | `security/gateway.ActionGateway.execute` (digest recomputed, `changed_after_approval`) | worker tool cards in `executors/claude_code` (OWN-05) |
| Reversibility of commands | `executors/step_grant.reversible`, `base.Grant.covers` | — |
| Recipients | `workflows/tools.find_contact`, and `draft_email` for an address in the owner's words → `RunScope.resolved`; the gateway checks it | — |
| Web addresses | `security/web_scope.WebScope`; `desktop_tools._open_url` and `_offer` (Swift's question) | fetching takes tool-result addresses too (OWN-06, partial) |
| Reads | `executors/read_scope.ReadScope` | — |
| Memory | `memory.Store.write` (`said` text must be in the owner's words; `approved` needs a card) | — |
| Presence | `presence`, `intake` step 1 | about four checks in `session` (RV-15) |

## 5. Not built yet (2026-11-15)

The rules above are the target; until each decision's code is merged, the code may differ. A change must move the
code toward these rules, never away.

- **1, 3, 10:** built (typed never approves; the hotkey held is a gesture; `intake.approves` is the one decider).
  Their owner checks are not run yet. The correction offer is level 1, so a plain spoken "yes" takes it while it's
  on screen (owner, 2026-11-15). Open: the hint leaves out "press Enter on Yes" until decision 2 is built.
  Speech with the hotkey held can't answer Swift's own question yet (FD-01).
- **2:** no keyboard Tab and Enter on the card's own button yet.
- **4:** built on `claude/elegant-shtern-2e16f9`, not merged: an address not in this request's words is asked about
  ("Open usiu.ac.ke?", level 1, typing never answers it), offering only the owner's own earlier or remembered
  addresses; `points_back` is deleted (FD-02). A remembered address is now asked about too (stricter than before).
  Owner check 330 rewritten, with 370 and 371; not run.
- **5:** built on the same branch, not merged: an address the owner said or typed in this request can be a
  recipient, marked "(from your words, not in your contacts)" on the send card (FD-03). Not built: offering to save
  it as a contact; calendar invites still take only contacts. Owner check elegant-shtern-2e16f9-1; not run.
- **6:** built on the same branch, not merged: a write into an app (or filling in an email) the owner's words
  didn't clearly ask for is asked about with a preview, level 1 (FD-04). Still a pattern: `owner_asked_to_write`
  decides between level 0 and 1, so its false matches write with no question (D4). Owner check
  elegant-shtern-2e16f9-2; not run.
- **8:** `swift.log` has no reason codes for connector failures yet.
- **7, 9:** apply when the W2 file tools and paying (C2) are built.
- Found by the ownership map, not in the decisions: worker tool cards aren't bound to a digest (OWN-05).

## 6. Where the model is stricter and looser than before

See [`foundation-rules-review.md`](../explorations/foundation-rules-review.md) §4, "Where the model is stricter,
looser, and why". In short: stricter on typed approvals, money and terminals; looser on recipients and addresses the
owner gave, and on unclear writes (a question instead of a refusal).
