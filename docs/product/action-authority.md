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
- **Swift's guess.** When the owner's words don't match a command Swift knows, Swift may guess what they meant, and
  only ask: "Set a timer for 2 minutes?" (level 1, Swift's own question, showing every detail the yes will use).
  A guess is made only from a request the owner started (the hotkey, the wake phrase, or typing), never from what's
  heard while a question is open or in the follow-up window, never for a web address or locking the PC, and never
  for anything above level 1. Saying again the words Swift guessed from doesn't approve it; saying the action
  itself, in words Swift understands exactly, does. A guess never acts until it's approved, and nothing lowers it.
- **Deleting a file always asks.** A move to the Recycle Bin is level 2; a permanent delete, emptying the bin, or a
  recycle Swift can't confirm is level 3 (ADR-019) *(foundation decision 7)*.
- **Learned trust** lowers one kind from level 1 to 0 (only kinds on its table, never level 3, never Swift's guess). **"Ask me about
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
| On screen and in front | `drawn.Drawn` (what the overlay drew): `seen` for confirm cards (`attention.set_seen`), `ask` for Swift's question (`session._on_screen`) | none (OWN-04 fixed) |
| An approval covers what its card showed | `security/gateway.ActionGateway.execute` (digest recomputed, `changed_after_approval`); the agent's tool cards and step cards through `ActionGateway.bind` / `allow` (`changed_after_approval`, `approval_reused`, journalled) | none (OWN-05 fixed, review pending) |
| Reversibility of commands | `executors/step_grant.reversible`, `base.Grant.covers` | — |
| Recipients | `workflows/tools.find_contact`, and `draft_email` for an address in the owner's words → `RunScope.resolved`; the gateway checks it | — |
| Web addresses | `security/web_scope.WebScope`; `desktop_tools._open_url` and `_offer` (Swift's question) | fetching takes tool-result addresses too, accepted: a fetch only reads (OWN-06) |
| Reads | `executors/read_scope.ReadScope` | — |
| Memory | `memory.Store.write` (`said` text must be in the owner's words; `approved` needs a card) | — |
| Presence | `presence`, `intake` step 1 | about four checks in `session` (RV-15) |
| Swift's guess (IA-01 phase 2) | `system/understand.propose` (only a plain command, `PROPOSABLE` intents, every slot read from the owner's words), `routing/rules.guessed` (`GUESS_SOURCES`: `voice`, `wake`, `typed`; the spoken-like sources count as `voice`, so `correction`, a change said on a card with Swift's name, may guess; `retry` only as its first try, `retry_of`, could. A hotkey or typed request made while Swift's question is open is one the owner started and may get a guess, while the wake phrase in that position, `beside`, may not: owner, 2026-11-25), `system/lane.SystemLane.propose` (its own yes/no question showing every slot; a yes runs `confirmed`), approved by `intake.approves` at level 1; `restated` keeps the bare grammar, so the guessed-from words ask again (`test_guess.py`, the seam scenario in `test_seam_replay.py`) | learned trust isn't built, so R2 has nothing to enforce yet |

## 5. Not built yet (2026-11-15)

The rules above are the target; until each decision's code is merged, the code may differ. A change must move the
code toward these rules, never away.

- **1, 3, 10:** built (typed never approves; the hotkey held is a gesture; `intake.approves` is the one decider).
  **On screen and in front** (claude/rule-gaps, 2026-11-18; built, not reviewed): `intake.approves(..., in_front=)`
  refuses at every level when the thing isn't on screen and in front. A click (`confirm.reply`) on an OK set aside in
  the stack, or on a card held while the owner is away, approves nothing (`Session._confirm_reply`), and so does a
  click on Swift's own approval question off screen. A click was on the thing, so a refused click means the screen and
  the backend disagree: that OK or question comes to the front (`_open_card` / `_bring`) with "Still waiting: click
  again to approve.", and the next click there approves. Owner check 430.
  Their owner checks are not run yet. The correction offer is level 1, so a plain spoken "yes" takes it while it's
  on screen (owner, 2026-11-15). Open: the hint leaves out "press Enter on Yes" until decision 2 is built.
  Speech with the hotkey held can't answer Swift's own question yet (FD-01).
- **2:** built (`overlay/src/keyed.ts`): while the text box is open, Tab reaches the card's own Approve/Reject or
  Yes/No (or a short list of choices), ringed on the card, and Enter presses it as a click (`confirm.reply` /
  `ask.reply`, source click). The overlay window never takes focus, so the text box holds the keyboard and tells
  the card which button is reached. Owner check 394 not run yet. **A7, keyboard entry** (Halo B8, owner approved
  2026-11-18 via the orchestrating session; not reviewed yet): its own hotkey (`hotkeys.card`, Ctrl+Alt+Enter) opens
  the text box already on the front card's first button, never when a card appears; Tab walks only the card's
  buttons, Enter presses the one reached as its own click (Approve keeps its 400 ms guard, typed words still never
  approve), and the box closes after the press or on Esc, giving the keyboard back to the app. It is the text box's
  exception, not a new one; `overlay/tests/focus.test.ts` checks the only `set_focus` is the text box's and that only
  the owner's hotkeys, the tray or Change open it. Owner check 429. The backend's typed-yes
  hints (`TYPED_YES_HINT`, `TYPED_APPROVE_HINT`) still say only "click … or say"; the text box shows the Tab way.
- **4:** built: an address not in this request's words is asked about
  ("Open usiu.ac.ke?", level 1, typing never answers it), offering only the owner's own earlier or remembered
  addresses; `points_back` is deleted (FD-02). A remembered address is now asked about too (stricter than before).
  Owner check 330 rewritten, with 370 and 371; not run.
- **5:** built: an address the owner said or typed in this request can be a
  recipient, marked "(from your words, not in your contacts)" on the send card (FD-03). Not built: offering to save
  it as a contact; calendar invites still take only contacts. Owner check 395; not run.
- **6:** built: a write into an app (or filling in an email) the owner's words
  didn't clearly ask for is asked about, level 1 (FD-04), showing every character a yes writes, marked as the
  worker's (FD-05). `owner_asked_to_write` still decides between level 0 and 1 by pattern, but since
  claude/rule-gaps (2026-11-18; built, not reviewed) only a clear ask stays at level 0: a writing verb leading the
  request, or a writing word with a place to write ("here", "into Word"). A writing word or a place alone ("what's
  here on my screen?", "is this sentence correct") now asks first instead of writing silently (D4), and so does a
  request phrased as a question ("what can I write here?", "can I write here?") unless a writing verb leads it
  ("can you write this here"). A pattern can
  still miss a clear ask (then Swift asks once) but no longer turns these questions into silent writes. Owner checks
  396 and 431; not run. Typing into a terminal, or anywhere in VS Code (OCT-01, a safeguard: its terminal
  can't be told from its editor), has its own card showing every character (level 3) instead of being refused.
  After its card ("Run this in …? Swift types it and presses Enter.") the real Windows writer types the command
  into a terminal and runs it (the owner's decision of 2026-11-15): only for a write approved as a terminal write
  (`desktop.writer(terminal=True)`), exactly the card's one line, then Enter only if the same window is still in
  front (checked before typing and again before Enter); text with a line break is refused. VS Code keeps the card
  on every write, typed without Enter, until `spikes/desktop/vscode_focus.py` shows its editor and terminal apart.
  Owner checks 397 and 399; not run.
- **8:** built: `ConnectorError.reason` (a content-free code: `http_503`, `clipboard_busy`,
  an error class) at every raise that fell back to `connector_failed`; the gateway's "action failed" line and the
  calendar and contacts read failures log it; `error_class` joins the swift.log summary; the interaction record
  keeps `answers` (local only). Owner check not run. Not covered: a desktop write stopped mid-way (`_changed`) and
  the A9 UIA state.
- **7, 9:** apply when the W2 file tools and paying (C2) are built.
- **"Ask me about everything"** (modes study §3): built on `claude/halo-b8-build-4fbdf7` (2026-11-18), not reviewed
  or checked yet. `swift/asking.py`: one record in the memory store, from the owner's words, on until they turn it off.
  Typed words may turn it on (kept as `typed`); only spoken words turn it off (owner, 2026-11-18: "Yes, not
  typed"); a record that can't be read counts as on. The gateway adds a card to `reversible` actions, except volume (its
  `Action.kind`); the system lane asks before its own changes (level 1, Swift's own question; volume and reads
  excepted), with "Asking because you said: ask me about everything." under it; no step card is offered or used, so
  every command asks. It only adds questions: `confirm` is never lowered. Rule tests in
  `tests/unit/test_asking_everything.py`, each failing with its guard removed; owner check 422.
  Not built: the tray's "Asking about everything" status and its "Stop asking" item, the line on the gateway's
  cards, and learned trust (kept but not used: there is none yet).
- Found by the ownership map, not in the decisions: worker tool cards weren't bound to a digest (OWN-05, fixed; a
  review by another author is pending).

## 6. Where the model is stricter and looser than before

See [`foundation-rules-review.md`](../explorations/foundation-rules-review.md) §4, "Where the model is stricter,
looser, and why". In short: stricter on typed approvals, money and terminals; looser on recipients and addresses the
owner gave, and on unclear writes (a question instead of a refusal).
