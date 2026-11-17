# Build spec

Measurements and colours not given here are `SPEC.md`'s. Token names are `tokens.css` names (`--accent`) and the
canvas's `b-*` variables (`b-accent`) for the same thing. New tokens are in `tokens-b8.css`. Board and frame names
point into `halo.pen`.

Code anchors (overlay, `overlay/src/`): `main.ts` (card rendering: `renderWorking`, `renderResult`, `renderConfirm`,
`renderConfirmVoice`, `renderQuestion`, `renderAsk`, `renderDue`, `renderNotice`, `renderProblem`, `renderConnection`,
`drawCapsule`, `drawRows`, `drawStackInline`, `drawLiveInline`, `drawFollowup`, `headRow`), `card.ts`, `deck.ts` /
`deckdraw.ts`, `stack.ts`, `live.ts`, `pane.ts` (`drawType`, `drawTray`, `drawLive`, the reader), `panes.ts`
(`paneSize`, pane views), `presenter.ts`, `styles.css`, `look/` (Step A: `halo.css`, `dress.ts`). Rust:
`src-tauri/src/` (`panes.rs`, `win.rs`, `hit.rs`, `placement.rs`). Backend: `src/swift/session.py`, `intake.py`,
`stack.py`, `attention.py`.

New components drawn (library, "B8 additions"): Block · Tree row, Block · Worker's pick, Block · Worker's content,
Edge · Timer, Orb · Timer, Watch · Title bar, Watch · Step, Run link, State · Notice, Stack · Row, Stack · Pile.
Build them as overlay parts with the same names.

---

## 1. Every surface in Halo (board 9) — restyles of built behaviour

None of these change behaviour; they put built surfaces into Halo. Do them as part of Step B.

**1.1 Stack, pile → list.** Pile (Stack · Pile, 280 × 64): three offset sheets (`--edge-3`, `--edge-2`, front
`--panel-solid` radius 14), count chip, "N things need you", "Next: …" (12 `--muted`). When an OK waits: front gets a
1.5 px `--warn` border, the chip `--warn` with a shield and `--on-warn` count, the next line `--warn-text` 600
"Needs your OK · <title>"; the orb badge is Badge · OK. Opened (clicking the pile, or "what's waiting?"): Stack · List,
320 wide, solid, radius 16, head 44 ("Waiting for you · N" counting only waiting items; chevron folds), optional
section labels (11/700 caps `--faint`: RUNNING, WAITING FOR YOU, EARLIER TODAY), rows = Stack · Row (28 px mark
disc + title 14/600 + line 12 `--muted` + Open pill; row height fits content, padding 12/14/12/16, 1 px `--rim`
divider), foot hint "Or say “what's waiting?”". Mark per kind: OK `--warn`/shield; question `--accent-soft`/?;
unfinished `--raise`/pause; timer `--accent-soft`/timer; done `--ok`/check; failed `--bad`/!. Unfolds upward from the
pile in 280 ms (B7). Empty: no pile, no badge; "what's waiting?" answers with a one-line Done card. Code:
`stack.ts`, `drawStackInline`, the stack pane in `pane.ts`, `paneSize` (`stack`).

**1.2 Text box** (`pane.ts drawType`/`drawFix`). 512 wide, solid, radius 18, 2 px border `--accent` (it has the
keyboard). One row 52 px: icon 16 `--muted`, the field 17 px, the caret `--accent`, then a Key "Enter" + what Enter
does ("sends", "sends a change", "presses Copy", "saves"). A note strip above the row only when the mode changes
Enter (padding 10/16, `--accent-soft`, icon + 13 px): follow-up "Follows “…”"; over a confirm card the whole box is
amber: 2 px `--warn`, strip `--warn-soft` with shield and "Typing can't approve. Enter sends this as a change." in
`--warn-text` 600; Tab reached the card: "Enter presses “Copy” on the card · Tab for the next" and the card button
wears a 2 px accent ring; fix mode: see §2.10 and `02-fixes.md` §3.

