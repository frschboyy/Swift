# The Claude Code executor, reviewed (2026-11-24)

- **Status:** review, read-only. No product code changed. Four bugs proven with fakes (EX-01..EX-04 in
  [`findings.yaml`](../audit/findings.yaml)), each a strict xfail in `tests/unit/test_executor_review.py`.
- **Scope:** `executors/claude_code.py`, `claude_mapping.py`, `base.py`, `providers.py`, `step_grant.py`,
  `read_scope.py`, and where they meet `workflows/tools.py` (`ToolHost`), `workflows/scope.py`, `library.py`,
  `security/gateway.py` and `session.py`. Line numbers are at `138b7b1`.
- **Builds on:** [`intent-architecture.md`](intent-architecture.md) (IA-01, the pipeline in §2, the responsibility
  map in §3, phase 0's `tool_refusals`). This doesn't redo it; §6 checks the parts this review depends on.

## In short

1. **`_watched` doesn't cancel the SDK's read every second.** It waits with `asyncio.wait(timeout=)`, which leaves the
   pending `__anext__` running. Proven over the SDK's own receive path (0.2.172, anyio 4.15): no message is lost
   across many wake-ups. It does cancel the read on a stall or a cancel, and a cancelled read *does* lose a message
   and closes the generator (also proven), so the stream must never be read after that. Today it isn't.
2. **The serious problems are at the end of a run, not in the middle.** While the CLI closes (`disconnect()`, up to
   5 s, then `taskkill`), the run has its answer but isn't finished. A cancel that lands then never finishes
   (**EX-04**, high: the session's request hangs and holds one of the three run slots until Swift restarts), and a
   change of mind said then is accepted and dropped (**EX-01**).
3. **Swift miscounts its own refusals as the model struggling.** The owner asking for a change on a command card, or
   declining a read card, counts as a failed tool call; two in a row move the run to Opus (**EX-02**).
4. **A retry meant for the first model check also catches Swift's own escalation**, and then sends the owner's
   request again into the middle of the turn (**EX-03**).
5. **Failures are traceable for Swift's tools (`tool_refusals`), not for Claude Code's own.** Workflow and web
   refusals in `can_use_tool` leave no log line; `denied` in the record names the tool but not why; a stall, an SDK
   error or an end with no result leaves no `denied` at all.
6. **The sibling's findings hold** where this review depends on them (§6), with one correction: Whisper (beam 5) is
   still a configurable engine; Parakeet is the default.

## 1. The executor as built

```
session._handle (one task per request)                    ToolHost (one per Swift)
  │ _open_scope: RunScope(grant from workflow) ──────────►  scopes[], _bound{run_id→scope}
  │ CURRENT_SCOPE.set(scope)  (ContextVar)                   resolve(run): _bound → CURRENT → the only open scope
  │ await _slots.acquire()   (MAX_RUNS = 3)
  │ providers.start(task) ──► ClaudeCodeExecutor.start
  │                             ├ _Run(level, grant bound in gateway)          ActionGateway
  │                             ├ options(run)  (cwd, CLI path: ExecutorUnavailable here)   bind/allow (OWN-05)
  │                             ├ _take_spare()  ◄── _Spare task (prewarm; binding list)    journal ALLOWED/FAILED
  │                             └ task = _pump(run)
  │ _run_once: tools.bind(scope, run_id)
  │ async for events(run_id) ◄──── run.queue ◄─────────────┐
  │   step / live / confirm → overlay                      │
  │ executor.result(run_id) ◄── run.finished ◄────────┐    │
  ▼                                                   │    │
_pump(run)                                            │    │
  connect (cold) or spare → set_model                 │    │
  loop:  query(request)                               │    │
         _watched(receive_response())  ── stall watchdog (1 s wake, 90 s, paused while run.held)
           _watch: steps / failures → _escalate → client.set_model
           as_event → steps_for, live.feed, outcome_for ──┘
         redirects? → next turn with REDIRECT_MESSAGE
  result = _final(outcome | error)
  finally: disconnect (≤5 s) → taskkill → finished.set() → _DONE → _refill()   ◄── EX-04: a cancel here skips the rest

CLI (claude.exe, one per run) ── can_use_tool ──► _ask
   Read/Glob/Grep  → ReadScope verdict: read | card | never
   WebSearch/Fetch → workflow capability, or web on outside workflows; fetch only given addresses
   in a workflow   → deny (manifest)                       ← no log line
   Bash/PowerShell → length, never-read paths, step/plan grant (_spend + gateway.allow), else a card
   other           → card → gateway.allow(bound) → allow / change / reject(interrupt)
                ── in-process MCP "swift" ──► request_stronger_model, propose_step/plan, show_result, add_caveat,
                                              ToolHost tools (host.call(name, args, run=run_id))
```

## 2. Responsibilities

The sibling's §3 table holds for understanding and authority. For the executor:

| Responsibility | Owner | Notes |
|---|---|---|
| Which provider runs | `providers.Providers.start` | first available; `ExecutorUnavailable` falls through |
| One run's life (connect, turns, end) | `ClaudeCodeExecutor._pump` | also owns cleanup; **EX-04** |
| Liveness (stall) | `_watched` + `run.held` | the session also watches retries (`_is_retry`, offline) |
| Changing course | `redirect` (same session) or the session's restart | **EX-01** |
| Model level and escalation | `_watch`, `_escalate`, `request_stronger_model` | **EX-02**, **EX-03** |
| "Not a failure" accounting | `run.expected` (a counter), `ToolResult.expected`, `_too_long` | two sources, not keyed by tool call (§4 W2) |
| Approval of Claude Code's own tools | `_ask` → `_decide` → `ActionGateway.bind/allow` | correct; one card, one call |
| Approval of Swift's tools | `ActionGateway.execute` via `ToolHost` | correct |
| Which scope a tool call belongs to | `ToolHost.resolve` | run id, then a ContextVar, then "the only one open" (§4 W3) |
| Workflow limits | `RunScope.allows` (Swift tools), `_ask` (Claude's tools), `_propose_*` | two places; only the first logs |
| Final card text and failure class | `_final`, `claude_mapping.outcome_for`, `failures.classify` | |
| Warm CLI | `_refill`, `_take_spare`, `ensure_spare`, `release_spare`, `close` | §4 W5 |

## 3. Proven bugs

Each has a strict xfail that asserts the right behaviour: run
`PYTHONPATH=src …/python.exe -m pytest -q -p no:cacheprovider tests/unit/test_executor_review.py --runxfail` to see
them fail for the stated reason.

### EX-04 (high). A cancel that lands while the run closes never finishes

- **Where:** `claude_code.py:1077-1087`. The `finally` awaits `client.disconnect()` (`:1080`, up to 5 s) and
  `_kill_tree` (`:1083`) inside `contextlib.suppress(Exception)`. `CancelledError` isn't an `Exception`, so a cancel
  delivered at either await leaves the `finally` there: `run.finished.set()`, `_DONE` and `_refill()` never run.
  `cancel()` (`:731-743`) only skips a run whose `finished` is set, so it calls `run.task.cancel()` on a run that
  already has its result and then waits on `finished` for ever.
- **Reproduced:** `test_a_cancel_while_the_run_closes_still_finishes_it` (a fake client whose `disconnect` takes a
  while). A scratch run confirmed that after the disconnect is released the task is done, `finished` is still unset
  and `cancel()` hasn't returned.
- **What the owner sees (read, not run):** the session calls `executor.cancel` inside `to_the_end`
  (`session.py:2953`), which waits however often it is cancelled, so the request's task never ends. Its `finally`
  (`session.py:2981`) never releases the run slot: after three of these, every agent request waits for a slot until
  Swift restarts. Quitting (`Session.close` cancels the runs) can hang the same way. The window opens when the answer
  arrives and lasts while the CLI closes: the card still says working, so an Esc then is plausible. How long the real
  CLI takes to close wasn't measured.
- **Fix (root):** move `finished.set()`, `_DONE` and `_refill()` into an inner `finally` so they always run; and in
  `cancel()`, when `run.result` is already set, wait for `finished` without cancelling the task.

### EX-01 (medium). A change of mind while the run closes is accepted and dropped

- **Where:** `redirect` (`:769-785`) refuses only when `finished` is set or the run was cancelled. After the last
  turn's check at `:1065` the pump never looks at `run.redirects` again, but `finished` isn't set until the
  `finally` ends.
- **Reproduced:** `test_a_change_of_mind_while_the_run_closes_is_refused_not_dropped`: `redirect` returns True, the
  result is the old answer marked `done`, and only one query was sent.
- **Effect:** the session records `redirected: same_session` and logs that the change was passed on
  (`session.py:4047-4051`), then shows the old answer as Done. The owner's correction is silently ignored.
- **Fix (root):** `redirect` returns False once `run.result is not None` (set synchronously before the `finally`);
  the session then restarts with the change, as it does for other providers.

### EX-02 (low). The owner's change or "no" to a card counts as the model failing

- **Where:** `_ask` returns `PermissionResultDeny(CHANGE_MESSAGE, interrupt=False)` (`:844-845`) and
  `READ_DECLINED_MESSAGE` (`:873`) without adding to `run.expected`. The CLI sends a denial back as a tool result with
  `is_error` (fixture `claude_denied_write.jsonl`), and `_watch` (`:1012-1015`) counts it as a failure. Two in a row:
  "Switching to Opus: tool calls kept failing". The module docstring (`:24-25`) says the owner asking for a change
  isn't a failure.
- **Same family, read not run:** workflow and web refusals (`:811`, `:814`), the OWN-05 `CHANGED_MESSAGE`
  (`:830`, `:841`), and a Swift tool's `outside_workflow` refusal (`tools.py:868-872`, not `expected`) also count.
- **Reproduced:** `test_asking_for_a_change_twice_is_not_the_model_struggling`.
- **Effect:** cost (Opus) and a misleading "Switching" step; no authority change.
- **Fix:** route every deny that is Swift's decision or the owner's through one helper that counts it as expected,
  as `_too_long` already does (`:235-241`).

### EX-03 (medium). A failed model switch mid-turn sends the request again

- **Where:** the retry at `:1059-1064` exists for the first model check ("Couldn't confirm model"). It wraps the
  whole turn, including `_watch` → `_escalate` → `client.set_model` (`:988`). When Swift's own escalation fails that
  way, it switches to the default model and `continue`s: `query(request)` again, while the first turn is still
  running in the same CLI session.
- **Reproduced:** `test_a_failed_switch_mid_turn_never_sends_the_request_again`: two identical queries.
- **Inferred:** that `set_model` to an unreachable model raises this text on the real CLI (the original case came
  from the first query). An escalation by the model's own `request_stronger_model` raises inside the MCP tool, not
  here.
- **Effect:** the agent sees the request twice mid-work and may redo steps. Each side effect still asks its card
  (step grants are spent once), so no authority break.
- **Fix:** retry only while no message of the turn has arrived (or catch the error in `_escalate` and keep the
  model).

## 4. Suspected weaknesses (not proven)

- **W1. `_watched` depends on the SDK's generator having no anyio scope across a yield.** Each `__anext__` runs in a
  new Task (`:1095`). That's fine for 0.2.172's plain generators (`client.receive_response` →
  `Query.receive_messages` over a memory stream); a cancel scope or task group inside them would raise "exit cancel
  scope in a different task". The first test in `test_executor_review.py` runs over the SDK's own code, so an SDK
  upgrade that changes this fails it.
- **W2. `run.expected` is a counter, not keyed by `tool_use_id`.** With parallel tool calls a Swift tool's expected
  credit can be spent on another tool's error delivered first; with a success between them, a later real failure is
  then counted twice in a row. A credit whose result never reaches the stream (an interrupted turn) swallows the next
  real failure. Low impact (escalation only).
- **W3. `ToolHost.resolve` falls back to the ContextVar, then to "the only open scope"** (`tools.py:833-839`). A
  warm CLI's SDK read task inherits the context of whatever called `_refill` (the previous run's pump: its scope,
  closed by then, so `resolve` drops it). Between `start()` and `bind` (`session.py:3837`) a call from a warm run
  with another run open gets "No Swift run is active". No cross-run leak found: `close()` runs after the CLI is
  disconnected. The fallbacks are still guesswork that the run id makes unnecessary.
- **W4. A cold connect that is cancelled or times out** (`:523`) leaves no PID for `_kill_tree`; cleanup relies on
  the SDK's own `disconnect` in `connect()`'s `except BaseException` (read in 0.2.172), whose `transport.close()`
  may not end the CLI's tree on Windows (the docstring says `claude` ignores CTRL_BREAK).
- **W5. Prewarm:** a run that ends while the owner is away refills the spare `release_spare` freed (`:1087`); after
  `Session.close` cancels the runs, each refills a spare that `executor.close` then cancels; the spare's options
  (web tools, the tool list) are fixed when it connects, so turning `web` on later isn't seen until the next spare.
- **W6. Workflow reads:** in a workflow run, Read/Glob/Grep are decided before the manifest check (`:800`), so a read
  outside the read folders gets a card. ADR-011 keeps reads pre-approved in W1; the comment at `:813` ("nothing
  else, not even with a card") overstates it. The taint rule (ADR-011 §257, W2) isn't built.
- **W7. An end with no result and no error** (the CLI's stream ends with no ResultMessage) reads "Stopped without an
  answer." with no `error_detail` (`:1156-1165`). Not reproduced.

## 5. Failure handling: what can be traced back

| Failure | What the owner sees | swift.log | Record | Gap |
|---|---|---|---|---|
| Swift tool refused (`system_action`, outside workflow) | the agent's words | `tool refused` + code | `tool_refusals` | covered by `138b7b1` |
| Claude's tool refused by a workflow (`:814`), web off (`:811`) | the agent's words | **nothing** | `denied: [tool]` | no reason |
| Never-read path, web address not given | the agent's words | a line, no record field | `denied` | not in `tool_refusals` |
| OWN-05 changed after approval | the agent's words | gateway `worker call refused` | `denied` | not in `tool_refusals` |
| Too long for a card | the agent's words | nothing | `denied` (hidden if worked around) | |
| `AskUserQuestion` denied | the agent's assumption | nothing | `denied` | |
| `propose_step/plan` in a workflow (`:879`, `:912`) | the agent's words | nothing | nothing (a tool result, not a denial) | |
| Owner rejects / no answer | Rejected card | `approvals` | `stopped_by` | fine |
| Budget, max turns (`STOP_REASONS`) | its own message | `status`, error code | `failure` | fine |
| Stall (90 s) | "Stopped without an answer (timed out…)" | `claude run stalled` | `error_detail` | fine |
| SDK/CLI exception | "Stopped without an answer (…)" | `claude run failed` + class | `error_detail` (local) | fine |
| Escalation | a "Switching" step | `claude escalated` | `escalations` | EX-02 makes some false |
| Lost change of mind | the old answer, Done | "passed on in the same session" | `redirected: same_session` | **EX-01: wrong** |
| Cancel during close | stuck "working" | nothing after it | none written | **EX-04** |

**Smallest change for traceability:** one `_refuse(run, name, reason)` helper in the executor that every deny in
`_ask`, `_ask_read` and `_propose_*` goes through. It logs codes only, counts the deny as expected (EX-02), and
reports to the run's scope (`host.resolve(run_id).refused(...)`), so `tool_refusals` carries Claude Code's tools too.
Codes: `outside_workflow`, `no_web`, `url_not_given`, `never_read`, `too_long`, `changed`, `declined`, `change`,
`no_questions`.

## 6. The sibling's findings, checked

- **Request lifecycle (its §2):** confirmed where the executor is involved: `_open_scope` → `providers.start` →
  `bind` → events → result (`session.py:2910-2943`, `3833-3894`). Addition: the scope opens before `start` and is
  bound after it, so the first tool call relies on `resolve`'s fallbacks only in that gap (W3).
- **`system_action` availability:** confirmed. It's a `ToolHost` tool, so every run with a host has it, and a
  workflow run without it in its grant is refused by `RunScope.allows` (`tools.py:868-872`), now logged as
  `outside_workflow`. `WORKFLOW_PROMPT` (`claude_code.py:101-112`) still says not to try another way after a refusal,
  with the new exception "unless the tool says to ask the owner first".
- **Provenance (IA-01):** confirmed: `system_tools.system_action` re-parses the owner's words with `owner_intents`
  (`system_tools.py:136-143`); each refusal now calls `scope.refused`.
- **Transcription:** confirmed for the default engine (`config.example.yaml:37`, `engine: "parakeet"`, through
  `onnx_asr`, `transcriber.py:401-410`). Correction: `WhisperTranscriber` (beam 5) is still selectable; it also
  returns one hypothesis.
- **Authority boundary:** confirmed for this executor: every Claude Code tool that isn't a read or a declared web
  lookup goes through `_ask` → `_decide` → `gateway.bind/allow` (`:834-843`); step and plan approvals bind each listed
  command (`_set_grant`, `_spend`, `:320-346`); settings files are ignored (`setting_sources=[]`, `:676`). None of
  EX-01..EX-04 approves anything that wasn't shown.

## 7. Changes, in order

| # | Change | Fixes | Risk / trade-off |
|---|---|---|---|
| 1 | `_pump`: inner `finally` for `finished`/`_DONE`/`_refill`; `cancel()` doesn't cancel a run with a result | EX-04 | Tiny. A cancel during close then waits for the close (≤5 s + taskkill), which is the honest wait |
| 2 | `redirect`: False once `run.result` is set | EX-01 | The session restarts the run with the change: slower (cold start), but the change happens |
| 3 | `_refuse` helper for every deny (counted expected, logged, `tool_refusals`) | EX-02, §5 | Touches the permission bridge: review by another author (product-rule area, though no rule changes) |
| 4 | Model-check retry only before the turn's first message | EX-03 | A real unconfirmed-model error mid-run then ends the run with an error card instead of a retry |
| 5 | Key `expected` by `tool_use_id` (`can_use_tool`'s context has it; Swift's MCP tools would need it passed in) | W2 | More state; only worth it if escalation counts matter |
| 6 | `ToolHost.resolve(run)` with a run id: no fallbacks | W3 | Calls without a run id (other providers) keep the ContextVar |
| 7 | Don't refill while released/closed | W5 | Needs a `released` flag in the executor |

Not proposed: replacing `_watched`'s per-message Task. It is correct today and the alternative (`asyncio.timeout`
around `__anext__`) would cancel the read on every timeout, which is exactly what loses messages.

## 8. Target architecture (reusing what exists)

The shape stays: one CLI per run, `_ask` as the only permission bridge, the gateway as the only approver.

- **A run's end is one state change.** `_Run` gets a phase (`running → answered → finished`) set by `_pump`;
  `redirect`, `cancel` and `_watched` read it instead of `finished`/`cancelled`/`result` separately. EX-01 and EX-04
  are both "answered but not finished" handled wrongly.
- **One refusal path** (`_refuse`, §5) that feeds the escalation counter, `swift.log` and `RunScope.refused`, so
  `tool_refusals` is the record of every "no" in a run, whoever said it.
- **Scopes by run id only** (`ToolHost.bind` already exists; the executor knows its run id in every callback).
- **Escalation reads outcomes, not `is_error`**: a tool result is a failure only when no Swift decision explains it.

## 9. Testing strategy

- **Executor unit tests with fakes** (`test_claude_prewarm.FakeClient`, the SDK's own `Query` over a memory stream as
  in `test_executor_review.sdk_client`): one test per state boundary: cancel and redirect in each phase (connecting,
  in a turn, waiting on a card, answered and closing, finished). EX-01/EX-04's tests become ordinary tests when fixed.
- **Stream contract test** (kept passing): `_watched` over the SDK's real receive path, so an SDK upgrade that adds an
  anyio scope or changes delivery fails here first (W1).
- **Refusal coverage:** a parametrised test over every deny branch of `_ask`/`_ask_read`/`_propose_*` asserting a
  reason code in `tool_refusals`, `run.expected` counted, and nothing of the request's words in the log line
  (`test_seams_audit_privacy.py`'s allow-list).
- **Session level:** one test through `Session` with a slow-closing fake: Esc right after the answer ends the request
  and frees its slot (`MAX_RUNS`), and a fourth request isn't queued.
- **Seam scenario:** not needed for EX-01/EX-04's fixes (no new screen), but "Esc as the answer lands" is worth a
  dev-harness scenario on port 1431 to see the card settle on Cancelled.

## 10. What was verified, and what was only read

**Verified (tests and a scratch script, fakes only):**

- `_watched` loses no message across repeated wake-ups, over the SDK's own `receive_response` and anyio stream.
- A cancelled pending read loses the handed item and finishes the generator (anyio 4.15.1, SDK 0.2.172).
- A stall ends `_watched` with `RunStalled`.
- EX-01, EX-02, EX-03, EX-04 as described, each failing under `--runxfail`.
- `test_executor_review.py`: 3 passed, 4 xfailed. Full suite: see the commit's report.

**Read, not run:**

- The session-level consequences of EX-04 (slot never released, quitting hangs) and EX-01 (the log line, the Done
  card).
- That the real CLI's `set_model` raises "Couldn't confirm model" (EX-03), and how long the real CLI takes to close.
- W1-W7, and the sibling checks in §6 beyond the lines cited.

**Not done:** no live CLI, no dev harness, no real-PC check.
