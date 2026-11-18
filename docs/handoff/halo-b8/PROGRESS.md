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

Each fix F1, F2 and F5–F7 has a seam scenario in `tests/unit/test_seam_replay.py` that fails without its fix (checked
by undoing the fix). F3 and F4 fail with F1 undone.

## B3 (grayscale)

Captured in headless Edge with `grayscale(1)`: OK (light band, shield, "Needs your OK"), Waiting (tag pill, 5 px
ring), Working (spinner, "Working", m:ss, steps), Stopped (one-line row, square mark), Failed ("!" disc, "Failed",
full card), Due (bell, "Due · now", 1 px accent border and 5 px ring: D8's default). Each pair the spec names differs
in at least two ways that survive grayscale (band or tag or row, mark shape, the word). No change needed.

## Where it is now

Board 9 §1, B3, the ADR-019 §8 items, B5, B7, B14, B13 and B4 are done (partials as marked). Next: B6/B9–B12 (the
watch), then the modes study, then the A-ideas.

## Left, in the README's order

1. **F8:** owner check halo-b8-build-4fbdf7-1 written (6bd887e). No `AllowSetForegroundWindow` change unless it fails.
2. **Step B, what's left:** old `styles.css` rules that Halo's later rules override were not removed one by one
   (ADR-019 §10 says so). Section labels in the stack list (RUNNING, EARLIER TODAY) come with B14 and A1.
3. **B-items:** all but B6/B9–B12 done (partials in the table).
4. **Modes study** (`01-build-spec.md` §4): not started.
5. **A-ideas:** the nine "Do next" (A5, A6, A9, A4, A1, A2, A7, A3, A8), then A10–A13 behind a setting that is off by
   default, each with an owner check. Not started.
6. Not done either: owner checks for the new surfaces; ADR-019 §10's before/after captures; the live loop on the
   real window (grayscale, reduced motion, forced colours, 150%). Only headless-Edge harness captures exist (dark and
   light, some anchors).
7. STT corrections (`claude/stt-corrections`): left alone as asked.

## Review flags (product-rule fixes: another author must review)

- **F1** (a lapsed OK and the front), **F2** (no OK brought forward without the owner), **F6** and **F7** ("stop"
  before a run and with nothing running) change confirm and stop behaviour.
- The new capability permission `core:app:allow-version` (read-only, for D10) should be looked at too.

## Tests at the stopping point

- Python: 2378 passed, 1 skipped, 31 xfailed (full suite, after F7; nothing in `src/` changed since).
- Overlay: `tsc --noEmit` clean; `npm test` 158 tests, 158 pass, 0 fail (plus 2 known "todo" findings).
- Vite production build: OK (after Step B).
- Rust (`cargo test`): 41 passed (after the resume, with the capability change of 982b154).
- `grep -rE "data-look|VITE_SWIFT_LOOK|look=halo" overlay` (excluding `node_modules`): clean except the git-ignored,
  stale `overlay/dist` (mermaid's own `data-look`, from 2026-11-15).

## Notes for whoever picks it up

- Harness design captures: run the harness **without** `?port=` (the live debug backend re-sends an empty stack and
  wipes an injected one). A headless-Edge CDP capture script is easy to rebuild: navigate to
  `dev/harness.html?theme=…`, call `__design(name)`, then `Page.captureScreenshot`. `dev/pane.html?label=…&state=…`
  does the same for panes.
- `session.py` is at its line ratchet (4985). Put new backend logic in small modules, as `stops.py` does.