**1.3 Tray menu** (`pane.ts drawTray`). 300 wide, solid, radius 16. Head: orb (dimmed to 45% when paused) + "Swift"
700 + status 12 (`--ok` when listening, `--muted` when paused). Position: label + current anchor name, then a small
screen (76 px, `--raise`, 1 px `--rim`) with six dots, the current one filled `--accent`. Smart placement switch
(34 × 20, `--accent`) + help 12 `--faint`. Items 36 px (icon 15 `--muted`, label 13, optional Key): Pause/Resume,
Type to Swift, Settings | Improve speech recognition, Clear saved recordings | Restart Swift, Quit Swift. Quit is
plain (red is for failure).

**1.4 Notices and problems** (`renderNotice`, `renderProblem`, `renderError`, `renderConnection`). New state line
**State · Notice** (40 px, mark 18 disc `--raise` + icon 12 `--muted`, label 13/600, optional time, close). Notices
are solid cards (`--panel-solid`, 1 px `--rim`), no origin unless the owner's words were involved. Mark per notice:
ready = `--ok` check, label in `--ok`; already running, say that again = info; hold to talk, hotkey taken = keyboard;
didn't catch that = mic-off; still starting, reconnecting, restarting = the 16 px spinner; engine stopped and couldn't
restart = `--bad` disc, label `--bad`, card border `--bad` (the only red notices). Sticky problems (reconnecting,
restarting, stopped, couldn't restart, still starting) have no close. Copy is on board 9, section 4; keep today's
behaviour (e.g. "Try again in a few seconds" for still starting).

**1.5 Follow-up window** (`drawFollowup`). The orb wears a 44 px ring (`--track`, arc `--accent`, inner radius
0.86) that drains over `followup_s`, and a pill (28 px, solid, 1 px `--rim`): mic `--accent` · "Reply without “Hey
Swift”" 12/600 · "· 6 s" `--faint`.

**1.6 "Say approve again"** (`renderConfirmVoice`). Not a new card: on the Needs your OK card it replaces the voice
rule line with a `--warn-soft` box (radius 10, padding 8/10): mic `--warn-text` + "Heard “approve”, but it's noisy
here. Say “approve” again, or click Send." 13/600 `--warn-text`.

---

## 2. B-items

**2.1 B3, states side by side** (board 7). Verify, don't redesign: each state differs in at least two ways that
survive grayscale (band, ring weight, mark shape, the word). Edges carry mark + word in the state's text colour;
badges carry the mark on the orb (working = orbit arc). Done when the grayscale screenshots in `03-verify.md` §4 tell
OK from Waiting, Waiting from Working, Stopped from Failed.

**2.2 ADR-019 §8 open items** (board 7).
1. Every confirm and question card has an origin line. The approval card (B1) leads with the worker's sentence inside
   Block · Worker's content (caption "The worker's words"); Swift's facts box rows "Runs in", "Will run" (command box,
   first line always shown, "▸ N more lines" folds the rest), "Removes"/"To"/etc.
2. Times on screen are relative: running `m:ss`; done "just now" (<1 min), "N min ago" (<1 h), "N h ago"; Due "now".
   Clock times only in the reader and the record.
3. Failed never fades and has no reading bar; keeps partial results (steps done, done, failed) and offers "Try again
   from step N". After 10 min it moves to the stack, still Failed.
4. A problem nobody asked about is Failed with Swift's origin on the left (e.g. Scheduled · nightly backup).
5. At right anchors the speaking pill grows leftwards; the orb's centre never moves (left anchors: rightwards).
6. Compact confirm (band 36, gaps 8, preview clamped to 2 lines) first; if still too tall, the deck folds to one edge.
   The card never scrolls; buttons never leave the window. Test at 150% with a short window.

