# ADR-013: Attention, conversation threads, and requests running side by side

- **Status:** Accepted (owner, 2026-10-26: approved as proposed, with the proposed answers in §9). Phase A first.
- **Decided by:** Owner
- **Date:** 2026-10-26
- **Builds on:** ADR-006 (the backend owns the state), ADR-009 (overlay UX), ADR-010 ("show me", confirm cards), ADR-012 (foreground mode)

## 1. Context

On 2026-10-26 the owner hit a bug.
- After rejecting a calendar card, their spoken correction started a new request (a follow-up).
- The last card's fade timer, still running, hid that request's new confirm card.
- Swift waited two minutes for an answer to a card nobody could see.

It was fixed (490b3dc). The owner asked to make sure this **class** of problem can't come back, and set three goals:

1. **Nothing fights for attention.** No overlay elements competing on screen, and no visible or invisible processes competing in the background.
2. **Related requests flow naturally.** A follow-up, a correction or a "yes" continues the same conversation in the overlay.
3. **Separate requests organise themselves.** Different requests run efficiently in the background and share the screen well.

Why the bug was possible:

| Root cause | Where |
|---|---|
| The overlay keeps **one global card** and **global timers** (fade, follow-up). Each message handler changes them directly; nothing says which request a timer or card belongs to. | `overlay/src/main.ts` (~1,000 lines of handlers) |
| The overlay only knew a new request had started when it saw "listening". Paths added later (follow-up, offer "yes", correction, "hey Swift, X" in one breath) skip that state. | Assumption from ADR-006, before those paths existed |
| The backend allows **one interaction at a time**. Speech during a run can only be a mid-run command; a new, unrelated request is impossible until the run ends. | `session.py`: `busy`, `_task`, `_active`, one `RunScope` in `ToolHost` |
| Nothing in the tests replays a **sequence** of overlay messages. | No overlay tests; the harness is manual |

## 2. Decision in short

1. **One presenter in the overlay.**
   - Every element on screen belongs to a request (`run_id`) or to Swift itself.
   - Timers belong to the element they act on and die with it.
   - Priority rules decide what is shown when several things want the screen.
   - Messages for requests that aren't the one in front can't take over.
2. **Threads.** The backend tags each request with a `thread_id`. Follow-ups, corrections and offer answers share their thread's id, and the overlay continues the same card instead of replacing it.
3. **Several requests at once,** with clear limits:
   - up to 3 running;
   - one in front, the others as one-line rows;
   - one confirm card at a time, the rest queued;
   - one writer in the owner's apps at a time.
4. **Regression tests for sequences:** the presenter as pure, unit-tested TypeScript, plus replayable scenarios in the dev harness.

## 3. The presenter: who gets the screen

### 3.1 Model

The overlay keeps a **list of requests** (`run_id` → state, steps, artifacts, card), plus Swift's own notices. It draws from that list through one function. Today, handlers instead poke the DOM and global timers directly.

| Layer | What | At most | Rule |
|---|---|---|---|
| **Focus card** | The request the owner is dealing with now: listening, working, its confirm card, its result | 1 | The newest request the owner started, unless another needs an answer (next row) |
| **Attention queue** | Confirm cards waiting for an answer | 1 shown | The oldest waiting card takes the focus card's place. Others wait, counted on it ("1 more waiting"). A card **never** disappears while waiting. |
| **Background rows** | Other running requests, one line each: spinner, short title, activity, elapsed time | 3 | Below or above the focus card, on the side away from the screen edge. Click or "show me the email one" to bring one to the front. |
| **Notices** | "Swift is ready", unread digests, connection problems | 1 | Only when nothing above is showing. Never over an active request. |
| **Attachments** | Follow-up "Listening for a reply", hints, "Changing it…" | (on a card) | Part of a card, never their own element |

### 3.2 Rules that make the old bug impossible

- **Timers belong to a card instance.** Replacing or removing the card cancels its timers. No timer is global.
- **A request's card only fades when it's finished**, its result has been read, and no other element has taken its place. Active requests never fade.
- **Every run message carries `run_id`.** Messages for a request that isn't in front update its background row, never the focus card. Messages for requests that have ended and been dismissed are ignored.
- **New requests are recognised from `run_id` / `thread_id`,** not from "listening". So the next way of starting a request doesn't need the overlay to be taught about it.

