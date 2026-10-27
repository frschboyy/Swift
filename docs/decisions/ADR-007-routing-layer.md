# ADR-007: A routing layer in front of Claude Code

- **Status:** Accepted (owner's decisions recorded in §9, 2026-10-23)
- **Date:** 2026-10-23
- **Builds on:** ADR-006 (Swift dispatches to Claude Code), ADR-005 (connector-ready integrations)

## 1. Context

Today every transcript goes to Claude Code on one model, whatever it says. Measured on the development laptop (i7-10610U, plugged in):

| Step | Time |
|---|---|
| Speech to text (Parakeet) | 0.5–1.2 s |
| Claude Code, started ahead of time (`prewarm`), first step | 0.2–0.4 s |
| Claude Code, one-word answer | 2.0–2.6 s |
| Claude Code, small file question | about 5 s |
| Claude Code, cost per request | $0.001–0.05 |

That is the right tool for "fix the failing test", but too heavy for "stop" or "what time is it". It also spends the same model on a lookup as on a refactor.

**Goal (owner): optimize usage for value.** Spend the least model capability that does the job well. Start cheap, judge quickly how demanding a request is, and move to a stronger model when the request turns out to need it.

## 2. Decision

```
transcript
  │
  ├─ 1. Rules ────────────── stop, cancel, approve/reject, time/date, "use opus …"
  │      (0 ms, offline)                         └─► handled by Swift
  │
  ├─ 2. Local classifier ─── route + demand estimate (10–30 ms, offline)
  │                            route: control | local | claude
  │                            demand: light | standard   (+ confidence)
  │
  └─ 3. Claude Code, pre-warmed, model picked from demand:
           light    → Haiku 5.5      (questions, lookups, short answers; read-only tools)
           standard → Sonnet 5.5     (project work; the default when unsure)
         and, while it runs, escalation (§6):
           Haiku → Sonnet → Opus 5.5, when the request proves more demanding
```

- **Everything that needs a model goes through Claude Code** (owner decision 1). That keeps one login and one permission system (the overlay's confirm card), and one pre-warmed process serves every model. Direct answers are Claude Code on Haiku, about 2 s.
- **Haiku or Sonnet is the starting point. Opus is reached only by escalation** or by an explicit "use opus" (owner decision 2).
- **Requests Swift has no dedicated route for** (email, calendar…) go to Claude Code to try (owner decision 3). There is no "not yet" card.
- **Claude Code is the safe fallback.** Anything the classifier isn't sure about goes to Claude Code on Sonnet.

## 3. Tier 1: rules

These are deterministic phrases, matched on the transcript after word fixes. They need no model and work offline:

- **Control:** "stop", "cancel", "never mind", "repeat that", "approve", "reject". The last two answer an open confirm card by voice.
- **Local:** time and date. Later, "open the Trading folder" or "open VS Code".
- **Model override:** "use opus …", "use haiku …", "think hard about …" set the starting model, and the prefix is removed before the request is sent.

The Phase 0 grammar prototype (`spikes/routing/grammar_proto.py`) is the starting point.

## 4. Tier 2: local classifier (route and demand)

- **Model:** a small sentence-embedding model in ONNX, for example `bge-small-en-v1.5` (about 130 MB; owner decision 4: acceptable). It runs on `onnxruntime`, which Swift already loads for Parakeet. Expect 10–30 ms per request on this CPU (to be measured).
- **Outputs:**
  - **Route** (`control`, `local`, `claude`) for whatever the rules didn't catch.
  - **Demand** (`light` or `standard`), with a confidence score. Below the confidence threshold, demand is `standard`.
- **Demand signals,** learned from labeled examples, not hand-coded:
  - `light` looks like questions and lookups ("what's in…", "how many…", "explain…", "translate…", "draft a short note…").
  - `standard` looks like changes and investigations ("fix…", "refactor…", "add a feature…", "why does … fail", whole-project scope).
- **Training data:**
  - `eval/utterances.jsonl`: 160 labeled utterances from the v2.0 spec, relabeled to route and demand.
  - `spikes/stt/prompts.txt`: 40 MVP-style requests, labeled.
  - **Swift's own history:** each interaction logs the starting model and whether it escalated. A request that started `light` and escalated becomes a `standard` example. A `standard` request that finished in one or two turns with no edits is a candidate `light` example. So demand estimates improve with use, the same loop as word fixes.
- **Why not a local LLM:** Phase 0 measured Qwen3 1.7B on this laptop at about 7 tokens/s decode. A routing prompt alone took about 12 s.

## 5. Tier 3: Claude Code with the right model

- **Starting model per request:** `ClaudeSDKClient.set_model()` before `query()`, on the pre-warmed client.
- **Map:** `executor.models` in `config.yaml`, default `{light: claude-haiku-5-5, standard: claude-sonnet-5-5, strong: claude-opus-5-5}`.
- **Light requests** get the same read-only tools as today. A "simple question" that turns out to need a file read can still do it, and if it needs more than that, it escalates (§6).
- **Cost guard:** `max_budget_usd` stays per request, with a higher cap once a run has escalated to Opus. The result card says which model or models ran.
- **Follow-ups** ("now commit it") still have no memory of the previous request (sessions aren't persisted, ADR-006). The router sends requests that refer back ("it", "that") as `standard`, so Claude Code can at least look at the repo state.

## 6. Escalation: moving to a stronger model mid-request

**Verified 2026-10-23** (`spikes/latency/model_switch.py`, claude-agent-sdk 0.2.172, Claude Code 2.1.307). A run started on Haiku called a Swift tool. The tool called `set_model("claude-sonnet-5-5")`, and **the same request continued on Sonnet with its context intact**:

- the tool call came at 2.0 s
- Sonnet's answer came at 4.0 s
- the result's usage listed both models, at $0.025 in total

Two triggers can start an escalation.

**1. The model asks.** Every run gets an in-process tool, `request_stronger_model(reason)` (`create_sdk_mcp_server`), pre-approved, plus one line in the prompt: *"If this request needs more capability than you have (multi-step changes, debugging, design decisions), call request_stronger_model with a short reason before attempting it."* Swift then:
- moves the session up one step (Haiku → Sonnet → Opus)
- shows a step on the overlay: "Switching to Sonnet: needs changes in 3 files"
- logs the escalation in the interaction record

**2. Swift notices.** The harness watches the run and escalates on signals that a weaker model is struggling:
- more than N turns at the current level (N tuned on real runs, starting at 8 for Haiku)
- the same tool failing twice
- an `error_max_turns` result, which retries the request one level up

Rules:
- **One step per request at a time,** and Opus at most once per request. A run never steps down mid-request.
- **Opus needs no confirmation by default** (`executor.escalation.confirm_strong: false`). The overlay always shows when it happens. Setting it to `true` puts a confirm card before the switch to Opus.
- **Each escalation becomes training data** for the demand classifier (§4). Requests that keep escalating teach Swift to start them higher next time. That's the "optimize for value" loop.

## 7. Orchestration frameworks (Hermes Agent and similar)

The owner asked whether a framework such as **Hermes Agent** (Nous Research, open source, MIT) should orchestrate, create and deploy agents per task. What its public descriptions say (mostly third-party write-ups, to be confirmed against the official docs in the spike):

- It's a full agent runtime in Python and TypeScript, model-agnostic (Anthropic, OpenAI, OpenRouter, Nous Portal), and it runs natively on Windows.
- **Subagents** are separate processes started through a delegate tool. They can be steered while running, and the provider and model can be set per subagent.
- **Skills** are `SKILL.md` files the agent writes and improves itself (the agentskills.io format).
- It has persistent memory with session search, cron-style scheduling, and messaging gateways.
- The write-ups describe no documented API for embedding it in another app.

| Option | Gives Swift | Costs and risks |
|---|---|---|
| **A. Swift's own router (this ADR)** | Routing in milliseconds, a model per request, escalation, permission prompts on the overlay | We maintain the router and its examples |
| **B. Hermes as the orchestrator** | Memory, scheduled jobs, self-written skills, subagents on mixed models | A second agent runtime and permission model that bypasses the confirm card unless it's bridged. No documented embedding interface. Self-modifying skills. Another hop of latency. |
| **C. Claude Code as the orchestrator** | Subagents, skills, hooks and MCP are already behind Swift's permission bridge | — (this is tier 3) |
| **D. Claude Managed Agents** | Hosted, scheduled agents with memory and sandboxes | Runs in Anthropic's sandbox, not on this PC's files |

**Decided:** A now. Claude Code (C) stays the main destination, and its subagents cover "make an agent for this task" within a request.

**Owner decision 5:** Hermes gets a viability spike later, not now (`docs/backlog.md`). The spike should check:
- headless use on Windows
- time to first step
- whether its tool calls can be intercepted for the confirm card
- whether it adds value over Claude Code for scheduled or background jobs

## 8. Plan and how each step is tested

1. **Route and demand eval set.** *Done 2026-10-23:* `eval/routes.jsonl` (274 requests; labeling rules in `eval/routes.md`), scored by `spikes/routing/eval_routes.py`. Relabel `eval/utterances.jsonl`, and add the 40 MVP prompts and about 40 new requests. Metrics:
   - route accuracy
   - demand accuracy
   - **under-estimates**: requests labeled `light` that need `standard`. These cost an escalation, but they must not produce bad answers.
2. **Rules, a starting model per request, and escalation in the executor.** *Done 2026-10-23:* `swift/routing` (rules plus an interim keyword demand estimate in `demand.py`, tuned on the train split only). On the test split it had 0 dropped, 0 under-estimates, 4 of 55 light over-estimated, and demand right 94.5% of the time. Escalation lives in `ClaudeCodeExecutor`. Live, a light question ran on Haiku for $0.0013, and Haiku escalated a refactor to Sonnet by itself at 5.5 s. No new dependencies. Tests:
   - unit tests for the rules and the escalation policy
   - a live run where Haiku escalates (extend `spikes/latency/model_switch.py`)
   - cost and latency on light requests: Haiku against Sonnet
3. **Local classifier.** Embedding model plus examples. Ship only if under-estimates stay low enough that escalations are rare, measured on the eval set.
   *Done 2026-10-23:* `swift/routing/classifier.py`, **off by default** (`demand_classifier.enabled: false`, owner decision 2026-10-23, below).
   - **How it works:** `bge-small-en-v1.5`, int8 ONNX (34 MB), CLS embedding. A weighted 7-nearest-neighbor vote runs over the 180 train-split examples (`swift/routing/examples.jsonl`) plus the owner's learned ones. Light needs at least 70% of the vote; otherwise the request goes to the default, standard. It loads in a background thread after the ready line, and the keyword estimate answers until it is ready or if the model is missing.
   - **Classifier alone was not good enough.** The train split has only 31 standard examples. On the test split, with k from 3 to 9 and a threshold from 0.5 to 0.8, it under-estimated 5 to 15 of the 13 standard requests. So the keyword estimate goes first, and the classifier decides only the requests the keywords can't place. Those used to default to Sonnet.
   - **Test split, 94 requests** (`spikes/routing/eval_classifier.py`; with the keywords alone in brackets):
     - dropped 0 (0)
     - under-estimates 1 of 13 (0)
     - over-estimates 1 of 55 (4)
     - demand accuracy 97.3% (94.5%)
     - route accuracy 91.5%, unchanged
   - **The one under-estimate** is nw14, "tell me which strategy is most promising and why": a judgment call that reads like a lookup. The keywords had sent it to Sonnet only because they abstained. We did not add a phrase for it, because that would be tuning on the test split. Escalation is the backstop. It was proposed as the default because it is near 0 on under-estimates and better on everything else. The owner followed the recommendation to keep it **off by default** until under-estimates are back to 0 (the keyword rules have 0): more standard examples, from `learn_demand.py` reviews of real escalations, should get it there. `enabled: true` turns it on.
   - **Route:** the classifier's route vote is logged as `route_hint` only. Control and local need an action that only the rules supply, so acting on the vote could drop a request.
   - **Cost** on the i7-10610U, measured with other sessions keeping the CPU about 80% busy:
     - 14–18 ms per request (median), p95 35 ms, 2 threads
     - load about 5 s, in the background
     - about 97 MB more memory
     - the fp32 model gives the same accuracy at about 20 ms and 183 MB, so int8 is the default
4. **Learning loop.** Interaction records carry `start_model`, `escalations` and `turns`. A script, like `learn_fixes.py`, proposes new demand examples for the owner to approve.
   *Done 2026-10-23:* `spikes/routing/learn_demand.py`.
   - **What it proposes:**
     - a light request that escalated becomes a standard example
     - a standard request that finished done in at most 2 turns, with no escalation and no Edit/Write approval, becomes a light candidate
     - runs with a model override are skipped
   - The owner answers y/n/s/q for each. Kept examples are appended to `demand_classifier.examples_file` (`%LOCALAPPDATA%\Swift\demand_examples.jsonl`). Rejected ones go there too, marked so they are never asked again and never loaded. The classifier loads the file at startup.
   - The log had no routed runs yet at the time of writing, so the first real review is still to come. Read the log from a normal terminal, or pass `--log`.
5. **Local open handlers.** *Done 2026-10-23:* "open my downloads folder", "launch Chrome", "open the Swift project in VS Code" are handled by Swift (`swift/routing/local.py`, `local` settings). The rule matches loosely ("open/launch/bring up" plus a short phrase with no conjunction or verb in it), but only a phrase that names a configured app, folder or project is opened; anything else, and any compound request, goes to Claude Code. Launching is `os.startfile`, or the editor with the folder as its only argument, without a console window. On the test split the 8 `planned` detours became correct: 0 dropped, 0 detoured, route accuracy 100%. Tests mock the launcher.
6. **Later:** the Hermes spike, scheduled jobs, follow-up context, voice approve/reject.

## 9. Owner decisions (2026-10-23)

1. **Direct answers:** through Claude Code on Haiku, using the existing login (about 2 s). No separate API key.
2. **Model choice:** based on how demanding the request is, with Haiku or Sonnet as the default. Requests that prove more demanding escalate mid-run. Opus is reached only by escalation or an explicit request. The goal is optimizing usage for value.
3. **Requests without a dedicated route:** Claude Code tries them. *(Recorded from the answer "Yes" to "say 'not yet', or let Claude Code try?". To be confirmed.)*
4. **Classifier memory** (about 130 MB extra): acceptable.
5. **Hermes:** not now. Run a viability spike later.

## Consequences

- Swift gains a "little brain" (rules plus a classifier), which reverses part of ADR-006's "mostly face" stance. Claude Code still does all model work, and its permission system is still the control.
- Simple requests run on Haiku. Model choice becomes measurable and self-correcting through escalations.
- Routing and demand quality become things to measure, so an eval set joins the STT test set.

## Step 5 notes (voice approvals, follow-up context)

- **§8 Voice approvals.** Push-to-talk is accepted while the state is `confirm` (only then). The backend state stays `confirm`; `confirm.voice` messages (`listening`, `transcribing`, `idle`, `hint`) update a line on the confirm card instead of the orb, which would clear the card. "approve"/"reject" answer the card like a click, "stop"/"cancel" cancel the run like Esc, anything else shows a hint and leaves the card open. A click while the voice answer is still transcribing wins. `approvals[]` in the interaction log gains `source` (`voice` | `click`) and `heard` (what was said on the card).
- **§9 Follow-up context.** `resume` was not used: with `--no-session-persistence` there is nothing to resume, and resuming needs the session id at connect time, which breaks the pre-warmed CLI. Instead the session keeps one previous exchange (request, answer summary, approved action titles) and prepends it, clipped, to the next Claude request within `followup_context_s` (default 300 s, 0 = off). An error or cancelled run, or saying "new topic" / "start over", clears it. Time/date and commands in between keep it.
- Live check (2026-10-23, Haiku, `debug.ask` through `Session` + `ClaudeCodeExecutor` on this repo): "Which file in src/swift/routing has the most lines?" answered rules.py (98) in 31.9 s for $0.0014; the follow-up "How many functions are defined in it?" got the context block and correctly answered 4 functions in rules.py in 8.2 s for $0.0010. Voice approvals are covered by unit tests only (no mic in the check).

## 10. Lanes: the simplest path that answers (addendum, 2026-10-27)

**Why.** The owner's interaction log (2026-10-27, `spikes/owner_checks/report.py --since 03:56`) showed everyday requests going through an agent run of 7–18 s. "What time will it be in two minutes?" took 18 s. "And what's the date?" and "what month is it?" went to the agent, while "What's the date?" was answered locally, because the rules were too literal. And "Show me" / "Show me the Word document", said after a research-into-Word run had finished, started new agent runs; one was even offered the research-into-Word workflow. The owner's goal: *"matching each request to the simplest, fastest, and most appropriate path; more sophisticated workflows remain for tasks that genuinely need them."*

**Decision.** Every request goes down the first lane that can answer it:

```
transcript
  ├─ control ──── stop, cancel, approve, … (rules, whole utterance)
  ├─ local ────── Swift itself, offline, a few ms
  │                 identity, open, undo, resume, "show me" (show_last), time, date
  │                 fast lane (routing/fast.py): time/date maths, other cities, conversions,
  │                 arithmetic and percentages, spelling
  ├─ light ────── one tool-free call to the light model (routing/light.py, executors/quick.py)
  │                 synonyms, definitions, translations, grammar, stable facts, a polite reply
  ├─ agent ────── Claude Code with tools, model picked by demand (§2–§6)
  └─ workflow ─── a matched workflow package runs on the agent (ADR-011)
```

**How a request picks a lane** (`routing/rules.py`, in this order):

1. **Control**, then **local** rules match the whole utterance. A leading "and", "so", "ok" or "Swift," no longer stops a local match ("and what's the date?").
2. **Fast lane:** `fast.answer(text)` returns an answer, so the route is `local` with action `answer`. The session works the answer out again when it replies, so the time is the time it answers. It covers:
   - time now, in or ago ("in two minutes", "in an hour and a half", "90 minutes ago");
   - the time in about 100 cities, from a built-in table of offsets and EU, US, AU and NZ daylight-saving rules (Windows Python has no tz database, and adding `tzdata` was not worth a dependency);
   - dates: today, tomorrow, weekdays ("next Friday's date"), explicit dates ("what day is the 3rd of November"), holidays ("how many days until Christmas"), "in 3 weeks", "what month / year / week is it", days left in the year;
   - conversions: length, mass, volume, temperature, speed, time, area and data sizes;
   - arithmetic with words or symbols, percentages ("15% of 80", "20% off 50"), square roots and powers;
   - "how do you spell …".

   Numbers can be words ("two hundred and fifty"). Anything ambiguous returns None and goes on, because a wrong answer is worse than a slow one.
3. **"Show me"** with no run going is `local` / `show_last`. It reopens the last run's artifact card, or, if that run wrote in an app (Word), brings that app and document to the front (`Desktop.show`). "The Word document" or "the doc" prefers the app. It never starts a run. `Library.match` also refuses any "show / let me see / bring up / where is …" request (`is_show`), so it can never trigger a workflow run or offer. During a run, the mid-run grammar (ADR-010 §6) still handles "show me", as before.
4. **Light lane:** `light.kind(text)` recognises a word question, a stable fact or a few words to send. The route stays `agent` with action `quick` and light demand, so the eval set and its "nothing is lost" test hold. The session first asks `QuickModel`: one Claude Code call on the light model with every tool off, no MCP servers, no settings files, no persisted session and one turn, using the owner's existing sign-in (owner decision 1: no separate API key). The interaction log records route `light`. If that call fails, is empty, or takes longer than 20 s, the request continues to the agent on Haiku, so this lane can only make a request faster. Anything about the owner's things ("my", "this", files, email, calendar) or about now ("today", "latest", "weather") is excluded and goes to the agent, which has the tools and data for it.
5. **Agent**, then a **workflow** if `Library.match` finds one, exactly as before.

**Cost and speed.** The fast lane needs no model and no network: measured in milliseconds. The light lane keeps one tool-free CLI connected ahead of time, the same way the agent's `prewarm` does, and uses a fresh one for each question so questions never share context. It saves the agent session's system prompt, tools, MCP server and loop; measured live on 2026-10-27, with the CLI already warm: 2.5 s ("a synonym for happy") and 1.8 s ("reply politely to say I'm running ten minutes late"), against 7–18 s through the agent. Warming the CLI took 17.5 s, in the background at startup. `executor.quick_answers: false` turns the light lane off.

**Not done / next.**
- A direct Messages API call would be faster still (under 1 s, no CLI process), but it needs an API key, which owner decision 1 ruled out. If the owner wants it, it fits behind `QuickModel.answer` without changing the router.
- The fast lane is English only and uses this PC's clock and time zone. City times outside the table go to the agent.
- Re-run `report.py` on the owner's next session to confirm these phrase families no longer reach the agent.
