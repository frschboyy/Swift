# ADR-016 Phase C (dialogue): status

Branch `claude/phase-c-dialogue-b22c15`, on top of `main` `50f8e0f`. Not pushed or merged.

## Done (committed, mostly tested)

- `src/swift/dialogue.py`: `Question`, `Answer`, `resolve` (yes/no, ordinals, names with "not X",
  numbers, durations, times, corrections "no, make it four", cancel, "never mind, <new request>"),
  `Dialogue` (one question on screen, others wait; one re-ask then shelve), `Carry` (60 s or same
  thread, forgotten on presence loss), `elide` ("make it louder", "20 more", "no, make it four").
- `src/swift/endpoint.py`: `more_coming` (trailing "and", "uh", "the", "twenty"…), `EndOfTurn`
  (0.8 s base, 1.3 s for free-text answers, +1.2 s extensions, 3 s cap).
- Slots in the grammar (`system/intents.py`: `SLOTS`, `missing`): "set a timer" and plain
  "remind me to X" (no day, no number, not "remind me what…") ask "For how long?" / "When should I
  remind you?". `system/lane.py`: `Outcome.ask`, `start`, `fill`, `redo`, `Outcome.done`.
- Session wiring (`session.py`, "the dialogue" block): lane questions replace `_system_confirm`
  (kept as a property); run questions through the new `ask_owner` tool (`workflows/tools.py`,
  `RunScope.ask_fn`); `find_contact` asks "Which Sam: Sam Lee or Sam Okoro?"; answers from the open
  microphone (`hear_wake`), the hotkey/typed (`_midrun_text`), clicks (`ask.reply`), or a recorder
  capture with end-of-speech when wake listening is off (`_capture_answer`); never while away
  (`hold_cards` shelves questions and forgets carry-over); a run's end drops only its own questions;
  a confirm card on screen takes precedence; unanswered → parked "asked" (the stack).
- Carry-over: system intents (`_carry_over`), fast lane moments now live in `Dialogue.carry`
  (`_thread_moment`, `_local_exchange`); fast lane "and tomorrow?" (`fast._other_day`).
- End of speech: `_capture_voice` snapshot check (`MicRecorder.snapshot`), wake utterances held
  and stitched (`_hold` / `_flush_held`), `WakeListener(end_silence=...)` longer for free text.
- Confirm cards read aloud (`speech.card_speech`, `Session._read_card`) for spoken requests;
  approval still needs "Swift, yes" / hotkey; typing never approves.
- Protocol: outbound `ask`, inbound `ask.reply`. Parity: 397/407, 0 harmful (was 365/375); new
  "dialogue" rows appended; `eval/routes.jsonl` cr10 and `routing/examples.jsonl` moved to local.
- Tests: `tests/unit/test_dialogue.py` (99). Last run: 96 passed, 3 failing (below).

## Left, in order

1. Fix the 3 failing tests in `test_dialogue.py`: half-duplex tail in two tests (already edited:
   `speaker._quiet_at -= 5.0`), and `test_without_wake_listening_swift_records_the_answer_itself`:
   the `LeadRecorder` levels path never releases (check `forward_levels`/`NoiseGate` with
   `LeadRecorder.on_level`; maybe the gate's floor needs more loud blocks first).
2. Run the whole suite (`uv run --frozen pytest -q -p no:cacheprovider`, ~4 min; run in the
   background) and fix regressions. Regenerate `eval/parity/passing.txt` with
   `score.py --write-passing` after checking nothing in the old file stopped passing.
3. Overlay: `overlay/src/protocol.ts` (`ask`, `ask.reply`), `main.ts` render Swift's question card
   from `ask` while state is `working` (reuse `renderQuestion`; options as buttons sending
   `ask.reply`; phases asking/listening/again/heard; close on `open:false`), tests, `tsc`, `npm test`
   (node_modules junction), dev-harness check on port 1431 (never 1420), revert launch.json.
4. Endpointing measurement spike `spikes/endpointing/measure.py` over the owner's saved clips
   (`%LOCALAPPDATA%/Swift/audio`, local only, counts only, never transcripts).
5. Owner checks from 100 in `docs/testing/owner-checks.md`, report lines in
   `spikes/owner_checks/report.py`, ADR-016 §16 "Phase C: built".

## Defaults taken (reversible; record in ADR-016 §16)

- §11 Q3: the microphone opens by itself only after Swift asked something, for `wake.question_s`
  (25 s); a typed request's question is answered by typing (no microphone).
- One exchange at a time; no continuous conversation mode.
- A bare number answering "For how long?" means minutes (a timer is reversible, the reply says it).
- A reminder with a day but no time, or "remind me about…", still goes to the agent.
- Lane yes/no questions keep the 45 s window; slot questions use the question window.
- Questions never show over a confirm card; the card hears "Swift, yes" first.

## Follow-up found (not in scope)

- "remind me to buy food for 5 people" reads "for 5" as a time (pre-existing grammar bug).
