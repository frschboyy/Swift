# Capsule redesign: what drives each design element

The owner's approved handoff (`design_handoff_swift_overlay/README.md`, direction 1a "Capsule")
mapped to the backend message and the code that drives each element. Every element is marked:

- **(a)** existed: restyled;
- **(b)** missing in the UI, but the backend already sent the data: built;
- **(c)** needed backend data that didn't exist: built when small and safe (the backend change is
  named), otherwise an **owner question** at the end. Nothing is drawn from made-up data.

Messages are in `overlay/src/protocol.ts` (mirror of `src/swift/ipc/protocol.py`). Decisions are
recorded in ADR-017 (`docs/decisions/ADR-017-capsule-overlay.md`).

## 0. System

| Element | Driven by | Code | Status |
|---|---|---|---|
| Tokens (dark + light), `--panel-solid`, `--on-*`, `--warn-text`, `--warn-soft`, `--warn-halo`, `--accent-soft`, `--accent-edge`; `--accent-2` retired | — | `styles.css` `:root` / `[data-theme]` | (a) |
| Theme follows Windows `AppsUseLightTheme`, live | Rust reads `HKCU\…\Themes\Personalize\AppsUseLightTheme` and watches it (`RegNotifyChangeKeyValue`), emits `theme` to every window; `get_theme` at start | `src-tauri/src/theme.rs`, `src/theme.ts` (`data-theme` on `#stage` in the main window and every pane) | (c) built (Rust only) |
| Glass: `backdrop-filter: blur(24px) saturate(1.4)`, panel opacity ≥ .86 | — | `styles.css` `.glass` surfaces | (a) |
| Type: Segoe UI Variable Display ≥ 20 px, Text below; no uppercase labels or letter-spacing; tabular numbers | — | `styles.css` | (a) |
| Motion tokens, enter/exit easing, no overshoot | — | `styles.css` `--dur-*`, `--ease*` | (a) |
| Icons: 24-unit viewBox, 2 px round stroke, a word beside every state icon | — | `dom.ts` `ICONS` (+ keyboard, bell, timer, pause, lock, mic-off, question, shield, retry, chevrons, word, play) | (a) |
| `prefers-reduced-motion`: opacity only, static heard ring, static ¾ arc spinners | — | `styles.css` | (a) |
| `forced-colors`: Canvas / CanvasText, ButtonText borders, amber band → Highlight | — | `styles.css` | (a) |
| 100–200 % scaling: CSS px throughout | Rust sizes windows in physical px from CSS px × scale | unchanged | (a) |

## 1. Presence capsule (`#capsule`, `capsule.ts` decides the state)

| State | Driven by | Status |
|---|---|---|
| idle dot (12 px, .6) | `state: idle`, nothing else on screen | (a) restyled (was nothing) |
| heard: accent edge, ringed orb, **Listening…** | `heard` (≤ 100 ms, before ASR); `heard.ts` keeps it 1.8 s; delay logged in debug builds | (a) |
| listening: orb scale + 5 live bars, live transcript | `state: listening`, `level` (30 fps), `transcript` | (a) bars (b) |
| transcribing: orb .7, transcript + "· · ·" | `state: transcribing`, `transcript` | (a) |
| can't hear: flat bars, "I can't hear you. Check your microphone." after **4 s** below room noise | `level` under 0.05 for 4 s (was 1.5 s) | (a) |
| working: ring spinner, **Working on it** + elapsed | `state: working` while the card is shrunk away or a chip is in front; the card itself shows the steps | (a) |
| speaking: orb + 6 wave bars, **Speaking**, **Stop** pill with Esc | **new outbound `speech {speaking}`** (session.py: sent when Swift starts and stops talking); Stop sends **new inbound `speech.stop`**; Esc does the same while Swift talks | (c) built |
| paused, mic off: solid, dashed edge, slashed ring, **Not listening** · Mic off · Resume | **new inbound `listen {on}`** (tray "Pause listening" / Resume) → `Lifecycle.set_listening` closes the open microphone; `presence` gains `paused` | (c) built |
| paused, locked: lock glyph, **Not listening** · Screen locked (or "PC was asleep") | `presence {listening:false, reason:"locked"|"asleep"}` (wake listening on) | (b) |
| The paused capsule persists and never fades | presence, until `listening` is true again | (b) |
| Clickable only while speaking (Stop) or paused (Resume); otherwise click-through | `data-hit` on the capsule only in those states | (a) |

