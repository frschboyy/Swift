# Swift reliability audit: are the fixes solving the problem? (2026-11-05)

Scope: the fixes of 2026-11-04 and 2026-11-05, including the uncommitted ones from today's owner checks, and the commit history behind them. This is an engineering audit, not a debugging session. No product code was changed for it.

**Who wrote this:** the same Claude session that wrote most of these fixes, so it is not independent. A separate review is worth doing (see "Limits").

## 1. The answer

**Mostly no.** Some fixes are sound, but the recent round is patching symptoms of four design gaps, and some of it causes new bugs.

The two worst symptoms in today's checks were caused by fixes made earlier the same day, and every test passed when those fixes landed:

| What you saw | Which fix caused it | Why the tests missed it |
|---|---|---|
| "Your timer is up" on repeat | S1 / O-08 (`e602d8d`) resends a card the overlay hasn't confirmed, and speaks each time | The tests use a fake overlay. The report printed **PASS** for "8 sent, 1 drawn, 7 not drawn" |
| A Wi-Fi card stuck on screen that couldn't be removed | S2 / T-06 (`d44cac0`) added a path that closes the question but never ends its card | The dialogue model checks that the question closes. It doesn't model the overlay's card |

Today's uncommitted fixes repeat the pattern. Section 3 shows one new regression I measured and two I found by reading the code. **They should not be merged as they stand.**

### Your example: "Did you mean Alex Samia?"

