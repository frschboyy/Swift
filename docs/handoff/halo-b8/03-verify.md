# Verify

"Built and functional" means all four layers below pass, then the owner checks. Commands are
`docs/testing/strategy.md` §3 (worktree rules, the main checkout's venv, never port 1420).

## 1. Unit, overlay and Rust

- Python: `PYTHONPATH=src /c/Users/frchi/Documents/Swift/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
- Overlay: `npx --no-install tsc --noEmit` and `npm test` in `overlay/`; Rust: `cargo test` in `overlay/src-tauri`.
- Pure logic gets unit tests next to the module (e.g. the cap height for B5, relative times for §8.2, the fold-same-rows
  rule for F5, the timer pill text for B14, the tree's middle-cut names for B13).

## 2. Seam scenarios (anything on screen)

Add to `tests/unit/test_seam_replay.py`, each failing before its fix:
F1 (expired OK frees the front), F2 (no stacked OK comes back without the owner), F3 (overlay restart shows the pile),
F4 (stage follows the presenter), F6 (stop before the run starts says so), F7 (stop with nothing running keeps the
Stopped card). Plus one per new on-screen behaviour where frames are involved: stack list contents and counts, the
follow-up window, the "again" line, timer edge/stack row, run link + tether data, A2's follow-up thread, A3's held count.

## 3. Harness design states

Add `__design` states (`overlay/dev/scenarios.ts`) for every frame on boards 4–9 marked PROPOSAL that the code now draws,
so each can be seen in the browser harness in dark and light at all six anchors: e.g. `stackPile`, `stackPileOk`,
`stackOpen`, `typeFollow`, `typeConfirm`, `typeKeyed`, `typeFix`, `trayListening`, `trayPaused`, every notice
(`noticeReady` … `problemHotkey`), `followup`, `confirmAgain`, `cardCapped`, `cardExpanded`, `treeCard`, `timerOrb`,
`timerEdge`, `timerDue`, `watchMonitor`, `watchDocked`, `watchMini`, `watchEnded`, `readerOpen`, `caveat`, `pinned`,
`glance`. Compare each against its board frame (`boards/*.png`) side by side.

## 4. The live loop on the real window

`docs/testing/live-ui-loop.md`: build the isolated test overlay (own identifier, `C:\st\t`), run the debug backend with
test hotkeys, then `node spikes/live_ui/seq.mjs <out> messy,conflict,repeat,timeout,hotkeys,engine`. All steps must be
`ok` except known-by-design items (`02-fixes.md` §4). Add sequences for what you build:
- B5: a long answer at the cap; Show all; Show less; Esc; an OK arriving while expanded.
- B14: set a timer, a card in front, the timer due, +5 min, Done.
- A3/A12/A13 once built: hover the orb (glance appears, no focus change), a second monitor if present.
Grayscale check for B3: capture the webview of OK, Waiting, Working, Stopped, Failed cards and desaturate; each pair
must still read apart. Reduced motion (`prefers-reduced-motion` via CDP `Emulation.setEmulatedMedia`) and forced colours
(`Emulation.setEmulatedMedia` with `forced-colors: active`) for every new surface. 150%: the confirm-fit sequence
(§8.6) with a short window.

Safety (the driver enforces it; keep it): never port 1420 or the owner's hotkeys; keys only to a checked foreground
window; clicks only where the point belongs to the test overlay; no full-desktop captures.

## 5. Owner checks

Number new checks in `docs/testing/owner-checks.md` (+ report lines in `spikes/owner_checks/report.py`, `plan.py`
at merge) for what only the real PC and the owner can judge: the B7 motion feel; B5 expand/collapse on real work; the
docked watch shrinking the work area; the text box getting the keyboard from another app (F8); captions (A6);
hold-during-calls with a real Teams call (A3); the orb glance and monitor-follow (A12, A13); the STT flag
(stt-corrections-1). Real speech, accents, noise and talking over Swift stay owner checks until an audio-file source
exists (`live-ui-loop.md` §5.1).