## 2. Main card

| Element | Driven by | Status |
|---|---|---|
| 512 px, glass, `overflow:hidden`, **no horizontal scrollbar** (tables wrap) | — | (a) bug fixed |
| Head row: modality icon (mic / keyboard) · the owner's words in quotes · close | `transcript {final}` gains **`typed`** (session.py) | (a) words, (c) built: modality |
| Status row: spinner · step verb (generic, never the provider) · elapsed; earlier steps with a green check | `step` (`activity`, `app`) via `agents.ts`; elapsed after 3 s | (a) |
| Answer: one line → display 28/34; otherwise 17/26 paragraphs 10 px apart; bold ≤ 600 | `result.summary`; `answer.ts` splits paragraphs and renders **bold**, *italic*, `code` and "- " lists as DOM (never innerHTML) | (a) bug fixed |
| Footer: byline ("Swift · via Claude") · Show, Copy | `result.agent`, artifacts | (a) |
| Reading-time bar 3 px, accent .6 | presenter `fadeAt`; time is `clamp(4 s, words × 240 ms, 20 s)`; held by hover, drag, Read more, scroll, selection; resumes 1.5 s after | (a) |
| Table (calendar): `auto 1fr auto`, rules, time muted tabular | `result.details` / `artifact` kind `table` | (a) |
| Long collapsed: 6 lines (156 px), mask, **Read more ⌄** · "N min read" · Copy | `needsReader` | (a) |
| Long open: grows in place to `min(70vh, 720px)` − capsule, body scrolls, accent edge, **Read less ⌃** · "Stays while open" · Copy; no fade | `setExpanded` holds the presenter | (a); "Show in Word": owner question 3 |
| Failed: `!` circle · plain title · reason · Details (mono) · **Try again** | `error` (`title`, `message`, `hint`, `detail`, `retry`) | (a) |
| Cancelled: one row, **Stopped** · description · ×, fades after 4 s | `result {status: cancelled}` | (a); Undo: owner question 4 |
| Not approved: one row, **Not done** · description · × | `result {status: rejected}` | (a) |

## 3. Confirm card