### 3.3 Space

> **Amended by ADR-015 (2026-10-27):** other requests get their own small, movable windows instead of rows, long answers scroll or open in a reader window, and a card's countdown runs only while the overlay shows it.

- The window stays 720 × 560 (ADR-009) and nothing moves mid-run.
- The focus card keeps its zone (`CARD_ZONE_H`). Background rows take at most 3 × 32 px. Past 3, it's "+N more".
- Smart placement still checks the caret, against the focus card's zone plus the rows.
- Collapsed mode (ADR-009) collapses everything to the focus card's line, with a count of the others.

## 4. Threads: related requests flow

### 4.1 What joins a thread

The backend decides: these are rules, not guesses in the overlay.

| Starts a new thread | Continues the current thread |
|---|---|
| A wake phrase or push-to-talk with a request that isn't a follow-up | A reply in the follow-up window |
| A request that matches a workflow or local command on its own | A correction (on a card, or after a rejection) |
| | "Yes" / "no" to an offer |
| | "Try again" |
| | A request within `followup_s` that refers back ("it", "that", "instead") |

The context passed to the provider already follows this (ADR-007 §9, the "proposed" line from 2026-10-26). Threads make it explicit, give it an id, and let the overlay show it.

### 4.2 How it looks

- **The thread's card stays in place** and continues: the last answer shrinks to one line ("Not added: Meeting, Thu 15:00"), and the new step or card appears under it. There's no fade-out and fade-in between turns.
- The owner sees the last two turns at most. "Show me" on the thread opens its earlier artifacts.

### 4.3 Protocol

`state`, `step`, `confirm.request`, `result`, `error` and `artifact` gain `thread_id` (optional, additive, still v1). A message without it is treated as its own thread, so old builds keep working.

## 5. Several requests at once

### 5.1 What starts one

While a request runs, speech is understood in this order:
1. **Mid-run commands** for the request in front: "show me", "stop", "approve", "reject", a change on its card. As today.
2. **A clear new request:** "hey Swift, what's the weather", or a workflow trigger or intent. This **starts another request beside the first**, which moves to a background row.
3. **Anything else** gets the hint, as today.

Push-to-talk works the same way, without the wake phrase.

### 5.2 Limits (the "background" half of "nothing fights")

| Resource | Rule | Why |
|---|---|---|
| Requests running | 3 at most. A fourth waits ("queued") and starts when one ends. | Each Claude Code run is its own process (~300 MB) and costs money. |
| Confirm cards | One shown; the rest queue in the order asked. Each waits for its own answer, with its own timeout starting when it's **shown**. | The owner can only answer one at a time, and no card is ever hidden. |
| Writing in the owner's apps (ADR-012 foreground mode) | **One writer at a time.** Another request that wants to write waits ("waiting for Word") until the first finishes or is stopped. | Two requests typing into the same window would corrupt it. |
| Microphone and speech model | One capture at a time (as today). Wake listening pauses while push-to-talk records. | One microphone, one speech model. |
| Notifications, digests | Never interrupt a focus card. Shown when the screen is free, or as the tray dot. | ADR-011 §13.4 rule, extended. |
| Prewarmed Claude Code | One spare as today. A second concurrent request starts cold (5–13 s); the working card says so. | Two idle spares would double the memory for a rare case. |

### 5.3 Voice with several requests

- **Commands go to the request in front.** "Stop" stops that one. "Stop everything" stops all of them.
- **Requests are named by what they're about:** "show me the email one", "stop the calendar one". Matching is on each request's short title (a workflow title, or the first words of the request).
- **Answers go to the card on screen,** which is always exactly one.

### 5.4 Backend

`Session` gains a **`Runs`** table, replacing the single `_task` / `_active` / `_record` / `_scope`:
- one `Run` per request: task, record, scope, confirm ids, thread;
- a **focus** pointer;
- an **attention queue**.

