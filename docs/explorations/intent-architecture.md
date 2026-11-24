# Understanding a request, then authorising it (2026-11-24)

- **Status:** investigation, not decided. No ADR. Phase 0 (observability) is built on this branch; nothing else is.
  Reviewed independently on 2026-11-24: phase 0 approved, phases 1-4 approved with conditions, phase 5 blocked as
  written. The conditions are folded in (§5.5) and the rule wording they need is §5.6.
- **Asked by the owner:** "set a timer for 1 minute" worked and "set up a timer for 1 minute" failed with "I couldn't
  set the timer. Swift didn't accept the request, so nothing was started." The same happens with Wi-Fi and Bluetooth,
  and the owner expects it with workflows. Separate understanding what the owner wants from deciding whether Swift may
  do it, so that a different phrasing or one misheard word stops being a dead end, without weakening the authority
  table in `CLAUDE.md`.
- **Built here:** the eval set and scorer [`eval/intent/`](../../eval/intent/), a ratchet test
  `tests/unit/test_intent_eval.py`, and finding **IA-01** in [`findings.yaml`](../audit/findings.yaml).
- **Builds on:** `7d83958` (the verb-list fix, branch `claude/keen-moser-4e5a0c`, not merged),
  [`context-aware-speech.md`](context-aware-speech.md) (what speech recognition exposes),
  [`ownership.md`](../architecture/ownership.md), [`action-authority.md`](../product/action-authority.md).

## In short

1. **The dead end is a policy check that reuses the narrow grammar.** The agent's `system_action` tool checks that the
   owner's own words asked for the action (`system_tools.owner_intents`), and that check *is* the lane's grammar
   (`intents.parse`). A phrasing the grammar misses goes to the agent and then gets refused for the same reason it
   left the lane: "Not done: the owner didn't ask for that." The agent's instructions forbid it from trying another
   way. "Swift didn't accept the request" is the agent's wording of that refusal; that text isn't in `src/`.
   Reproduced with fakes (§1).
2. **Understanding and authority aren't separate today.** The rule that a worker must never pick a system action
   ("what a worker read never acts by itself") is enforced by re-parsing the owner's words with the grammar. So every
   gap in the grammar is also a gap in what the owner is *allowed* to ask for.