| Element | Driven by | Status |
|---|---|---|
| Solid panel, warn border, 4 px warn halo, 40 px amber band: shield · **Needs your OK** · countdown `0:42` | `confirm.request`, presenter `confirmDeadline` | (a) |
| Band says "Paused · you're away" and the countdown stops while the owner is idle or away | `presence.state !== "here"` → the card reports `card.seen {visible:false}` (the backend's countdown stops) and the presenter freezes its own | (b) |
| Title is an action sentence; **no internal tool name** | `confirm.request.title`; the `tool` chip is gone | (a) bug fixed |
| Facts box (`76px 1fr`), key value 600 | calendar: `artifact calendar_event`; email: `email_draft` (66 px body preview); others: `detail` (whole command, pre-wrap, audit A-12) | (a) |
| Change: Now (struck) → After (600) | `calendar_event.before` | (a) |
| Voice hint | the push-to-talk hotkey (approvals need a click or voice; see conflicts) | (a) |
| Reject · Change … **Approve** (`--warn` fill, check), Send for email; all fit in 512 px | `confirm.reply`; **Change opens the typing box** (typed text on an open card is a change, never an approval) | (a), Change (b) |
| "Later" removed | expiry now does it | (a) bug fixed |
| 3 px warn countdown bar | presenter | (a) |
| Countdown 45 s, only while visible and present; on expiry → the stack as **Held**, never approve or reject | `Attention.on_expire` (**new**): the session sets the card aside like "Later" with reason `expired`; `confirm_timeout_s` default 120 → 45 s | (c) built |
| Approve ignores clicks for 400 ms | presenter `approveAt` | (b) |

## 4. Question card

| Element | Driven by | Status |
|---|---|---|
| While Swift speaks: tag **Swift is asking** · "Speaking… I'll listen when I'm done", no timer | `followup {question:true}` + `speech {speaking:true}` | (c) built (speech message) |
| Waiting: tag **Waiting for you**, halo, question 20/26, listening pill · `0:18` · bar | `followup {open, seconds, question}` re-sent by the backend when Swift stops talking (`speech_done`); the card waits the backend's whole window | (b) |
| "Or type Ctrl Space" · Answer later · Cancel request | the real `type` hotkey from `hello.ok`; **Answer later** = `stack.action skip` on `parked:<thread>`: the backend parks the question now and closes the reply window; **Cancel request** = `stack.action end` on it: the question is dropped, nothing is parked | (c) built (`Session._stack_action`) |
| Never labelled "Done"; silence → stack "Unanswered question" | backend parks it (`asked`) | (a) bug fixed |

## 5. Concurrent requests

| Element | Driven by | Status |
|---|---|---|
| "Got it" pill: check · **Got it:** · title, ≤ 300 ms, click-through (no hit region), 2.5 s | `runs` (new row) | (a) |
| Chip 280 × 56: state icon, title (ellipsis) + activity, elapsed; hover → "Open" + accent border | `runs.rows[]` (`state`, `activity`, `started_ms`) | (a) |
| Needs-you chip: amber shield, "Needs your OK" in `--warn-text`, warn border | row `state: confirm` | (a) |
| Ready-to-read chip (green check) | row `state: result` | (a) |
| Click → bring forward; drag → move, remembered | `focus`, `drag_pane` | (a) |
| A working card shrinks to its one line after 12 s without news or hover | `workingQuiet` (30 s → 12 s) | (a) |

## 6. Waiting stack

| Element | Driven by | Status |
|---|---|---|
| Closed 280 × 80, two back layers, amber count badge, "**3 things need you**", "Next: …" | `stack.items` | (a) |
| Double-click opens; click outside or Esc collapses (200 ms) | `watch_outside`; Esc is grabbed while it is open | (a), Esc (b) |
| Open: 320 w, solid, "Needs you · N", rows with type icon (shield / ? / pause), **titles wrap**, reason line | `stack.items[].kind/reason` | (a) bug fixed |
| Hovered or selected row: **Open** · **Skip** · **End** (30 h); max 6 rows then scroll | `stack.action` | (a) |
| "Held" reason for an expired card | `reason: "expired"` (new) | (c) built |

## 7. Typing box

| Element | Driven by | Status |
|---|---|---|
| 512 × 52, 2 px accent border, keyboard icon, 17 px, "Type to Swift", "Enter sends · Esc closes" | `type` pane | (a) |
| Only surface that takes focus | `init_typing` | (a) |
| While a confirm is open: "**Typing can't approve.** Click Approve, or say "approve"." and "Enter = Change" | presenter `pendingConfirm` → `TypeView.confirm` | (b) |

## 8. Timers, alarms, reminders

| Element | Driven by | Status |
|---|---|---|
| Solid card, accent border + halo, 40 px accent circle (timer / bell), label · title, primary **Done**; never fades | `result` whose `run_id` is `due-timer-…`, `due-alarm-…`, `due-reminder-…`, `due-away-…` (`session._show_due`); sticky until Done | (b) |
| "Timer · 10 minutes" label | only the kind is known ("Timer", "Alarm", "Reminder"); the length isn't sent | owner question 6 |
| +5 min / Later | no snooze in the scheduler | owner question 6 |
| Soft chime | backend `system.control.chime` (unchanged) | (a) |

## 9. Tray menu

| Element | Driven by | Status |
|---|---|---|
| 280 w solid panel: orb · **Swift** · live status | left click on the tray icon opens a `tray` pane window; status from `presence` | (c) built (Rust: tray click → pane) |
| Position: current value + 3 × 2 anchor picker | `get_prefs` / **new `set_anchor`** | (c) built |
| Smart placement toggle + help text | **new `set_smart`** | (c) built |
| Pause listening | inbound `listen` | (c) built |
| Type to Swift (real hotkey) | `hotkeys.type` | (a) |
| Settings | **new `open_settings`**: opens `config.yaml` in its default app (Swift never writes it) | (c) built |
| Quit Swift | **new `quit_app`** | (c) built |
| The native menu stays on right-click (same items, plus Open logs folder) | — | (a) |

## Behaviour kept (each has a test or an owner check)

Click-through outside painted parts; no focus stealing; capture exclusion; drag anywhere and
stay dropped (`prefs.dropped`); the tray's Position anchors and the smart caret flip; Esc and
the hotkey stop; countdowns only while shown and present (ADR-015); hover, drag and Read more
hold an answer; the question card waits the backend's whole window; held cards come back
after unlock; waiting cards come forward by themselves; "Got it" for a second request; stack
open/skip/end; typing never approves; generic status labels; Swift speaks (ADR-016 B).

## Conflicts with safety rules (the rule kept)

1. **Voice hint.** The README's hint is "Or say "approve"". Approving by voice needs push-to-talk
   or Swift's name (a bare "approve" from the open microphone isn't taken), so the card keeps
   "Or hold <push-to-talk> and say "approve", "reject", or what to change."
