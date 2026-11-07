# What changed from the pack at `b9ca8c3`

For the owner. This pack was rebuilt from `main` at `6cdc25f` (52 commits later). The old pack is kept unchanged beside it in `docs/design/pen-dev-handoff-b9ca8c3/`, so you can compare them or delete it.

## What was wrong in the old pack

**Old `README.md` (the brief)**

| It said | Now |
|---|---|
| "Don't redesign how several requests are arranged yet. That decision is open" | Decided: the Deck. The brief now asks directions to draw it |
| Six states to draw | Eight, adding the deck and the deck folded for a long answer |
| "Show the visual language for a chip" | There are no chips |
| With several requests "the screen fills with similar shapes" | Written about the chips. Replaced with what the edges look like now (draft, yours to edit) |
| "Motion between windows is being worked out separately" | One curve and 280 ms moves are built; windows still can't share motion |
| `28-concurrent` "is a harness layout", chips in their own windows | The harness now draws what the app draws |
| "Cards are currently up to 512 px wide", with no window size | Added: the main window is a fixed 720×560 |
| 34 overlay states and 14 windows | 35 overlay, 15 Deck and 12 window states |

**Old `INTERACTION.md`**

- Part 2 called the Deck a proposal the owner "hasn't chosen". It's now described as current behaviour.
- The "Got it" pill: gone. The edge says it instead.
- Chips as windows that can be dragged: gone.
- "A confirm card that's due waits as an amber edge while your pointer is on the card": **not built.** That's Step 2. Today it takes the front at once.
- "A card waiting behind another can show as a chip, a line and a stack row": the chip and the "more cards waiting" line are gone. It can still be an edge or a stack row until Step 2.
- "An answer that finishes in the background disappears after 20 s": still true, and still Step 2.
- Missing altogether: the capsule shrinking to the orb, the neutral stack, Read more folding, what takes the front, and "stop" asking which.

**Old screenshots showing behaviour that no longer exists**

| Old file | What's wrong |
|---|---|
| `p07-chipRunning`, `p08-chipNeedsYou`, `p09-chipReady` | The windows no longer exist. Removed, and the later `p` numbers moved up |
| `28-concurrent` | Chips stacked under the card, instead of edges behind it |
| `06-capsuleWorking` | A capsule saying "Working on it" under a card that says the same |
| Every state with a card open | The capsule isn't yet the orb alone. `06` and any working card show the pill; I checked `06` by eye and the rest from the code at `b9ca8c3` |
| `29`, `p10` | Stack always amber. Neutral is now possible (`p12`) |
| All overlay states | Taken at 1184 px wide, not the real 720×560. This matters most for `16-answerLongOpen`, which showed far more text than the real window fits |

**Old `tokens.css`:** one token is new, `--dur-move: 280ms`. All colours are unchanged. I added the Deck's geometry and a note on the timing in `shuffle.ts`.

## Not fixed: the darker band behind card footers

You asked me to note this as fixed. **It isn't.** The rule is unchanged since `b9ca8c3`, at `overlay/src/styles.css:408`:

```css
.card-in > .card-foot, .card-in > .confirm-actions { position: sticky; bottom: 0; z-index: 1; background: var(--panel-solid); }
```

On a glass card, the footer's solid colour shows as a band: `rgb(31,33,39)` on a card of `rgba(32,34,40,.88)`. It's visible in dark and light, on any card with a footer except the solid confirm card (`12-answerText`, `10-working`, `27-questionWaiting`). So the brief still lists it as a defect. I didn't find a commit that claims to fix it.

## Bugs and mismatches found (reported, not fixed)

1. **The footer band,** above.
2. **The typing box's approval line falls short of the product rule.** Under a confirm card it says "Typing can't approve. Click Approve, or say “approve”." (`overlay/src/pane.ts:109`, `p03-typeConfirm`). Hands-free approval needs Swift's name or the hotkey, and the confirm card's own hint does name the hotkey. I didn't test what a bare "approve" does here, so this is about the wording only. It touches a product rule, so whoever fixes it needs a separate reviewer.
3. **`docs/handoff/README.md` and ADR-018 are out of date.** They say Step 1 is on a branch, unmerged, and "Keep Step 1?" is listed as open. The Deck's commits are on `main`, and `worktree-deck-step-1` is at the same commit. Either the merge went ahead with that decision still open, or those lines just weren't updated. Only you know which.
4. **The capsule's "Working on it" pill looks hard to reach.** It needs a working request with no card open. I couldn't produce it from the harness, and `__design("capsuleWorking")` no longer shows it. I haven't proved it's unreachable in the app. If it is, it's dead code.
5. **The harness's `__design` reset doesn't close a live view.** Run `liveResearch` then `liveDone` on one page and both panels show. It's harness only, and every capture here used a fresh page.
6. **`__design` can be wiped if it's called too early.** The backend's resync on connecting can arrive after it and return the overlay to idle. This blanked 21 captures on one of my runs before I made the script wait for the resync. It's harness only.
7. **`__design("concurrent")` returns after 300 ms,** while the first edge still says "Got it". I waited for it to settle before capturing. `d02` shows the landing.
8. **`pane.html` has no `wall=busy`,** so the separate windows have no busy-wallpaper shots.

## How the screenshots were checked

There are 140 captures, each from a fresh page, through the harness on port 1431 with its debug backend on 8765.

- **Automatic check on each:** the right theme, the right capsule state, the state's words on screen, the right number and kind of edges, nothing outside the window, and no "Swift is ready" or "Reconnecting". All 140 passed, with no console errors.
- **Leak check:** I also ran all 34 `__design` states in one page, one after another, and compared them with the fresh pages. The only real difference is item 5. `working` also differed, but only by its clock not having appeared yet.
- **By eye:** I looked at every final image, on contact sheets, in both themes and on the busy wallpaper. I didn't open each one at full size.
- **One retake:** `01-capsuleIdle` came out with no dot in the final run, and the automatic check didn't catch it, because an idle dot has no words to check. I retook it in both themes and viewed both. I didn't find out why it happened.

## What I couldn't verify

- **Anything on the real PC.** These are from headless Edge, not Tauri's WebView2 on your screen. How edges feel, whether they animate smoothly, 150% scaling and real transparency are all unchecked. Owner checks 168–182 cover these.
- **Glass over a real desktop.** Blur is rendered against the harness's page background, not your wallpaper or apps.
- **Pane window sizes.** `p` shots are drawn at the size the page lays out, not in a real window that Rust has sized.
- **Motion.** Stills only. The landing, swap and fold were not checked as movement.
- **Five of the six anchors.** Only bottom centre and top centre were captured.
- **Whether the "What bothers us now" list is what you think.** It's still a draft, yours to edit before sending.
- **The state of `d14-deckNoCard` in the app.** It's built from injected frames, as are all the `d` states except `d12`'s base. They use the same frames and stand-in requests as `concurrent`, but no real backend produced them.