3. **Measured on 129 requests** at `7d83958`: 85 handled correctly, **31 dead ends**, 1 false action (a compound's second
   half became a reminder's label), **0 wrong confirmations**, and every question and negation left alone. Before
   `7d83958`: 39 dead ends. Widening the verb list fixed 8. The grammar is safe and narrow; nothing catches what it misses.
4. **Swift already has every part the fix needs, unused or used for something else:** a sentence-embedding model
   loaded at start-up that already logs "a rule missed this" and never acts on it (`routing/classifier.py`); the
   lane's own yes/no question, which runs the intents it held (`Outcome.ask` → `SystemLane.confirmed`); the
   dialogue's question card; and the authority table's level 1 row, which already covers "Swift's own question about
   the owner's request".
5. **The embedding model detects topic, not speech act** (spike, §4.3). It recovers the right family for 28 of the 31
   dead ends, but it also calls 30 of 36 questions, negations and unsupported requests system commands ("don't turn
   off the wifi" → radio, confidence 1.0). It may only *propose*, after a deterministic speech-act gate, and only as a
   question.
6. **Speech recognition has no alternatives to offer.** Parakeet in `onnx-asr` 0.12 decodes greedily (argmax per
   step, `onnx_asr/asr.py` `_decoding`): one hypothesis, with each chosen token's log-probability. N-best would mean
   writing a new decoder. What can work is closed-set recovery: Swift's own command vocabulary, as `HEARD_AS_WIFI`
   already does for one word.
7. **The proposal (§5):** one understanding step that the router, the lane and `system_action` all call. It returns
   the speech act, the grammar's intents when they match, or else *a proposed intent* from the embedding model, with
   slots taken by the grammar's own slot readers. A proposal never acts: it becomes Swift's own level 1 question,
   "Set a timer for 2 minutes?", and a yes runs it through the lane as today. Intent confidence decides only whether
   Swift asks; the authority table decides what approves. Phase 0 makes every failure observable before anything
   changes.
8. **The independent review** found my claim "no rule changes its wording" wrong in five places, and three holes in
   phase 2 as first written (a guess with a missing slot ran with no yes; repeating the misheard words could approve
   a guess; "command" wasn't defined positively). This version carries its conditions (§5.5) and its worded rule
   changes R1-R6 (§5.6). Phase 5 stays blocked until re-specified per P5-1 to P5-5.

## 1. The dead end, traced and reproduced

**Path for "set up a timer for 1 minute" before `7d83958`:**

1. `rules._route`: `system_intents.parse` returns None ("set up" isn't in `_SET`), so it's `Route("agent", ...)`.
2. `session` `_handle`: `library.match` matches no workflow; the agent gets the request and the workflow catalogue.
3. The agent calls `mcp__swift__system_action` with `{"request": "set a timer for 1 minute"}`, as its prompt says
   (`claude_code.py` `WORKFLOW_PROMPT`).
4. `system_tools.system_action`: `it.parse(phrase)` succeeds (the agent's phrase is canonical), then
   `owner_intents(scope.said, scope.answers)` re-parses *the owner's* words, finds nothing, and `missing` is non-empty.
   A timer isn't in `FROM_ANSWERS`, so there's no offer to ask: `NOT_ASKED_PLAIN`, "Not done: the owner didn't ask for
   that. Say in one short sentence that you didn't do it."
5. `WORKFLOW_PROMPT`: "If a Swift tool says something wasn't done, don't try another way: say so in your answer." The
   agent says it in its own words.

Passing the owner's own words to the tool doesn't help either: `it.parse("set up a timer for 1 minute")` is None, so
the tool answers "isn't a system action Swift knows".

**Reproduced** (scratch script over `tests/unit/test_system_phase_a2._host_and_scope`, the lane's fakes, a fresh
`ActionGateway`, no real action), at `7d83958^` and at `7d83958`:

| Owner's words | Before `7d83958` | At `7d83958` |
|---|---|---|
| set up a timer for 1 minute | agent → `NOT_ASKED_PLAIN` | lane: timer set |
| set up a reminder to call mum at five | agent → `NOT_ASKED_PLAIN` | lane: reminder set |
| turn the wifey off | agent → `NOT_ASKED` (agent asks) | same |
| switch the white fi off | agent → `NOT_ASKED`; the answer "wifi" can't stand in | same |
| time me for two minutes | agent → `NOT_ASKED_PLAIN` | same (`test_intent_eval.py`, strict xfail) |

Radios off and volume get `NOT_ASKED`, which lets the agent offer a guess. But the owner's answer counts only if it
can replace exactly one word of the request (`owner_intents`, `MAX_STAND_IN`): "turn the wifey off" + "wifi" works;
"switch the white fi off" (two words heard for one), "go offline" and "turn off the thing that connects me to the
internet" are refused again after the owner answers.

**Not observable:** the refusal logs nothing (`system_action`'s `missing` branch has no `logger` call), and the run
ends with status `done`, because the agent answered. `swift.log` and the run record show an ordinary agent run.
The classifier's "a rule missed this" line has no request id, so it can't be joined to the run.

## 2. The pipeline, stage by stage

What each stage decides, and every point where a valid request can be rejected or lose its meaning (✗). Read from the
code at `7d83958`; the rows marked *measured* were exercised by the eval or the reproduction.

| # | Stage | Where | What it decides | Where meaning is lost |
|---|---|---|---|---|
| 1 | Capture | `audio/`, `wake.py`, `endpoint.py` | When speech starts and ends; the wake phrase | ✗ end of speech too early cuts the request (V-03/V-04, not in scope here) |
| 2 | Recognition | `stt/transcriber.py` `ParakeetTranscriber` | One transcript, greedy; `Word.p` per word | ✗ one hypothesis only; a confident wrong word (32 of 118 wrong words had p ≥ 0.9, context-aware-speech §2) passes untouched |
| 3 | Clarity | `transcriber.assess`, `session._refuse_unclear` | `unclear` (mean p < 0.7, more than one word): "It sounded like ..." and nothing acts; `partly`: unclear words named to the agent | ✗ the offer re-runs the *same* words on a yes, so a misheard command is refused again downstream |
| 4 | Intake | `intake.collapse_repeats`, `session._yes_to_unclear`, `same_request`, `route_midrun`, `_new_request` | Duplicates, a yes to the unclear offer, mid-run commands, changes to a card | — |
| 5 | Router | `routing/rules.py` `_route` | control → local patterns → `memory.parse` → `fast.answer` → `intents.parse` (system) → after pleasantries → open → model override → `light.kind` → agent with demand | ✗ **a phrasing the system grammar misses goes to the agent** (*measured*: 31/129) |
| 6 | Demand | `ClassifierEstimate` (bge-small kNN) | Light or standard model; logs a route hint it never acts on | ✗ knows "this looks like a system request" and drops it |
| 7 | After routing | `session._handle` (≈ lines 2780–2900) | `timers.heard`, carry-over (`dialogue.elide`), `system.claims` (a reminder to list or cancel with none set → agent), open target, undo, resume, offline, light lane, workflow match | ✗ `claims` and the open target send requests to the agent on purpose (each has a reason) |
| 8 | Workflow | `library.match`: triggers, then `Intent` (actions × subjects; `is_question`) | Which playbook and which tools (`Grant`) | ✗ a compound with a system part that a workflow takes loses `system_action` (*measured*: "turn off wifi and send Sam an email" → email-draft) ✗ a calendar or email phrasing outside the action and subject words goes to the agent with the catalogue (*measured*: 4 of 13; not a dead end) |
| 9 | System lane | `system/lane.py` `start` | Missing slot → "For how long?"; disruptive → "Turn off Wi-Fi?" (level 1); else do it, journal, undo | — |
| 10 | Agent | `executors/claude_code.py`, Swift's MCP tools | Reasoning; calls `system_action` with a phrase | ✗ `WORKFLOW_PROMPT` forbids another way after a refusal |
| 11 | Provenance | `system_tools.system_action` → `owner_intents` | Whether the owner's words (or answers) name the intent | ✗ **the dead end** (*measured*); ✗ `owner_intents` splits clauses with `_CLAUSE`, `parse` with `_SPLIT`: two splitters for one question |
| 12 | Workflow grant | `ToolHost.call` → `scope.allows` | A workflow's run may use only its tools | ✗ refuses `system_action` in an email or calendar run, even when the owner asked |
| 13 | Approval | `intake.approves`, `ActionGateway.bind/allow` | Who may approve which level; binds an approval to the action's digest | — (correct; not changed by this proposal) |
| 14 | Record | `runlog.py`, the interaction log | `route`, `action`, `intents`, `status` | ✗ no reason code for a tool refusal; ✗ a dead end ends `done` |

## 3. Responsibilities and their owners

| Responsibility | Owner today | Second owners (duplicates) | Gap |
|---|---|---|---|
| Recognition and its confidence | `stt/transcriber.py` (`Word.p`, `assess`) | — | No alternatives (greedy) |
| Correcting what was heard | — | `intents.HEARD_AS_WIFI`; calendar's `had`/`ad` "opens" intent (`swift.yaml`); `library.likeness` (event titles); `dialogue._close` (answers to options); `session` "It sounded like ..."; `system_tools` answer stand-in; the agent's prompt ("offer your best guess") | **No owner.** Seven local fixes, no shared vocabulary of what Swift controls |
| Speech act (command, question, negation, compound) | — | `library.is_question` (workflows); `system_tools._NOT` (answers only); `dialogue.resolve` (answers); `rules._after_pleasantries`; `light._NOT_LIGHT`; `intake.fragment`; the system grammar's narrowness, implicitly | **No owner for requests.** Questions and negations are safe today only because the grammar is narrow. A wider understanding needs this first |
| Canonical system intent | `system/intents.py` `parse` | `system_tools.owner_intents` re-parses with another clause splitter | Duplicate (small) |
| Workflow intent | `workflows/library.py` (`Trigger`, `Intent`) | — | A second grammar, by design (packages declare their words) |
| Similarity ("this is like that") | `routing/classifier.py` | — | **Owner exists, unused** for routing: its route vote is logged, never used |
| Slots | `intents.py` (`seconds_of`, `find_when`, `SLOTS`); `dialogue` (slot questions, `elide`) | library trigger inputs | — |
| Policy: level of an action | `intents.disruptive`, `action-authority.md` table, gateway risk per tool | — | — |
| Policy: who approves | `intake.approves` (one place, foundation decision 10) | — | — |
| Policy: the owner asked for it (provenance) | `system_tools.owner_intents` | — | **Coupled to the grammar**: the root of IA-01 |
| Clarification | `dialogue.Question` (lane slots, yes/no approval), `ask_owner` (agent) | `session._unclear_offer` (its own yes) | Mostly one owner |
| Execution | `system/lane.py`, `ActionGateway`, executors | — | — |
| Failure observability | `runlog.py` record | the classifier's own log line | **Gap**: no reason codes for refusals, no candidates |

**What this means:** the missing owner is not a classifier or a permission layer. Swift has both. What's missing is
**one understanding step** that owns the speech act and the candidate intents and that every consumer calls (router,
lane, `system_action`). And the provenance check should ask that step *whether Swift understood the owner to ask for
this*, not whether a regular expression matched.

## 4. The evaluation set

### 4.1 What it is

`eval/intent/cases.jsonl`, 129 rows: timers 30, radios 31, reminders 18, volume 16, theme 10, lock 11, workflows 13.
Kinds: 55 natural variants, 25 speech-recognition corruptions (observed ones marked: "wafer", "volume town", "had
lunch"; the rest plausible), 16 questions, 14 negations, 9 compounds, 10 unsupported (another device, a recurring
reminder, someone else's reminder). Each row says what the owner meant: system intents with the slots that matter, a
workflow, the agent with a system part, the agent alone, nothing, or a question back (`clarify`).

`eval/intent/score.py` runs the real code with no session, no model and no real action: `rules.route`,
`intents.parse`, `load_library().match`, and `system_action`'s check (`owner_intents`), including the owner's answer
standing in for one word after the agent asks. Outcomes: `correct`, `slow_ok` (the agent's `system_action` would
accept), `asks` (recoverable after the agent's question), `to_agent` (no lane took it; the agent may still manage),
`dead_end`, `wrong_route`, `false_action`, `wrong_confirm`.

```bash
PYTHONPATH=src /c/Users/frchi/Documents/Swift/.venv/Scripts/python.exe eval/intent/score.py --show
```

### 4.2 Scores

| | correct | slow_ok | asks | to_agent | dead_end | wrong_route | false_action | wrong_confirm | n |
|---|---|---|---|---|---|---|---|---|---|
| **At `7d83958`** | 85 | 2 | 4 | 6 | **31** | 0 | 1 | 0 | 129 |
| Before `7d83958` | 77 | 2 | 4 | 6 | 39 | 0 | 1 | 0 | 129 |

By kind at `7d83958`: variants 35 correct / 16 dead ends of 55; corruptions 6 / 14 of 25 (3 recoverable); questions
16/16 and negations 14/14 correct; compounds 4 correct, 2 slow_ok, 1 recoverable, 1 dead end, 1 false action;
unsupported 10/10. By family, dead ends: timer 10, radio 10, reminder 4, theme 3, volume 2, lock 2, workflows 0
(4 `to_agent`).

**Read it as:** the grammar never acts on what wasn't meant (0 wrong confirmations; the one false action is
`rem-c01`, "remind me to call mum at five and email Sam the notes", where the email half becomes the reminder's
label). The cost is a quarter of the requests dead-ending. Routing parity is unchanged at 413/423, 0 harmful.

`test_intent_eval.py` holds this: dead ends ≤ 31, false actions ≤ 1, wrong confirmations 0, every question and
negation correct, and IA-01 as a strict xfail.

**Limits.** I wrote the rows; real use will differ. The corruptions are mostly plausible rather than taken from the
owner's clips. `asks` assumes the owner answers with the thing's name ("wifi", "dark mode"). No model runs, so
`to_agent` and `slow_ok` say where a request went, not what the agent then said.

### 4.3 Spike: can the existing embedding model recover the dead ends?

Scratch script (not committed): the classifier's own `Embedder` (bge-small-en-v1.5, already on this PC), 7 nearest
neighbours over the parity set's labelled rows plus `examples.jsonl`, the same vote as `DemandClassifier`.

- **Dead ends:** 28 of 31 get the right family (radio 9/10, timer 9/10 with "let me know when 5 minutes are up" voted
  reminder, reminder 4/4, volume 2/2, lock 2/2, theme 2/3). "Turn on duck mode" → radio, "turn on the wafer" → focus
  (low confidence, 0.30).
- **Not commands:** 30 of 36 questions, negations and unsupported requests get a system family: "don't turn off the
  wifi" → radio 1.00, "how do I lock my computer" → lock 1.00, "lock the front door" → lock.
- **Cost:** 11 ms p50, 16 ms p90 per sentence on this PC, already loaded at start-up.
- **Caveat:** the parity set's phrasings may be close to some eval rows, so 28/31 may be optimistic.

So the model is a good *topic* detector and no speech-act detector. It can propose a family after a deterministic gate
has said "this is a command"; it can't decide anything.

## 5. Proposal: the smallest change

### 5.1 The shape

```
transcript (+ Word.p)
   │
   ▼
understand(text, context)  ── one function, one owner (new small module, system/understand.py)
   │  act:        command | question | negation | other      (deterministic; a command is found positively, §5.3)
   │  intents:    intents.parse(text)  → source "grammar"    (unchanged: the only thing that acts directly)
   │  proposal:   if act == command and no intents:
   │                family  ← classifier kNN (existing model, system examples from eval/parity)
   │                slots   ← the grammar's own readers (seconds_of, find_when, on/off, the device vocabulary)
   │                → source "similar", only when every required slot is read from the owner's words (never
   │                  asked: P2-1), the intent is on the proposable list (P2-5) and the source may propose (P2-4)
   ▼
router · lane · system_action      call understand(); restated, same_request, timers.heard, dialogue.elide and
                                   system.claims keep the bare grammar (C1-1)
   │
   ├─ source grammar  → the lane, exactly as today (level 0, or level 1 when disruptive)
   ├─ source similar  → Swift's own question showing every slot: "Set a timer for 2 minutes?"  (level 1; the
   │                    lane's yes/no; never through start, fill or redo)
   │                    yes → SystemLane.confirmed(intents) → the same execution, journal and undo
   │                    disruptive → the lane's one question (lane.question, "Turn off Wi-Fi?"), never two
   └─ nothing         → the agent, as today
```

**Why this is level 1:** the authority table's level 1 already lists "Swift's own question about the owner's request"
and "the owner's words don't clearly ask", approved by a gesture, Swift's name, or a plain spoken yes while it's on
screen. A guess is that, and `intake.approves` and its table are unchanged (the review verified this in `intake.py`).
It is not true that no rule changes: a guess needs its own bullet (R1), learned trust must exclude it (R2), and
restating the guessed-from words must not approve it (P2-2). Only intents on an explicit list may be guessed (P2-5):
not `search` (a web address must come from the owner's words, foundation decision 4), and not `lock` (a TV's "yes"
on the open microphone must not lock the PC, the reason `FROM_ANSWERS` already excludes it).

**What confidence does and doesn't do:** the embedding's vote decides only whether Swift *asks*. It never lowers a
level, never skips a question, and never reaches the gateway. "Intent confidence and execution authority are
independent" becomes a property of the code: the proposal path has no route to execution except the owner's answer
through `intake.approves`.

### 5.2 Phases

| Phase | What | Owner it changes | Product rule? | Gates |
|---|---|---|---|---|
| **0. See every failure** | `system_action` logs `system action refused` with a reason code (`not_asked`, `unknown`, `missing_slot`, `outside_workflow`) and the intent name, and adds it to the record (`tool_refusals`). The classifier's route hint moves into the record (`route_hint`, `route_conf`). An `understood` field (act, source, family, score: names and numbers only) is reserved. `roadmap.py`/`report.py` count "agent run with a system refusal" as a dead end. Transcript stays local-only | `system_tools`, `classifier`, `runlog.SUMMARY_FIELDS` | No (log privacy: structure only; the allow-list test) | unit tests; `test_runlog.py`, `test_seams_audit_privacy.py` (the allow-list) |
| **1. One understanding step** | `understand()` wraps `intents.parse` and the speech-act gate. The router, `SystemLane.claims/run` and `owner_intents` call it; `restated` and the other grammar callers keep the bare grammar (C1-1). `_CLAUSE` and `_SPLIT` become one splitter that accepts nothing more (C1-2). **No behaviour change intended**, except closing HA-SYS-09/10 if the gate takes retraction (C1-2, C1-3) | `system/intents.py` (+ a small `understand.py`), `system_tools`, `rules` | **Approved with conditions** C1-1 to C1-3 | parity must not drop; eval: no row changes outcome; a test that the merged splitter finds nothing the old one didn't; `test_system_lane`, `test_system_phase_a2`, `test_dialogue`, `test_health_SYS` |
| **2. Proposals** | When a command is found positively and the grammar finds nothing, the kNN family plus the grammar's slot readers propose one intent from the proposable list, with every required slot read from the owner's words. The lane asks its own yes/no question showing every slot, then runs it with `confirmed`, never through `start`/`fill`/`redo`. Sources: `voice`, `wake`, `typed` only (never `followup`, `beside`, `answer`, `over_speech`). The classifier not loaded yet means no proposals | `understand.py`, `SystemLane` (`propose` → `Outcome(ask=yes_no)`), `classifier` (system examples) | **Approved with conditions** P2-1 to P2-8; rule text R1, R2 | eval: dead ends fall, **false_action and wrong_confirm stay 0, no question, negation, statement, report, retraction or third-party request gets a proposal** (new rows, P2-3); a test per excluded source; a test that each slot appears in the question; a test that a guess plus a slot answer runs nothing; a test that repeating the guessed-from words re-asks; parity; a seam scenario for the guess card (said, clicked, typed never approves); owner checks |
| **3. Workflows and compounds** | A workflow run whose owner's words hold a system intent **by grammar match, never a guess** (P3-1) gets `system_action` in its grant; it's still provenance-checked and still through the gateway. The kNN can also name a workflow: a choice of playbook *and* of grant, which only narrows from no grant, with no input filled from a guess (P3-2) | `library`/`scope` grant | **Approved with conditions** P3-1 to P3-3; rule text R3 (ADR-011 §4.2) | eval (`radio-c02`); `test_workflows_*` |
| **4. Closed-set recovery of misheard words** | `HEARD_AS_WIFI` moves out of `intents.parse` into the proposer, one owner (P4-1: today it is a grammar match, so it already acts and counts as provenance), and becomes a small vocabulary per slot (Wi-Fi, Bluetooth, timer, minutes, dark mode) with the sound-alikes seen in saved clips. It can make Swift *ask*, never act; allowing a guessed "on" is a deliberate widening. A low `Word.p` in a slot position only lowers the bar to ask, never fills a slot. A yes to a guess is a labelled pair (heard → meant) for the corrections test set, and a *candidate* example that the owner reviews per example before the kNN uses it; learned examples feed the proposer only, never `intents.parse` (P4-2) | `understand.py`, `intents.py`, `stt/recordings` (labels) | **Approved with conditions** P4-1 to P4-4; rule text R4, R5 | `eval/stt/gate.py` unchanged (no transcript is rewritten); eval corruptions; owner checks 201 and 206 and `test_health_SYS` still pass through the proposal path; W-03 meaning measure |
| **5. The agent's last word** (only if the eval still shows agent-side dead ends after phase 2) | **Blocked as written.** Re-specified per P5-1 to P5-5: when `system_action` is refused, the tool asks what phase 2's `understand()` would propose for one clause of the owner's own words (same thresholds, source list, intent list and veto); the agent's phrase is only an equality filter against that one top proposal and never supplies a slot. Non-disruptive: Swift's level 1 question once per run per intent, then the gateway. Disruptive: no extra question; the gateway's card stays the one approval at its level | `system_tools`, `scope` (the once-per-run record) | **Blocked** until re-specified and reviewed again; rule text R6 | eval; seam scenario; red-team rows: a page or tool output saying "lock the PC" / "turn off Wi-Fi" / "set a timer" with owner words that don't name it, each refused with no question |

Phase 0 is worth doing on its own and first: it turns "the owner noticed" into a count.

**Phase 0, built (2026-11-24, this branch):** `RunScope.refused(tool, code, intents)` logs `tool refused` (a code and
intent names only) and, through `note_refusal`, adds `{"tool", "code", "intents"}` to the run record's `tool_refusals`,
which `swift.log`'s interaction line may carry (`runlog.SUMMARY_FIELDS`; the key is `code`, not `reason`, because the
report's privacy check treats `'reason':` there as words). `system_action` reports `system_off`, `unknown`,
`missing_slot`, `not_asked`, `not_asked_offer` and `gateway_<status>`; the tool host reports `outside_workflow`
(replacing its own log line). `ClassifierEstimate.route` is now the backend's router: when the classifier votes that a
rule missed an agent request, `Route.hint` carries `route_hint` and `route_conf` onto that request's record (replacing
the free-standing log line, which named no request); the vote is now taken even when the keywords set the demand. The
owner's report counts dead ends, refusal codes and votes (owner check `intent-architecture-3011f9-1`). Tests:
`tests/unit/test_tool_refusals.py` (both through the whole session), `test_owner_report.py`. `session.py` changed two
lines in place and stays at its ratchet. The `understood` field waits for phase 1, and must hold names and numbers
only, never slots (P2-8). **Cost (review note 0-a):** the classifier now votes on every agent-route router call, about
11 ms on the event loop, up to three times a request (the session also routes to check for control words and new
requests, and those hints are thrown away). Kept on purpose: voting only when the keywords don't set the demand would
lose the hint on 8 of the 31 dead ends. The independent review approved phase 0.

### 5.3 The speech-act gate (phase 1), concretely

Deterministic, small, and tested by the eval's question and negation rows, and by new rows for the shapes the review
named (P2-3):

- **Command, found positively:** an imperative verb leading a clause, or "I want/need you to / can you / please"
  followed by one. Anything else (a statement, past tense, reported speech: "my timer just went off", "I turned the
  wifi off yesterday", "the video says turn on dark mode", "I wonder if I should ...") is no command and gets no
  proposal.
- **Veto:** a negation or retraction anywhere in the utterance ("no wait", "never mind", "actually don't", "cancel
  that") or a third party anywhere ("remind Sam", "tell Sam to", "for Sam") vetoes every proposal in it.
- **Question:** `library.is_question` (moved to `understand.py`, one owner) plus "how do/should/why/does/what's the
  best". The system grammar's own read intents ("is my wifi on", "how long is left") stay grammar matches: they're
  reads.
- **Negation:** "don't / do not / never / no ... / leave X on / without / I don't want / you don't need to". A
  negated request is never proposed. A negated *grammar* match ("don't turn off the wifi") doesn't happen today and
  the eval keeps it so.
- **Compound:** the one clause splitter. A compound proposes only when every part is a grammar match or a proposal;
  otherwise the agent gets it whole, as today.
- **Elsewhere:** "on my phone / on the TV / router / in Chrome / the front door" → never proposed.
- **Grammar matches too (C1-3):** the grammar itself switches Bluetooth on for "bluetooth on?" (HA-SYS-03). Phase 1
  either applies the gate to grammar matches or leaves HA-SYS-03 open, and says which.

### 5.4 Risks

- **Asking too often.** A proposal on every near miss is worse than a dead end. Bars: a proposal needs the gate, a
  kNN family vote ≥ a threshold *and* every required slot read. Measure proposals per day in phase 0's counts before
  turning phase 2 on.
- **A wrong proposal costs a "no".** Acceptable because nothing acts. It must never cost more: no proposal for a
  disruptive change unless it uses the same single question the lane already asks.
- **The open microphone and false wakes (threat model T2/T6).** Today a false wake reaches an action only with an
  exact command; with guesses, anything near a command reaches a question on screen, which a plain yes from the room
  approves. Mitigations: only `voice`, `wake` and `typed` may start a guess (P2-4), lock is never guessed (P2-5), and
  the yes rules are unchanged (presence, on screen, not over Swift's own voice). The threat model needs the line in
  R5. Stricter still, if the owner wants it: a guess from a hands-free request approved only by Swift's name or a
  gesture (§7).
- **Two grammars drifting.** Phase 1 exists to stop that: one step, one splitter, and the eval as the ratchet.
- **The model not loaded** (first seconds after start, or the file missing): no proposals; behaviour as today.
- **Eval bias.** I wrote it. Owner checks and the owner's saved clips must extend it (phase 4's labels do that).
- **`session.py` growth.** Proposals live in the lane and `understand.py`; the session only shows the lane's question,
  which it already does.

### 5.5 The independent review's conditions (2026-11-24)

The full note: `side-session-notes/local_21c78fa6-0963-4228-8f5d-7caf912c796a/review-intent-architecture-phases-2-5.md`
(reviewer: session `rule-review`, not the author). Each condition below is part of its phase's definition of done.

**Where "a new path into an existing rule" hid a real change:**

1. Restating a request approves level 1; for a guess it must exclude the words Swift guessed from (P2-2, R1).
2. Phase 5 as written lowered a disruptive change on the agent path from a card (gesture or name) to a plain yes
   (P5-2).
3. A spoken yes to an action isn't the owner approving a training example; `learn_demand.py` asks per example (P4-2, R4).
4. The threat model's "Words written down" covers words said again or corrected, not a yes to a guess (P4-3, R5).
5. False wakes (T2/T6) reach a question on screen far more easily (§5.4, R5).

**Phase 1.** C1-1: `restated.restated_as` keeps comparing grammar matches only; say which grammar callers call
`understand()` and which don't. C1-2: the merged splitter accepts nothing the old `_intents` didn't (test it on the
eval and the HA-SYS-09/10 rows); better, close HA-SYS-09 and HA-SYS-10. C1-3: apply the gate to grammar matches, or
keep HA-SYS-03 open.

**Phase 2.**
- P2-1: a guess never runs through `start`, `fill` or `redo`; every required slot is read from the owner's words.
  (Today a slot answer goes to `fill` → `start`, which runs a non-disruptive intent with no yes, and a TV saying
  "five minutes" would fill it.)
- P2-2: repeating the guessed-from words re-asks; it never approves.
- P2-3: a command is found positively; negations, retractions and third parties veto (§5.3).
- P2-4: sources `voice`, `wake`, `typed` (spoken-like sources map to `voice`); never `followup`, `beside`, `answer`
  or `over_speech`.
- P2-5: an explicit proposable list: `timer.set`, `alarm.set`, `reminder.set`, volume, mute, media, brightness,
  theme, dnd, radio. Not lock, search, settings, window or screenshot. A new grammar intent isn't proposable until
  listed.
- P2-6: the question is rendered from the payload and shows every slot `confirmed` uses; a disruptive guess uses
  `lane.question`, one question.
- P2-7: a guess shows no `asking.NOTE` and asks even for `asking.EXEMPT` intents (volume).
- P2-8: the `understood` field holds names and numbers only, never slots.

**Phase 3.** P3-1: the grant follows grammar matches only. P3-2: a kNN-named workflow chooses a grant too; it only
narrows, and no input is filled from a guess. P3-3: ADR-011 §4.2 says `needs` is the permission list shown at
install, so the run-time addition is written there (R3).

**Phase 4.** P4-1: `HEARD_AS_WIFI` moves into the proposer (one owner), with owner checks 201 and 206 still passing
through the proposal path. P4-2: a yes makes a candidate example the owner reviews; examples feed the proposer only.
P4-3: heard → meant pairs live in the local interaction log and the recordings index only (R5). P4-4: `Word.p` only
lowers the bar to ask.

**Phase 5 (blocked).** P5-1: per-clause phase 2, the agent's phrase only an equality filter, top-1, no slot from the
agent. P5-2: a disruptive intent adds no question; the gateway's card is the approval. P5-3: once per run per intent;
a "no" is final for the run, held on `RunScope`. P5-4: run exactly the proposed intent. P5-5: red-team eval rows.

### 5.6 Rule wording the phases need (the review's R1-R6, for the owner to accept)

- **R1** (`CLAUDE.md` and `action-authority.md` §3, after "What a worker read never acts by itself"; phase 2):
  > **Swift's guess.** When the owner's words don't match a command Swift knows, Swift may guess what they meant, and
  > only ask: "Set a timer for 2 minutes?" (level 1, Swift's own question, showing every detail the yes will use).
  > A guess is made only from a request the owner started (the hotkey, the wake phrase, or typing), never from what's
  > heard while a question is open or in the follow-up window, never for a web address or locking the PC, and never
  > for anything above level 1. Saying again the words Swift guessed from doesn't approve it; saying the action
  > itself, in words Swift understands exactly, does. A guess never acts until it's approved, and nothing lowers it.
- **R2** (same files; phase 2): learned trust "lowers one kind from level 1 to 0 (only kinds on its table, never
  level 3, never Swift's guess)".
- **R3** (ADR-011 §4.2, under `needs`; phase 3):
  > A run also gets `system_action` when the owner's own words in this request name a system action that Swift's
  > grammar knows (not a guess). It isn't in `needs` and isn't shown when installing, because it's the owner's
  > request, not the workflow's. The tool still does only what the owner's words name, through the gateway.
- **R4** (`action-authority.md` §3 Memory, and `CLAUDE.md`'s copy; phase 4):
  > Memory is written only from the owner's words or an approved card. A yes to Swift's guess approves that action
  > only. An example learned from it is kept only after the owner reviews it, and it can only make Swift ask, never act.
- **R5** (`threat_model.md`, "Privacy of saved recordings", "Words written down"; phases 2 and 4): "...and the words
  the owner meant when they said them again, corrected them, or said yes to Swift's guess of them." And T6's
  controls: "a guess (any request near a command) only asks; lock is never guessed".
- **R6** (`threat_model.md` T1 or T3; phase 5 only):
  > A worker's call never makes Swift guess. Swift's guess about the owner's words is the same with or without the
  > worker. A refused worker call may only bring that same guess forward once, at the level the worker's own path
  > needs (a disruptive change keeps its card), and only with details from the owner's words.

No change is needed to level 3, "typed words never approve", `intake.APPROVES` or its test, presence, or the
gateway's digest rule (verified by the reviewer in `intake.py` and `gateway.py`).

## 6. What was verified, and what was only read

**Verified (tests, scripts or the harness of fakes):**

- The dead end, with fakes, before and at `7d83958` (§1); `test_intent_eval.py` reproduces it as a strict xfail.
- Every number in §4.2 (`eval/intent/score.py` against `src` and against `7d83958^`).
- Parity 413/423, 0 harmful, at `7d83958`.
- Parakeet in `onnx-asr` 0.12 decodes greedily with one hypothesis (read in the installed package's
  `asr.py` `_decoding`).
- The kNN spike's numbers and its 11 ms p50 (§4.3), on this PC with the installed model.
- `test_intent_eval.py`, `test_findings_register.py` and `test_structure_ratchet.py` pass.
- Phase 0: `test_tool_refusals.py` (including two runs through the whole session) and `test_owner_report.py`;
  the full suite at `a2c5b3e`, 2523 passed (the one failure, the `noqa` count at 79 > 78, is already on `main`);
  parity unchanged.
- By the independent reviewer, reading the code: a lane question's yes passes `intake.approves(level=1)` and a slot
  answer doesn't; `HEARD_AS_WIFI` is inside `intents.parse`; the agent path's Wi-Fi off is a card approved only by a
  gesture or the name; phase 0 logs no content.

**Inferred from reading, not run:**

- That the agent turns `NOT_ASKED_PLAIN` into the owner's exact sentence (the model's wording; no live agent was run).
- The stage table's rows not marked *measured* (§2).
- How phase 1 wires `restated` (P2-2 depends on it), and P2-3's false positives (no proposer exists to measure).
- That the seam harness can show a proposal card with no new frame kind (it is the lane's existing question).

**Not done:** no seam scenario or harness run (nothing on screen changed); no real-PC check (owner check
`intent-architecture-3011f9-1` covers phase 0).

## 7. For the owner to decide

1. Whether Swift should ask "Did you mean ...?" (phase 2) at all, or prefer a dead end to a question. The eval says
   about a quarter of everyday phrasings are at stake.
2. Phase 0 first, alone, to count dead ends in real use before anything else changes (recommended).
3. Whether `7d83958` merges as it is (it's a partial fix: 8 of 39; nothing here conflicts with it).
4. Whether to accept the rule wording R1-R6 (§5.6). R1 and R2 come with phase 2, R3 with phase 3, R4 and R5 with
   phase 4, R6 only if phase 5 is re-specified.
5. Whether a guess from a hands-free request should need Swift's name or a gesture, not a plain yes (stricter than
   level 1; a new cell in `intake` and the table). The review leaves it to the owner.
6. Whether phase 0 merges now. The review approved it.