`ToolHost` gets one `RunScope` **per run**. An MCP call names its run: in-process through the executor's run binding, and over HTTP (phase B) through the per-run token ADR-010 §3.3 already planned. The gateway, journal and artifacts are already per scope, so they don't change.

This is the biggest change here. `session.py` is about 1,500 lines built around "one interaction".

## 6. Ensuring it stays fixed

- **Presenter as a pure module** (`overlay/src/presenter.ts`): `(state, message) → state`, and `state → what to draw`. It has unit tests run by Node's built-in test runner on the TypeScript compiler's output, so no new packages. Covered sequences:
  - result → follow-up → working → confirm (the 2026-10-26 bug);
  - reject → correction;
  - offer → "yes";
  - two requests side by side with both confirm cards;
  - a late message from a finished request;
  - a reconnect mid-request.
- **Harness scenarios:** the same sequences as replay buttons in `overlay/dev/harness.html`, using `__shim.inject`, for checking by eye.
- **Backend tests:** two requests with interleaved confirm cards; the writer lock; the run limit; voice targeting ("stop the email one").
- **Invariant checks in the overlay** (debug builds): at most one focus card, no timer without its card, a waiting confirm card always visible. A violation is logged with the message sequence that caused it.

## 7. Order of work

| Phase | Scope | Fixes |
|---|---|---|
| **A: presenter and threads** | `presenter.ts` with tests; timers per card; `run_id` / `thread_id` everywhere; threads in the session; harness scenarios | Goals 1 and 2 for single requests. The 2026-10-26 class of bug is caught by tests. |
| **B: several requests** | `Runs` in the session; per-run scopes; limits (§5.2); voice targeting; background rows | Goal 3 |

A is useful on its own and is a prerequisite for B.

## 8. Alternatives considered

- **Keep one request at a time and queue new ones.** Simpler, and still a clear improvement: a new request waits and starts afterwards. But a 2-minute research run would block "what time is it". Running side by side is what the owner asked for.
- **Separate windows per request.** Rejected here; **reversed by ADR-015** after the owner checks of 2026-10-27 ("overlays can be anywhere, and can be moved"): more transparent windows to keep click-through and out of the way (ADR-009), and they fight for screen space, which is exactly what the owner wants to avoid.
- **Let the provider handle multitasking** (one agent session juggling several requests). Rejected: it couples unrelated requests' context and approvals, and works differently per provider.

## 9. Owner's decisions (2026-10-26: the proposed answers, approved)

1. **Direction:** one presenter with layers; threads for related requests; up to 3 requests side by side with one confirm card and one app writer at a time?
2. **A clear new request while one runs:** start it beside the first (proposed), or queue it to start afterwards?
3. **Limit:** 3 at once (proposed), or another number?
4. **Background rows:** shown under the focus card, at most 3 lines (proposed)? Or only as a count ("2 more running") until you ask?
5. **Order:** phase A (presenter, threads, sequence tests) first, then B?

## 10. Implementation status: phase A (2026-10-26)

| Part | Where | Checked by |
|---|---|---|
| Presenter: card ownership, deadlines instead of timers, hover/drag hold, follow-up window, notices never over a request, stale answers ignored, invariants | `overlay/src/presenter.ts` | `overlay/tests/presenter.test.ts` (12 sequences, `npm test`); also run by `uv run pytest` (`tests/unit/test_overlay_presenter.py`, skipped without Node 22.6+) |
| The overlay draws through it: one 250 ms clock, no fade timers left in `main.ts`; debug builds log broken rules with the last 12 messages | `overlay/src/main.ts` | Harness, by eye |
| Threads: `thread_id` on `state`, `step`, `confirm.request`, `result`, `error`, `artifact`. A follow-up, a correction, "try again" and an offer's answer continue the thread; the card shows the thread's last two answers above it, one line each. | `session.py` (`CONTINUES_THREAD`, `_send`), `presenter.ts`, `main.ts` | `test_hands_free.py`, presenter tests |
| Replays | `overlay/dev/scenarios.ts`, harness buttons "Replay: correction after reject", "Replay: 3-turn thread" | Harness |

