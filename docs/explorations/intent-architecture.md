# Understanding a request, then authorising it (2026-11-24)

- **Status:** investigation, not decided. No ADR. No product code changed.
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
   │  act:        command | question | negation | other      (deterministic; library.is_question + negation words)
   │  intents:    intents.parse(text)  → source "grammar"    (unchanged: the only thing that acts directly)
   │  proposal:   if act == command and no intents:
   │                family  ← classifier kNN (existing model, system examples from eval/parity)
   │                slots   ← the grammar's own readers (seconds_of, find_when, on/off, the device vocabulary)
   │                → source "similar", only when every required slot is read or askable
   ▼
router · lane · system_action      all call understand(); none parses on its own
   │
   ├─ source grammar  → the lane, exactly as today (level 0, or level 1 when disruptive)
   ├─ source similar  → Swift's own question: "Set a timer for 2 minutes?"  (level 1; the lane's yes/no)
   │                    yes → SystemLane.confirmed(intents) → the same execution, journal and undo
   │                    disruptive → the same one question ("Turn off Wi-Fi?"), never two
   └─ nothing         → the agent, as today
```

**Why this is level 1 and needs no new rule:** the authority table's level 1 already lists "Swift's own question
about the owner's request" and "the owner's words don't clearly ask", approved by a gesture, Swift's name, or a plain
spoken yes while it's on screen. A proposal is exactly that. `intake.approves` is unchanged. A proposal is never made
for anything above level 1 (no system intent is level 3 today), and `search` opens a web address, which must
come from the owner's words (foundation decision 4), so it's never proposed. Learned trust never lowers a proposal to
level 0: it isn't the owner asking.

**What confidence does and doesn't do:** the embedding's vote decides only whether Swift *asks*. It never lowers a
level, never skips a question, and never reaches the gateway. "Intent confidence and execution authority are
independent" becomes a property of the code: the proposal path has no route to execution except the owner's answer
through `intake.approves`.

### 5.2 Phases

| Phase | What | Owner it changes | Product rule? | Gates |
|---|---|---|---|---|
| **0. See every failure** | `system_action` logs `system action refused` with a reason code (`not_asked`, `unknown`, `missing_slot`, `outside_workflow`) and the intent name, and adds it to the record (`tool_refusals`). The classifier's route hint moves into the record (`route_hint`, `route_conf`). An `understood` field (act, source, family, score: names and numbers only) is reserved. `roadmap.py`/`report.py` count "agent run with a system refusal" as a dead end. Transcript stays local-only | `system_tools`, `classifier`, `runlog.SUMMARY_FIELDS` | No (log privacy: structure only; the allow-list test) | unit tests; `test_runlog.py`, `test_seams_audit_privacy.py` (the allow-list) |
| **1. One understanding step** | `understand()` wraps `intents.parse` and the speech-act gate. The router, `SystemLane.claims/run` and `owner_intents` call it. `_CLAUSE` and `_SPLIT` become one splitter. **No behaviour change intended** | `system/intents.py` (+ a small `understand.py`), `system_tools`, `rules` | Touches the provenance check: review | parity must not drop; eval: no row changes outcome; `test_system_lane`, `test_system_phase_a2`, `test_dialogue` |
| **2. Proposals** | When the act is a command and the grammar finds nothing, the kNN family plus the grammar's slot readers propose one intent. The lane asks its own yes/no question, then runs it with `confirmed`. Only sources that start a request (voice, wake, typed); never from an answer or the open microphone mid-question. The classifier not loaded yet means no proposals | `understand.py`, `SystemLane` (`propose` → `Outcome(ask=yes_no)`), `classifier` (system examples) | **Yes**: a new source of level 1 questions. Independent review | eval: dead ends fall, **false_action and wrong_confirm stay 0, no question or negation gets a proposal**; parity; a seam scenario for the proposal card (said, clicked, typed never approves); owner checks (`plan.py --next-id`) |
| **3. Workflows and compounds** | A workflow run whose owner's words hold a system intent (per `understand`) gets `system_action` in its grant; it's still provenance-checked and still through the gateway. The kNN can also name a workflow, which only sets which playbook the agent gets (no action) | `library`/`scope` grant | Yes (a grant): review | eval (`radio-c02`); `test_workflows_*` |
| **4. Closed-set recovery of misheard words** | `HEARD_AS_WIFI` becomes a small vocabulary per slot (Wi-Fi, Bluetooth, timer, minutes, dark mode, lock) with the sound-alikes seen in saved clips. It's used only by the proposer: it can make Swift *ask*, never act. A word with low `Word.p` in a slot position strengthens a proposal. A yes to a proposal is a labelled pair (heard → meant) for the corrections test set and, approved by the owner, a new example for the kNN | `understand.py`, `stt/recordings` (labels) | Yes (the vocabulary changes what Swift may ask): review | `eval/stt/gate.py` unchanged (no transcript is rewritten); eval corruptions; W-03 meaning measure |
| **5. The agent's last word** (only if the eval still shows agent-side dead ends after phase 2) | When `system_action` is refused, the tool asks `understand()` whether Swift independently proposes the same intent for the owner's words; if so, Swift asks its own question instead of refusing. `WORKFLOW_PROMPT` then needs no change | `system_tools` | Yes: review; threat model T3 (an injected page can make the agent *ask for* the PC to be locked; it still needs the owner's yes on Swift's own question) | eval; seam scenario; red-team rows (a page asking for "lock the PC") |

Phase 0 is worth doing on its own and first: it turns "the owner noticed" into a count.

**Phase 0, built (2026-11-24, this branch):** `RunScope.refused(tool, reason, intents)` logs `tool refused` (reason
code and intent names only) and, through `note_refusal`, adds the entry to the run record's `tool_refusals`, which
`swift.log`'s interaction line may carry (`runlog.SUMMARY_FIELDS`). `system_action` reports `system_off`, `unknown`,
`missing_slot`, `not_asked`, `not_asked_offer` and `gateway_<status>`; the tool host reports `outside_workflow`
(replacing its own log line). Tests: `tests/unit/test_tool_refusals.py`, including the whole session path. **Not done
yet:** the classifier's route hint on the record (the session doesn't hold the classifier; it needs a small seam in
`ClassifierEstimate`), the `understood` field (phase 1 fills it), and counting dead ends in `report.py`/`roadmap.py`.

### 5.3 The speech-act gate (phase 1), concretely

Deterministic, small, and tested by the eval's question and negation rows:

- **Question:** `library.is_question` (moved to `understand.py`, one owner) plus "how do/should/why/does/what's the
  best". The system grammar's own read intents ("is my wifi on", "how long is left") stay grammar matches: they're
  reads.
- **Negation:** "don't / do not / never / no ... / leave X on / without / I don't want / you don't need to". A
  negated request is never proposed. A negated *grammar* match ("don't turn off the wifi") doesn't happen today and
  the eval keeps it so.
- **Compound:** the one clause splitter. A compound proposes only when every part is a grammar match or a proposal;
  otherwise the agent gets it whole, as today.
- **Elsewhere:** "on my phone / on the TV / router / in Chrome / the front door" → never proposed.

### 5.4 Risks

- **Asking too often.** A proposal on every near miss is worse than a dead end. Bars: a proposal needs the gate, a
  kNN family vote ≥ a threshold *and* every required slot read. Measure proposals per day in phase 0's counts before
  turning phase 2 on.
- **A wrong proposal costs a "no".** Acceptable because nothing acts. It must never cost more: no proposal for a
  disruptive change unless it uses the same single question the lane already asks.
- **The open microphone.** A TV saying "set a timer" could get a proposal. Proposals come only from sources that start
  a request (wake or hotkey), and the yes rules are unchanged (presence, on screen, not over Swift's own voice).
- **Two grammars drifting.** Phase 1 exists to stop that: one step, one splitter, and the eval as the ratchet.
- **The model not loaded** (first seconds after start, or the file missing): no proposals; behaviour as today.
- **Eval bias.** I wrote it. Owner checks and the owner's saved clips must extend it (phase 4's labels do that).
- **`session.py` growth.** Proposals live in the lane and `understand.py`; the session only shows the lane's question,
  which it already does.

## 6. What was verified, and what was only read

**Verified (tests, scripts or the harness of fakes):**

- The dead end, with fakes, before and at `7d83958` (§1); `test_intent_eval.py` reproduces it as a strict xfail.
- Every number in §4.2 (`eval/intent/score.py` against `src` and against `7d83958^`).
- Parity 413/423, 0 harmful, at `7d83958`.
- Parakeet in `onnx-asr` 0.12 decodes greedily with one hypothesis (read in the installed package's
  `asr.py` `_decoding`).
- The kNN spike's numbers and its 11 ms p50 (§4.3), on this PC with the installed model.
- `test_intent_eval.py`, `test_findings_register.py` and `test_structure_ratchet.py` pass.

**Inferred from reading, not run:**

- That the agent turns `NOT_ASKED_PLAIN` into the owner's exact sentence (the model's wording; no live agent was run).
- The stage table's rows not marked *measured* (§2).
- That a proposal fits the level 1 row without changing `intake.approves` (read against `action-authority.md`; needs
  the independent review the table asks for).
- That the seam harness can show a proposal card with no new frame kind (it is the lane's existing question).

**Not done:** no seam scenario or harness run (nothing on screen changed); no real-PC check; the full Python suite
wasn't run (no product code changed).

## 7. For the owner to decide

1. Whether Swift should ask "Did you mean ...?" (phase 2) at all, or prefer a dead end to a question. The eval says
   about a quarter of everyday phrasings are at stake.
2. Phase 0 first, alone, to count dead ends in real use before anything else changes (recommended).
3. Whether `7d83958` merges as it is (it's a partial fix: 8 of 39; nothing here conflicts with it).
