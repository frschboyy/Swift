# Independent review of the reliability audit (2026-11-05)

Reviewed: `docs/audit/2026-11-reliability-audit.md` at `9900136`, and its Step 0 fixes at `7ffa9f5`. No product code was changed. Nothing real was acted on: the Wi-Fi in this report is the test suite's fake.

## 1. The verdict

The audit's direction is right and its diagnosis is too narrow. Three things need changing:

1. **Step 0 is not safe to call finished.** Two failures remain that the audit doesn't list. A bare "yes" can switch off Wi-Fi after a question that never appeared on screen. "What time is it" during a question loses the answer and leaves a dead Yes/No card.
2. **The stuck card is older and wider than the audit says.** T-06 is the path you hit, but the fault dates from `cd3f97b`, and it has more ways in.
3. **Build less than the ledger, and in a different order.** Test the seam first, then remove the one kind of request that has no owner. Run-owned questions already survive the events that break system questions. Decide on a ledger only after that.

## 2. What I reproduced

**Method:** I drove the real `Session` with fake devices and a fake agent, and recorded the frames it sent. I replayed those frames through the real overlay (`main.ts`, `presenter.ts`, the DOM) in the dev harness on port 1431, then read what was drawn.

| # | Scenario (Swift has asked "Turn off Wi-Fi?") | `cd3f97b` | `d44cac0`, or `9900136` where marked | Step 0 (`7ffa9f5`) |
|---|---|---|---|---|
| A | Unsure answers until it goes to the stack, then a timer | not run | **Stuck** "Working on it". Stop and Esc do nothing (the backend sends no frame). Timer refused | Fixed |
| B | **Dropped guard:** the run is brought forward, the question runs out, the run goes on | not run | `9900136` plus the uncommitted work: **regression confirmed.** `stage=result`, and the new step never draws | Fixed (guard restored) |
| C | Screen locks while the question is open, then unlocks | **Stuck** | **Stuck** | Fixed |
| D | **"What time is it?"** during the question | **Answer lost, dead card** | **Answer lost, dead card** | **Still broken** |
| E | D, then a timer falls due | not run | not run | **Timer refused too** |
| F | **Confirm card on screen, "Swift, turn off the Wi-Fi", approve the card, then a bare "yes"** | not run | not run | **Wi-Fi turned off. The question was never drawn** |
| G | Question beside a run, the run is brought forward, then a bare "yes" | not run | **Wi-Fi turned off** | **Wi-Fi turned off** |
| H | The run finishes with its answer on the card, then the question runs out | not run | not run | **"No answer, so I've left it as it is." replaces the answer** |

"Not run" means I didn't capture that scenario at that commit.

**Controls that behaved correctly:** "no", a timeout at rest, a new agent request, and a second system question. A bare "yes" with a confirm card on screen also did nothing.

**More on the failures:**

- **D:** the card keeps "Turn off Wi-Fi?" with Yes and No. Clicks are ignored and the countdown runs out to nothing, because `state` is already `result` when the question closes. The answer's frame is refused by the presenter's "late, stale answer" rule, since `local-2` isn't the card's run and isn't in front. The seams audit logged the same first step in real use: at 17:37:09 on 2026-11-04 a Wi-Fi question was dropped as `elsewhere`, and since `ab09f51` that request is answered locally.
- **F:** the only sign of the request is a row reading "turn off the wifi: **Stopped**". That row is the audit's C1 in one line: Swift says the request has stopped while its question is still listening.
- **Your log (15:51:11 to 15:53:46):** it fits scenario A. `_shelve` runs with no "unanswered in time" line and no shelve turn from `_lane_answer`, which leaves `_unsure_answer`, followed by the 10-second due loop. The audit's chain for that instance is right.

**Suite on Step 0:** 1,474 Python tests passed with 14 xfail; overlay 83 passed with 1 todo; `tsc` clean; parity 413/423, 0 harmful. **All of that passes with D, E, F, G and H present.**

**Limits:**

- The replay is one-way, in a browser and not Tauri.
- The fake outbox doesn't yield the way a socket does, so frames could arrive in another order. In D, the answer is refused in either order.
- B, G and H call `_bring` directly. In the product that is a row click or naming a request by voice. F uses only speech and a card reply.
- D to H were not run on the real PC.

## 3. Where the audit is wrong or overstated

