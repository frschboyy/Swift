# ADR-020: One record per conversation, so Swift keeps track of what you meant

- **Status:** Accepted (2026-11-10): the owner took the recommendations (§6). Step 1 of §5 is being built on `claude/owner-check-fixes-08ab4a`.
- **Decided by:** Owner
- **Date:** 2026-11-10
- **From:** the owner checks of 2026-11-09 (21:55–23:01), the fixes on `claude/owner-check-fixes-08ab4a`, and an outside review of those fixes the owner asked for.
- **Touches:** ADR-014 (the stack), ADR-016 §5 (Swift asks, you answer), ADR-018 (the Deck). Product rules in `CLAUDE.md` are kept as they are.

## 1. Why

Swift feels like a rigid command processor. The owner wants it to understand what they mean whatever the wording or speech-recognition errors, keep context across follow-ups, match an existing request or start a new one, recover from misunderstandings, ask useful questions, say what it's doing and what it needs, and get better from use.

The night's findings share one cause. **Swift keeps what you asked, what it asked back, what you answered and what it did in different places, each with its own idea of "the same request".** Each place was then patched separately:

| Finding (2026-11-09) | Where the link was lost |
|---|---|
| "Turn off the wafer" → "Wi-Fi" refused (128, 144) | The permission check read only the first transcript (`RunScope.said`); the answer lived in the dialogue |
| "Yeah, turn it off for now. Thanks. Hold on a second." became a new request (144) | `dialogue.resolve` judged the words alone; anything unclear that could be a request went elsewhere, before the open question had its say |
| Two of the same in the stack (131, 8) | `parked.py` compared words; the lane knew the intent |
| Waiting shown as "Working on it" (144) | A row's state came from the run; the question's state from the dialogue |
| A question ran out while out of view (164) | The question's window didn't know what was on screen |
| The yellow card for airplane mode (9) | The greeting made the grammar fail, so the agent got it, with a different approval path |
| Rigid replies (128, 144) | Recovery was left to the agent's wording of a refusal |

The fixes on the branch are real, but several are special cases: a word swap for misheard answers, a greeting rule, a "yes followed by hold on" rule. More of them won't make Swift feel natural.

## 2. How a request goes today

1. **Heard.** Wake word or hotkey → local speech-to-text (parakeet) → a transcript with word confidences. Wake detection is the same speech-to-text matching "hey swift" in text (`wake.py`).
2. **Claimed.** In `session._interaction` the transcript goes, in order, to: an open confirm card, an open question (`dialogue.answer`), the mid-run grammar, "the same request again", and then routing.
3. **Routed.** `routing/rules.py`: a fixed list of controls and local answers, then the system grammar (`system/intents.py`), then workflows (`workflows/library.py`), else the agent.
4. **Matched to unfinished work.** `parked.py` by words ("continue", "finish the email to Ada", the same words again). Since `f6449c0`, system commands match by intent.
5. **Clarified.** The system lane asks its own Yes/No or "For how long?". The agent asks through `ask_owner`. Each question has an `AnswerWindow`.
6. **Done.** Through the gateway (approval cards, journal, undo). The agent's `system_action` checks the owner's words before doing anything.
7. **Shown.** The overlay's presenter, from `state`, `runs`, `ask`, `confirm.request` and `stack` messages.

**Weak points the night showed:**

- **No single owner of "what the owner wants".** `RunScope.said`, `RunScope.answers`, `Parked.said`, `Run.words`, the record's `transcript` and the dialogue's `Question.request` each hold part of it.
- **Provenance is implicit.** Whether words came from the owner (said, typed, clicked) or from the agent is decided case by case. That is why each product-rule fix needed two rounds of review.
- **The open question doesn't come first.** A reply is judged as words. Its link to the question on screen is checked only after "is this a new request?".
- **Recovery is in the agent's prompt.** Whether Swift offers a guess, retries or gives up depends on the model's wording.
- **Wake detection is speech-to-text.** 10 of 21 wake-ups needed a second "Hey Swift". On the saved clips, the first was heard as "He had swift", "And Swift", "They're swift", "He's wave", and similar. Text matching can't safely accept those.
- **Learning stops at words.** Saved recordings improve word fixes (`stt/fixes.py`), but nothing learns that "wafer" meant Wi-Fi in that sentence, or which wording the owner uses for which request.

## 3. Options

### A. One conversation record, owned by the backend (recommended)

A small module (`swift/conversation.py`), not more of `session.py`. Every request gets one record, which lives until it's done, ended or expires from the stack:

