# Halo Step B: hand-over (2026-11-14)

Branch `claude/halo-step-b-c7b584` (worktree `a9-gmail-focus-03dda1`), 5 commits on `ca28895`, not pushed, not merged:

- `be5a984` blocks.ts: answer blocks shared by the card and the reader pane
- `fc3b8c6` card.ts: one card renderer for every card; the two question cards merged
- `8f89098` look/dress.ts reads the card's state (`data-card`), not class names
- `0678d7f` lineAboveFoot: a line said on a card goes above its footer in one place
- `93a127a` owner checks 303–304, report lines, ledger, ADR-019 §9, handoff row

## Line counts (`git diff --numstat ca28895 HEAD -- overlay/src overlay/tests`)

| File | + | − |
|---|---|---|
| overlay/src/main.ts | 112 | 302 |
| overlay/src/card.ts (new) | 95 | 0 |
| overlay/src/blocks.ts (new) | 80 | 0 |
| overlay/src/pane.ts | 4 | 23 |
| overlay/src/look/dress.ts | 13 | 14 |
| **Total** | **304** | **339** (net −35) |

Tests: no test file changed.

## Card kinds the map found, all through the one renderer

Working (full and one-line), approval (calendar, change, email, command with B1 lead, B2 step, file change),
answer (line, text, table, long, Read more), artifact opened after a run, Stopped / Not done, Swift's question
after an answer, a run's question (choice, Swift's own yes/no, speaking), due (timer, alarm, reminder, away),
Swift's notices (ready, already running), problem with a request (Failed) and without (plain, info).
Not through it: deck edges and stack rows (views.ts: a run's other sizes, SPEC §7, drawn in pane windows),
the live view and the reader pane (pane windows; the reader now shares blocks.ts).

## Pixel check

Harness, headless Chrome over CDP (Edge's debugging port won't open on this PC), 720×560 at 100%, frozen clock,
reduced motion and zero-length CSS animations, spinners and level bars stopped. 50 states (the 45 `__design`
states plus asks, B1/B2/file approval cards, plain and info problems, a list answer, the reply-window line) ×
both looks × both themes = 200 captures. `main` was a `git archive` of `ca28895` served on port 1436; the branch
on 1434 (1431 was taken by another process; nothing used 1420).

- main vs main (noise floor): 197/200 identical; 3 differ by 6 px (Halo confirm cards, the listening bars).
- branch vs main: 197/200 identical. **Default look: 100/100 identical.** Halo: 3 differ, 6–22 px, an 11×11 px
  corner patch at most 14/255; their DOM is identical except the new `data-card` attribute, and a re-capture of
  Halo light matched `main` on `confirmAway` exactly. So: noise.
- Screens: `halo-step-b-screens/` here (13 states × 2 looks × 2 themes), plus `capture.mjs` and `compare.mjs`.

## Suites

overlay `tsc --noEmit` clean; `npm test` 134 tests, 132 pass, 0 fail, 2 todo (both are O-03, which node:test counts at two levels).
Python: 2116 passed, 1 skipped, 35 xfailed, with the known privacy test deselected. Routing parity 413/423, 0 harmful (unchanged).

## Decisions left for the orchestrator (nothing here was taken)

1. ADR-019 §8's Step B items: fold the deck when a compact confirm still doesn't fit; confirm/question origin line;
   "just now" instead of clock times; Failed not fading; a problem with no request saying Failed; the orb moving at a right anchor.
2. Making Halo the default and deleting the look switch (look/index.ts says "Step B deletes this switch"). The brief
   kept both looks, so the switch and dress.ts stay. Doing it would delete dress.ts and much of the default card CSS.
3. Edges and stack rows staying out of the card renderer (my call; say if you want them in).
