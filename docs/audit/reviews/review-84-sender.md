# Review: §8.4 sender, commit 4454900 (claude/dazzling-curie-f61a88)

Verdict: REJECT as-is (small fixes; then pass with notes).

## Blocking
1. tests/fixtures/protocol/frames.json:29 — fixture added but overlay/src/protocol.examples.ts not regenerated.
   `tests/unit/test_protocol_contract.py::test_the_typescript_examples_are_up_to_date` FAILS on the branch.
   Fix: `python tests/protocol_contract.py`, then tsc in overlay/, commit the .ts.
2. src/swift/background.py:40 — sends via `session._send`, which tags with `self._current()` = the run in front
   (session.py:952-957, 1011-1014) when the scheduler task has no _RUN. With an owner request in front, the
   scheduled failure gets the owner's thread_id, is `run.remember`ed into the owner's run (replays with it) and
   is drawn as that request's error, replacing whatever card is in front (a confirm/question card included).
   It also skips `_due_blocked()` which the due path honours. Fix: `with session._as(session._none)` (or
   `_raw_send`) and queue it behind the front card like due cards, or at least never into a run's thread.
   Add a seam test with a request in front.
3. Claim "the only background runs are the scheduler's due items" is false: the weekly improvement pass
   (`backend/__main__.py:142-145`, `session.start_own` session.py:2533) is a run nobody asked for; its failure
   goes through `_send_result` as an ordinary "asked" Failed card with no Swift origin. Either route it
   (origin + detail) in this change or correct background.py's docstring and PROGRESS.md row 32 and record it.

## Notes
4. Coverage gap: only `notify_due`'s inline path is guarded. When something is in front, showing happens later in
   `_wait_due` (session.py:3741, its own task) or `_screen`/`ready` → `_kick_due`; exceptions there are not
   caught by `guarded` (unretrieved task exception, no card). The likeliest real failure (`_show_queued_due` →
   `_send_result`) is mostly on that deferred path.
5. background.py:26 `classify(..., "Swift")`: a matched kind gives AI-provider text for a timer —
   OSError "network is unreachable" → "Can't reach the AI service"; "401"/"authenticat" → "Sign in to Swift again".
   No raw text leaks (detail dropped, only fixed table text), but it's wrong. Suggest: always `_FALLBACK`, or
   whitelist kinds that make sense locally.
6. Overlay disconnected: card is dropped, not queued/stacked (`overlay_connected()` not checked). Item itself is
   still fired-not-shown, so it returns on restart (hint text true). Acceptable; say so in PROGRESS.
7. Sender throwing: if `_send` raises, the new exception replaces the original (original kept as __context__);
   scheduler still catches `Exception` and logs — loop survives. No duplicate per retry: scheduler `_handed`
   prevents refire in this run; there is no retry. Doesn't block beyond an awaited websocket send.
8. Test (tests/unit/test_seam_replay.py:1797): calls `guarded` directly with a stand-in `on_fire`, so it doesn't
   cover the wiring in `_make_system` nor a real `notify_due` failure; "fails without the change" only via
   ImportError. Does run the real overlay presenter (`_shows` stage error). Add: a request in front (item 2), and
   a real notify_due failure (e.g. patch `system.due_text` to raise).

## Passes
- Card text is Swift's own: fixed fallback or failures-table text; `detail` dropped; no provider name.
- origin_detail = Item.title = owner's label or a fixed "Timer/Alarm/Reminder"; rendered by `swiftOrigin`
  (main.ts:2078) via `el(...)` text, as "· label" in Swift's origin header. Not an instruction/approval path.
- Log line has code, kind, error class only; no label. Re-raise → scheduler `logger.exception`, whose traceback
  formatter strips messages (logging_setup `_traceback`) — not re-verified on a live sink.
- Sign-in watch (signin.py:137) catches and logs only; no card — fine, not a run.

Tests run: new seam test PASS; test_failures + test_protocol PASS; test_protocol_contract 1 FAIL (item 1).