| Audit says | What I found |
|---|---|
| T-06 "caused the stuck card" | True for the path you hit. The fault came with `cd3f97b`, when a system question got a card whose request had already finished. C and D reproduce at that commit. T-06 added one way in, and fixing T-06 left D. |
| O-08 "caused the timer loop" | Half true. O-08 made a refusal visible by retrying it. Before O-08 the timer left the schedule when sent, so a refused card was lost silently (the comment in `_show_queued_due` names that case). It is still a workaround, but it swapped silent loss for a loud loop. |
| §7's known gap: a card "can stay" with another request in front | Not what I measured. With the guard restored, B and the confirm-card version draw correctly. The real remaining gaps are D, E and H. |
| Restoring the guard protects an answer you're reading | It doesn't: `_front_busy()` is false once the run has ended, so H gets through. The guard asks "is anything busy?" when the question should be "is this question's card the one on screen?". |
| C2: the overlay "can refuse without saying so" | Too narrow. Only due cards have an acknowledgement, so **any ordinary answer can vanish with no trace** (D). Also, frames are half-applied: `setStage` writes `state = "result"` even when the presenter ignored that frame. That half-applied write is the mechanism behind regression B. |
| "Replace `fragment` with a rule that uses confidence" (done, bar 0.7) | The repo's own history argues against it. `1a0ff5d`: a clean "Stop." scored 0.46 and a misheard "Sure." 0.71, so confidence was not used. `0bf901d`: "Yes." heard correctly at 0.54 to 0.65. The audit's "Kern" scored 0.57, inside that range. A one-word request said clearly can now get "Say that again?". This needs measuring on saved clips. |
| Step 4: "interpret it once", and the safety check compares against that | Normalise once, yes. Interpret once, no. `owner_intents` is a safety gate, and it works because it reads the owner's words apart from everything it checks. Sharing one interpretation means one misreading passes both. The Bluetooth fault took about 5 lines to fix (sentence splitting), with no shared reading. |
| Protocol tests and the dialogue model are "Root" | By the audit's own definition they detect faults and don't remove causes, so they are safeguards. Worth keeping, and worth labelling correctly. |
| "Atomic by construction" for the ledger | Only for the state. The frames go out separately through 2 doors (25 `_raw_send`, 32 `_send`) and fire-and-forget tasks (8 `_background`, 17 `create_task`). In D the question's close arrives after the answer. Atomic needs a single ordered outbox too. |
| Figures | Mostly close. I counted 140 sleeps in tests, not 97 (my count includes `time.sleep`). 60 of the last 180 commits touched `session.py`, against the audit's 61. These don't change any conclusion. |

**What the audit got right:**

- The `scope.resolved` gap: at `9900136` a rejected address passed `draft_email` (measured). Step 0 fixes it.
- The sentence-split bug, including the table. Step 0 fixes it, except that "Mute. Write a haiku." still finds nothing.
- Report check 149 passing a failure. **It still would:** at `report.py:471`, 8 sent, 1 drawn and 7 not drawn is not a FAIL.
- C4 generally, and "don't name a cause until it's reproduced at the seam".

## 4. What the audit missed

**M1. The power to answer follows hidden state (safety).** `_listening_for` checks that a window is open and no confirm card is up. It never checks that the question is on screen. `_front_for_question` also ignores `_bring` returning False, so T-01's "its request comes to the front" silently fails under a confirm card. The result is F and G. CLAUDE.md allows a plain "yes" "while the question is open", so this may be within the letter of the rule. It isn't within the intent: a "yes" said to someone else, with nothing asking on screen, changes the machine. The owner has decided it is a product-rule bug (§8).

**M2. Run-owned questions don't have these faults.** I ran a run's own question through the same events. With a question open, "what time is it" drew the answer and kept the run as a row. A lock closed the question and left the working card live. After a confirm card, the question came back on screen. The difference is structural: a run's question has a live `Run` and a single exit (`_settle`, then the run's result). A system question has a dead `Run`, a `local-N` id and about 47 lines of `lane` branches in `session.py`. **That contrast is the strongest evidence in this review and the audit doesn't draw it.** It also shows C1 is sharper than "14 holders": the failures I reproduced need a request with no owner.

**M3. The overlay has two state machines.** `state` and `pres.card.kind` are written separately and disagree. `notInFront` only applies when `rows.length > 0`, so with no rows a foreign frame counts as in front. `P.violations` reported nothing in any stuck replay, even with debug on: the invariants exist but don't cover this. The audit calls this a "likely" future bug in §4. It is the live mechanism of B and D.

