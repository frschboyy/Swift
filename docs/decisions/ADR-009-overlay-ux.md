# ADR-009: Overlay UX: readable failures, movable placement, visible status

- **Status:** Accepted
- **Date:** 2026-10-24
- **Decided by:** Owner (requested a full UX review); changes below implemented on `claude/swift-identity-providers`

## Context

The owner asked for a review of the whole overlay experience, not only error handling and placement. This ADR records what the review found, what changed, and what was deliberately left alone.

## Audit: what the overlay did before

Walked through every state (idle, listening, transcribing, working, confirm, result, error) and every path into them (push-to-talk, debug scenarios, second launch, backend start and failure, hotkey registration).

### Failures

1. **Raw provider text was the headline.** An executor failure showed `result.summary` as the card's message: "API Error: 529 {"type":"overloaded_error"...}", "Claude Code stopped without an answer (CLIConnectionError: ...)". The title was always "Claude Code ran into a problem", and the hint always "Try again. If it keeps failing, run `claude`...", whatever the cause.
2. **No way to act.** The only interaction was clicking the card away. Trying again meant speaking the whole request again.
3. **Everything was red.** "I didn't catch that" (nothing broken) looked the same as a crashed engine.
4. **Silent failures.** A tap of the hotkey (shorter than 0.3 s) did nothing visible. Push-to-talk while a run was going did nothing visible. Push-to-talk while the backend was reconnecting was dropped on the floor.
5. **Backend failure was technical and permanent.** "Swift's backend isn't available: could not start the backend (C:\...\python.exe): ..." stayed on screen with no way to act on it.
6. **Hotkey conflicts** read as "push_to_talk: cannot register 'ctrl+shift+space' (in use by another app?): ..." and faded after 8 s, although Swift is unusable without push-to-talk.
7. "Retrying (rate limit)…" steps used the CLI's internal error codes.

### Placement

8. **Fixed at bottom centre.** The 720 x 560 window is click-through except for card controls, but cards still visually covered whatever was there, often the text being typed in.
9. **No way to move it**, by mouse or setting.

### Status and feedback

10. **No sign Swift had started.** The window is transparent; after launch nothing showed until the first push-to-talk. The tray tooltip said "Swift" in every state.
11. **No sense of time during long runs.** No elapsed time, nothing when no step had arrived for a long time. Runs of a minute or more looked stuck.
12. **Cancelling needed the keyboard.** Esc was the only way to stop a run; mouse users had no control.
13. **A silent microphone looked like Swift not listening.** A muted or wrong input device gave a flat orb and "Listening..." indefinitely.
14. **Confirm cards had no deadline.** The run stopped after `confirm_timeout_s` (120 s) with "No answer in time" but the card never said so.

### Results

15. **Fixed 6 s fade for every result**, whether a five-word answer or a 300-character summary with a six-row table.
16. **No copy.** Answers could only be read; the window can't take focus, so text selection and the web Clipboard API don't work.
17. **"Cancelled" card said "Cancelled." twice** and stayed 6 s for something the owner just did.
18. Lists and tables over six rows were cut silently.

### Accessibility and polish

