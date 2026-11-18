# Handoff: Halo B8, every surface, the A ideas, and the live-test findings

For the Claude Code session that builds and verifies this. Written 2026-11-18 from the pen.dev work in
`docs/design/halo-system/halo.pen`. **Read this file, then the four below, in order.**

| File | What |
|---|---|
| [`01-build-spec.md`](01-build-spec.md) | Every item to build: what it looks like, how it behaves, where it lives in the code, and when it's done |
| [`02-fixes.md`](02-fixes.md) | Bugs and UX problems found by running the real overlay and by the STT review, each with a reproduction and the test to add |
| [`03-verify.md`](03-verify.md) | How to prove it works: harness states, seam scenarios, the live loop on the real window, owner checks |
| [`tokens-b8.css`](tokens-b8.css) | The new `b-*` tokens (monitor, paper, worker, fade, motion), dark and light |

Background you need: `CLAUDE.md` (working rules, product rules, port 1420 is the owner's Swift),
[`brief-halo.md`](../brief-halo.md) (Step A is built: `overlay/src/look/`, dev-only `?look=halo`; Step B makes Halo
the only look), `docs/design/halo-system/SPEC.md`, `tokens.css`, ADR-019, and
[`docs/testing/live-ui-loop.md`](../../testing/live-ui-loop.md) (how to drive the real overlay).

## What to look at

The design source is `docs/design/halo-system/halo.pen` (open in pen.dev; **the owner must have saved it**: check the
file has the boards below, else ask). Exports in `docs/design/halo-system/boards/`:

| Board | Covers |
|---|---|
| `1-components.png` | The component library, including the "B8 additions" column |
| `4-growth-motion.png` | B5 cards that grow and expand by hand; B7 motion storyboards and timing tokens |
| `5-watch.png` | B6 monitor, B9 placements, B10 card and watch as one run, B11 life, B12 "Open the answer" |
| `6-new-blocks.png` | B13 file tree, B14 running timer, B4 shapes (mind map, document preview, chart, project cards, fallback) |
| `7-open-items.png` | B3 states at three sizes plus the grayscale test; ADR-019 §8's six open items |
| `8-exploration.png` | A1–A13 (ideas, scored) |
| `9-every-surface.png` | Built surfaces Halo never drew: stack pile → list, text box (5 modes), tray, notices and problems, follow-up window, "say approve again"; §6 the modes study (trust offer, trust used, trust list, plan card, "ask me about everything") |
| `stt-corrections-1/` | The STT correction UI on screen, and its review |

Every frame is tagged **BUILT** (today's behaviour) or **PROPOSAL**. Dark and light rows are both drawn.

## The owner's decision: Halo is the main UI (2026-11-18)

The owner has given the go-ahead for Step B: **Halo becomes Swift's only look**, in debug and release builds, with no
switch. Today it only appears with `$env:VITE_SWIFT_LOOK = "halo"; npm run tauri dev` (or `?look=halo` in the
harness). Record this in ADR-019 (Step B approved) and in `brief-halo.md`.

What that means in code (Step B, `brief-halo.md`):
- Delete the switch: `overlay/src/look/index.ts` (`lookFrom`, `applyLook`), the `import.meta.env.DEV` imports in
  `main.ts` (≈ l.185) and `pane.ts` (≈ l.61), `?look=` in `overlay/dev/b4.html`, `overlay/tests/look.test.ts`, and the
  `VITE_SWIFT_LOOK` mention in `docs/testing/owner-checks.md`.
- Halo's values become the only tokens: fold `look/halo.css` (unscope it from `#stage[data-look="halo"]`) and
  `tokens-b8.css` into `styles.css`, delete the old values and every old-look rule Halo replaces. `dress.ts` becomes the
  one card renderer (state line + origin + blocks + footer), replacing the per-kind drawing in `main.ts`. Keep the test
  that `styles.css` matches `docs/design/halo-system/tokens.css`.
- Panes (text box, stack, tray, live, reader) take the same tokens: `pane.ts` loses its switch too.
- Done when: `npm run tauri dev` with no environment variable shows Halo; a release build shows Halo;
  `grep -r "data-look\|VITE_SWIFT_LOOK\|look=halo" overlay` finds nothing; the old look's screenshots
  (`docs/design/pen-dev-handoff/screens/`) are no longer the reference, the boards are; all tests pass.

## Order of work

1. **Fixes first** (`02-fixes.md` §1): real bugs on the confirm/stack path. Each one: a seam scenario that fails, the fix, the scenario passing.
2. **Halo Step B: Halo as the only look** (above, and `brief-halo.md`), extended by `01-build-spec.md` §1 (every surface).
3. **B-items** (`01-build-spec.md` §2), in this order: B3 → §8 open items → B5 → B7 → B14 → B13 → B4 shapes → B6/B9–B12.
4. **Modes study** (`01-build-spec.md` §4): not built yet although all seven decisions were taken 2026-11-14. "Ask me about everything" → learned trust → plan card.
5. **A-ideas** (`01-build-spec.md` §3): the nine "Do next" first (A5, A6, A9, A4, then A1, A2, A7, then A3, A8). A10–A13 are "Explore": build them behind a setting, off by default, and add an owner check.
6. **STT corrections** (`claude/stt-corrections`, 83376f1): merge only with the owner; apply `02-fixes.md` §3 on that branch.

## Rules that every item keeps (don't soften them for looks)

- Amber means an OK is waiting now, nothing else. Red means failure, nothing else. Every mark has a word.
- The state sets the treatment; blocks carry content. Shapes appear only on Done and in the reader, never on an approval or a question.
- Swift never takes focus; the text box is the only exception (A7's keyboard-entry hotkey opens the text box on the
  card's buttons, so it is that same exception, and only the owner's hotkey does it). Only painted pixels take clicks.
- Approval: Swift's own button, the same button from the keyboard (Tab then Enter), or speech with Swift's name or the hotkey held. Typed words never approve. Approve ignores clicks for 400 ms. `intake.approves` is the one place this is decided.
- No provider name on screen ("via Claude" is gone; the byline is "Swift").
- The confirm card never scrolls, and its buttons never leave the window: compact first, then fold the deck.
- Reduced motion: a 120 ms fade only. Forced colours: the amber band becomes Highlight, halos drop. Check at 150%.

## Decisions for the owner (answered 2026-11-18: the defaults below, exactly)

| # | Question | Default |
|---|---|---|
| D1 | B5: does expanding one card pause other Done cards' reading timers? | Only the expanded one |
| D2 | B7: does the orb's "something is coming" brighten for runs Swift started too? | Only for answers asked for |
| D3 | B9: remember the watch placement per kind of run, or reuse the last? | Reuse the last |
| D4 | B10: when the watch is docked, does the tether reach the sidebar? | No; the Run link chip is enough |
| D5 | B12: may the reader take focus when clicked into (a second exception)? | Yes, only when clicked into |
| D6 | B14: two timers: "4:12 · 2" on the pill, or split arc? | "4:12 · 2" |
| D7 | B4 chart: Worker's pick as grey fill (drawn) or grey outline? | Grey outline (bars keep equal weight) |
| D8 | B3: Due's ring 5 px like Waiting, or 3 px? | 5 px (differs by surface, bell, no close) |
| D9 | §8: does a Failed card moved to the stack still count on the badge? | Yes |
| D10 | Every surface: "Swift is ready" on every start, or after an update/crash only? | After update or crash only |
| D11 | A4: one pin or two? | One |
| D12 | A1: ship "Earlier today" with the stack list, or later? | With it |