**M4. Speech acceptance is tuned by incident.** This is the largest cluster in the history. Eight commits (`5daa4d9`, `3a1af29`, `14546a8`, `fe18a5f`, `e9ef032`, `0bf901d`, `d44cac0`, `7ffa9f5`) change how speech is accepted, around bars now at 0.2, 0.4, 0.5 and 0.7, and I found none that proves a cause. Wake after idle has now had three rounds without a proven cause. C3 is about parsing and doesn't cover this. The saved-recordings loop (B-06) could score any change to these bars, and nothing requires it.

**M5. The way of working is a cause.**

- The four S-commits carry 6 to 12 finding IDs each and 285 to 866 added lines. `7ffa9f5`, written right after the audit's rule to label fixes and reproduce them at the seam, is again 430 lines bundling about 10 changes, with no seam replay and no class labels.
- The big promises have been made before: ADR-013's "one presenter decides" (which added the silent refusal rule), then S1's "one owner of what is on screen". The handoff's "split `session.py`" (about 4,400 lines, §4 step 3) has not been done, and the file is now 4,878 lines.

A plan with a long migration should expect that history.

## 5. The fixes, classified

**Since `ab09f51`.** Rows not listed agree with the audit.

| Fix | Audit | Mine | Why |
|---|---|---|---|
| S3 one window per question | Root | **Root for the clock, Partial for T-01** | `answer_window.py` is clean. "Comes to the front" isn't guaranteed (F) |
| S2 one approval table | Root | **Root for who may approve** | It doesn't ask what is being approved, or whether it can be seen (F, G) |
| S4 lane capabilities | Root | **Partial** | A 2-entry table, and the older `online()` check sits beside it |
| Protocol tests, dialogue model | Root | **Safeguard** | They detect. The virtual clock itself is root |
| O-08 | Workaround, "caused" the loop | **Workaround, exposed the refusal** | See §3 |
| T-07 lock | Safeguard | Safeguard | Now 4 checks where speech acts, and a third miss is likely. `intake`'s `presence` step should be the one place |

**Step 0 (`7ffa9f5`).**

| Item | Class | Note |
|---|---|---|
| Guard restored | Safeguard | Stops B. Wrong question, so H remains |
| `_shelve` tells its card | Symptom | Fixes A and C. D is the same fault by another path |
| Backoff and "said once" | Workaround, Safeguard | Both go once a due item can't be refused |
| `resolved` only after yes | **Root** | Keep |
| `owner_intents` by sentence | **Root** | Keep. No false opening found in the negative and reported-speech cases I tried |
| `fragment` | **Partial** | The hesitation rule is sound. The confidence bar is unproven and `"?" in answer` is one more matcher. `intake` now imports a private helper from `stt.transcriber` |
| Stack and aside lifetimes | Partial | Reasonable; more constants |
| Short "Hey Swift" | Unproven | Counter added, so it can be judged |

**Earlier fix history (32 commits).** Classified from all 32 messages. I read diffs only where a chain led back to the code, so treat single rows as provisional.

| Class | n | Commits |
|---|---|---|
| Root | 8 | `d165ea5` `78c501f` `874ee40` `912fbde` `c1c9299` `5c24dcf` `1f1711e` `bb6925f` |
| Partial | 10 | `b72f4f9` `0de8981` `465b885` `3178507` `4493c09` `cdac5d8` `ab09f51` `95e9bf1` `5daa4d9` `e9ef032` |
| Safeguard | 7 | `5415a68` `3a393ff` `88560b6` `1a0ff5d` `3a1af29` `24cf31b` `da437c0` |
| Workaround | 3 | `14546a8` `fe18a5f` `0bf901d` |
| Symptom | 3 | `490b3dc` `bdbb5ad` `cd7eec8` |
| Feature that seeded the fault | 1 | `cd3f97b` (`b72f4f9` also added the silent refusal rule) |

**What this shows:** "mostly no" is unfair to the whole history. The action and safety work (processes, retries, read scope, the gateway) is mostly root or a well-placed safeguard. The repeat fixes sit in two places: **what is on screen** and **what was heard**.

**Three findings that came back:**

- `cd7eec8` to X-03: the log redaction list needed widening.
- `5415a68` to T-07: the lock rule was fixed again.
- `0de8981` to O-08: "kept until shown" was reported when sent, not when drawn.

`1a0ff5d` is the model to copy: measured on your clips, with the alternative ruled out.

## 6. Is the ledger right?

**The problem is real. The ledger is not the first thing to build.**