19. `--faint` (#6c6f7d) on the panel was about 3.6:1, below 4.5:1 for small text (bylines, hints).
20. Error cards weren't announced (`aria-live="polite"` on everything, no `role="alert"`).
21. Hotkeys were printed as config strings ("Ctrl+Shift+Space" or "ctrl+shift+space").
22. No forced-colors (high contrast) support.

### What already worked well and was kept

- The backend-owned state machine and the "face, not brain" split (ADR-006).
- Non-activating, click-through, capture-excluded window mechanics.
- Hover pauses the fade, with the draining bar showing time left.
- Attribution ("Claude Code is reading", "Swift · via Claude Code"), ADR-008.
- Answering confirm cards by voice.
- Reduced-motion support.

## Decisions

### 1. Failures are classified into something the owner can act on

`swift/failures.py` turns raw failure text into a `Failure`: a plain **title** ("Can't reach Claude Code", "Claude Code isn't signed in", "Usage limit reached", "Claude Code is busy right now"), a one-sentence **message**, a **hint** saying what to do, whether **retry** could help, a **severity** (`error` or `info`), and the raw text as **detail**. The raw text is logged and available behind "Show details", never the headline.

- Kinds: auth, billing, rate_limited, overloaded, too_large, offline, timeout, service, crashed, and Claude Code's own budget / max_turns stops. Unknown text keeps the provider's words as the message (they may be written for people), with the provider's hint.
- Classification knows failure kinds, not providers: titles use `ProviderInfo.name`. Provider-specific fixes come from `ProviderInfo.error_hint` and the new `signin_hint`.
- Executors may classify themselves (`ExecResult.failure`; Claude Code does, from the result event or the SDK exception). Otherwise the session classifies `summary`.
- The `error` message gains optional `title`, `detail`, `retry` and `severity` fields. Old fields are unchanged.

### 2. "Try again" re-runs the failed request

A new inbound `retry` message re-runs the last failed transcript, routed as before, without speaking it again. It's offered only when the failure is retryable **and** there is a transcript to repeat. Failures *during* a run are still never retried automatically, since the run may have changed files (ADR-008); retrying is the owner's choice.

### 3. Nudges are info, not errors

"I didn't catch that", a too-short press ("Hold to talk: keep Ctrl+Shift+Space held while you speak"), and "Swift is still starting" use the info style: accent colour, info icon, 5 s fade. Errors stay red, fade after 12 s (paused on hover), and are announced with `role="alert"`.

### 4. Placement: six anchors, drag to move, smart flip away from the caret

Considered:

- **Free positioning (drag anywhere).** Rejected for now: the window is a fixed transparent box whose cards hug one edge. Free positions get awkward across monitors with different DPI, and an offset that suits one monitor can be off-screen on another.
- **Avoiding "important content" in general.** Swift can't tell what matters on screen. The one reliable signal is the **text caret**: where the owner is typing.
- **Moving during a run.** Rejected: a card jumping while it's being read is worse than one in a slightly bad place.

Chosen:

- Six anchors (top or bottom; left, centre or right) per monitor. The overlay still follows the cursor's monitor.
- **Drag any card by its header**: Rust follows the cursor while the button is held, then snaps to the nearest anchor on the drop monitor (thirds across, halves down) and saves it. A press without movement is a click.
- **Tray → Position**: the same six choices, for when dragging isn't practical, plus a checkbox "Move away from where I'm typing".
- **Smart placement** (on by default): on push-to-talk, if the card zone at the chosen anchor covers the foreground app's caret (`GetGUIThreadInfo`), the overlay opens at the opposite edge in the same column. It never moves while an interaction is running. Apps without a system caret (most browsers) report none, and the overlay stays put.
- Preferences live in `%LOCALAPPDATA%\Swift\overlay.json`, written by the overlay. `config.yaml` stays the owner's file.
- Long runs can be **collapsed** to one line (spinner, activity, elapsed time, expand). The choice is remembered.
- The working card's step list is click-through. Only its header and Stop button take the mouse, so a long run blocks less.

### 5. System status is always visible

- On first connect: a brief "Swift is ready. Hold Ctrl+Shift+Space and speak."
- The tray tooltip follows the state: starting, ready (with the hotkey), reconnecting, stopped.
- Push-to-talk while the backend is starting, reconnecting or down shows a card saying which, instead of doing nothing.
- A backend that can't run gets a card saying what's wrong in plain words (config error, engine didn't launch, engine stopped), with details and Open logs. It stays until dismissed or the connection comes back.
- Hotkey conflicts name the key and stay until dismissed.

### 6. Runs show time and give control

- Elapsed time after 3 s. A "Still working" note when no step has arrived for 20 s.
- A **Stop** button next to the Esc hint.
- Push-to-talk during a run explains that Swift is still busy and how to stop it.
- Confirm cards show a draining bar for `confirm_timeout_s` (sent as `timeout_s`) and a countdown in the last 30 s.
- While listening, 1.5 s of silence from the mic turns the pill into "Can't hear you. Check your microphone".

### 7. Results fit their length and can be copied

- Fade time is 4 s plus reading time (45 ms a character), between 6 and 20 s. Hover still pauses it.
- **Copy** puts the summary plus the full list or table on the clipboard (Win32 clipboard; the overlay never has focus). Cut lists say "and N more (Copy includes them)".
- Cancelled is a one-line acknowledgement for 2.2 s. "Rejected" reads "Not approved".
- Every card has a dismiss button. Clicking the body still dismisses, except on buttons and details.

### 8. Accessibility

- Muted and faint text raised to at least 4.5:1 on the panel. The panel is slightly more opaque (0.95).
- Errors use `role="alert"`, other cards `role="status"`. Icon-only buttons have labels. The collapse toggle reports `aria-expanded`.
- Hotkeys are drawn as keycaps.
- 28 px minimum targets for icon buttons.
- `forced-colors` support. Reduced motion also stops the spinner.

## Consequences

- Protocol additions are backward compatible (new optional fields, one new inbound type). `PLAN.md` §3's table still describes the core fields.
- `ExecResult` and `ProviderInfo` gain optional fields; executors that don't set them get session-side classification.
- New Rust commands: `begin_drag`, `get_placement`, `copy_text`, `open_logs`, `set_status`. New windows-sys features: DataExchange, Memory, KeyboardAndMouse.
- Not verified on hardware yet (REQUIRES-HW, owner-run): dragging the real window across monitors with different DPI; smart flip in Notepad, Word and VS Code (VS Code may not expose a system caret); the clipboard in the release build; tray Position checkmarks.
- Not done, possible later: free positioning; avoiding the mouse pointer or the foreground window's focused control via UI Automation; resizing the window to the card so the transparent area shrinks.
