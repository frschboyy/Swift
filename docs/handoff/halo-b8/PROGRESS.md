# Halo B8: progress (branch `claude/halo-b8-build-4fbdf7`)

Stopped once for the owner's credits (at 6b4a5a1) and resumed on the owner's "Yes, resume". Every commit below
passed its tests when it was made. Nothing is half-done, and there is no WIP commit. Not pushed, not merged.

`halo.pen` check: board 9 (every surface, with the stack pile → list redraw and §6 modes) and A12/A13 (board 8)
are in the saved file.

## Committed

| Item | Commit | Kind |
|---|---|---|
| F1: an OK that lapses into the stack frees the front | 7593e4c | root (`_skip_card` clears the focus; two old tests that asserted the bug were updated) |
| F2: a lapsed OK never comes back to the front by itself | 0f65f42 | root (`P.promotion` skips `confirm` rows) |
| F3: after an overlay restart, a lapsed OK is in the pile | 3dbe236 | scenario only (F1's cause) |
| F4: the stage follows the presenter after a lapse | 847ca92 | scenario only (F1's cause; `syncStage` already followed `P.stageOf`) |
| F5: the same request asked again folds into one edge, "×N" | 3b69df1 | root (`deck.ts foldSame`; D: fold within 60 s) |
| F6: "stop" said before the request starts stops it, and says so | ff6d805 | root (new `swift/stops.py`; Esc while capturing stays a silent discard, per `test_voice`/`test_session`) |
| F7: "stop" with nothing running keeps the Stopped card | c5c1f77 | root (`stops.KEEP_S` 10 s) |
| Step B: Halo is the only look, no switch (ADR-019 §10, `brief-halo.md`) | 6259429 | structural |
| §1.1 the stack, pile → list | 0954d62 | restyle |
| §1.2 text box, §1.3 tray | 1b8bd21 | restyle |
| §1.4 notices and problems (State · Notice); D10 "ready" after update/crash only | 982b154 | restyle + D10 (`ready.ts`; `core:app:allow-version` added to the capability) |
| §1.5 the reply window on the orb, §1.6 "say approve again" | 7ef03b9 | restyle |
| Owner checks halo-b8-build-4fbdf7-1..5 (F8, F1-F4, F6-F7, board 9, D10) | 6bd887e | checks |
| Harness: design states draw without a backend; Due states carry origin | b85f980 | harness fix |
| B3: verified in grayscale (no code change; see below) | (this file) | verify |
| §8.2 relative times ("just now", "N min ago") | cb1074d | built |
| §8.3 a request's Failed card never fades | c45efec | partial (no "Try again from step N", no move to the stack) |
| §8.6 a compact confirm that still doesn't fit folds the deck | 5038d71 | built |
| §8.5 at right anchors the pill grows leftwards | efb9659 | built |
| §8.4 a problem with a run nobody asked for is Failed with Swift's origin | 5bac599 | overlay side (nothing sends it yet) |
| §8.1 confirm and question origin line; Block · Worker's content | 6ef45ea | partial (no "Runs in"/"Removes" rows: not on the frame) |
| B5 cards grow to a cap; Show all / Show less, Esc, the orb | a37589e | built (no node-boundary cut for diagrams; reading time is given back, not restarted) |
| B7 motion: grow, fold, edge forward, drain; reduced motion keeps the bar | 19cc84e | built (no tail ordering, no deck move 160 ms after a drain) |
| Owner check -7 (B7) | 46fbe4a | checks |
| B14 a running timer on the orb; "+5 min" on its Due card | 1743e23 | built (new `timers` and `due.snooze` frames; no Edge · Timer, stack RUNNING row, voice "5 more") |
| B4 Worker's content and Worker's pick in grey | 2f138f4 | restyle (shapes were built; no D7: charts carry no pick) |
| B13 file lists as a tree | 167dc5a | built (new `tree` shape; no Open / Show in folder / double-click yet) |
| B6/B11 the watch as a monitor | 97a522f | partial (no step counts "Step 4 of 6", no console line under the paper) |
| B10 Run link on the card; the card holds while its watch is open; watch clock ticks again | 7ccf5df | partial (no B9 docked/mini placements, no tether, no B12 open-from-record) |
| Modes §3 "ask me about everything" (+ owner check -9) | 64dd679 | built; **product rule: needs review** (no tray label yet) |
| A9 micro-feedback | 11abdda | built |
| A4 Pin an answer as an edge | aa1b6b6 | built (no open-in-reader from the edge) |
| A12 orb glance behind `explore.orb_glance` (off by default); the `explore` settings (+ owner check -10) | 0c29585 | built (no next meeting: the overlay has no calendar data) |
| "Ask me about everything": a function, not a lambda with a noqa (lint gate) | 0ee8239 | fix to 64dd679 |
| A5 Block · Caveat (new `add_caveat` tool, `caveat` on the result frame) (+ owner check -11 with A9, A4) | 2fe397d | built (no "Check sources") |
| Forced colours for the new parts | af39398 | built |
| A6 captions (off by default, on/off by voice) and A1 earlier today in the stack (one commit: shared files) (+ checks -12, -13) | 94fb6f9 | built; A6 partial: no automatic default from muted sound or Windows captions |
| A2 a follow-up on the same card (+ check -14) | 52dca0c | built (presentation; a follow-up is still a new run in the same thread) |
| A8 how Swift shows things, in the tray (+ check -15) | 916377e | built (no "speak answers" / "watch opens": backend settings) |
| A7 keyboard entry on the card's buttons (owner approved 2026-11-18) (+ check -16) | 943d42e | built; **focus rule: needs review**; uses the text box's existing exception, so CLAUDE.md is unchanged |
| "Ask me about everything": typed words can't turn it off; the true source is kept; fails closed (owner, 2026-11-18) | b3721d3 | root fix; **product rule: needs review** |
| Test: a "yes" while a lapsed OK waits in the stack approves nothing | 806a75d | test only |
| Text box: typed text then Enter never presses the card's button | 373e932 | root fix (found by the A7 test request); **product rule: needs review** |

Each fix F1, F2 and F5–F7 has a seam scenario in `tests/unit/test_seam_replay.py` that fails without its fix (checked
by undoing the fix). F3 and F4 fail with F1 undone.

## The gaps branch (`claude/halo-b8-gaps-6b8791`, from 8587d11)

Builds what the list below left. One commit per item; this table is kept current after each.

| Item | Commit | Kind |
|---|---|---|
| B5 diagrams cut at a node boundary; "Show all · 11 rows / 1 item / 5 steps" | 64f1d4b | built (`answer.ts howMuch`, `nodeCut`; harness `cardCappedRows`) |
| B7 the tail settles last (final 120 ms of the grow) and retracts first (80 ms); the deck moves up 160 ms after a drain | d3e92a4 | built (`shuffle.ts DECK_AFTER_DRAIN_MS`; measured in the harness: fade 400 ms, clear ≈ 600 ms) |
| B14 Edge · Timer with a card in front; RUNNING row with Cancel; voice "done" / "5 more"; Edge · Got it "Done: Tea timer" (+ check halo-b8-gaps-6b8791-1) | 3de9557 | built (`timers.heard`, `timers.stack_action`, `Drawn.front`; seam test `test_b14_done_and_five_more_*`; harness `timerStack`, `timerGot`; parity 413/423 unchanged). Voice "done" answers with a one-line Done card ("Done: Tea timer."), not the Got-it edge a click shows |
| B4 D7 (`pick` on charts, a grey dashed outline + "Worker's pick" tag) and the fallback line (+ check halo-b8-gaps-6b8791-2) | 6ee126d | built (`shapes.Chart.pick`, `shapes.fallback`; the line rides the result's existing `note`, so it sits above the words, not under them; harness `answerChartPick`, `answerFallback`) |
| B6 Watch · Step rows, "Step N" in the meta line, the console line under the paper | 1330b93 | built (`live.ts` steps from the `doing` items). **Not built:** "of 6 · about 1 min left": a run doesn't know its total until a plan says so (§2's plan card can supply it) |
| "Ask me about everything": the tray's "Asking about everything" status and "Stop asking about everything" item; "Asking because you said…" on the gateway's own cards (+ check halo-b8-gaps-6b8791-3) | 5d872cb | built (`presence.asking`, new inbound `asking` {on: false}, `asking.from_tray`; the gateway passes `because=` to its confirmer only on a card it shows solely because of the setting). **Product rule: needs review** |
| A2 replace the answer in place while the same run goes on | — | **blocked**: each request is its own run (run records, Stop, the stack and the journal are per run); a follow-up resumes the provider's session in the same thread as a new run. The overlay already keeps the same card for it (52dca0c). Making a follow-up the same run is a backend redesign, not a gap |

| §8.1 "Runs in" on command cards | 5a8f26f | built (`confirm.request.facts.runs_in`: the executor's own folder, never the agent's words; harness `confirmRunsIn`). **"Removes" blocked**: telling what a command removes from its text is the parser two reviews fooled (`claude_mapping.py confirm_card`); it comes with Swift's own delete tool (decision 7, not built), whose paths are known |
| §8.3 a Failed card keeps its steps (✓, ! where it failed) and offers "Try again from step N"; after 10 min it moves to the stack, still Failed, counted on the badge (D9) (+ check halo-b8-gaps-6b8791-4, with §8.1) | 3ab5fe8 | built (new `retrying.py`: the step goes to the worker as Swift's context note, never into the owner's words; `retry` takes optional `from_step`; the stack row is the overlay's own, like a timer's; harness `failedPartial`, `?failms=` shortens the 10 min) |
| B13 tree Open / Show in folder / double-click (path from the file system), arrow keys and Enter in the reader (+ check halo-b8-gaps-6b8791-5) | 609d124 | built (new `files.py`: a tree's `root` is kept only if it's an absolute folder in the read folders that exists; each entry gets `found` from the disk; `tree.open` acts only under a folder verified this session and never runs code: .exe/.bat/.ps1/.lnk… are shown in their folder). Structural: new `frames.py` holds the small inbound frames (`due.snooze`, `asking`, `watch`, `tree.open`); session.py 4985 → 4980, ratchet lowered |
| A1 voice "what did you find about …" (+ check halo-b8-gaps-6b8791-6) | 410c2dd | built (`recent.found`: the best-matching earlier answer of this session, again, as this request's answer; nothing runs; intercepted before routing like B14's "done", so parity is unchanged, 413/423). **"Answers from before a restart" blocked, and so is B12's "Open the answer" after a restart:** no answer is kept on disk (run records are content-free by design; the interaction log keeps the owner's words, not answers). Keeping answers adds a kept-data category to `docs/security/privacy.md`, with no retention built yet (§5): the owner's decision |
| A6 captions on by themselves when the sound is muted or Windows Live captions runs, until the owner says on or off (+ check halo-b8-gaps-6b8791-7) | 0326562 | built (`captions.refresh` on each lifecycle tick (60 s) and each overlay: `control.get_mute` and `tasklist` for LiveCaptions.exe, read only; "captions off" is now kept as a record, so a muted PC doesn't turn them back on). Up to a minute late after the sound changes |

Group 1 is done (B5, B7, B14, B4, B6, "ask me about everything"; A2 blocked). `session.py` is at its ratchet (4985):
nothing more goes into it.

## B3 (grayscale)

Captured in headless Edge with `grayscale(1)`: OK (light band, shield, "Needs your OK"), Waiting (tag pill, 5 px
ring), Working (spinner, "Working", m:ss, steps), Stopped (one-line row, square mark), Failed ("!" disc, "Failed",
full card), Due (bell, "Due · now", 1 px accent border and 5 px ring: D8's default). Each pair the spec names differs
in at least two ways that survive grayscale (band or tag or row, mark shape, the word). No change needed.

## Where it is now

Stopped here (a natural end, not a credit stop): everything below is not built and recorded as such.

## Left, in the README's order

1. **F8:** owner check halo-b8-build-4fbdf7-1 written. No `AllowSetForegroundWindow` change unless it fails.
2. **Step B, what's left:** a rule-by-rule cull of old `styles.css` rules Halo's later rules override (needs before
   and after captures of every state). Stack section labels (RUNNING, EARLIER TODAY) wait for A1.
3. **B-items, partial parts** (each commit says what it lacks): §8.1 "Runs in"/"Removes" rows (not on the confirm
   frame); §8.3 "Try again from step N" and a Failed card moving to the stack after 10 min (D9); §8.4 a sender for
   scheduled/watching errors; B5 node-boundary cuts and "Show all · 11 rows"; B7 tail ordering and the deck moving
   160 ms after a drain; B14 Edge · Timer, the stack RUNNING row with Cancel, voice "done"/"5 more", "Done: Tea
   timer"; B4 D7 (charts have no pick) and the fallback line; B13 Open / Show in folder / double-click (path from the
   file system) and reader arrow keys; B6 step counts and the console line; B9 docked and mini placements (a Windows
   app bar), the tether, B12 "Open the answer" from the run record after a restart.
4. **Modes study:** §3 built. **§1 learned trust and §2 the plan card not built**: both are product-rule work (one
   lowers an approval level and adds an offer card; the other adds `propose_plan` and grants used in order) and
   deserve their own session and review. Also not built for §3: the tray's "Asking about everything" status and
   "Stop asking" item, the line on the gateway's own cards.
5. **A-ideas:** the "Do next" list is done except A7 and A3: A5, A6 (partial: captions don't yet turn on by
   themselves when the sound is muted or Windows captions are on, since Swift reads neither), A9, A4, A1, A2, A8.
   **A7** built after the owner's approval: its hotkey opens the text box on the card's buttons, so it stays the text
   box's exception (CLAUDE.md unchanged; action-authority.md and the B8 README say how). **A3** hold during calls is skipped until the call-detector spike exists.
   Explore: A12 built (out of the README's order, before A5; nothing depended on it), behind `explore.orb_glance`,
   off by default. **A10, A11, A13 not built**, by instruction; their off-by-default switches are already in
   `config.yaml explore`.
6. **The live loop on the real window** (`docs/testing/live-ui-loop.md`: the isolated test build, `seq.mjs`) was not
   run. What ran instead, in headless Edge against the dev harness (no backend): grayscale (B3), reduced motion
   (B7), forced colours (every new part), the confirm fit in a short window at 1.5× (§8.6), the orb's position at
   three anchors (§8.5), and captures of every new state in dark and light.
7. STT corrections (`claude/stt-corrections`): left alone as asked.

## New owner checks (provisional ids, `plan.py --renumber` at merge)

halo-b8-build-4fbdf7-1 F8 the text box gets the keyboard · -2 F1-F4 a lapsed OK · -3 F6/F7 "stop" · -4 every surface
(board 9) · -5 D10 "Swift is ready" · -6 B5 grow and Show all · -7 B7 motion · -8 B14 timer on the orb, +5 min · -9
"ask me about everything" · -10 A12 orb glance · -11 A9, A4, A5 · -12 A6 captions · -13 A1 earlier today · -14 A2 follow-up · -15 A8 how
Swift shows things · -16 A7 keyboard entry. Report lines (LOOK) and ledger areas are in.

## Harness states added

stackPile, stackOpen (one click), typeFollow, typeKeyed, typeFix, trayListening (pane.html), noticeReady,
noticeRunning, noticeHoldToTalk, noticeNotCaught, problemStarting, problemReconnecting, problemRestarting,
problemStopped, problemCantRestart, problemHotkey, followup, confirmAgain, failedScheduled, cardCapped,
cardExpanded, timerOrb, timerTwo, timerDue (+5 min), treeCard, pinned, caveat, capsuleCaptions, stackRecent,
followupThread, trayDisplay (pane.html). Harness without `?port=` now draws
design states (a stand-in socket); `?explore=1` turns the glance on.

## Review flags (product-rule fixes: another author must review)

- **F1** (a lapsed OK and the front), **F2** (no OK brought forward without the owner), **F6** and **F7** ("stop"
  before a run and with nothing running) change confirm and stop behaviour.
- **"Ask me about everything"** (64dd679) changes where cards are decided (gateway, system lane, step grants). The gaps branch adds its tray item (turns it off only) and the gateway's `because=` line (display only, never in the digest).
- B14 added `timers`/`due.snooze` frames and `due.snooze` sets timers from Swift's own items: worth a second look.
- A5 gives the worker a new tool (`add_caveat`); what it says shows on Done cards, marked as the worker's.
- A12 makes the idle orb take the pointer, only when `explore.orb_glance` is on.
- **b3721d3**: "ask me about everything" off only by speech; fails closed. **373e932**: typed text then Enter never
  presses a card button (a race between the pane and the main window). Both product-rule fixes.
- Seen, not changed (806a75d): the backend accepts a `confirm.reply` for an OK in the stack, off screen; the overlay
  can only send one for a card it shows.
- Not changed, worth a decision: memory facts ("remember that …") typed in the text box are still stored as `said`;
  only the asking setting now records `typed`.
- **A7** (943d42e) is a focus-rule change: a hotkey opens the text box on the card's buttons. Tested by
  `overlay/tests/focus.test.ts`.
- A6 and A1 add optional fields to existing frames (`speech.text`, `stack.recent`); captions and "ask me about
  everything" are kept as records in the memory store (keys `captions-on`, `asking-everything`), left out of
  "what do you know about me".
- The new capability permission `core:app:allow-version` (read-only, for D10) should be looked at too.

## Tests at the stopping point (373e932 + this file)

- Python: 2397 passed, 1 skipped, 31 xfailed, 0 failed (full suite).
- Overlay: `tsc --noEmit` clean; `npm test` 172 tests, 170 pass, 0 fail (2 known "todo" findings).
- Rust (`cargo test`): 41 passed.
- Vite production build: OK.
- Routing parity: 413/423, the same ten web misses as before this branch.
- `grep -rE "data-look|VITE_SWIFT_LOOK|look=halo" overlay` (excluding `node_modules`, `target` and the git-ignored,
  stale `dist`): nothing.

## A full run that failed test_example_file_is_valid (checked 2026-11-18)

The orchestrator's full Python run "on 0e4112b" ended 1 failed: `tests/unit/test_settings.py::test_example_file_is_valid`,
passing on its own. Cause (reproduced): that run used this worktree while A7 was being written. The run imports
`swift.settings` at collection; minutes later the test reads `config.example.yaml`, which by then had A7's
`hotkeys.card` line, which 0e4112b's `Settings` forbids (`extra="forbid"`): `SettingsError: config.example.yaml:
hotkeys.card: Extra inputs are not permitted`. 0e4112b's settings with 0e4112b's example pass; HEAD's pair passes; the
full suite at 943d42e passed (2391). No code fix: don't run the suite in a worktree another session is editing.

## Notes for whoever picks it up

- Harness design captures: run the harness **without** `?port=` (the live debug backend re-sends an empty stack and
  wipes an injected one). A headless-Edge CDP capture script is easy to rebuild: navigate to
  `dev/harness.html?theme=…`, call `__design(name)`, then `Page.captureScreenshot`. `dev/pane.html?label=…&state=…`
  does the same for panes.
- `session.py` is at its line ratchet (4985). Put new backend logic in small modules, as `stops.py` does.
