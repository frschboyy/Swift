# ADR-015: Overlay windows: room to read, cards that wait their turn

- **Status:** Accepted (owner feedback from the owner checks of 2026-10-27 is the brief; built on the same day)
- **Decided by:** Owner
- **Date:** 2026-10-27
- **Amends:** ADR-013 §3.3 ("the window stays 720 × 560") and §8 ("separate windows per request: rejected"); ADR-013 §5.2 and ADR-014 §4 (when a card's countdown runs)
- **Builds on:** ADR-009 (overlay UX, placement, dragging), ADR-013 (presenter, several requests), ADR-014 (presence, held cards)

## 1. Context

The owner checks of 2026-10-27 found five problems with how the overlay shows things:

| Check | What happened | Why |
|---|---|---|
| 17 | A research result was cut off at the bottom of the overlay; the full answer couldn't be seen. | One 720 × 560 window. The card had no height limit, so a long answer ran off the window's edge, with nothing to scroll. |
| 18 | A held card didn't come back by itself after the owner returned (held 10:58:43, back 10:58:45 in the backend log; nothing redrawn). | The overlay redrew a card that came back only from what it still remembered about it. When that memory had moved on (another request's `runs` message, a replaced card), "back" was ignored, and nothing told the backend. |
| 19 | Cards waiting behind another card didn't come back by themselves. Their countdown ran while they were out of sight, so a meeting set-up ended unfinished instead of being settled. | The backend started a card's countdown when it *sent* the card, not when the owner could *see* it. A card the overlay failed to draw still counted down. |
| 20–27 | "Why do we need to squeeze so much when we have so much screen to use from, as long as we are not covering the screen for too long, overlays can be anywhere, and can be moved." | ADR-013 §3.3 and §8 kept everything inside one window: other requests as 28 px rows, long answers clipped to six rows. |
| 29 | "What's on my calendar" showed plain text, not the table. | The calendar workflow publishes its table as an artifact; the result card only drew the provider's summary. |

The principle stays the owner's: **Swift adapts to the user, not the user to Swift.**

## 2. Decision in short

1. **One movable window per thing that needs the owner's eyes.** The card in front stays in the main overlay window. Each other running request gets its own small window, and a long answer can open in a reader window. Windows go in free screen space, can be dragged anywhere, and their position is remembered **per kind**.
2. **Cards queue, then come forward by themselves,** one at a time, in the order asked.
3. **A card's countdown runs only while the owner can answer it:** the overlay has drawn it, says so, and the owner is present (ADR-014). It pauses while the card is hidden, waiting in line, held, or the owner is away.
4. **Long answers scroll, or open in a larger reader.**
5. **Nothing covers the screen for long.** Windows shrink back to a chip after a quiet period.
6. **Calendar lists render as a table.**

## 3. Windows

### 3.1 Kinds

