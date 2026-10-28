# ADR-016 Phase C (dialogue): status

Branch `claude/phase-c-dialogue-b22c15`, on top of `main` `50f8e0f`. Not pushed or merged.
What was built is in ADR-016 §16.

## Done

- Everything in ADR-016 §16.1: the dialogue, slots, `ask_owner`, carry-over, end of speech,
  confirm cards read aloud, the `ask` / `ask.reply` protocol, the overlay's question card (`ask.ts`).
- Tests: 1240 Python, 78 overlay, `tsc` clean. Parity 397/407, 0 harmful; `passing.txt` regenerated.
- End-of-speech measurement: `spikes/endpointing/measure.py` (ADR-016 §16.3).
- Owner checks 100–108 in `docs/testing/owner-checks.md`, with report lines.

## Left

1. Dev-harness look at the question card (port 1431, never 1420): `window.__shim.inject("ask", {...})`
   while state is `working`, with phases asking → listening → again → heard, and options as buttons.
2. Merge into `main` when the owner says so. `main` has moved on (the recordings loop); expect
   conflicts in `session.py`, `owner-checks.md` and `report.py` (recordings uses checks 110–116).
3. The owner runs checks 100–108.