2. **Esc closes the front card.** Esc is a global hotkey (`RegisterHotKey` takes it from every
   app). It is grabbed while Swift works, asks, speaks or the stack is open, as before, but not
   for an answer card that is only being read: that would take Esc away from the owner's app
   for up to 20 s. The × and a click on the card close it.
3. **Typing.** "Enter = Change" sends the typed text as a change; it never approves.
4. **Logs.** New log lines (`speech`, `listen`, `card expired`) carry no content.
5. **Capture exclusion.** The new tray pane is capture-excluded like every pane.

## Owner questions

1. **Idle dot.** The README says "or hidden, per setting". It shows by default; there is no
   setting yet. Keep it, or add a tray toggle?
2. **"Present" = input within 60 s.** Swift's presence monitor calls the owner idle after 10 min
   and away after 30 min (ADR-014). The countdown pauses on those; a 60 s threshold would need a
   new presence level. Worth it now that expiry only moves the card to the stack?
3. **"Show in Word"** on an open long answer: Swift has no action that opens an answer in Word.
   Add one (the desktop lane can write in Word), or leave it out?
4. **Undo** on a cancelled card: nothing can undo a stopped run. Left out (× only).
5. ~~**"Answer later"**~~ Built: Answer later parks the question in the stack at once, Cancel
   request drops it (both through `stack.action` on the question's thread). No question left.
6. **Timer card details**: the label ("Timer · 10 minutes") and **+5 min / Later** need the
   scheduler to send the item's kind, length and a snooze action. Today only the kind (from the
   run id) and the text exist, so the card shows "Timer" and **Done**.
7. **Question window**: the README says 20 s; the backend's `wake.question_s` is 25 s (set after
   owner check 26). The card counts down whatever the backend sends. Change the config default?
8. **Push-to-talk while paused**: with listening paused (mic off), holding the hotkey still
   listens (it is an explicit act each time), and the capsule goes back to "Not listening" after.
   Should paused also refuse push-to-talk?
9. **Confirm "soft tick"** (developer notes): the overlay plays no sound. Use the backend chime
   for confirm cards too?
10. **The provider on a confirm card.** The old card said "Claude Code wants to:"; the design has no
   such line, so it is gone (the facts show exactly what will run, and the byline still names the
   provider on answers). Bring it back as a small line?

## Proof

- Suites: Python 1094 passed (`uv run --frozen pytest -q -p no:cacheprovider`), overlay 61 passed
  (`npm test`) with `tsc --noEmit` clean, Rust 25 passed (`cargo test`).
- New tests: `tests/unit/test_capsule_backend.py` (speech, listen, expiry, Answer later / Cancel,
  typed, protocol), `overlay/tests/capsule.test.ts` (capsule states and words, answer shapes and
  marks, reading time, theme), presenter (away pause, 400 ms, 1.5 s resume), stack (wording, icons,
  whole titles), panes (sizes, tray pane), Rust `theme` and `tray_origin`.
- The dev harness replays every state: `__design(name)` in `overlay/dev/harness.html` (32 states;
  `__design.list` names them), and `overlay/dev/pane.html?label=…&state=…` draws the pane windows
  (`__pane.list`). `?theme=light`, `?wall=white|black|busy`, `?anchor=top-right`, `?bare`.
- Screenshots of every state in dark and light, compared with the handoff frames, are in the
  session notes folder (`capsule-screens/`, 61 files).
- Checked in the harness: click-through regions, Approve's 400 ms guard, no tool name on a card,
  Esc grabbed while Swift speaks, the typing box keeping its text while its notice changes.
