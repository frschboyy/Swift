# Brief: ADR-016 Phase C, real conversation (dialogue)

This is the task as given to the session on branch `claude/phase-c-dialogue-b22c15` (2026-10-28). To resume it, check that branch and worktree first (see `README.md` §2), then continue from what's there.

Build **ADR-016 Phase C: Dialogue**, as specified in `docs/decisions/ADR-016-assistant-parity.md` §5.1. Read the whole ADR first, especially §3, §4, §5, §10, §11, §13–15, and what A1, A2 and B left for C: §13.4, §14.4, §15.4.

## Scope

1. **A dialogue manager:** a new module `swift/dialogue.py` with a narrow interface, owned by the session, on top of ADR-013's threads. Keep the wiring in `session.py` small.
2. **Pending questions:** `ask_owner(question, kind=yes_no|choice|free, options?)`, for runs (a Swift tool through the MCP server) and for lanes.
   - Swift shows the question card and speaks it.
   - As soon as speech ends, it **opens the microphone with end-of-speech detection, no hotkey**. There's a time limit and a visible state; reuse the Capsule question card ("Swift is asking" / "Waiting for you").
   - The answer goes to the pending question, not to the router. A clearly unrelated new request still wins.
   - Never while away or locked.
3. **Resolving answers:**
   - yes and no;
   - ordinals and names ("the second one", "Sam Lee, not Sam Okoro");
   - numbers and times;
   - corrections ("no, make it four");
   - cancel.

   Ambiguous or inaudible answers get one re-ask, then the card goes to the waiting stack as "Unanswered question".
4. **Disambiguation and slot filling:**
   - `find_contact` with several matches asks "Which Sam: Sam Lee or Sam Okoro?";
   - a reminder with no time asks "When?";
   - "set a timer" with no length asks "For how long?".

   Slots live in the intent, so `swift/system/intents.py` and the dialogue share one mechanism.
5. **Carry-over and ellipsis:** the last intent or answer is kept for about 60 s, cleared when presence is lost ("and tomorrow?", "make it louder", "send it"). Integrate with `routing/fast.py`'s follow-up context.
6. **End-of-speech detection:**
   - `end_silence_s = 0.8` cuts people off. A trailing "and" or "uh", or a number cut off mid-way, keeps listening, up to a cap.
   - The window is longer for free-text answers.
   - Measure it against the owner's local clips: never upload them or quote their transcripts.
7. **Confirm cards read aloud** (deferred from B): the title and key facts.
   - Voice approval still needs Swift's name, or the hotkey.
   - A bare "yes" never approves.
   - Typing never approves.

## Defaults (record them in the ADR as reversible)

- The microphone opens automatically only after Swift asks something (§11 Q3).
- One exchange at a time; no continuous conversation mode.

## Must keep working

Owner checks:
- 26–27 (a question parked, then picked up later);
- 46 (unsure speech: say it again);
- 53 (Wi-Fi "yes" needs "Swift, yes");
- 69 (the Capsule question card);
- the waiting stack;
- half-duplex: Swift never hears itself;
- concurrency.

The audit's A-07 and A-08 fixes (cards never cancelled by another request ending) must hold. Add tests for that.

## Proof

- Tests for: answer resolution, slots, carry-over, end-of-speech, pending question vs. a new request, confirm read-aloud, and the safety rules.
- Run every suite and parity, as in `CLAUDE.md`. Parity must not drop.
- Owner checks numbered from **100**, plus report lines.
- An ADR-016 §16 "Phase C: built".
- Logs stay content-free: kinds and counts only.
