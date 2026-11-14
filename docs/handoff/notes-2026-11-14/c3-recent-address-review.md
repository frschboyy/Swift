# C3: an address given earlier opens (branch claude/c3-recent-address-83f24a)

Commits: 27bcdbe (code + tests, root), 52a5df9 (check 305, ledger, report, workstreams). Based on cc4a18d; main is now c0c2604.

## For the reviewer
- Source of the owner's words: `Exchange.owner` (record transcript = today's RunScope.said, plus RunScope.answers = Answer.said),
  stamped `heard_at` = clock.now() at the start of `_interaction` (before capture). Set in `_remember` and `_local_answer`.
- "Same conversation" = `_thread_context`'s decision. Only when it returns context does `RunScope.earlier` get
  `last.owner_words()` (`session.py`, `_thread_context`). The resumed-from-stack path gives none.
- `_open_url` adds `scope.earlier` entries heard within `RECENT_ADDRESS_S = 600` to the WebScope it already builds.
- Edge worth a look: the parked-question branch of `_thread_context` ("however long ago") also passes the words; the 10-min filter still applies.
- `Exchange` moved to `src/swift/exchange.py` (re-exported from session.py; tests import it from there). session.py 5058 -> 5008.
  `SESSION_MAX_LINES` in test_structure_ratchet.py was NOT lowered, so other branches growing session.py still merge; lower it at merge if wanted.
- Mutation checks: each refusal test failed against the mutant dropping its limit (agent answer counted / no window / no follow-up gap check).

## Verified
- Full suite: 1 failed (the known test_a_whole_drive_or_volume_spelled_another_way_is_never_a_blanket_read), 2133 passed.
- Parity 413/423, harmful 0, unchanged from before the change.
- report.py's new 305 line, run on 2026-11-14 12:30+ rows: FAIL at 12:35:49 (correct for the old behaviour).
