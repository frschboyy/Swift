# ADR-017: The Capsule overlay (the owner's approved redesign)

- **Status:** Accepted; built on branch `claude/overlay-redesign-625122` (2026-10-28), awaiting the owner's checks 63–75.
- **Date:** 2026-10-28
- **Builds on:** ADR-009 (overlay UX), ADR-013 (several requests), ADR-014 (presence), ADR-015 (pane windows, card timing, the stack, typing), ADR-016 B (Swift speaks)
- **Spec:** `docs/design/swift-overlay/design_handoff_swift_overlay/README.md` (high fidelity; it wins over the HTML frames). What drives each element: `docs/design/swift-overlay/IMPLEMENTATION.md`.

## 1. Context

The owner's notes on the old overlay (`Swift-design-screens/NOTES.md`): a raw tool name on the confirm card, the Later button cut off, a question labelled DONE, a horizontal scrollbar on most cards, no visible "not listening" state, truncated stack titles, small low-contrast type and a flat hierarchy. They chose direction **1a "Capsule"** in Claude Design and exported a handoff: a small pill at the anchor is Swift's body, every card grows out of it and folds back into it, in dark and light.

The brief: build it so that **every element is backed by working functionality**, keep every current behaviour, and never fake a state with made-up data.

## 2. Decision

1. **The capsule is Swift's body** (`capsule.ts`, pure). One state at a time, most urgent first: the owner talking (listening, transcribing, can't hear after 4 s), heard, speaking (with Stop), paused (mic off with Resume; screen locked or asleep), working, idle dot. It is a hit region only when it has a button; otherwise clicks pass through.
2. **Dark and light follow Windows**, live. Rust reads `AppsUseLightTheme` and waits on the registry key (`RegNotifyChangeKeyValue`, no polling); every window gets `theme`. Tokens are the README's, keyed off `#stage[data-theme]`. Without Rust (the harness) the webview's colour scheme stands in; `?theme=` pins one.
3. **Cards** keep their behaviour and take the design's shapes: a head row with how the owner asked (mic or keyboard) and their words; status with checked steps; one-line answers as display text; paragraphs apart with bold/italic/code kept as marks (`answer.ts`, rendered with textContent only); a wrapping table; a long answer clipped at six lines that opens in place; failed with Details and Try again; Stopped / Not done in one row; timers and reminders that stay until Done. Nothing scrolls sideways.
4. **The confirm card is unmistakable**: solid, amber band with the countdown, facts (an event, a change as Now → After, an email with a body preview, or a command in full), Reject · Change · Approve. The internal tool name is never shown. Later is gone. Approve ignores its first 400 ms.
5. **A countdown never answers for the owner.** It runs only while the card is shown and the owner is here (presence `here`; idle or away stops it, and the card says "Paused · you're away"). When it runs out, the card goes to the waiting stack ("held, no answer in time") with its whole time back for when it is opened (`Attention.on_expire`). Held 12 h it still gives up as before. The default countdown is 45 s.
6. **Swift's question** is its own card: "Swift is asking" while it speaks (no timer), then "Waiting for you" with the backend's whole reply window. Answer later puts it in the stack now; Cancel request drops it.
7. **The tray menu is a pane** opened by a left click on the tray icon (position, smart placement, pause listening, type, settings, quit). The native menu stays on the right click, with the same actions.
8. **Pause listening** closes the open microphone until resumed, and the capsule says "Not listening · Mic off" for as long as it lasts: the privacy indicator never fades.

## 3. What the backend gained (small, narrow)