**2.3 B5, cards that grow and expand by hand** (board 4). Cap = window free height (560 − 2×16 − 36 − 10 = 482) minus
34 per deck edge shown; the deck folds to one edge before the body is cut. At the cap: the body clips, a 56 px fade
(`--card-fade` → `--panel`) marks the cut, and a ghost button "Show all · <how much>" ("2 min read", "11 rows",
"5 steps") sits under it; diagrams cut at a node boundary. Expanded (by hand only): 640 wide, up to the work area's
height minus gutters, body scrolls inside, state line and footer pinned, "Show less" replaces Show all, the deck folds
to one edge (an OK arriving shows there in amber). Collapse: Show less, Esc, or a click on the orb; returns scrolled to
the top; the deck unfolds 160 ms later; never collapses on its own while the pointer is over it; an expanded card
doesn't fade, Done's reading time restarts when it folds. Grows away from the orb at all six anchors.

**2.4 B7, motion** (board 4; tokens in `tokens-b8.css`). Grow out of the orb: 280 ms `cubic-bezier(0.22,1,0.36,1)`,
scale from the orb corner, content fades in over the last 100 ms, tail settles last (120 ms). Fold into the orb:
220 ms `cubic-bezier(0.4,0,1,1)`, tail retracts first, the orb pulses once (200 ms). Edge forward to card: 320 ms
`cubic-bezier(0.2,0.8,0.2,1)`, front card folds first, edge slides and widens 492 → 512. Done drains: linear bar over the
reading time, then a 400 ms ease-in fade drifting 8 px toward the orb; the deck moves up 160 ms later; hover pauses the
drain. Reduced motion: every one is a 120 ms crossfade; the bar still drains.

**2.5 B14, running timer** (board 6). No card while it counts. On the orb: Orb · Timer (44 px ring, `--track`, arc
`--accent`, inner radius 0.8, the orb inside) + a time pill (22 px, solid, 1 px `--rim`, timer icon + `m:ss` 12/600)
on the screen side of the orb; under a minute it shows seconds; two timers "4:12 · 2". With a card in front it's an
Edge · Timer (draining 64 px bar + time). In the stack it's a row under RUNNING with Cancel. Due: unchanged Halo Due
card (solid, accent ring, no close), buttons "+5 min" ghost and "Done" primary, voice "done"/"5 more". +5 min →
card folds, arc full at 5:00. Done → card folds, Edge · Got it "Done: Tea timer" for 2.5 s.

**2.6 B13, file tree** (board 6). Block · Tree row: 28 px, radius 8, indent 18 px per level, chevron (right/down;
hidden for files), icon 16 (folder `--accent`, files `--muted`), name 14 (fills), meta 12 `--faint`. Folders start
collapsed except the one that answers the question. Long names are cut in the middle so the extension stays; full name
in a tooltip after 500 ms. "+ N more in <folder>" row (`--accent` 600) opens in place. Selected row: `--accent-soft`
fill, name 600; the footer shows the path with Open (primary) and Show in folder. Double-click opens (path read from
the file system, never the worker's text). Keyboard (arrows, Enter) only in the reader. Never a delete action from the
tree. Capped on a card (B5); the reader shows all of it.

**2.7 B4 shapes** (board 6; compare is built). Each on Done cards and in the reader only. The worker's part sits in
Block · Worker's content (3 px left bar `--worker-bar`, caption 12 `--faint`: "Compared/Grouped/Outlined by the
worker, not checked by Swift"); the worker's choice is Block · Worker's pick (grey chip `--worker-soft`, 12/600
`--muted`, never accent). Mind map: centre pill (88 px circle `--accent-soft`) + up to six branch boxes in two columns.
Document preview: Swift renders the PDF page itself (150 × 196 thumbnail, the passage highlighted) plus file name, page,
an excerpt box and "Open at page N"; text excerpt: line-numbered lines, the matching lines highlighted. Chart: bars only,
built from layout, values Swift's; Worker's pick months per D7. Project cards: up to three per row, status as icon +
word (never amber/red), due, progress bar. Fallback: if a shape doesn't fit, plain text plus one grey line saying why.
Diagram: board 4.

