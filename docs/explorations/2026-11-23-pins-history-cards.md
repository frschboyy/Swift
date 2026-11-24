# Pins, History, card size and the stack's actions: design for the owner's OK

- **Status:** Phase 1, design only. Nothing here is built. Waiting for the owner's answers (§8).
- **Date:** 2026-11-23. **Branch:** `claude/cards-stack-design-5fec91`.
- **From:** the owner's runs of 2026-11-18/19, items 3, 5, 9, 10 and 11.
- **Mockups:** [`overlay/dev/cards-stack-mock.html`](../../overlay/dev/cards-stack-mock.html), served by the dev
  harness on port 1431 (`/dev/cards-stack-mock.html`). Screenshots are in
  [`docs/design/cards-stack-2026-11-23/`](../design/cards-stack-2026-11-23/).
- **Touches:** ADR-018 (the Deck) §2 and its "Keeps" line on ADR-015 §9; ADR-019 (Halo) A1, A4/D11, B5 and
  `CardSpec.size`. What changes in each is in §7.

## 1. The model: four places, each with one meaning

The owner's roles, made into one rule: **a thing is in exactly one place, and the place says what it is.**

| Place | What's there | Where | Lasts |
|---|---|---|---|
| **In front** (ADR-018) | The one card the owner is dealing with | The card growing out of the orb, or the workspace when expanded (§4) | While it's in front |
| **Behind** (ADR-018) | Still in flow: running, next in line | Edges behind the card | Until it comes forward or ends |
| **The stack** | Unfinished work that waits for the owner | The corner | Until opened, cancelled, or it runs out (its ring) |
| **Pins** (new) | Finished work the owner chose to keep and go on with | Pills on a shelf above the stack, same corner | Until unpinned (restart: §8 Q2) |
| **History** (new) | A record of what happened | A sidebar from the right edge, opened from a "History" link | Since Swift started (restart: §8 Q2) |

What leaves the stack: "Earlier today" (A1) moves to History; nothing finished is in the stack any more. Timers
still counting (B14, RUNNING) stay: they are unfinished. The stack's badge already leaves both out (`waits()` in
`stack.ts`), so the count doesn't change.

## 2. What the code does today (read 2026-11-23, at `2cc19e4`)

### 2.1 Pin (A4)

- `main.ts:1377–1395`: one module variable, `pinned`, drawn as a 34 px edge above the deck rows. A new pin
  replaces the old one (D11). The edge holds the answer's text in its tooltip and an Unpin ×; **a click on it does
  nothing**, so the pinned answer can't be read again or continued. That is the owner's "disappears with no way
  back".
- `pinButton` (`main.ts:1911`) is added to the footer **only for short answers**: the long branch of `drawFoot`
  (`main.ts:1882–1895`) has Show all, Show, Say and Copy, no Pin. So long answers, which are the research results
  the owner wants to keep, can't be pinned. Questions, confirms, failures and notices have no Pin either.
- The pin is overlay-only state: a reload of the webview loses it, and the backend doesn't know it exists.

### 2.2 Earlier today (A1)

- `src/swift/recent.py`: requests that ended with an answer today, newest first, at most `MAX_RECENT = 6`, sent
  with `stack` as `recent`. Open brings the run back with `session._bring(run)`.
- It reads `session._runs` and `session._gone`, and **`_gone` keeps only `MAX_RUNS = 3`** (`session.py:375`,
  `:727`). So "Earlier today" shows at most a handful, older answers fall off silently, and anything a pin or
  History must reopen needs its run kept longer (§5.1).
- Drawn as a section of the open stack (`views.ts:119–134`).

### 2.3 Card size (B5)

- Default card: 512 px wide (`--card-w`), at most the window's height less the capsule and deck
  (`styles.css:1302`). The main window is a fixed 720 × 560 (`tauri.conf.json`, `resizable: false`).
- A long **text** answer is cut with a 56 px fade (`.answer--long`, `styles.css:645`) and does not scroll; mind
  maps, previews, charts and project cards do scroll (`styles.css:652–689`). So whether the card scrolls depends on
  the block, which is why "Show all" reads as meaningless on some cards.
- "Show all · N more" (`main.ts:1891`) sets `card--open`: 640 px wide (`--card-w-expanded`), the details drawn in
  full (`renderDetails(…, expanded)`), the body scrolling, the deck folded to one edge, and the card held until
  dismissed (seams decision 6, `presenter.ts:301`). "Show less" undoes it.
