# C3: an address given earlier opens (branch claude/c3-recent-address-83f24a)

Commits: 27bcdbe (code + tests, root), 52a5df9 (check 305, later renumbered 330), d736d59 (merge of main c9f3b2e; check 305 -> 330).

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

## After the merge of main c9f3b2e (d736d59)
- Full suite: 2137 passed, 1 failed: `test_a_card_counts_down_on_the_backend_s_clock_seen_away_and_back`. It's flaky and not from C3:
  it failed once on main c9f3b2e as well, then passed on main and 3 times out of 3 on the branch. The volume-spelling failure
  above is fixed on main.
- Parity 413/423, harmful 0 (the same 10 weather/news misses).

## Second review (2026-11-14, a reviewer other than the author, against the owner's decision and CLAUDE.md's product rules)
Verdict: **matches the owner's decision; no blocker.** What I checked, and what I found:
- **Only the owner's words.** `Exchange.owner` = `record["transcript"]` (set only in `_interaction`, from capture: spoken
  or typed) + `scope.answers` (filled only by `ask_owner` from `Answer.said`, which `_take_answer` sets only for a
  non-click answer that isn't yes/no/cancel). So a click on an option the agent wrote, a card typed answer (arrives as a
  click), and any yes never add an address. The agent's answer, `Exchange.request`, desktop_context and tool output never go
  in. **A yes to the address the agent offered doesn't count:** as decided.
- **A partial name doesn't widen it.** I checked WebScope by hand: "usiu" and "my university is usiu" allow nothing; only a
  spelled-out address ("usiu dot ac dot ke", "usiu.ac.ke") does. So "open my university's website" after only a name still
  has to ask.
- **10 minutes.** `heard_at` is set when the request starts (before capture), and answers given later in that run get the same
  stamp, so the age is always overstated, never understated. The filter is `now - heard <= 600` in `_open_url`, on the
  virtual clock; test_desktop covers the edge. One exception that errs the other way: a run that never went through
  `_interaction` (a stack resume, debug.run) has `heard_at` None, so `clock.now()` is used when it's remembered. Its answers
  then count as younger by up to the run's length. Minor; that run has no transcript.
- **Same conversation.** `scope.earlier` is set only where `_thread_context` returns context (after `_open_scope`, so it is the
  current run's scope). A new topic, a gap over `followup_s`, an error or a cancel leave it empty. A resumed stack item gets
  none. The chain is capped at `EARLIER_MAX` (4) plus the previous exchange, so words further back can't open even inside
  10 minutes. That errs on the strict side.
- **Parked-question branch** ("however long ago"): it passes the words, but the 10-minute filter still drops old ones. OK.
- **Logs content-free.** No new log line carries words or an address; `record["context"]` is still id and age only.
  `Exchange` lives only in memory (`_last_exchange`, `dialogue._carry`); `Parked`, which is written to disk, has no `Exchange`
  field. So the owner's words don't reach any new file.
- **Other product rules:** recipients, approvals, typing and locking are untouched. The tool stays "reversible", with no card,
  as before. Writing into apps and memory are untouched.
- **Agent guidance.** desktop_open's description and NOT_NAMED_URL tell the agent to ask with `ask_owner` (kind 'free'),
  never to offer an address. That matches "the agent asks for an address rather than offering one".

Not blockers, but the owner should know:
1. **The site's paths go with it, now for 10 minutes.** This rule already existed: "or its site" lets the agent open any path,
   query or subdomain of an address the owner gave (`https://usiu.ac.ke/x?q=…` and `evil.usiu.ac.ke` both pass). C3 makes
   that last up to 10 minutes of the conversation instead of one request. The only place it could send what it read is that
   same site, which the owner named.
2. **"It sounded like X" + yes:** that transcript is Swift's own earlier hearing of the owner. Same-request behaviour as before;
   now it lasts 10 minutes too.
3. `SESSION_MAX_LINES` is still not lowered (see above); it's the merger's call.
