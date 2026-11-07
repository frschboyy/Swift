# ADR-018: The Deck: how requests share the screen

- **Status:** Direction accepted by the owner (2026-11-06). Step 1 is built on a branch (2026-11-07), not merged and not yet run on the real PC. Building it needed one backend change, which the owner approved: see §4.1.
- **Decided by:** Owner
- **Date:** 2026-11-06
- **Amends:** ADR-013 §3.1 and its "commands go to the request in front" (§4.1 below), ADR-015 §3 (request windows go, and the main window draws other requests), ADR-015 §11 bug 4 (the "Got it" pill goes), ADR-013 §11 and `FINISHED_ROW_S` (in Step 2), ADR-017 §2.1 (what the capsule shows while a card is open)
- **Keeps:** ADR-015 §9, the owner's waiting stack: its corner, double-click to expand, click outside to fold, Open / Skip / End. ADR-017: the capsule is Swift's body, and cards grow out of it.
- **Prototype:** [Swift Overlay Motion Study](https://claude.ai/artifact/1bAiWg7RaY64DgCewuQbLY), private to the owner. It plays today's model, the Deck and the two rejected models through the same scenarios.

## 1. Why

The owner asked for a cleaner, more fluid way for requests to coexist, without stacked pieces competing for attention. Their example: a second request shouldn't take centre stage, but hiding it gives too little assurance that it was received.

What the code does today (the prototype's page has the full critique):

- At the default anchor, a chip opens in the top-right corner, over 1,100 px from the card (`panes.rs` `default_origin`).
- The acknowledgement comes in unconnected pieces: "Got it" for 2.5 s (`ACK_MS`), then a chip elsewhere after 600 ms (`CHIP_DELAY_MS`).
- Each pane is clipped to its own window, so nothing can move between surfaces.
- A card waiting behind another shows as a chip, a line and a stack row at once.
- An answer that finishes in the background disappears after 20 s (`FINISHED_ROW_S`).

## 2. Decision

A request is in one of three places, and each place has one meaning.

| Place | What's there | Where |
|---|---|---|
| **In front** | The one thing the owner is dealing with, and the only thing a voice answer can reach | The main card, growing out of the capsule |
| **Behind** | Everything still in flow: running, next in line, ready | Labelled edges behind the card, in the main window |
| **In the corner** | What was put aside and waits for the owner | The waiting stack, a pane window |

Rules:

1. **The card in front never moves because of something else.** New arrivals pass behind it.
2. **Nothing swaps under the pointer or while the owner is talking** (Step 2). A due card waits as a visible amber edge, with no countdown until it's on screen.
3. **A request has one body from start to finish.** Words, edge, card and fold-back are one element changing shape, so it never shows in two places.
4. **One timing curve.** The design's easing, 280 ms for moves, 160 ms for surfaces, never overshooting. Reduced motion is a 120 ms fade only.
5. **The capsule says only what the card can't.** While a card is open it shrinks to the orb, unless it is listening, speaking or paused. The paused state is the privacy indicator and is unchanged.
6. **Amber means an OK is waiting,** nothing else. The stack's badge is neutral unless a card inside needs one.

## 3. The owner's decisions (2026-11-06)

| Question | Answer |
|---|---|
| Which model? | The Deck (rejected: Beads, Field) |
| Other requests can no longer be dragged on their own. OK? | Yes. They move with the main card, and Watch still opens a free-floating live view |
| Can Step 1 go before review item 9? | Yes. This departs from the reliability review's order (§7) on purpose: Step 1 only changes how existing rows are drawn, and everything that needs item 9 stays in Step 2 |
| How does a card reach the corner? | A handoff between windows now, with a spike on one large window after Step 1 is on the owner's screen |
| When is Step 1 built? | After the short real-PC checks and before the two weeks of daily use (handoff §4, between c and d). **Changed by the owner on 2026-11-07:** built before the short checks, which they weren't in a position to run. So those checks now test the reliability fixes and Step 1 together |

## 4. Step 1: the Deck, overlay only

No protocol change: `runs` rows already carry title, words, state and activity from the moment a request starts (`_chip_now`). The backend still decides what is in front, so a due confirm card takes the front at once, as today. It now shuffles instead of cross-fading.

One commit each, in this order:

1. **`overlay/src/deck.ts`, pure, with tests:** rows to an order, and each edge's depth and inset. It holds at most 3 edges, then "+N". Stable order: a new request goes on the far end.
2. **Edges in the main window, one drawing path.**
   - `drawRows` draws edges with `views`' chip content, and each edge is a hit region (`data-hit`). A click still calls `askFocus`.
   - The card's max height gives up the deck's height.
   - The harness now draws what the owner sees, which removes a limit the handoff lists.
3. **The request landing.** A new row's edge starts at the capsule's rectangle, below the card, and moves to its slot, saying "Got it: …" for 2.5 s before it settles. This replaces the pill. Instant answers (under `CHIP_DELAY_MS`) don't flash an edge.
4. **Remove the request panes.** Delete:
   - `PaneKind::Request`, `chips_from_top`, `STACK_RESERVE`, `places.request`. An old `overlay.json` must still load: check with a `prefs.rs` test;
   - `CHIP_DELAY_MS` as a window delay, `MAX_PANES`, `requestRows`, and the request branches of `wantedPanes`, `pane.ts` and `paneSize`;
   - `#gotit`, `drawGotIt`, `acks`, `ACK_MS`, the `.gotit` styles, and the "more cards waiting" line;
   - the tests that only cover these (`panes.test.ts`, the chips cases of `panes.rs`). The stuck-chip sequence (bug 1) stays for the panes that remain.
5. **The shuffle.** A small helper animates an element from its old rectangle to its new one, for swaps and for a card folding back into the capsule. Reduced motion skips it.
6. **The capsule's orb** while a card is open (`capsule.ts`, with tests).
7. **The stack's look.** A neutral badge and glow unless an OK waits; layers unfold into rows; a handoff at its edge in the direction of the main window. `fit_pane`, `watch_outside` and its behaviour stay. Check against b9ca8c3: a pane sizes to layout, not mid-animation.
8. **Read more folds the deck** to one edge ("2 more running"), so a long answer isn't squeezed. That was the owner's objection in ADR-015 §1, and the prototype doesn't show it, so it's the first thing to check on the real screen.

**Checks that go with it:**

- Overlay tests for `deck.ts` and the deletions. Rust tests for the placement that remains.
- A seam scenario in `tests/unit/test_seam_replay.py` for what the rows now mean on screen: second request, third, a card coming forward. It must fail with the fix undone.
- New owner checks and report lines, starting at 168. Rewrite the existing checks that name chips or a dragged chip window (at least 17–21, 25, 152, 158, 164, 165; the rewrite must look for others).
- Top anchors mirror the deck. The prototype shows only bottom centre, so check all six in the harness.
- The final line count. This is a structural step, so it should remove more than it adds. If it doesn't, say so to the owner before keeping it.

**Not proven until the owner runs it:** how the edges feel on the real screen and whether WebView2 animates them smoothly. The prototype simulated the windows in one page.

### 4.1 What building Step 1 found (2026-11-07)

**Rule 1 and the backend disagreed.** The prototype has a second request land behind a card that doesn't move. The backend, under ADR-013 §3.1, gave the front to a request said beside a working card at its first `state` or `step`, usually within milliseconds, so the new request took centre stage: the owner's own example in §1. **The owner's decision (2026-11-07): it stays behind.** So Step 1 isn't overlay only after all. No message changes.

- **What takes the front:** only what the owner must see: its answer or an error (`TAKES_FRONT`), its confirm card, and its question. Progress stays on its edge. A request stopped by name doesn't come forward to say so.
- **A long request that finishes behind the card still comes forward, even over a card being read.** Holding it until the owner is clear is Step 2, and needs item 9. An answer it displaces stays as an edge for 20 s, and a click opens it. Only the newest request said comes forward: an older one behind it says "Ready to read" for 20 s, as before, and so does one that finishes while a confirm card is up.
- **A request being spoken comes to the front:** the owner is talking to it.
- **"Stop" and a change of mind.** The card in front is what they mean, so they could reach the older request just after the owner said a new one. While the request just said hasn't been in front, a plain spoken "stop" or "actually …" asks which, and nothing stops or changes. Naming one, "stop everything", Esc and the card's Stop button work as before. A confirm card or a question on screen settles it: those keep their own answers.
- **With an answer on the card,** spoken "stop", "stop it", "stop that", naming one and "stop everything" reach those behind it: with one behind, a plain "stop" stops it; with several, it asks. "Never mind", "enough", "quiet" and "cancel" stay with the answer. Esc doesn't reach them, because an answer has nothing to stop. **With the hotkey or by typing, "stop" here brings the one behind forward without stopping it**, so it takes a second "stop". A reply to the answer stays a reply, and joins the answer's conversation.
- **On a tie, a name means what's still running, then the card on screen** ("stop the research one" with two research requests).
- **A said or typed answer reaches only what's on screen.** The independent review found this wasn't true on three paths, all older than this work: more words after the name, typing, and a recorded answer with wake listening off. There is now one gate, in `_take_answer`; only a click on the question's own button is exempt. **An answer refused this way can still start a request when it's long enough:** "Swift, yes please turn it off now" with the question hidden goes to the agent as a request. Wi-Fi stayed on in every reproduction, but what a real agent does with those words is unproven.
- **A question said over:** a new request during Swift's question still sets it aside to the stack, as it did, and now passes behind.

`test_deck_requests_keep_their_places_as_they_come_and_go` fails with the old `TAKES_FRONT`. The review's reproductions are kept in `tests/unit/test_front_rules.py`.

**With wake listening off,** the microphone opens for an answer only under `_may_record_answer`, and the recording follows the question on and off the screen. If the question leaves the screen while the owner is speaking, those words are lost without notice; the recording starts again when it's back.

**Passed by the independent reviewer (2026-11-07):** the answer gate. **Checked and held:** no hands-free listening while locked. **Not covered by it, and waiting for the owner's ruling:** "Say yes and I'll send a correction" isn't a question, so a "yes" takes that offer with its card hidden, and typed "yes" works there, though a spoken bare "yes" doesn't. That's older than this work. The correction would need its own card to send, though that's from reading the code and hasn't been run. Also older: with its question on screen, the hotkey starts a new request instead of answering a question from the system lane; a click, typing and the open mic all answer it.

**Left for the owner, from the same review:** only the newest request counts as "just said", so with three running, after the newest stops, a plain "stop" reaches the card though an older one is still behind; and "pause" and "mute" don't ask which, though "pause" keeps the request as unfinished. Also still open: a provider that won't start at all, behind the card, shows its error with the old request's words; and a typed request coming forward shows the mic icon.

**After a swap, a card named the wrong request.** The backend sends a request's words once, so a card brought forward kept the last card's words and clock, and could show its finished artifacts. `onRuns` now takes them from the row (`wordsComingForward`), which the seam checks as `cardWords`.

**A row's id changes** from `req-…` to the provider's id when its run starts. `deck.ts` treats a new id with the same `started_ms` as the same request.

**Line count.** Step 1 adds more than it removes: source, overlay and Rust +899, −363, a net of +536, of which `deck.ts`, `deckdraw.ts` and `shuffle.ts` are 340 and the rest is mostly the edges' styles. The deletions are what §4 lists. This misses the structural-step test in `CLAUDE.md`, so the owner decides whether to keep it. The spike in §6 is where most of the window code would go.

## 5. Step 2: hold, in-line and ready rules (needs review item 9)

The overlay can't safely delay a card alone. The backend treats the first in line as on screen (`_open_confirm`, `_on_screen` in `session.py`), so a card still drawn as an edge could be approved by voice. That would break a product rule.

What Step 2 needs from item 9:

- a versioned snapshot naming `front`, the ordered `behind`, and `stack`;
- an acknowledgement of the version actually drawn, which `_open_confirm` and `_on_screen` then read;
- an inbound "busy" signal (pointer on the card, Read more open). The backend decides when to swap, and the overlay only reports. While the microphone is capturing, the backend already knows.

Then:

- A due card holds as an amber edge until the owner is clear.
- Cards in line leave the stack list and show only as edges.
- The card that was displaced comes back when the front is free, instead of the newest (`presenter.promotion`).
- Ready answers come forward by themselves, replacing the 20 s row (`FINISHED_ROW_S`).

This step touches a product rule, so someone other than the author reviews it. It also ends the silent refusals at `presenter.ts:273–277`, which is item 9's own goal.

## 6. Spike: one large window (after Step 1, about half a day, unproven)

The main window spans the work area. The stack, live view, reader and tray menu become DOM inside it, so cards really fly to the corner and dragging needs no window moves. The typing box keeps its own window for focus. This would delete most of `pane.ts`, `PaneSync`, `panes.rs`, `drag_pane`, `fit_pane` and `watch_outside`, and reverse part of ADR-015.

Measure on a branch, against today's windows on the same PC:

- WebView2 memory and GPU, idle and animating;
- full-screen video and a game underneath;
- click latency through the 33 ms hit-test poll;
- whether Windows treats it as a full-screen app (notifications, Focus Assist);
- what happens to dragging between monitors.

Keep it only if it's no worse on each of these and removes more than it adds. Otherwise, handoff stays and nothing is lost.

## 7. Alternatives considered

- **Beads** (dots on the capsule): the smallest build and the calmest, but with no names on screen. That breaks the design's "a word with every state icon" and makes "stop the research one" harder to use without looking.
- **Field** (one surface, everything flies): the most striking, but it pulls the eye away from the active card and needs the unmeasured one-window surface from day one.
- **The stack inside the deck:** simpler, but it reverses the owner's own design with no strong enough reason. Things in the corner are out of the flow, and the separation is useful.
- **A tear-off chip:** dragging an edge off would keep free chips, but also keep the request pane code. The owner chose to drop them.