- `CardSpec.size` (`card.ts`) is the named hook for growth and only knows `"fit"`.

### 2.4 The stack row's hover

`styles.css:1001–1005`: `.stack-actions { display: none }`, and `display: flex` on hover, `aria-selected` or
focus. Showing them adds a 6 px gap and a 28 px button row to that row, so **every row below moves down 34 px**,
and moves back when the pointer leaves. Moving the pointer down the list makes it jump row by row. (The ui-fixes
session owns the stack's scroll jump, a different bug; see §9.)

### 2.5 Skip and End: what each does

From `session.py:1362–1408` (`_stack_action`), `stack.py:order` and `timers.stack_action`:

| Row kind | **Skip** does | **End** does |
|---|---|---|
| A confirm card waiting in line (`card:`) | Moves it to the back of the line and the bottom of the list | Stops its request (`_end_run`); with no run, takes the card out of line (`_card_done`). The action is not done |
| A card put off, held or timed out (`card:`) | Moves it to the bottom of the list | As above |
| An unfinished conversation (`parked:`) | Moves it to the bottom of the list | Forgets it (`parked.drop`) |
| Swift's question, unanswered (`parked:`, asked) | Moves it to the bottom | Cancels the question and stops its request |
| Came due (`due:`) | Moves it to the bottom | Same as its "Done" button: dismissed |
| Failed (overlay's own, `failed:`) | **Nothing** (`main.ts:2069`) | Removes it |
| Earlier today (`recent:`) | Not shown | Not shown |

So they are different, but **Skip in the stack list only reorders the list.** Nothing about the item changes, and
the list has no meaningful order to the owner (it already sorts by kind, then age). The only Skip that does
something real is the one on the card in front ("Later", "Answer later", a timeout): it puts the card into the
stack. That one isn't on the stack and is unchanged.

## 3. The surfaces

### 3.1 The corner: pins shelf, stack and the History link

One column in the corner the owner chose for the stack (ADR-015 §9; same pane window, `PaneKind::Stack`), top to
bottom:

1. **Pins shelf:** each pin a 32 px pill, at most 220 px wide: pin icon, a title of up to 24 characters (the
   owner's words, as edges are titled), and a one-line hint in `--muted` (for an answer: its first line; for a
   conversation: "3 turns"). Up to 4 pills shown; more fold into "+3 pinned", which opens History at its Pinned
   section. Neutral glass (`--edge-1`, `--accent-edge` border, as today's pinned edge): never amber, it never
   needs an OK.
2. **The stack**, as today (closed pile, double click opens).
3. **"History"**: one line, 12 px, `--faint`, underlined, right-aligned under the stack. Shown only when there is
   history. With nothing waiting and no pins, it stands alone in the corner (§8 Q3).

Hover on a pill: an × crossfades over the right end of its hint (Unpin), in the pill's own space, nothing moves.
A click anywhere else on the pill opens the pin (§3.3).

### 3.2 The stack's rows: actions without layout shift

Every row has a fixed height, 56 px: mark (28 px) · title over reason · a **fixed 96 px slot on the right**.

- At rest the slot shows the row's age ("12 min"), or its ring.
- On hover, keyboard focus or selection, the age fades out and two 28 px icon buttons fade in, in the same slot:
  **Open** and **Cancel** (§3.4). `opacity` and `visibility` only, 120 ms; the row's box never changes, so no
  other row moves. Reduced motion: no fade, an instant swap.
- The buttons are in the DOM all the time (so Tab reaches them and screen readers read them), hidden only
  visually at rest.

### 3.3 A pin, opened

A click on a pill brings that request back to the front: the same `_bring(run)` that "Earlier today"'s Open uses
today, so it's the same run with its answer and thread, nothing runs again, and a reply goes on with that
conversation (the conversation session's follow-ups on finished cards). Its card shows a filled pin in the
footer ("Pinned"); a click there unpins. Closing the card returns it to the shelf; it never goes to the stack.

Pin is offered on every card with a finished run: Done (short **and** long, fixing §2.1), a finished
conversation, and Failed (to retry later). Not on Needs your OK, Swift's question, Working, Due or notices: those
are unfinished, and the stack already keeps them.

### 3.4 Skip and End become one action: **Cancel**

The stack rows get **Open** and **Cancel**. Skip goes from the stack. The card in front keeps "Later" /
"Answer later", which is the real put-aside action. Cancel's words say what it does to that kind of row, in its
tooltip and its spoken label:

| Row | Button | Tooltip |
|---|---|---|
| Confirm waiting, put off, held | Cancel | "Cancel: it won't be done" |
| Unfinished conversation | Cancel | "Cancel: Swift forgets where it got to" |
| Swift's question | Cancel | "Cancel the request" |
| Came due | Done (its Open is already Done; one button) | "Dismiss the reminder" |
| Timer | Cancel (as today) | "Cancel the timer" |
| Failed | Dismiss | "Remove from the stack" |

**No card, no shift:** Cancel is confirmed in place. The first click turns the slot into a red "Cancel?" text
button for 3 s (the Open button fades out under it); a second click does it, and the row collapses out of the list
over 160 ms (rows below close the gap once, the only movement, and only because something left). Esc or 3 s
untouched puts the slot back. This is the overlay's own guard on the owner's own click, not an approval: product
levels are unchanged (§6).

### 3.5 History sidebar

- **Opening:** the History link, or "show my history" said or typed (the light lane; §8 Q5). Esc, the ×, or a
  click outside closes it.
- **Where:** the right edge of the work area, full height less 12 px gutters, 360 px wide (`--history-w`), glass.
  On a left anchor too: the owner asked for the right edge (§8 Q4).
- **Motion, "push":** the sidebar slides in from the right (`translateX(100%) → 0`, `--dur-move` 280 ms,
  `--ease`), and the corner column (pins and stack), when it's in a right corner, slides left by the sidebar's
  width at the same time, so the two meet and nothing overlaps. Closing reverses it with `--ease-exit`. Reduced
  motion: a 120 ms fade, no movement. It pushes only Swift's own surfaces, never other apps' windows (no AppBar).
  On a narrow work area (the 1280 px mockup, board C) the pushed column reaches the capsule; there the column
  stops at the main window's edge and the sidebar overlaps it instead (Swift never covers its own orb).
- **Inside:** a header ("History", a filter field, ×), then a **Pinned** section (all pins, the overflow from the
  shelf), then days ("Today", "Yesterday" once it survives restarts), newest first. Each row, 48 px fixed: state
  mark (check, alert, stopped), title (owner's words), result line or "Stopped" / "Cancelled" / "Failed", time on
  the right. Hover: Pin and Open icons crossfade over the time, as in §3.2.
- **Reopen: yes** (§8 Q1). A click on a row brings the request back to the front like a pin. History is a record
  you can step back into; Pins are what you chose to keep in sight. The difference is where it lives, not whether
  it works: refusing to reopen a past answer would make the owner adapt to Swift. A History row that can't be
  reopened (its run is gone: after a restart or past the retention limit) is drawn without Open and says
  "Record only" on hover.
- **What's recorded:** every request that ended (answered, failed, stopped, cancelled), Swift's own notices
  excluded. Its title, state, time and, while the run is retained, its answer.

## 4. Card size: default, Expand, Minimize

### 4.1 Default

- 512 px wide, at most the main window's free height, as today. **The body always scrolls** when its content is
  taller: the fade-and-cut of `.answer--long` goes, and text answers scroll like charts and mind maps already do.
  The fade stays only as a "more below" hint at the scroll edge and disappears at the bottom.
- The details (`renderDetails`) are drawn in full in the default card too: there is no hidden "more" behind a
  button any more. B4's per-block previews (six rows, twelve ideas, the mind map's selected branches) stay; they
  are layout choices, and Expand gives them room.
- The footer: byline · **Expand** · Pin · Say · Copy (Show where there are artifacts). Expand appears only when the
  content is wider or taller than the default card shows (`Panes.needsReader` already measures this).

### 4.2 Expand

Expand moves the card into a **workspace**: a pane window beside the screen edge on the orb's side (right for
centre and right anchors, left for left anchors), sized to the content:

| Content | Width | Height |
|---|---|---|
| Text, lists | max(560 px, ⅓ of the work area) | its content, up to the work area less 24 px |
| A wide block in it (table, comparison, chart, diagram, code, project cards) | up to ½ of the work area, the block's natural width if less | as above |

Never the whole desktop: width ≤ ½ the work area, always. At 1920 px a 600 px workspace clears the main window's
720 px column; on narrower screens (board E, 1280 px) it overlaps the deck's edges, which stay readable to its left
but not clickable under it. Unproven which is better there: overlap, or the main window sliding aside. The card's state line and footer stay put; only the
body scrolls. It holds until the owner closes or minimizes it (seams decision 6, unchanged). The card in front is
now the workspace: voice replies and the conversation reach it, as before. The main window keeps the capsule
and the deck, which **no longer folds** for a long answer (ADR-018 §4.8 becomes unnecessary: the card left the
deck's space).

The motion is ADR-018 rule 3 (one body): the card grows from its place toward the edge, 280 ms,
`--ease-grow`; reduced motion, a fade.

### 4.3 Minimize, and resizing by hand

- **Minimize** (the same footer button, now "Minimize", `collapse` icon) puts it back as the default card in the
  main window, scrolled to where the owner was. Esc and a click on the orb do the same, as Show less does now.
- **By hand:** the workspace's left (or right) edge and its bottom edge can be dragged, between 400 px and ¾ of
  the work area wide. The owner's size is remembered (`overlay.json`, beside the panes' places) and Expand uses it
  next time instead of the content rule, until "Reset size" in the workspace's menu. The default card isn't
  resizable (§8 Q6).

## 5. Who owns what, and what has to change

| Responsibility | Owner today | After |
|---|---|---|
| The stack list | backend `stack.py` + `session._stack_items` | unchanged, minus `recent` |
| Earlier today | backend `recent.py` | becomes History: the same module, renamed, kept longer |
| Pins | overlay `main.ts` (`pinned`) | **backend** (a `pins` list on `stack`), so they outlive a webview reload and voice can reach them later |
| Finished runs' answers | `session._gone`, 3 runs | a bounded store of finished runs (§5.1) |
| Card size | `main.ts` `expanded` + `card--open` | `CardSpec.size: "fit" | "workspace"`, the workspace a pane (`PaneKind::Workspace`) |
| The stack rows' look | `views.ts` `stackOpen`, `styles.css` | same files |

### 5.1 Keeping finished runs

Pins and History need the run (answer, thread, artifacts) after `_gone` drops it. Smallest change: a separate
`finished` store in `recent.py`, at most 50 runs (pinned ones never evicted), in memory only. Run records stay
content-free on disk, as `privacy.md` says now. Keeping answers across a restart would put answer text on disk:
that's a privacy decision (§8 Q2).

### 5.2 Protocol

- Outbound `stack`: `recent` is replaced by `pins` and `history` (each `StackEntry`, kinds `pinned` and `past`).
  History may be sent only while the sidebar is open, to keep `stack` frames small.
- Inbound `stack.action`: actions become `open | cancel | pin | unpin` (`skip` stays accepted for the card in front's
  "Later" path, which uses it; `end` becomes `cancel`). One version bump of `PROTOCOL_VERSION`.

## 6. Product rules

- Nothing here approves anything. Pin, Unpin, Open, Expand, Minimize and History are the owner's own reversible
  view actions (level 0). Cancel ends the owner's own request or forgets a card; it never runs an action. A
  cancelled confirm is a "no", which needs nothing.
- **Reopening a confirm card is not possible from Pins or History.** Neither holds unfinished work; a confirm that
  was cancelled stays cancelled. So no approval can be reached through these surfaces, and `intake.approves` is
  untouched.
- A reopened answer that offers "Say yes and I'll send a correction" follows the existing rule (ADR-018 §4.1): a
  yes only while it's in front.
- The workspace is "on screen and in front" when expanded, for every rule that asks. The backend already treats
  the focused run as in front; the overlay must not report the main card as gone when it moves to the workspace.
  This is the one place a seam scenario must prove a product rule still holds (§9).
- Logs: pins, History opens and Cancel log kinds and counts only, never titles (`swift.log` rule).

## 7. What changes in the ADRs

**ADR-018 (the Deck):**

- §2's table gains two rows, Pinned and History, with "The stack" redefined as unfinished work only.
- "Keeps: … Open / Skip / End" becomes "Open / Cancel; Skip stays on the card in front as Later".
- §4.8 "Read more folds the deck" is replaced: Expand moves the card to the workspace, and the deck stays.
- §6's one-window spike gains a reason: the History push and the workspace's growth are each a window move
  synchronised with a CSS slide today, which one window would make one animation.

**ADR-019 (Halo):**

- A1 "Earlier today in the stack" is superseded by History (§3.5).
- A4 "Pin" and D11 "one at a time" are superseded: several pins, a shelf of pills, reopenable, backend-owned.
- B5: "Show all / Show less" becomes Expand / Minimize; the default card scrolls; `CardSpec.size` gains
  `"workspace"`; SPEC §7 gains the workspace's sizes (§4.2) and `--history-w: 360px`.
- Board 9 §1 (the stack row): fixed 56 px rows with the right slot (§3.2); the "EARLIER TODAY" label goes.

ADR-015 §9 is amended through ADR-018 (Skip leaves the stack).

## 8. Questions for the owner, each with a recommendation

1. **Can History items be reopened?** *Recommended: yes*, the same way as a pin, as long as Swift still has the
   answer (§3.5). Otherwise History is a read-only log and anything worth going back to has to be pinned in
   advance, which makes the owner predict what they'll need.
2. **Do pins and History survive a restart?** *Recommended: not in the first build.* Keep 50 finished runs in
   memory; after a restart History is empty and pins are gone. Making them survive means storing answer text on
   disk, a privacy change to decide on its own (where, how long, "forget" behaviour). Asked as a follow-up once
   the owner has used pins for a few days.
3. **Where does "History" show when nothing waits and nothing is pinned?** *Recommended: alone in the corner, as
   the faint underlined word, only when there is history;* plus "History" in the tray menu. The alternative,
   hiding it until something waits, makes History unreachable at exactly the quiet moments the owner may want it.
4. **Which edge does the sidebar use at a left anchor?** *Recommended: always the right edge*, as asked, so it's
   always in one place. Alternative: the orb's side, matching the workspace.
5. **"Show my history" and "open my pinned …" by voice in the first build?** *Recommended: "show my history" yes*
   (it only opens a panel); opening a pin by name later, with the memory and routing work, so it can be tested on
   the parity set.
6. **Is the default card resizable by hand too, or only the workspace?** *Recommended: only the workspace.* The
   main window is fixed and holds the capsule and deck; a resizable default would mean resizing that window and
   moving the deck. Expand plus a remembered workspace size gives the same freedom.
7. **Cancel's in-place confirm: keep it, or act on the first click?** *Recommended: keep the 3 s "Cancel?" for
   rows that stop a request or forget a conversation*, act at once for Done, Dismiss and timers. A wrong click on a
   cancelled request can't be undone.
8. **How many pins are shown on the shelf?** *Recommended: 4*, the rest under "+N pinned". No limit on pins
   themselves beyond the 50-run store (pinned runs never evicted).

## 9. Coordination with the other sessions

- **ui-fixes** owns the stack's scroll jump, the timed-out card's lifecycle, the footer and Watch. My §3.2 changes
  the stack row's layout and §4.1 the footer's buttons: whoever lands second rebases. The workspace (§4.2) reuses
  the docked Watch's edge placement (`panes.rs` docked rect) but not its AppBar; no change to Watch itself.
- **conversation** owns follow-ups on finished cards. A reopened pin or History item is a finished card in front,
  so its replies go through that work, unchanged here. The finished-run store (§5.1) is something both need:
  agree one owner (recommended: `recent.py`, renamed `history.py`) before either builds it.
- **listening** owns the card's mic button: the footer in §4.1 leaves its place as it is.

## 10. Phase 2: the build order, one finding per commit (after the owner's OK)

1. Stack rows: fixed slot, no layout shift (overlay only). Seam: rows' rectangles unchanged on hover.
2. Skip leaves the stack; End becomes Cancel with in-place confirm (overlay + protocol `cancel`).
3. Finished-run store (backend), replacing `_gone`'s role for A1.
4. Pins: backend list, the shelf, reopen, Pin on long answers and conversations.
5. History: the link, the sidebar pane, the push, reopen.
6. Default card scrolls; Show all/less goes.
7. Expand/Minimize and the workspace pane, with the hand resize and remembered size.
8. ADR-018 and ADR-019 amended; owner checks from `plan.py --next-id` for each of 1–7.

Each screen step gets a seam scenario that fails with the change undone. Step 7's "in front" (§6) is reviewed by
someone other than its author.