This is a partial fix. It is in the right layer (the tool, not the agent's judgement), and it closes open finding X-01. But it doesn't reach the cause, and it adds new problems.

- **The cause:** `directory(query)` promises "contacts matching the query", but nothing defines "matching". The real connector appears to match the start of a name (Google's search is documented that way, though I didn't call it live), the fake matches any substring, and a test connector matches any word. `find_contact` treated whatever came back as a match.
- **What the fix adds:**
  - **A rule that's too blunt:** word equality has no idea of titles or descriptions. "Dr Lovelace" now gets "I couldn't find a Dr Lovelace. Did you mean Ada Lovelace?", and "Ada from the university" gets a similar question (both measured).
  - **The wrong input:** it compares the words the agent chose to search for, not the owner's words.
- **The gap it leaves (read in the code, not run):** every candidate is added to `scope.resolved` *before* the question is asked. If you say "no" to Alex Samia, that address still counts as a known recipient, so a later `draft_email` to it would pass the recipient check. The card is then the only protection.

## 2. Four underlying causes

### C1. A request isn't a thing in the system (the biggest)

There is no single record that says "this request exists, is in this state, and is in this place". That information is spread across at least 14 backend holders: `Run`, `_focus`, `_cards`, `_aside`, `_expired`, `_stack_skipped`, `parked`, `dialogue`, `_followup`, `_question`, `_offer`, `_fix_offer`, `_due`, `_due_sent`. The overlay has its own copies: `state`, `pres`, `asked`, `question`, among 59 top-level variables in `main.ts`.

The clearest evidence is in your report: `Turn off the Wi-Fi.` shows `local done` at 15:51:11, **while its question was still open**. A system request has already finished when it asks, so its card has no owner. The card lives on as a `local-N` id, and the meaning of a request type is carried in id prefixes (`local-`, `due-`).

This explains: the Wi-Fi card that couldn't be removed, a card in two places, the timer refused behind a stuck card, stale stack items, and most of the seams audit's O and T findings. It is also what you asked for in section 2 of your feedback: one source of truth.

### C2. The overlay can refuse without saying so

The backend sends a card and hopes. The presenter can silently decline it (`shown: false`), and the backend never learns why. Two ad hoc acknowledgements were added afterwards (`card.seen`, `due.shown`), and the due retries are guesswork built on top. My backoff from today makes the guessing politer, but doesn't remove it.

### C3. What was said gets re-parsed by many separate matchers

The same text goes through the router, `intents.parse`, `owner_intents`, the mid-run grammar, the dialogue, `_short_kept`, `fragment`, `names` and the workflow library. Each has its own rules. There are about 40 regex and word-set constants across these modules, and three filler lists that differ, one of which I added today. The model's confidence for each word is also mostly thrown away.

**The Bluetooth bug shows this best, and I gave you the wrong cause earlier.** I said the grammar didn't recognise the doubled sentence. That is only half of it. The interaction log shows what actually happened:

1. The router sent the doubled sentence to the agent.
2. The agent correctly called `system_action`.
3. Swift's safety check, `owner_intents`, splits clauses on words like "and" but **not on full stops**, so it found no request in your words.
4. The tool answered that the owner hadn't asked for it, and the agent reported "I didn't turn Bluetooth on".

Speech recognition adds full stops, so this affects ordinary speech, not just repeats. Measured today:

| Said | `owner_intents` finds |
|---|---|
| "Turn the volume down and write a haiku about tea" | volume |
| "Turn the volume down. Write a haiku about tea." | **nothing** |
| "Turn on Bluetooth. Please turn on Bluetooth." | **nothing** |

So the feature's own documented use fails when spoken as two sentences. My `collapse_repeats` hides this for an exact repeat only.

### C4. The checks confirm their own assumptions

- **The report can pass a failure:** it passed check 149 while the loop was running, because it counted events without comparing them.
- **The model stops at the seam:** the dialogue model has no overlay in it, and that seam is where today's two worst bugs were.
- **Tests reach into internals:** 38 test files touch `session._…`. My stuck-card test sets `q.reasked = 99` and only checks the frames sent, not what the overlay would show.
- **Timings are guessed:** 97 sleeps in the unit tests.
- **Causes are asserted too early:** I named causes before proving them, including this Bluetooth one.

One thing here worked well: the strict `xfail` on X-01 flagged itself as soon as the contact fix landed. That method is worth keeping.

### What these do to the code

- `session.py` is at 4,871 lines with about 110 attributes set up in its constructor. It was changed in 61 of the last 180 commits, despite the rule to add small modules.
- 110 comments in the source cite a specific date, which is a record of one patch after another.
- Time limits are spread over four modules, with no table showing them together: 25 s, 45 s, 10 min, 30 min, 12 h, 24 h.

## 3. Each fix, classified

Root = removes the cause. Partial = right place, incomplete. Safeguard = a sensible defence, but not a cure. Workaround = copes with the cause. Symptom = handles the case that was reported.

Today's fixes were tested or read closely for this audit. Earlier ones are classified from the commits and from having built them, not from a fresh review of each.

### Earlier fixes

| Fix | Class | Verdict |
|---|---|---|
| Report outcomes (Q-01) | Partial | Right change, but still passes count-only checks (C4) |
| Lock: nothing heard acts afterwards (T-07) | Safeguard | Keep. It is the second fix for this rule (`5415a68` in October) |
| Protocol contract tests (layer A) | Root | Keep. It solves message shapes, but not behaviour |
| Virtual clock and dialogue model (layer C) | Root, for what it covers | Keep and extend across the overlay seam |
| One window per question (S3) | Root | The best example: one owner of one thing, replacing scattered timers. C1 needs the same treatment |
| Resync on reconnect (S1) | Root | Keep |
| "One owner of what is on screen" (S1) | Partial | The title claims more than it does: ownership only holds at reconnect |
| `due.shown` resend (O-08) | Workaround | **Caused the timer loop** (C2) |
| Lane capabilities (S4) | Root | Keep |
| Watchdog and bounded waits (S4) | Safeguard | Keep. Anything can hang, so these are worth having |
| One approval table (S2) | Root | Keep. One rule, tested through every way in |
| Unsure answer re-ask (T-06) | Symptom | **Caused the stuck card** (C1) |

### Today's fixes (uncommitted)

| Fix | Class | Verdict |
|---|---|---|
| Shelved question tells its card | Symptom | Needed until C1 is fixed. See "dropped guard" below |
| Dropped `_front_busy` guard | **Regression (read, not run)** | With a run in front and no rows, `state: result` for `local-N` overwrites the overlay's `state`, so the working card can stop updating. A "Kept…" line can also replace an answer you are reading. Restore it and fix properly under C1 |
| `setTimeout` to clear the card | Symptom | Breaks the presenter's own written rule ("never setTimeout callbacks"). Remove |
| Timer said once | Safeguard | Keep. Saying an event once is correct whatever else is wrong |
| Due retry backoff | Workaround | Keep only until C2 is fixed |
| `fragment`: one word never reaches the agent | **Regression (measured)** | Swift asks "Which day, Monday or Tuesday?", you say "Tuesday", and it answers "Say that again?". "Both" and "Second" fail too. It ignores confidence ("Kern" 0.57, "Ah." 0.20, against a clear word). Replace |
| `collapse_repeats` | Symptom | Harmless, but hides the C3 gate bug. "Turn on Bluetooth. Please turn on Bluetooth." still fails |
| Contact guess question | Partial | See section 1. Fix the `resolved` order first |
| Question expires in the stack after 10 min | Partial | Reasonable behaviour, wrong home (another constant) |
| Set-aside card gives up after 30 min | Partial | Same. It also holds an agent slot for the whole 30 min |
| Stack hides what is on screen | Safeguard | It filters the view without fixing the state. Measured: ending a stack item whose question is open **leaves the question open**. That needed a contrived state to reach, but it is the same fault you reported |
| Opened item leaves the stack at once | Partial | Fine as a stopgap |
| Short "Hey Swift" kept | **Unproven** | Plausible: 5 short clips were dropped in that window. But the logs hold no words, so I can't show those clips were wake phrases, and it doesn't explain "after 10 minutes". False wakes aren't measured. I called this a "likely cause", which was too strong |
| Keep the speech model warm | **Speculative** | The room keeps the model busy (20 to 50 clips per 5 min), so this would rarely run. Remove |
| Transcription counts as the prime | **Metric change** | Check 13's number improves, but nothing gets faster for you. You asked me not to just change the expected output, so this needs your call. Mic was back in 671 ms; 2,062 ms was the model finishing a clip already in progress |

Also from the suite: 2 tests fail on the uncommitted work (1,461 passed).

- **X-01:** a good failure. The strict `xfail` now passes, so its marker should go.
- **`test_ptt_while_working…`:** uses "uh, hmm" as a stand-in request, which `fragment` now refuses. The test needs a look, but it also shows `fragment` reached further than I intended.

## 4. Weaknesses that haven't shown up yet

1. A contact you rejected stays usable as a recipient (section 1). **This touches a product rule, so fix it first.**
2. Two-sentence spoken requests that mix a system action with other work are refused (C3).
3. Request status is wrong in the data: a system request says `done` while it waits, so lane timings and report rows can mislead.
4. The overlay's `state` and `pres` can disagree (C1). Other bugs of this kind are likely.
5. A burst of cards can tie up agent slots for up to 30 minutes each.
6. The stack is only re-sent when code remembers to send it, so anything derived from it can go stale.
7. False wakes will rise by an unknown amount if the short-clip rule stays.

Not investigated, still open:

- **Gmail "couldn't put the cursor in the body":** this comes from a focus check in `desktop/windows.py`. I don't yet know why focus failed.
- **Wake reliability after idle:** the real cause is still unknown.

## 5. What I recommend, in order

**Step 0: stop the bleeding (small).** On the uncommitted work:

- Restore the `_front_busy` guard, and remove the `setTimeout` and the keep-warm.
- Replace `fragment` with a rule that uses confidence and never applies when Swift has just asked something.
- Move `scope.resolved` to after the owner's answer.
- Make `owner_intents` split on sentence ends.
- Keep "said once". Decide the check 13 metric separately.

**Step 1: a request ledger (C1, the main piece).** One small module holds every request, including system requests and due items, with an id, thread, state, place (front, stack, or none), deadline and policy. Every change goes through one transition function, and what's sent to the overlay is derived from it.

- **Atomic by construction:** the backend is a single asyncio loop, so a transition can't be interrupted if it doesn't `await` partway through.
- **Your rules become invariants:** "one place at a time" and "every open card has a live request" get enforced in one spot, and the model can check them.
- **Not a rewrite:** migrate one kind at a time, system requests first (where today's bugs are), then due items, then cards and the stack. Each step deletes the old holders, so `session.py` shrinks.

**Step 2: the overlay draws what it's told (C2).** The backend sends a versioned snapshot of the requests, the overlay draws it, and it reports what it drew. This retires `due.shown`, the backoff, and most of the presenter's decisions about who may show.

**Step 3: one policy table.** All lifetimes in one place, by request type, which is the context-aware policy you asked for.

**Step 4: one reading of what was said (C3).** Normalise a transcript once into sentences with word confidence, interpret it once, and have every later step use that result. The safety check then compares against the interpretation rather than parsing again. Separately, give `directory()` a defined contract, and put one resolver over it that returns exact, close or none.

**Step 5: tests across the seam (C4).** Replay the model's frames through the real `presenter.ts`, and assert things like "no working card without an open request". Add replays of real sessions from content-free traces. Make the report read ledger transitions, so sent without drawn is a FAIL.

**Rules for future fixes:**

- Reproduce it at the seam where it happens, before naming a cause.
- Label the fix with the classes above.
- A workaround names what would replace it.
- Each structural step must delete code.
- Track the count of regressions from fixes, and the size of `session.py`.

**The rest of your feedback:** I'd build the timer widget and the stack redesign on the ledger, since both need its states. The owner-checks rewrite should come last, so the fresh baseline from Check 1 describes the system as it ends up.

## 6. Limits

- **Independence:** you asked for a new session. The app wouldn't offer one from this turn, so this was done here, by the author of the fixes.
- **Coverage:** I did not re-read all 180 commits line by line. Earlier fixes need the same scrutiny that today's got.
- **Not run in the real overlay:** the stuck card and the dropped-guard regression come from reading the code and the logs. The chain of events fits your log, but I haven't replayed it in the harness.
- **Not measured:** Google's search behaviour live, the false-wake rate, and whether the wake fix helps.

## 7. Step 0: done (2026-11-05)

- **Removed:** the `setTimeout` in the overlay, the speech-model keep-warm, and the check 13 metric change. Check 13's measure is back as it was, and its decision is still the owner's.
- **Restored:** the `_front_busy` guard. This leaves a known gap: a shelved system question with another request in front gets no closing line, so its card can stay until that request next updates the screen. Step 1 removes it.
- **Replaced:** `fragment`. Hesitations alone never start a request. One word needs confidence below the clarity bar to be refused, and it's never refused when Swift has just asked something.
- **Fixed:** a guessed contact counts as a recipient only after the owner says yes. No answer or "no" leaves it unusable. Titles no longer count as part of a name.
- **Fixed:** `owner_intents` reads each spoken sentence, so a two-sentence request can reach `system_action`.
- **Kept, still unproven:** the short "Hey Swift" rule. The `short_wake` counter in the "wake listening" log line now shows how often it fires.
- **Not changed:** ending a stack item while its question is open still leaves the question open. Step 1 fixes that at the source.

**Update after the independent review** ([2026-11-reliability-audit-review.md](2026-11-reliability-audit-review.md), on `claude/reliability-audit-review`). Where section 7 and the review differ, the review's order is the one being followed. Done so far: a plain "yes" answers only what is on screen (`dde1105`), one overlay state (`34b9395`), no lost answers (`b653549`), report check 149 (`6ae9672`), and `fragment` reduced to hesitations alone. That last change removes section 7's one-word confidence rule, so a misheard single word like "Kern" reaches the agent again until a bar is scored on saved clips.