**2.8 B6/B11 watch as a monitor** (board 5). **Decided, not built** (b8-prompt-fix). Solid `--mon-bg` in both themes,
radius 12, no glass/rim/tail/state line/amber. Watch · Title bar (36 px): LIVE pill (dot + "LIVE" mono 11/700
`--mon-live`, breathing every 2 s, steady with reduced motion), title 13/600, clock mono 12 `--mon-muted`, ×. A 2 px
progress line under it (never goes back). Meta line mono 11 `--mon-faint` ("Step 4 of 6 · about 1 min left"). Steps:
Watch · Step rows (mono 12; ✓ `--mon-ok` done, › `--mon-live` now 700, ○ todo `--mon-faint`, times right). Sources: 14
px state discs. Paper view: a white page (`--paper`, `--on-paper`) with one console line always under it. Footer: Stop,
spacer, Show in <app> / Open the answer. States: LIVE, FINISHED (`--mon-ok`), ENDED (grey: you stopped it).

**2.9 B9/B10/B12 watch placements, one run, open the answer** (board 5). Placements behind one Dock button: beside the
card (built placement), docked sidebar (an app bar on the orb's edge: Windows shrinks the work area; orb and card move
to its inner edge), mini (300 px, title + progress + current step, in the orb-side corner opposite the orb). One run:
same title, same clock to the second, a 2 px accent tether from the watch's title bar to the card or edge, and a Run
link chip on the card ("In the watch · 01:40"); while the watch is open the card never fades and the watch never closes
by itself; when the run ends the card turns Done with "Open the answer" and its reading time starts only after the
watch closes. Open the answer opens the run record in the reader (works after the card faded, after a restart).

**2.10 STT corrections UI** (branch `claude/stt-corrections`): the flag after the heard words and the fix pane, plus
the six fixes in `02-fixes.md` §3. Fix pane in Halo: §1.2's box with the flag note, the heard words selected, "What
went wrong" chips (selected = `--accent-soft` + `--accent` border + check), hint "Corrections stay on this PC…".

---

## 3. A-ideas (board 8)

All PROPOSAL. Do-next first, then Explore behind a setting (off by default) with an owner check each.

