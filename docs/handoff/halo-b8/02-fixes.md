# Fixes

Found by running the real overlay (an isolated test build against the debug backend; `docs/testing/live-ui-loop.md`
§4) and by putting the STT correction UI on screen (`docs/design/halo-system/boards/stt-corrections-1/`). Each needs a
scenario that fails first (`tests/unit/test_seam_replay.py` for anything on screen), then the fix.

## 1. Confirm and stack path (bug candidates: confirm with a failing seam scenario first)

**F1. A lapsed OK keeps the session busy.** Repro: `debug.run email`, let the 45 s countdown run out (log: `card
expired into the stack`), then `debug.run research` within ~20 s → `debug.run ignored: busy | state='confirm'`. A new
spoken request then logs `next request recorded while the last one starts | state='confirm'`. Expected: once a card
expires into the stack the front is free. Look at `session.py _expire_card` (≈ l.1409) and `_front_busy` (≈ l.986):
the state after expiry.

**F2. A lapsed OK comes back to the front by itself.** Repro: after F1's lapse, press push-to-talk and release in
silence (an "I didn't catch that" error card). The overlay sends `focus` and the backend re-sends `state=confirm` +
`confirm.request` with a fresh 45 s countdown: the lapsed approval is in front again, unasked. Expected: only the owner
brings a stacked item back (Open, or "what's waiting?"). Look at what sends `focus` after an error card in `main.ts`
(the deck's auto-focus) and `session.py _focus_row`.

**F3. A lapsed OK shows as the front card with no countdown after the overlay restarts.** Repro: lapse an OK, restart
the overlay (not the backend): the first card is the stacked OK, without its countdown. Expected: the pile, with the
amber count.

**F4. The overlay's stage stays `confirm` after the card leaves.** After F1's lapse, `#stage[data-state]` is still
`confirm` with no card. Check what reads it (Esc grab `set_escape`, hit regions) and make it follow the presenter.

## 2. UX found on the real window

**F5. Identical deck rows.** Asking the same thing twice or three times gives identical "what time is it · Ready to
read" rows and a "+2". Proposal: the same words within a minute fold into one row with a count ("×3"), or each row shows
its time. Owner's call; default: fold with a count.

**F6. "Stop" while listening or transcribing drops the request silently.** During a working run, "stop" shows a
Stopped card; before the run starts, the capsule just goes idle. Expected: the same Stopped card ("Stopped “…”"), or a
one-line "Didn't send" notice.

**F7. Repeated "stop" removes the Stopped card at once.** A second "stop" closes the confirmation that the first one
stopped it. Expected: "stop" with nothing running leaves the Stopped card to fade on its own.

**F8. The text box didn't get the keyboard once** while the owner was in VS Code (Windows' foreground lock); it did
another time. Make an owner check of it; if it recurs, use `AllowSetForegroundWindow` from the hotkey handler before
`set_focus` (`src-tauri/src/lib.rs` ≈ l.524).

## 3. STT corrections (branch `claude/stt-corrections`, review on canvas)

1. **The flag at rest fails contrast** (`--faint` at 55% opacity ≈ 2.7:1; needs 3:1). Draw it at full `--faint`, `--text`
   on hover; drop the opacity (`styles.css .heard-flag`).
2. **Saving gives no sign it worked.** After Enter, the flag becomes a check with tooltip "Corrected" for the card's
   life (or Edge · Got it "Thanks, saved" for 2.5 s).
3. **Tooltip over-promises** ("helps Swift learn your voice" reads as training, which D1/privacy.md say doesn't happen).
   Use: "Heard that wrong? Correct it: it helps Swift hear you better."
4. **Picked kind is a border only.** Selected chip: `--accent-soft` fill, `--accent` text, a check.
5. **Two kind labels need context:** "Accent or pronunciation", "Other voices or noise".
6. **Pane opens 10 px short** (`paneSize` gives 200, content 210). Open at 212.

Not from that branch: `.card-foot` paints a solid band behind "Swift" and Copy on every card in the harness; Halo's
footer has no fill. Check on main.

## 4. Things that were checked and are fine (don't "fix")

- `debug.say "approve"` approves: `debug.say` stands for speech with the hotkey (`intake.SPOKEN_LIKE`); the one hold
  was the noise doubt asking once more. Hands-free plain "approve" can't be tested with `debug.say`.
- The "[Context: the previous voice request…]" text on a card came from the echo worker echoing its prompt.
- The OK stays in front while other answers arrive; a real double click on Send sends one `confirm.reply`; cards never
  move the foreground; the engine dying shows "Reconnecting…" and recovers without a restart.
