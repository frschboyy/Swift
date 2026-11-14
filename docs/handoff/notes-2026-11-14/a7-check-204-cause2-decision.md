# A7 / check 204, cause 2: what main does, and the decision needed

Branch `claude/a7-check-204-df2c13` (worktree a7-check-204-df2c13).

## What main does today (proven by replay)
Scenario `test_the_request_said_again_to_its_question_reopened_from_the_stack_is_not_a_second_request`
(tests/unit/test_seam_replay.py): Wi-Fi asked "Turn off Wi-Fi?", unanswered and parked; opened from the stack, asked again;
one unclear answer is asked again; then "He has turn off Wi Fi." while the question is open and on screen.

- `dialogue.answer` gives turn `elsewhere` (it looks like a new request).
- `_take_answer`: `q.own`, so `moved_on`, and the question is settled with None (it goes back to the stack).
- `_start_beside` -> `_same_request` matches the still-live system run ("Turn off the wifi"), so it shows "still on it" and starts nothing.
- The run then ends unanswered: **the Wi-Fi stays on, the question goes, and it's parked again.** No agent, no approval card (4b9ecd9 closed that).
  So the owner's restatement is lost: the "lost" case in the brief.

## The decision (product rule: a bare "yes" never approves, except Swift's own question about a reversible change the owner just asked for, open and on screen)
Does the owner saying the request again count as a yes to that open question?

- **A. Yes, strictly.** It counts as a spoken yes only when: it's spoken (never typed); the question is Swift's own, about a reversible change, open and on screen; and the restatement parses to *the same system intent* (system_intents.parse equal to the question's intents, e.g. "turn off the wifi" / "can you turn the wi-fi off"). A fuzzy match doesn't count.
- **B. Never a yes; the question stays.** A restatement keeps the question open and on screen and asks it again once ("Turn off Wi-Fi? Say yes to do it."), with no park, no "still on it", and no second request. The owner still has to say yes.
- **C. Treat it as a fresh request.** The old question goes and a new own "Turn off Wi-Fi?" is asked. Same as B for the owner, but with a new card and more churn.

**Recommendation: A + B.** An exact same-intent restatement approves (it's the owner's own words asking for the change, which is stronger than "yes"). A fuzzy same-request match, like 14:44:20's misheard "He has turn off Wi Fi." (it doesn't parse to a system intent), falls back to B (asked again, never approved). So the 14:44:20 utterance itself would get B: asked again, then the owner says yes.
B alone is the conservative option and touches no approval path. If chosen, it needs no product-rule review beyond the usual.