| # | Kind | Build |
|---|---|---|
| A5 Caveat | Refinement | New block **Block · Caveat**: `--raise` box radius 12, scale icon `--muted`, one line why the answer may be wrong (sources disagree, old data, a guess) in 14 `--muted`, "Check sources" ghost. Done cards only; never on a confirm (facts there are Swift's). Needs the worker to say so: a `caveat` field on results |
| A6 Captions | Refinement | The speaking pill widens to show the words being said (16 px, ≤ 2 lines), "Captions · say “captions off” to hide" 12 `--faint`. On by default when the output is muted or Windows captions are on |
| A9 Micro-feedback | Refinement | Approve fills left to right during its 400 ms guard (55% opacity → full); Copy becomes "Copied" with `--ok` check for 1.5 s; hovering a Done card pauses its bar and shows "Paused while you read"; voice requests get Edge · Got it for 2.5 s |
| A4 Pin | New | "Pin" button on Done cards; the answer becomes a 34 px pinned edge on the far side of the deck (`--edge-1`, `--accent-edge` border, pin icon, title + one line, ×). Never fades. One at a time (D11) |
| A1 Recent | New | "Earlier today" section in the stack list (§1.1) from run records; "what did you find about …" opens the reader |
| A2 Follow-up on the same card | New | A follow-up while a card shows keeps the run: the origin line adds "then “…”" (14/600 `--muted`, mic), the answer is replaced, "First answer" ghost shows the previous |
| A7 Keyboard entry | Refinement | A hotkey moves focus into the front card on purpose; 2 px accent ring on the reached button; Tab walks buttons (Approve still needs Enter and its 400 ms); Esc returns focus to the app it came from. Key strip hint |
| A3 Hold during calls | New | During calls, screen sharing, presenting: new cards wait as a count ("Holding 3 till your call ends" pill, moon icon) on the orb; an OK shows only as Badge · OK (no sound, no card over the shared screen); after the call one digest card (origin "While you were in your call · 42 min", list rows, "Go through them"). Needs a call/share detector: spike it first (the one technical risk) |
| A8 Settings | New | "How Swift shows things" page in the Swift window (or a pane until it exists): segmented controls for reading time (1×/1.5×/2×/Until I close), text size, motion, speak answers, watch opens; defaults follow Windows |
| A10 What can I say? | Explore | "What can I say?" on a card lists its accepted phrases in a `--accent-soft` block (mic per line; "· asks for your OK" where it does); the hint learns from repeats (3 manual Copy-to-Word → one hint) |
| A11 Next-step chips | Explore | ≤ 2 chips "Next" (grey label) from Swift's own verbs, learned; a chip that needs an OK opens that OK, never runs |
| A12 Orb glance | Explore | Pointer rests 400 ms on the orb → read-only glance (280 wide, solid): next meeting, running timers, "N waiting · 1 needs your OK" (amber line); one line when quiet; leaves 200 ms after the pointer; not while a card shows; never focus |
| A13 Orb follows the active monitor | Explore | After 1.5 s on another monitor, the orb fades across to the same anchor there (120 ms each way); never while a card or OK is up; off with one monitor |

Shared: neither A12 nor A13 takes focus or a click; both off in full screen; both reduced-motion safe; both have a
switch in A8.

---

## 4. The modes study (not built; all seven decisions taken 2026-11-14)

Source: `docs/explorations/modes-study.md` (rules, data model, where each check goes) and `docs/handoff/workstreams.md`
(the decisions). Designs: board 9, section 6. The study's own order: "ask me about everything" first, then learned
trust (Wi-Fi off, Bluetooth off, airplane mode on only), then the plan card. Each gets owner checks and a rule test per
product rule (each failing with its guard removed). None of it lowers a product rule.

| Part | Screen (board 9 §6) | Build |
|---|---|---|
| "Ask me about everything" | Tray status "Asking about everything" (`--accent` 600) + item "Stop asking about everything"; on a card that asks only because of it: shield-check line "Asking because you said: ask me about everything." | `asking.everything` in the memory store, set by words (typed works: it only asks more); gateway treats `reversible` as `confirm`; no grants offered or used; trusts kept, not used; not reads in read folders, not volume; stays on until turned off |
| Learned trust: the offer | Waiting for you card, origin "Learned · you've turned Wi-Fi off 3 times this week", title "Turn Wi-Fi off without asking from now on?", footer hint "Say it or click · typing can't create a trust", Not now / Always | After 3 approvals in 3 runs within 14 days, none rejected, once per kind. `Action.kind`, the kinds table, a count over the journal; a yes goes in the memory store. Spoken "always do X" can create one for a kind on the table; typed can't; `config.yaml` can't |
| Learned trust: used | Done card, "Wi-Fi is off." + check-check "You said not to ask." + Undo | Spoken reply stays short ("Wi-Fi's off.") |
| Learned trust: list and undo | "What do you do without asking?" → Done card with one row per trust (since date, uses) and "Ask me again" | `Store.forget` (keeps versions); "ask me again about Wi-Fi", "stop doing that without asking" (the last used); "What do you know about me" ends "And N things I do without asking." |
| The plan card | Needs your OK, 640 wide: "A plan in N steps", rows = number disc + step in words + its commands (mono 12 `--muted`) + "covered" (`--ok` check) or "will ask you · it publishes/sends" (shield, `--muted`, never amber); footer hint "Steps 3 and 4 get their own card"; Stop, Change, "Go ahead with 1 and 2" (approve) | `propose_plan` tool next to `propose_step` (multi-step tasks only); `WorkerTask.grant` becomes a tuple of `Grant`s used in order; `_ask` checks the current and later steps; only `step_grant.reversible` commands are covered; unknown later commands show "will ask"; a changed plan is a new card; file edits not covered (decision 5). Seam scenario in `test_seam_replay.py` |