```text
Conversation
  goal          the owner's request, in their words (what the stack and cards show)
  intent        what Swift understood: system intents, a workflow, or "for the agent"; with what's unresolved
  heard         every utterance in it, each with its source: said | typed | clicked | agent | read
  question      Swift's open question: which slot it resolves, the options, the window, on screen or not
  plan          what the worker was sent (playbook, context): never shown, never matched against
  state         listening | understanding | asking | waiting for OK | doing | checking | done | partly done | failed | parked
  outcome       what was verified, not what was attempted
```

- **The permission check reads the record**, and only `heard` entries with source `said` or `typed` count as the owner asking, within this conversation's intent. The agent can propose; it can never add an owner entry. One function, one test that fails if a second source of "owner's words" appears (the `CLAUDE.md` rule for "one owner of X").
- **An open question claims an utterance first.** Its result is one of: answer, correction ("Bluetooth instead"), wait, cancel, a new request, or unclear. It is judged against the question's slot, not as free words. "Wi-Fi" after "Did you mean Wi-Fi or Bluetooth?" fills the slot. It never swaps a word in a sentence.
- **Recovery is the backend's.** When the system lane or `system_action` can't resolve a slot, the record moves to `asking` with the slot and its candidates. The worker may word the question, but the backend decides whether to ask, how many times, and what counts as the answer.
- **Matching uses the record.** Same intent: a fresh card replaces the stack item. "Continue" or a click: resume. For agent requests, "the same intent" starts as the same words and later becomes a light-model comparison, still deterministic about permissions.
- **The overlay shows the record's state.** The names in the state list above become the labels; none says "Claude Code".

**Against the product rules.** Better understanding never widens permission. Approval stays where it is (cards; the name for hands-free; the one plain-yes exception). Logs record states and sources, never words. Memory still only from the owner's words or an approved card.

**Cost.** Medium. It replaces `RunScope.said/answers`, `Parked.said/words`, `Run.words`, `Question.request` and the stack's title logic, so it should delete more than it adds. Per `CLAUDE.md`: prototype on a branch, keep it only if it removes more than it adds.

### B. A model in front of everything

Every utterance first goes to a small model (local, or the light lane) that returns intent, slots, and which open question it answers. The grammar becomes a fast path.

- **For:** handles any wording ("I was wondering if you could disable Wi-Fi"), tolerates misheard words.
- **Against:** latency on every request (B-05 is already 8–25 s on the first one), cost, and audio-derived text leaving the PC unless the model is local. It would need the owner's decision on a local model (decision 19). A model's opinion can't be what grants permission, so A's record is still needed underneath.

### C. Keep patching

Add grammar, special cases and prompt text per finding.

- **For:** cheapest per fix; nothing moves.
- **Against:** the night's findings are already the result of this. Each product-rule fix took two review rounds. Swift stays a command processor.

## 4. Recommendation

**A first, then B's model only where the grammar fails**, with the record underneath, so a model can interpret but never authorize. Separately, and the owner's call because it adds a dependency: **a dedicated local wake-word model** (openWakeWord or similar), scored on the owner's saved clips and false wakes before it replaces anything (the check 191 count already points this way).

**Feedback loop, inside the rules:** when the owner corrects Swift ("I meant Wi-Fi"), the record holds both the heard and the corrected words. A weekly pass proposes, on a card, "When you say 'wafer' in 'turn off the …', you mean Wi-Fi?". It is applied only on approval, like word fixes today, and scored on the saved clips (W-03 first).

## 5. The first small step

No behaviour change; make the record exist and be the one owner of the owner's words:

1. Add `swift/conversation.py` with `Conversation` (goal, heard with sources, question, plan, state) and one function, `owner_words(conversation)`.
2. Point `system_action`, `owner_asked_to_write`, `owner_asked_for_email` and the stack title at it. Delete `RunScope.said/answers` and `Parked.said`.
3. A test that fails if any of those reads words from anywhere else, plus the night's scenarios in `test_seam_replay.py` replayed through it.
4. Measure: lines removed vs added. Keep it only if it removes more.

Then, one at a time: the open question claims first and resolves by slot (replacing the word swap and the "yes … hold on" rule); backend-owned recovery (replacing the prompt text); record states on the overlay.

## 6. Decisions (the owner, 2026-11-10: "go ahead with your recommendations")

1. **A, then B** where the grammar fails, with the record underneath so a model interprets but never authorizes.
2. **Try a dedicated wake-word model.** A new dependency, approved to be tried: scored on the owner's saved clips
   (misses and false wakes) before it replaces anything, and kept only if it beats speech-to-text matching on both.
3. **An answer on the open microphone can't switch a radio on** (kept as built): a TV can't turn Bluetooth on.
   "Turn on the Wi-Fi" said as a request still works.
4. **A question back in view gets a whole countdown** (kept as built), as cards and check 141 do.
5. **Merge after the real-PC checks 201–211 pass,** with step 1 of §5 included if it is kept (it must remove more than it adds).