Checked in the dev harness:
- the 2026-10-26 sequence keeps the corrected card on screen 13 s later, with the rejected answer as a line above it;
- a three-turn thread reads as one card;
- the email demo through the real backend still fades its result on its own, with no console errors.

**Not done in phase A:**
- several requests at once (phase B);
- background rows and voice targeting (phase B);
- a request that refers back ("it", "that") outside the follow-up window still starts a new thread.

## 11. Implementation status: phase B (2026-10-27)

| Part | Where | Checked by |
|---|---|---|
| `Run` per request (task, record, provider run, tool scope, thread, cards); the old single-run attributes resolve to the run whose task is running, else the one in front | `session.py` (`Run`, `_per_run`, `_RUN`, `_current`, `_as`) | the whole suite |
| A clear new request during a run starts beside it; it takes the front when it first shows something. Mid-run grammar first, then a change of mind, then a new request, else the hint. On a card, only questions and Swift's own answers start beside it (anything else is a change to the card) | `_midrun_text`, `_hear_busy`, `_new_request`, `_start_beside`, `_launch` | `test_runs.py` |
| At most 3 (`MAX_RUNS`); a fourth waits as a "queued" row and the card in front says so | `_interaction` (`_slots`) | `test_runs.py` |
| One confirm card on screen; others wait in order with their countdown stopped (`Attention.set_queued`; Swift's own cards wait before counting); the card's request comes to the front; a held card (ADR-014 L2) still holds | `_ask_card`, `_card_done`, `_show_next_card`, `attention.py` | `test_runs.py`, `test_held_cards.py` |
| One writer in the owner's apps; the other waits with "Waiting for Word: another request is writing there" | `ToolHost.writing`, `desktop_tools._one_writer` | `test_runs.py` |
| Per-run tool scopes: a call names its run (Claude Code passes its run id; otherwise the scope of the calling task, `tools.CURRENT`; the only one open) | `ToolHost.open/bind/resolve/close`, `ClaudeCodeExecutor._sdk_tool` | `test_runs.py`, `test_desktop.py`, `test_claude_executor.py` |
| Voice targeting: "stop the research one", "show me the email one", "stop everything", "the other one"; matched on each request's short title and words. Esc and "stop" act on the one in front | `rules.route_target`, `Session._named`, `_find` | `test_runs.py` |
| Protocol: `runs` (outbound: focus, rows, waiting), sent only while there is more than one; `focus` (inbound) | `ipc/protocol.py`, `overlay/src/protocol.ts` | `test_runs.py` |
| Presenter: rows (`onRuns`, `visibleRows`, at most 3 + "+N more"), another request's news never touches the card, `promotion` when the card in front is gone; new invariants (card not the one in front, a row for the one in front, duplicate rows, cards waiting with none shown, too many rows) | `overlay/src/presenter.ts` | `presenter.test.ts` (8 new sequences) |
| Rows drawn under the card (or above it, at the top of the screen), clickable; the clock asks for the next row when the card fades | `overlay/src/main.ts`, `styles.css`, `index.html` | typecheck; owner checks 17–21, 25 |

**Decided while building:**
- **The front moves only when something new is shown.** A request started beside another takes the front with its first card, not when it's heard, so the card on screen never blanks while the new one starts.
- **A finished request in front stays until its answer fades.** Then the overlay asks for the newest running row (`promotion` → `focus`); the backend doesn't guess when the owner has read it.
- **A request that ends in the background** keeps its row ("Done: …") for 20 s.
- **A provider's card waiting in line** pauses through `Attention` (Claude Code's cards); a provider without it keeps its plain timeout while waiting.
- **Push-to-talk during a run** no longer always gives a hint: a clear request starts beside it (`test_show_me.py`, `test_voice_confirm.py` updated).

**Owner-run:** checks 17–21 and 25 in `docs/testing/owner-checks.md`; `report.py` reports them.

**Not done:** the harness replay buttons for several requests (`overlay/dev/scenarios.ts`); collapsed mode showing a count of the others; over-HTTP MCP per-run tokens (no HTTP provider yet).
