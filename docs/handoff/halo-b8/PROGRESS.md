# Halo B8: progress (branch `claude/halo-b8-build-4fbdf7`, stopped 2026-11-18)

Stopped early at the orchestrator's request (the owner's credits were running out). Every commit below passed
its tests when it was made. Nothing is half-done, and there is no WIP commit. Not pushed, not merged.

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

Each fix F1, F2 and F5–F7 has a seam scenario in `tests/unit/test_seam_replay.py` that fails without its fix (checked
by undoing the fix). F3 and F4 fail with F1 undone.

## Where it stopped

Board 9 §1 ("every surface", part of Step B) is done: §1.1–§1.6. Nothing after it has been started.

## Left, in the README's order

1. **F8** (the text box didn't get the keyboard): **not done.** It still needs its owner check in
   `docs/testing/owner-checks.md` (`plan.py --next-id` gives `halo-b8-build-4fbdf7-1`) and a `report.py` line. No
   `AllowSetForegroundWindow` change unless it recurs.
2. **Step B, what's left:** old `styles.css` rules that Halo's later rules override were not removed one by one
   (ADR-019 §10 says so). Section labels in the stack list (RUNNING, EARLIER TODAY) come with B14 and A1.
3. **B-items:** B3 → ADR-019 §8 open items → B5 → B7 → B14 → B13 → B4 shapes → B6/B9–B12. None started.
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
- Rust (`cargo test`): **not run** at the stop. The capability JSON changed in 982b154, so run it before merging.
- `grep -rE "data-look|VITE_SWIFT_LOOK|look=halo" overlay` (excluding `node_modules`): clean except the git-ignored,
  stale `overlay/dist` (mermaid's own `data-look`, from 2026-11-15).

## Notes for whoever picks it up

- Harness design captures: run the harness **without** `?port=` (the live debug backend re-sends an empty stack and
  wipes an injected one). A headless-Edge CDP capture script is easy to rebuild: navigate to
  `dev/harness.html?theme=…`, call `__design(name)`, then `Page.captureScreenshot`. `dev/pane.html?label=…&state=…`
  does the same for panes.
- `session.py` is at its line ratchet (4985). Put new backend logic in small modules, as `stops.py` does.