- **Wrong unit.** "One place at a time" fails for a request. One run can hold several cards (`Run.cards`) and a question, be a row, and have a card in the stack. Due items aren't requests, and parked threads outlive the process. What must be in one place is **what's on screen**.
- **Wrong order.** Step 2 (the overlay draws what it's told) and step 5 (tests across the seam) come after the riskiest work, though the seam is where the worst failures are. The harness work for this review was a few small scripts, and it found D to H within a day.
- **Too broad for its evidence.** Everything I reproduced follows from the ownerless `local-N` card, the two overlay state machines, or hidden answer authority. None needs a new central holder.
- **Risk of a 15th holder.** A partial migration leaves `session.py` with both the old state and the new, and the handoff's unstarted split suggests partial is likely.
- **What the audit has right:** starting with system requests, requiring each step to delete code, and one lifetime table.

**Alternative, not yet prototyped:** run the system question inside its `Run`, through the `_ask_owner` path, so the run stays alive until it's answered. Rows, replay, Stop, Esc, `_bring`, `_kick_question` and the "busy" check on due cards then already apply. It should remove `_confirm_lane`, `_lane_reprompt`, `_close_lane_ask`, `local-N` as a card id and most of the `lane` branches.

**Questions a prototype must answer:**

- Plain "yes" needs its own rule.
- `_ask_lane`'s slot filling must carry over.
- Reopening from the stack must work.
- A waiting question must be able to wait without an agent slot (the slots already apply only to the agent, so this looks fine).

If that prototype doesn't delete more than it adds, the argument for a ledger gets much stronger.

## 7. Revised priorities

**Now, each small and in its own commit:**

1. **Answer only what's on screen (M1).** `_listening_for` refuses a question whose card isn't in front, and `_front_for_question` handles a False. Fixes F and G. The owner has decided the question must be visible (§8), so this comes first.
2. **The overlay holds one state (M3).** Derive `state` from the presenter and drop half-applied frames. Stops the mechanism of B and removes the need for the guard.
3. **No lost answers (D, E, H).** Close the question's card before the new request's answer goes out. Replace the guard with "is this question's card on screen?".
4. **Report check 149 FAILs when sent exceeds drawn.**
5. **`fragment`:** keep the hesitation rule and turn the one-word confidence bar off until measured.

**Next:**

6. **A seam replay test.** Real `Session` frames through the real overlay in `npm test` or similar, with invariants like "no working card without a live owner" and "every answer is drawn or has a row". Start with scenarios A to H, D to H as strict `xfail`. Every later step lands against this.
7. **System questions owned by a live `Run`.** A one-day prototype first; keep it only if it deletes more than it adds.
8. **Due items never get refused.** When a card is in the way they go in the stack, which already exists. `due.shown`, the backoff and the tries counter go.

**Then decide:**

9. **One versioned screen snapshot** derived from the existing owners, and acknowledged when drawn. This is the audit's step 2, moved up and without a prerequisite. Moving the presenter's decisions to the backend is what ends silent refusal. **Decide on the ledger here:** build it only if new failures still come from holders disagreeing.
10. **Speech (M4, C3).** Normalise once into sentences. Require any change to a confidence bar to be scored on saved clips. Keep the safety gate reading the owner's words independently. Prove the cause of wake after idle before another fix.
11. **The lifetime table.** Useful, cheap, and no reproduced failure depends on it.

**Unchanged from the audit:** the timer widget and stack redesign wait for 8 and 9, and the owner-checks rewrite comes last.

**Working rules to add to the audit's:** one finding per commit; a screen fix isn't done until it has a seam replay; someone other than the author reviews any fix to a product rule; a commit that claims "one owner of X" names the test that would fail if there were two.

## 8. Owner's decision (2026-11-05)

Does a plain "yes" count when "Turn off Wi-Fi?" isn't on screen? **No: the owner's answer was "No, must be visible".** So scenarios F and G in §2 are product-rule bugs, and item 1 in §7 stands as written. The exception in CLAUDE.md still says "while the question is open"; it should also say the question must be on screen. That wording isn't changed here.

## 9. Not covered

- Scenarios D to H on the real PC.
- The Gmail focus failure.
- Google's live search behaviour.
- False-wake rate.
- The run-owned design is reasoned and partly evidenced (M2), not built.

The capture and replay scripts are in the session's shared notes folder (`local_d97ba2d9…/review-repro/`). They weren't committed because they are throwaway; item 6 is the proper version.