| Kind | Window | What it shows | Size | Where it goes first |
|---|---|---|---|---|
| **Main** | `overlay`, as today (ADR-009): transparent, click-through outside its cards | The voice orb and the card in front: listening, working, the confirm card, the answer | 720 × 560, the card up to the window's full height; its body scrolls | The owner's anchor (tray menu or drag), flipped away from the caret (ADR-009) |
| **Request** | `pane-run-<n>`, one per other running request (replaces ADR-013's rows) | A chip: spinner, short title, what it's doing, elapsed time. Click: bring it to the front | 300 × 44 | Stacked on the side of the screen away from the main window, newest nearest |
| **Reader** | `pane-reader` | A long answer in full: summary, list or table, scrollable, with Copy | Up to 560 × 70 % of the screen height | Beside the main window, on the side with more room |
| **Waiting** | (part of the main card) | "1 more card waiting" on the card in front | | |

- **Pane windows are sized to their content,** so they are clickable all over and need no click-through regions. They never take focus (`WS_EX_NOACTIVATE`, as the main window), stay on top, have no taskbar entry, and are excluded from screen capture.
- **Without pane windows** (the dev harness in a browser, or a shell that can't open one), the overlay falls back to ADR-013's rows under the card.
- **Moved by dragging anywhere on them** (a press that doesn't move is a click). The position is remembered per kind, as a fraction of the monitor's work area, in `overlay.json` (beside the main anchor), so it holds across monitors and resolutions. A second window of the same kind stacks under the first.
- **Free space:** with no remembered position, a pane goes on the side away from the main window's anchor (left anchor → right side), so it never covers the card in front.
- **At most 3 request windows** (the run limit, ADR-013 §5.2). A queued request (4th) is a line on the card in front, as before.

### 3.2 Who owns what

- The main window keeps the one connection to the backend and the one presenter (ADR-013 §6). Panes are thin: the main window tells each what to show (`pane` event), and a click comes back as an action (`pane-action` event) that the main window sends on.
- Which panes exist is a pure function of the presenter's state and the reader (`overlay/src/panes.ts`): `wantedPanes(presenter, reader, label)`. It is unit-tested like the presenter; main.ts opens, updates and closes windows to match.

### 3.3 Chips after a quiet period

| Window | Quiet means | Then |
|---|---|---|
| Main, working | No new step and no pointer over it for 30 s | It collapses to its one-line compact form (ADR-009); a new step or hover opens it again |
| Main, answer | As today: it fades after its reading time; hover holds it | |
| Reader | No pointer over it and no scrolling for 60 s | It shrinks to a chip ("Research: the history of tea · Open"); a click opens it again. Closing it (×) removes it; "Read all" on another answer replaces it |
| Request | Always a chip | When its request ends: "Done: …" for 20 s (ADR-013), then it closes |

A confirm card never shrinks: it is the one thing waiting for the owner. It is hidden only while held (owner away).

## 4. Cards: queue, come forward, countdown only while seen

### 4.1 Queue

Unchanged from ADR-013 §5.2: one card on screen, the others wait in the order asked, and the card's request comes to the front. What changes is how a card comes back:

- **The backend redraws it** (replays the request's card: state, steps, artifacts, the card) whenever it comes forward: next in line, back after a hold, or brought to the front. The overlay doesn't need to remember a card it hid.
- This fixes check 18. Coming back after a hold, the overlay used to redraw only if its own state still matched the card. Now the backend replays the card first, then sends `confirm.hold` (`held: false`) with the time left.

### 4.2 The countdown

A card's countdown (`confirm_timeout_s`, 120 s) runs only while **all** of these hold:

1. it is the card on screen (not waiting in line: ADR-013 §5.2);
2. the overlay has drawn it and said so (`card.seen`, `visible: true`);
3. the owner is here or idle (ADR-014 §4).

Otherwise it is paused, with the time it had left. Back from being away, it gets at least `return_s` (60 s), as before.

- **`card.seen`** (inbound, new): `{request_id, visible}`. The overlay sends `visible: true` when the card is drawn and not put aside, and `false` when it hides it (held, replaced, the window gone). An overlay that never says so leaves the card paused, never expired: at worst it waits the held-card limit (12 h, ADR-014) and is parked, never lost.
- **Where:** `swift.attention.Attention` (`set_seen`, `require_seen`), used by Swift's own cards (`Session._swift_confirm`) and Claude Code's (`ClaudeCodeExecutor._decide`). A provider without it keeps its plain timeout.
- The overlay's own countdown line follows the backend's: it starts from the `timeout_s` the backend gives on `confirm.request` or `confirm.hold`.

This fixes check 19: a card that isn't on screen can't run out.

## 5. Long answers

- **The card scrolls.** The main card can use the window's full height; past that its body scrolls (wheel, without taking focus). Nothing is clipped without a way to see it.
- **"Read all"** on an answer longer than the card shows (about 600 characters, or a list or table with more than 6 rows) opens the reader pane with all of it. "Show me" on an answer does the same.
- **Reading time** still decides when the card fades (6–20 s, held while hovered). The reader stays until closed or until it shrinks to a chip (§3.3).

## 6. Calendar lists

The calendar workflow's table artifact (`kind: "table"`, phase `done`) is drawn on the answer card: "Your calendar: Wed 28 Oct" with When / What / Where. More than 6 rows: the first 6, and "Read all" for the rest. The provider's sentence stays above it.

Any finished `text`, `list` or `table` artifact is drawn the same way, so other workflows get it for free.

## 7. Alternatives considered

- **Keep one window and make it taller.** Simpler, but a taller window covers more of the screen all the time, and still can't put a background request somewhere the owner chooses.
- **A full webview, with its own backend connection, per window.** Each window would need its own presenter and the backend would need per-window routing. One owner of the state (ADR-006) is simpler and keeps the ADR-013 invariants in one place.
- **Start a card's countdown when it is sent, and trust the overlay.** That is what failed in check 19.

## 8. Implementation status (2026-10-27)

| Part | Where | Checked by |
|---|---|---|
| Countdown only while seen, shown and present: `set_seen`, `require_seen` | `src/swift/attention.py` | `tests/unit/test_card_timing.py` |
| `card.seen` inbound; cards replayed on back and when they come forward; seen cleared when hidden | `src/swift/ipc/protocol.py`, `src/swift/session.py` (`hold_cards`, `_show_next_card`, `handle`) | `test_card_timing.py`, `test_held_cards.py`, `test_runs.py` |
| The presenter says which card is seen (`seenCard`); a card that comes back is drawn whatever the overlay remembered | `overlay/src/presenter.ts`, `overlay/src/main.ts` | `overlay/tests/presenter.test.ts` |
| Which panes exist and what they show | `overlay/src/panes.ts` | `overlay/tests/panes.test.ts` |
| Pane windows: no focus, on top, capture-excluded, sized to content, dragged anywhere, position remembered per kind, placed away from the main window | `overlay/src-tauri/src/lib.rs` (`open_pane`, `close_pane`, `fit_pane`, `drag_pane`), `panes.rs`, `win.rs`, `prefs.rs`; `overlay/src/pane.ts`, `entry.ts` | `cargo test` (`panes.rs`: never over the card in front, chips and reader apart, remembered places stay on screen; `prefs.rs`); owner checks 17–20 |
| Card body scrolls; "Read all"; answers draw finished table/list/text artifacts | `overlay/src/main.ts` (`renderResult`, `finishedArtifacts`), `styles.css` | owner checks 18, 29; in the dev harness at 720 × 560 the card stays inside the window and scrolls |
| Quiet period: working card collapses after 30 s, reader to a chip after 60 s | `overlay/src/panes.ts` (`workingQuiet`, `readerTick`), `main.ts` | `panes.test.ts`, owner checks 19, 23 |

**Not done:** the main window still snaps to its six anchors when dragged (ADR-009); only pane windows go anywhere. Not seen on a real screen in this session: the pane windows themselves (they build, and the placement tests pass); owner checks 17–20 are the proof.

**Owner-run:** checks 17–25 in `docs/testing/owner-checks.md` (the change-of-mind checks moved to 38–40); `report.py` reports them.
