# ADR-015: Overlay windows: room to read, cards that wait their turn

- **Status:** Accepted (owner feedback from the owner checks of 2026-10-27 is the brief; built on the same day)
- **Decided by:** Owner
- **Date:** 2026-10-27
- **Amends:** ADR-013 §3.3 ("the window stays 720 × 560") and §8 ("separate windows per request: rejected"); ADR-013 §5.2 and ADR-014 §4 (when a card's countdown runs)
- **Builds on:** ADR-009 (overlay UX, placement, dragging), ADR-013 (presenter, several requests), ADR-014 (presence, held cards)
- **Amended:** 2026-10-27, after the owner checks at 17:00: §9 the waiting stack (replaces "continue" as the main way back to unfinished requests; amends ADR-014 §5), §10 typing to Swift, §11 four overlay fixes

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

---

# Amendment, 2026-10-27 (evening): the waiting stack, typing to Swift, four fixes

The owner checks at 17:00 on 2026-10-27 (log 17:00–18:20) found that the way back to unfinished work ("continue") confused the owner, and four overlay bugs. The owner designed the replacement.

## 9. The waiting stack

### 9.1 The owner's design

In the owner's words:

> "a list of cards on the bottom corner that need attending to - they start of stack on the UI so they dont take up space, but when you double click they expand and you see all the cards you need to attend to and then you can click one - if you choose not to click one of the cards in the expanded stack view you can click anywhere else outside and they revert back to that compressed stack view... When they are in the expanded view you may be able to just go ahead and skip or kill a waiting card if you do not need it anymore, but ofcourse you can also do that if you click the card"

So:

- **Compressed** (the default): one card in a bottom corner, with up to two edges behind it, the number waiting, and the top card's title. It takes about 300 × 72 px.
- **Double click:** it expands upwards into the list of everything waiting.
- **A click anywhere outside it** compresses it again. So does opening a card.
- **Each card** can be:
  - **opened** ("Show" for a card, "Resume" for a conversation): it comes on screen, or the conversation goes on;
  - **skipped**: back to the stack, last in line;
  - **ended** (×): gone. A request is stopped and is **not** kept as unfinished.
- **The card on screen** has the same choices: **Later** (skip: it goes into the stack, off screen, its countdown paused) and **End** (■), beside Approve and Reject.
- A card that just joined the stack glows for 4 s, so the owner notices it.
- The voice "continue" stays as a shortcut. The "Unfinished: …" line now says "It's with your waiting cards" instead of asking the owner to say "continue".

### 9.2 What is in it

| Kind | What | Open | Skip | End |
|---|---|---|---|---|
| **waiting** | A confirm card in line behind the one on screen (ADR-013 §5.2) | It comes on screen now; the one there waits behind it | Last in line | Its request stops; not parked |
| **later** | A confirm card the owner skipped ("Later") | Back on screen, with the time it had left | Stays | Its request stops; not parked |
| **held** | The card on screen while the owner is away (ADR-014 §4) | The owner is here, so it comes back | Stays | Its request stops |
| **parked** | A conversation left unfinished (ADR-014 §5): stopped, a card unanswered, or Swift's question unanswered | The conversation resumes in its own thread, with its parked context | Last in the stack | Dropped |

- A **question pushed off the screen** (a card, or another request brought to the front, takes the front from Swift's question) is parked at once, reason `asked`, so it waits in the stack instead of fading unanswered. This is what happened in check 26: the question came from a request beside another, and a card took the front.
- Order: the held card, then cards (in the order asked), then conversations (newest first). Skipped items go last.
- **Countdowns:** a card in the stack is not on screen, so it doesn't count down (§4.2). A card skipped and never answered gives up after the held-card limit (12 h, ADR-014), like a held card, and is parked.

### 9.3 How it works

- **Backend:** `swift/stack.py` (the items and their order, pure); `Session._stack_items`, `_send_stack`, `_stack_action`, `_skip_card`, `_open_card`, `_end_run`, `_resume_parked`, `_question_aside`. Cards skipped from the screen are kept in `Session._aside`, out of the line `_cards`, so "the first in line is on screen" (ADR-013 §5.2) still holds.
- **Protocol:**
  - outbound `stack {items: [{id, kind, title, reason, since_ms, thread_id}]}`, sent whenever the list changes (and to a newly connected overlay);
  - inbound `stack.action {id, action: "open" | "skip" | "end"}`, where `id` is `card:<request id>` or `parked:<thread>`.
  - Setting a card aside and bringing it back reuse `confirm.hold` (§4.1), so the overlay hides and redraws it the way it does a held card.
- **Overlay:**
  - `overlay/src/stack.ts`: compressed or expanded, what each line says, the glow (pure, tested).
  - The stack is a pane window (`pane-stack`, §3) in the bottom corner on the request chips' side. Chips that would come up from the bottom now start above it.
  - It grows upwards when it expands (`fit_pane` keeps its bottom edge). Dragged, it remembers its bottom-left corner.
  - Panes never take focus, so "a click anywhere else" is watched by Rust: `watch_outside` polls the mouse button while the stack is expanded.
  - Without pane windows (the dev harness), the stack is a short list under the card.
- **Logs:** `stack action | kind=… action=…`, `question moved to the waiting stack`. No titles or words are logged.

### 9.4 Alternatives considered

- **Keep "continue", and show more "Unfinished" lines.** The owner found it confusing: which one would "continue" pick? The stack shows them all, and a click says which.
- **The stack inside the main window.** The main window lives at the owner's anchor, and the owner asked for a corner. A pane can go anywhere and be dragged.
- **Single click to expand.** The owner asked for a double click. A single click on a chip elsewhere means "bring it to the front"; here it does nothing, so a stray click doesn't open the list over their work.

## 10. Typing to Swift

- **Opened by** `hotkeys.type`, `Ctrl+Alt+Space` by default. It is configurable in `config.yaml`, and `""` turns it off. It is also opened from the tray: **Type to Swift…**. Pressing the hotkey again closes it.
- **A text box** (`pane-type`) where the cards appear. It is the one pane that takes the keyboard (`win::init_typing`: no `WS_EX_NOACTIVATE`). It stays on top, has no taskbar entry, and is excluded from screen capture.
  - **Enter** sends it. **Esc** or clicking away closes it, keeping what was typed for next time.
  - While it is open, Swift doesn't grab Esc system-wide (§ ADR-009), so Esc reaches the box.
- **The same path as speech:** inbound `text {text, thread_id?}`, handled by `Session._start_typed`:
  - It is routed by the same router and runs through the same gateway, as source `typed`.
  - Nothing running: a request.
  - Something working in front: the mid-run grammar ("stop", "show me", "actually …", or a new request beside it, still `typed`).
  - On an open confirm card: an answer, like voice.
- **Typing never approves a card on its own.**
  - "approve", "yes" or "Swift, approve" typed on a card shows the hint "Typing can't approve. Click Approve, or say “Swift, approve”."
  - Rejecting, stopping and asking for a change by typing all work.
  - Approvals stay with clicks, or with voice plus Swift's name (ADR-014 T2).
- **Follow-ups:** the box names the conversation on screen when it opened ("Following up: …"). A typed request then continues that thread, but only if it is still the backend's current thread.
- **Logs:** `typed request | chars=N`. The text itself is not logged; the interaction record keeps the transcript, as for speech.

## 11. Four fixes (owner checks of 2026-10-27, 17:00)

| Bug | What happened | Cause | Fix |
|---|---|---|---|
| 1 | A chip stuck on "What time is it? Working on it 2:44" (still counting at 19:12) after the answer was shown on another card. `source='beside' … route='local' action='time' … interaction_ms=0` at 17:13:00, 17:18:30 and 17:38:43. Clicking it logged `focus ignored known=False` | The beside request's row opened a pane window. Its answer, 0 ms later, took the front, and a second sync "closed" the window while it was still being created: the close did nothing. The window then opened, the first sync sent it the stale view, and nothing ever closed it | `PaneSync` (`panes.ts`): one sync at a time, and a sync asked for during another runs again right after it, so it sees the window it just opened. A window nobody wants is closed: a sweep every 3 s (`pane_labels`), a pane that says "ready" with nothing to show, and the backend sending `runs` again when the overlay asks about a request it doesn't know. A request younger than 600 ms gets no window yet, so instant answers don't flash one |
| 2 | Dragging the reader or a pane made it disappear on release (check 19) | Not reproduced here. After its drag the main window is always re-placed topmost and shown (`win::place`); a pane was only moved | After a drag, the pane is shown and made topmost again where it was dropped (`win::reshow`). The press no longer starts a text selection or native drag in the webview (`preventDefault`) |
| 3 | Cards went too quickly to answer. Check 26's question didn't stay for its 25 s, although the backend logged `question window \| seconds=25.0` | The pointer leaving a card gave it 2.5 s (`RESUME_MS`), whatever the reply window. And a card taking the front from the question dropped it without a trace | Letting go of a card never shortens it below the backend's reply window (`presenter.onHold`). A question pushed off screen goes into the stack (§9.2) |
| 4 | When a second request was captured, nothing showed it (checks 21, 25), so the owner repeated it and made duplicates | Its chip appeared only when the request first did something, far from the card, labelled "Working on it". A request waiting for a slot had no chip at all | At once, on the main card: "Got it: “<the request's words>”" for 5 s. The backend sends a started request's row with its words straight away (`Session._chip_now`, row `words`). A request waiting for a slot gets a chip too ("Waiting to start"), up to 5 chips |

### 11.1 Every auto-hide timer, reviewed

The rule: **nothing that needs an answer hides while the owner is present and hasn't answered**, unless it goes somewhere they can find it.

| Timer | Needs an answer? | Now |
|---|---|---|
| Confirm card countdown (120 s, backend) | Yes | Runs only while on screen, drawn and the owner present (§4.2). "Later" puts it in the stack, paused |
| Answer reading time (6–20 s) | Only if it asks something | At least the backend's reply window (25 s for a question), even after the pointer leaves. Unanswered, it is parked and waits in the stack |
| Answer pushed off by a card | Only if it asks something | Parked at once; in the stack (§9.2) |
| Error card (12 s) | "Try again" is optional | 20 s when it offers "Try again"; 12 s otherwise |
| Notices (4–5 s): ready, already running, "hold to talk" | No | Unchanged |
| Mid-run hint (4 s) | No | Unchanged |
| Request chip "Done: …" (20 s) | No (a question in it is parked, below) | Unchanged |
| A question from a request behind another | Yes | Parked after its window, then in the stack |
| Working card collapse (30 s), reader to chip (60 s) | No; nothing is hidden | Unchanged |
| Card held while away | Yes | Hidden while away, in the stack as "held", back on return (ADR-014 §4) |

### 11.2 Implementation status

| Part | Where | Checked by |
|---|---|---|
| Stack items, order, actions; cards set aside; questions pushed off screen parked; ended requests not parked | `src/swift/stack.py`, `src/swift/session.py`, `src/swift/ipc/protocol.py` | `tests/unit/test_stack.py` |
| Typing: same router, source `typed`, never approves, follow-ups in the thread on screen | `Session._start_typed`, `settings.py` (`hotkeys.type`) | `test_stack.py` |
| Chip at once with the request's words | `Session._chip_now`, `Run.words`; `panes.ts` `newRows`, `CHIP_DELAY_MS`; `main.ts` "Got it" | `test_stack.py`, `panes.test.ts` |
| One pane sync at a time; strays closed | `panes.ts` `PaneSync`; `main.ts` `sweepPanes`; `lib.rs` `pane_labels` | `panes.test.ts` (the bug 1 sequence) |
| Reply window never shortened by hover | `presenter.ts` `onHold` | `presenter.test.ts` |
| Stack and text box panes: placement, growing upwards, folding on a click outside, focus for the text box, drag fix, tray item | `pane.ts`, `stack.ts`, `styles.css`; `lib.rs` (`open_pane`, `fit_pane`, `drag_pane`, `watch_outside`), `panes.rs`, `win.rs`, `prefs.rs` | `stack.test.ts`; `cargo test` (`panes.rs`: the stack clear of the card, the chips and the reader; the text box where the cards appear) |

**Not seen on a real screen in this session:**
- the stack and text-box windows;
- the drag fix (bug 2 wasn't reproduced);
- whether Windows gives the text box the keyboard from the tray as well as from the hotkey.

Owner checks 15, 16 (the stack) and 16b (typing), and 19 (drag) are the proof.

**Coordination:** a second request said *while the first is still being captured* is queued by the voice and audio session's capture queue. Once it becomes a request, it gets its chip and "Got it" line from `_launch` / `_chip_now` like any other.

## 12. Read more in place, cards stay where dropped, web for ordinary requests (owner checks of 2026-10-28)

- **Read more / Read less replaces Read all.** The owner found the separate reader window hard to read and wanted the card itself to open. A long answer shows six lines and the first six rows. **Read more** opens the same card to the whole answer, which scrolls inside it. **Read less** closes it again. While the card is open it holds, as hover does, and closing gives back the time it had left. The reader pane's code stays, but nothing opens it from a card now.
- **A dragged card stays where it was dropped.** The real cause of "it disappears when I let go": the main overlay snapped to the nearest corner, which moved the card out from under the pointer. Hover ended, and an answer faded 2.5 s later.
  - Now the drop point is remembered (`dropped` in `overlay.json`, a fraction of the work area) and the overlay stays there. The nearest anchor still decides which way cards grow and which side the other windows go.
  - Choosing a corner from the tray's Position menu clears the drop point. Smart placement still moves off the text caret.
  - After a drag, an answer gets back the time it had left (at least 2.5 s).
- **Web search and fetch in ordinary requests.** "Research the history of tea and summarise it" had no web: only workflows that declare `web.search` / `web.fetch` got it.
  - Now `executor.web` (on by default) allows both, without a card, in runs that aren't in a workflow. They only read.
  - A workflow that doesn't declare them (calendar, email) still never gets them, so a web page can't steer a run that holds Swift's tools.

Checks 18, 19 and 19b are the proof.