| Message | Why | Where |
|---|---|---|
| outbound `speech {speaking}` | The capsule's Speaking state; the question card's "I'll listen when I'm done" | `Session._speak` / `speech_done` |
| inbound `speech.stop` | Stop on the capsule (and Esc while Swift talks): only the voice stops | `Session.handle` |
| inbound `listen {on}`, presence `paused` | The tray's Pause listening and the capsule's Resume | `Lifecycle.set_listening` (unlock doesn't reopen a paused microphone) |
| transcript `typed` | The head row's keyboard or mic icon | `Session` capture |
| stack reason `expired` | A card whose countdown ran out, in the stack | `Attention.on_expire`, `Session._expire_card` |
| `stack.action` skip / end on `parked:<thread>` while Swift's question waits | Answer later / Cancel request | `Session._stack_action` |

New log lines carry no content: `listening paused`, `listening resumed`, `card expired into the stack`, `speech stopped by the owner`, `question put off into the stack`.

## 4. Safety rules kept where the handoff differs

1. **Voice approval** needs push-to-talk or Swift's name, so the confirm card's hint names the hotkey instead of the README's bare "say approve".
2. **Esc** is a system-wide hotkey (`RegisterHotKey`), so it is grabbed only while Swift works, asks, speaks or the stack is open, never for an answer that is only being read (that would take Esc from the owner's app for up to 20 s). The × or a click closes those.
3. **Typing never approves.** "Change" opens the typing box; "Enter = Change" sends a change.
4. **Capture exclusion and no focus stealing** hold for the new tray pane like every pane; only the typing box takes the keyboard.

## 5. Deferred (owner questions, in IMPLEMENTATION.md)

Idle dot setting; a 60 s "present" threshold (presence says idle after 10 min); "Show in Word" on a long answer; Undo on a stopped card; the timer card's length and +5 min / Later (no snooze in the scheduler); the question window (README 20 s, config 25 s); push-to-talk while paused; a sound for confirm cards. The provider's name on a confirm card ("Claude wants to:") was dropped with the design; the facts show exactly what will run.

## 6. Verification

- Python 1094, overlay 61 (presenter, stack, panes, capsule, answer, theme), Rust 25 (theme DWORD, tray placement): all pass.
- Dev harness: `__design(name)` replays each state (`overlay/dev/scenarios.ts`, 32 states), `dev/pane.html` draws the chip, stack, typing box and tray menu. Every state was compared with the frames in both themes, on the stand-in, white and busy wallpapers, and with a top anchor; screenshots are in the session notes (`capsule-screens/`).
- Checked in the harness: click-through regions (idle, listening and "Got it" pass clicks; Stop, Resume, cards and chips take them), Approve's 400 ms guard, no tool name on a card, Esc grabbed while Swift speaks.
- Owner checks 63–75 (`docs/testing/owner-checks.md`) cover what only the real PC shows: the live theme switch, the tray, 150 % scaling, focus and capture.
- The live view (§7): Python 1094 → 1110 (`tests/unit/test_live_view.py`: the mapping of search and fetch results, notes, the writer's paragraphs, show me / Watch / Stop / Show in Word, nothing with content in the log or the record, the report's checks 90–95), overlay 71 (`tests/live.test.ts`), Rust 27 (`web_link`, live view placement). Drawn in the harness in dark and light (`__design("liveResearch")`, `__design("liveDone")`, `dev/pane.html?state=liveRunning`); owner checks 90–96.

## 7. The live view of a running request (added 2026-10-28)

The owner asked several times to watch research happen instead of waiting blind ("show me while the word document is writing… another separate overlay or the document as it is writing"). Before this, "show me" during a run only brought the app forward and the card showed a few step lines.

1. **A pane window per running request** (kind `live`, ADR-015 §3), drawn by `views.liveCard` in the reader's layout on a glass panel: a LIVE badge and the title; what it is doing now ("Searching: history of tea", "Reading britannica.com"); the text being written, in its own box that follows the newest paragraph unless the owner scrolled up in it; the **sources** so far (title, site, found / reading / read / couldn't read), each opening in the browser; short **notes**; then **Show in Word** and **Stop**. At most three open (as many as can run); a second cascades in from the first; dragged, the kind remembers where (`overlay.json` `panes.live`). Like every pane it never takes focus and is capture-excluded; the window is only as big as the view, so clicks beside it go through.
2. **Opened by** "show me" while the request in front works (its confirm card keeps "show me" for its own detail), "show me the research one" (in front or not), "show me" with the wake word while one runs, or **Watch** on the working card or a running chip (Watch doesn't bring the request forward).
3. **Closed by** ×, or by itself 45 s after its request ended while nobody points at it. Ended, it says Done / Stopped / Didn't finish with the answer's first lines, and **Open the answer** opens the reader (or brings a background request forward, whose answer this window doesn't have whole).
4. **Stop stops that request only** (`run.stop {run_id}`); Show in Word brings forward the app that request writes or wrote in (`live.app {run_id}`), during the run or after it.
5. **Data.** `live {run_id, kind}` for every request, in front or not (`step` is sent only for the request in front): `doing` from each step; `source {url, title, site, state}` from Claude Code's WebSearch results (the CLI's structured result, else its `Links: [...]` line, else links in the text; at most 8 a search) and WebFetch calls (reading → read / failed), only http(s) addresses (`claude_mapping.LiveMapper`); `note` from Claude's own text between tool calls (not a helper's), at most 280 characters; `text`, each paragraph the desktop writer just wrote (one line in `desktop_write`'s loop through `RunScope.live`, apart from its gate); `hint` for the view's buttons. Outbound `watch {run_id, title, words, open}` opens a view; inbound `watch` says one opened or closed, for the log. The overlay keeps 30 sources, 12 notes and 20 000 characters of text a request (`live.ts`).
6. **Privacy.** Titles, addresses, notes and written text go to the overlay only. The interaction record gets counts (`live: {source, note, text}`) and `views: {kind: "live"}`; log lines carry run ids and booleans only (`live view asked for`, `live view`, `request stopped from the live view`, `live view: app shown`). A source opens only through Rust's `open_link`, which accepts a plain http(s) address and nothing else. Nothing new leaves the machine: the view only shows what the run already fetched.
