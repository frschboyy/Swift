# Workflow intelligence and lifecycle: audit (2026-11-10)

The question: can Swift's architecture let workflows be discovered, created, run, changed, grown, reused and retired as it learns the owner, without an architectural change for every new kind of intent?

Read from the code on `main` at `f46e9f6`, then checked against `bd3d0cb`: the 27 commits between them change no claim here (the workflow code gained `refresh_now`, today's date for a workflow picked up from the stack, and `RunScope.answers`; line numbers are `f46e9f6`'s), and ADR-020 (one record per conversation, accepted the same day) is reconciled in §9.3. Tests weren't run for this audit; where a claim rests on a test, the test is named. Nothing was changed.

## 0. The short answer

- **Swift has the right skeleton and almost none of the lifecycle.** Its trust boundary (gateway, grants, journal, product rules), its package format and its worker abstraction are sound and worth keeping. What's missing is everything that makes a workflow a *living object*: a run record, a store Swift writes to, triggers other than speech, a step runtime, memory, and a place to see it all.
- **Today a workflow is a prompt with a tool allow-list.** A matched package's `SKILL.md` is pasted into one Claude Code run, and the tool host refuses tools the manifest didn't declare. That's all a workflow does at run time. It has no steps Swift knows about, no state after the run, and no history apart from one line in the interaction log.
- **Of the lifecycle's six stages, only Execution (interactive, one run) is implemented.** Discovery is partial (a fixed phrase lists three workflows). Creation, growth, modification and retirement are by hand-editing files and restarting Swift. Learning doesn't exist.
- **The design for most of it is already written and decided** (ADR-011, product-direction §5–§7, handoff §4 groundwork and steps 4–8). The gap isn't a missing vision. It's that the groundwork the design depends on, above all **run records**, hasn't been built, and every later stage needs it.
- **Recommendation:** don't build a workflow engine. Build run records first, then a Swift-owned store for workflows and memory, then schedule triggers on the existing scheduler. Recipes come only when runs show something worth hardening. §9 has the phases.

## 1. What Swift can actually do today

| Piece | What it does | Where | Evidence |
|---|---|---|---|
| Workflow package | Folder with `SKILL.md` (Agent Skills) and `swift.yaml` (`swift.workflow/v0`): triggers, typed inputs, settings, `needs`, provider, demand, `shows`. Validated with errors in plain words | `workflows/library.py` | `test_library.py` (9 tests) |
| Library | Built-ins plus `%APPDATA%\Swift\workflows`; an owner's package with a built-in's name replaces it. Loaded **once at start-up** | `library.py: load_library`, `backend/__main__.py:291` | No reload path exists in `src/swift` |
| Built-in workflows | Three: `calendar-event` (2.1.0), `email-draft`, `research-into-word` | `workflows/library/` | `test_playbooks.py` (13 tests, fakes) |
| Matching | Slot phrases (`add {event} to my calendar`), `intent` word pairs, question intents, calendar-title intents; a description match is *offered* ("I have a workflow for that…") | `library.py: Library.match`, `session.py:2853–2864` | `test_library.py`, `test_playbooks.py` |
| Run | The playbook, inputs, setting defaults, the time and the request become the agent's prompt (`Package.request`); the run gets a `Grant` | `library.py:236`, `workflows/scope.py: Grant`, `session.py:2902–2910` | `test_claude_executor.py` |
| Permission boundary | Tool host refuses tools outside the grant; Claude Code's own write tools refused in workflow runs; web only if declared; every side effect through `ActionGateway` (validate, resolve recipients, policy, digest-bound confirm, journal, verify) | `scope.py: RunScope.allows`, `claude_code.py:465–507`, `security/gateway.py` | `test_workflows.py`, `test_desktop.py`, `test_calendar.py` |
| Follow-ups | A follow-up in a workflow's thread keeps its playbook and tools ("send it", "actually say …"); corrections on a card (`revise`) stay in the same run | `session.py:2858–2862`, gateway `revise` | ADR-011 §15 |
| Undo | Gateway remembers approved actions for 15 min in memory; `undo_last_action` reverses the newest one through a card | `gateway.py`, `tools.py:569` | ADR-011 §16 |
| Listing | "What workflows do I have?" (one regex) lists title, "(yours)", an example phrase, and packages that failed to load | `routing/rules.py:91`, `session.py:4060` | `test_playbooks.py` |
| Scheduler | Timers, alarms, reminders in a JSON file; survive restart; missed items fire once marked missed; kept until shown | `system/scheduler.py` | scheduler tests; commit `3fca2ee` |
| Unfinished work | Stopped or unanswered conversations parked 24 h in a JSON file; "continue" restarts the conversation with its context | `parked.py` | ADR-014 §5 |
| Concurrency and attention | Up to 3 requests at once; one card on screen, others wait; cards held while away, put aside into the stack, never decided for the owner | `attention.py`, `stack.py` | ADR-013–015 |
| Workers | `Executor` protocol and `ProviderInfo`; one real worker (Claude Code), one mock | `executors/base.py`, `providers.py` | — |
| Records | `interactions.jsonl` (one line per interaction, with `workflow`, steps, approvals, status, cost); `journal` (PENDING/DONE/FAILED/UNKNOWN per side effect, receipts) | `runlog.py`, `security/journal.py` | — |
| Learning pattern | Word fixes and demand examples: Swift proposes, the owner approves on a card, the result is a visible record | `stt/improve.py` | product-direction §5.1 |

**What isn't there at all:** a memory or preference store; per-owner values for workflow `settings`; any non-speech trigger for a workflow; a step runtime; a run record per run; a catalogue the agent can see (a plain agent run isn't told which workflows exist: `self.library` is used only for matching and listing); external MCP servers (the only one is Swift's own in-process `swift` server, `claude_code.py:490`); any workflow screen in the overlay (`overlay/src` has no workflow code).

## 2. The lifecycle, question by question

Key: **I** implemented · **P** partly · **A** architecturally supported, not built · **N** not supported (a real gap) · **U** unknown.

### Discovery

| Question | | Why |
|---|---|---|
| Recognise a request as a larger repeatable process | **N** | Matching asks "which package fits this sentence", never "is this a pattern". There's no record across runs to look at. |
| Identify repetitive activity, automation opportunities | **N** | Designed (ADR-011 §8 L1–L2, product-direction §5.6 review job). The interaction log has the data in principle; nothing reads it for patterns. |
| "What workflows can you help me with?" | **P** | Only the exact phrasing in `rules.py:91`. "What can you automate for me?" goes to the agent, which isn't given the library. |
| Discover new capabilities from tools, integrations, agents | **N** | Capabilities are a hard-coded dict (`CAPABILITIES`, 17 entries). No external MCP, no registry, nothing reports tools at run time. |

### Creation

| Question | | Why |
|---|---|---|
| Describe an outcome, Swift builds the workflow | **N** | ADR-011 §5.1 (W4). Today the owner writes two files by hand. |
| Steps, dependencies, tools, permissions, outcomes | **P** | `needs` declares tools and gives each a risk; `shows` declares outputs. Steps and dependencies exist only as prose in `SKILL.md`. |
| Clarifying questions | **I** (in a run) | `ask_owner`, `find_contact`'s "which one", the question card (ADR-016 §16). Not for building a workflow, since that doesn't exist. |
| Propose a workflow it can't fully automate | **A** | A playbook can already say "ask the owner for this part". Nothing proposes one. |
| From tasks, conversations, recurring patterns | **N** | "Make that a workflow" needs run records (handoff §4 step 6). |

### Execution

| Question | | Why |
|---|---|---|
| Multi-step, multi-tool, multi-app | **I**, inside one agent run | The agent sequences tools; Swift sees tool calls, not steps. Specialised agents: one worker only. |
| Interactive | **I** | |
| Background | **P** | Up to 3 concurrent requests, but each is a live conversation with a working card, a 90 s no-progress watchdog and a $1.00 budget (`claude_code.py:295`). Nothing runs unattended for long. |
| Scheduled | **N** for workflows | The scheduler holds only `timer`/`alarm`/`reminder` (`scheduler.py: KINDS`). A manifest with `schedule` is refused ("not supported yet (W5)", `library.py: _LATER`). |
| Event-driven | **N** | No watchers, no file or mail events. |
| Survive interruption and restart | **P** | Safe, not durable: an interrupted side effect is reported and never retried (`journal.unfinished`), and the conversation can be "continued" for 24 h. The run itself is lost: no step state, and the Claude Code session isn't resumed. |
| See what's happening, intervene | **I** for the run on screen | Working card with normalised activities, live view, stop, redirect mid-run, revise on a card. Nothing for runs that aren't conversations. |

### Growth and evolution

| Question | | Why |
|---|---|---|
| More sophisticated as capabilities arrive | **P** | A playbook improves for free when the agent does, and by editing `needs`. That's the strength of playbooks. |
| Incorporate new tools, integrations, agents | **P** | Adding a Swift tool takes a `ToolSpec`, a `CAPABILITIES` entry and a gateway `POLICY` entry: three edits in code. Adding a worker is documented and small (`providers.py` docstring). External tools: none. |
| Recognise a workflow could improve | **N** | No per-workflow history to judge from. |
| Learn from corrections and preferences | **N** across runs | `revise` corrects within a run and is forgotten after. |
| Extend without rebuilding | **P** | Edit the files, restart Swift. |

### Modification and maintenance

| Question | | Why |
|---|---|---|
| Change steps, conditions, schedules, permissions | **P** | By hand-editing; no schedules exist; no permission diff shown. |
| Detect outdated, broken, redundant parts | **P** | Load-time validation only: a broken package is skipped and listed "Couldn't load". No health check of capabilities against what tools exist at run time, no tests replayed. |
| Update when tools or requirements change | **N** | |
| Preserve configuration, avoid regressions | **N** | `version` is validated and never used. No history, no migration, no `tests/` folder read. The owner's settings values don't exist yet, so there's nothing to preserve. |

### Removal and lifecycle management

| Question | | Why |
|---|---|---|
| Pause, disable, archive, delete | **P** | Delete or rename the folder (a `_` or `.` prefix hides it, `load_library`). One global switch, `workflows.enabled`. No per-workflow state. |
| Recognise a workflow no longer useful | **N** | No last-used record. |
| Inactive vs retired | **N** | |
| Dependencies when removing | **N**, and not yet needed | Workflows don't depend on each other or share components. That will change once they do. |

### Learning the owner (§3 of the brief)

| Question | | Why |
|---|---|---|
| Recurring activities and patterns | **N** | |
| Preferences and constraints | **N** | No store. `config.yaml` is settings, not memory. |
| Recurring requests → workflows | **N** | |
| Remember workflows and their configuration | **P** | The files are the memory; per-owner setting values don't exist. |
| A request modifies an existing workflow | **P** | Only within a thread (a follow-up keeps the grant). Across days, "change the digest to Sunday" has nothing to change. |
| Suggest automations | **N** | |
| Adapt to changing priorities | **N** | |

**The safety half is the strong half.** The brief asks that Swift never silently create automations or act on what it believes. The code already enforces the parts that exist: the gateway fails closed on an unknown tool; side effects outside the owner's own apps always need a card; recipients only from contacts; typing never approves; nothing learned can write memory because there is no memory to write. The design (product-direction §5.2, §5.5) keeps that true for what comes next: patterns never act, nothing learned widens autonomy, only the owner's words or an approved card write memory. **Keep those as the acceptance tests for every phase below.**

## 3. The architecture, area by area

| Area | State | Notes |
|---|---|---|
| Workflow representation | **Good start** | Agent Skills + manifest is portable (Claude Code, Codex, Hermes read `SKILL.md`), readable and safe to share (no code). The manifest is strict and gives clear errors. Weakness: the format has no notion of *instance*: the owner's configuration, enabled state, schedule and history have nowhere to live except in the package itself. |
| Persistence | **Missing layer** | Packages are read-only to Swift: nothing in `src/swift` writes one. Swift can't create, edit, version or disable a workflow, so W4 and every learning feature need a writer first. |
| Orchestration | **Delegated** | The agent is the orchestrator. Right for breadth, wrong for anything repeatable, cheap or testable. Recipes (ADR-011 §4.3) are designed, not built; the five examples in `docs/explorations/workflows/` have `recipe.yaml` files nobody reads. |
| Decomposition, dependencies | **None in Swift** | Inside the agent's context only. |
| Agent and tool discovery | **Static** | `CAPABILITIES` (library), `POLICY` (gateway) and `TOOLS` (tool host) are three hand-kept tables. `Risk` in `library.py` is `read/none/reversible/external`, while ADR-011 §3 and ADR-019's deletion rule need `destructive`. The gateway's `POLICY` and the library's risk can disagree, and no test checks they match. |
| Capability management | **Per run** | `Grant` is the right primitive: a run may use exactly what it declared. Scopes (`files.write: {within: …}`) are parsed and ignored (W2). |
| Scheduling | **Good mechanism, narrow use** | The scheduler is the best-built durable piece Swift has: atomic writes, missed-item handling, kept until shown, bad rows set aside. It only knows three kinds of item. Extend it, don't add a second one. |
| Events | **None** | Watchers are handoff step 5. |
| Long-running state, recovery | **Safe, not durable** | The journal's rule (never re-run a side effect whose state is unknown) is exactly right and must survive any resume design. What's missing is a record of *where a run was*. |
| Background, concurrency | **Conversational** | Concurrency means "several conversations", bounded by the screen. There's no notion of a run with no card. |
| Memory, preferences | **Missing** | Designed in detail (product-direction §5) with the safety rules already in `CLAUDE.md`. |
| Versioning, migration | **Field only** | `version` validated, unused. ADR-011 §6.1 proposes the owner's folder as a git repository; nothing does it. |
| Errors, retries | **Deliberately no retries** | `failures.py` classifies, the watchdog ends stuck runs, providers aren't retried mid-run because a run may have changed something. Correct for agent runs. Recipe steps would want per-step retry of *read* steps only. |
| Permissions, confirmations | **Strongest area** | See §2. Two gaps for workflows: no permission diff when a package's `needs` grows (ADR-011 §6.3), and an owner's package can silently replace a built-in with wider `needs`. The replacement is logged ("your workflow replaces the built-in one") and nothing else happens. |
| Observability, history | **Two logs, no run** | The interaction log is per *interaction*, the journal per *side effect*. Neither is per *run of a workflow* with its steps, inputs, worker, outcome and why. "Why did this workflow fail?" and "when did it last run?" can't be answered. |
| UI | **Moment-only** | The overlay is built for the request in front of the owner: cards, stack, Deck. Right for running; no place to inspect, list, edit or monitor. The Swift window (handoff step 7) is planned. |
| Extensibility | **Workers: yes. Tools: by code** | A new worker is one executor file. A new tool is a code change in three tables. External tools need ADR-005's plugin host. |

**Two structural risks to name now:**

1. **Matching won't scale by hand-tuning.** `calendar-event/swift.yaml` already carries six triggers and four intents with comments about which words broke which coding request ("no bare 'event' or 'call' here: 'remove the event listener'"). Each new workflow adds words that can collide with every other. Two intents that both match produce no run (`len(intended) == 1`), which is safe but degrades silently as the library grows. ADR-011 §10 open problem 5 says the same. At 10–20 workflows this needs the local sentence model (already on the PC for the classifier) and a measured parity set per workflow, as routing has (`eval/parity`).
2. **`session.py` (4,976 lines) owns workflow routing.** Every stage above would otherwise land there. The groundwork's split (handoff §4) has to come first, or at least the workflow parts go into their own modules from day one.

## 4. What is preventing dynamic workflows

In order of what blocks the most:

1. **No run record.** Learning, hardening, history, "why did it fail", last-used, retirement, resume and the review job all read runs. Swift writes interactions and side effects, not runs. *This is the single foundation everything else stands on.*
2. **No Swift-owned writable store.** Swift can't write a workflow, a setting value, a memory or a schedule for a workflow. Creation by voice, modification, enable/disable and learning all need one writer with versions.
3. **No trigger besides speech.** Without `schedule` and `event` triggers, "recurring" and "proactive" are impossible, however good the workflow.
4. **No instance layer.** A package is a definition. Swift needs per-owner *installations*: enabled or paused, setting values, schedule, last run, health, version pinned. Today the definition is all there is.
5. **No step model Swift understands.** Without it, Swift can't show progress per step, retry a read, resume after a restart, replay tests, or say "what would happen if I changed this step". Playbooks are fine without it; recipes need it.
6. **Static capability tables.** Fine for now. They become the bottleneck once tools come from outside (MCP, Windows agent connectors).
7. **No inspection surface.** Voice and cards can't show a list of workflows with their history and permissions.

## 5. Extend, don't replace

| Keep and extend | Into |
|---|---|
| `Package` / `swift.yaml` | Add `schedule`, `watch`, `budget`, `history` (already reserved in `_LATER`). Keep the definition read-only; put instance state elsewhere |
| `Grant` + `RunScope` | The grant for every run, scheduled or not; scopes once W2 needs them |
| `ActionGateway` + `Journal` | Unchanged as the only door to side effects. The journal becomes the side-effect part of the run record (handoff §4: "generalizing the action journal") |
| `Scheduler` | Add a `workflow` kind (or a generic `trigger` row with a package name and inputs), reusing its file, missed-run handling and kept-until-shown |
| `InteractionLog` | Becomes a view of run records, keeping its allow-list into `swift.log` |
| `parked.py`, `stack.py`, `attention.py` | Where a background or scheduled run surfaces when it needs the owner: a run that needs approval becomes a held card in the stack, never an action |
| `Executor` / `ProviderInfo` | The `WorkerTask` contract (handoff §4): request, context pack, grant, budget, privacy class |
| The propose → approve → visible record pattern (`stt/improve.py`) | The template for every suggestion: workflow proposals, memory, hardening |
| `Library.match` | Keep slots and intents for precision; add a scored description match on the sentence model for offers |

**Don't build:** a general workflow engine, a graph editor, n8n or Temporal as the runtime (ADR-011 §9 decided this; the reasons still hold), or a second scheduler.

**Replace eventually:** the three hand-kept capability tables, with one registry (`ToolSpec` carrying its capability name, risk and gateway policy) and a test that every tool appears exactly once. That is a structural step that deletes code, so it fits the rules.

## 6. The ideal lifecycle

One object model, five nouns:

- **Definition**: the package (`SKILL.md`, `swift.yaml`, optional `recipe.yaml`, `tests/`). Versioned. Read-only at run time.
- **Installation**: the owner's copy of a definition: enabled / paused / retired, setting values, triggers, pinned version, created from (said, approved suggestion, file), last run, health. One small file per installation in Swift's store.
- **Trigger**: speech (today), schedule (scheduler row), event (watcher). Every trigger starts a run the same way.
- **Run**: an append-only event log: trigger, inputs, worker and why, steps, tool calls, approvals, artifacts, outcome, cost. Side effects keep the journal's rules.
- **Suggestion**: a proposal with evidence (which runs, how many times), never applied without a card.

The lifecycle, with what moves it:

```
 observed ──(review job, counts)──► suggested ──(owner approves card)──► draft
                                                                          │ dry run (reads real, side effects shown not done)
 said "make that a workflow" / described ─────────────────────────────────┤
                                                                          ▼
                    ┌──────────────── active ◄──── resumed ────┐
                    │  runs on its triggers                    │
   needs attention ◄┤  (health check fails: never runs         │
   (owner told)     │   half-broken)                           │
                    ├──► paused (owner, or "for a week") ──────┘
                    └──► retired (owner; or suggested after N weeks unused) ──► deleted (card, ADR-019)
                          kept in history, "bring it back" works
```

Rules that hold at every edge:

- **Only the owner moves a workflow to active, wider permissions, or deleted.** Swift may move it to *needs attention* by itself (a health check failed), and may *suggest* retiring.
- **Paused is the owner's choice and keeps its triggers; retired drops the triggers and keeps the definition.** That's the difference between "inactive" and "no longer useful".
- **Every change is a new version with its source and the run it came from**, so "undo that" and "why is it like this?" work.
- **A permission that grows is shown first and approved by click or "Swift, yes"**, never by typing.
- **A scheduled run never takes a consequential action unattended.** It does its reads, then holds its card in the stack until the owner is there (ADR-014 already does this for cards).

## 7. The user-facing experience

Two surfaces, matching product-direction §7:

**By voice and on cards**, for the moment:

| The owner says | Swift answers with |
|---|---|
| "What can you automate for me?" | The library's descriptions plus what it has noticed (once there are run records): a list card, each with "Set it up" |
| "What workflows do I have?" | Today's list, plus state and last run: "Tech digest, every morning, last ran 08:00, fine" |
| "What are you doing in the background?" | Active runs and the next scheduled ones |
| "Which need my attention?" | Held cards from scheduled runs, workflows marked *needs attention*, waiting suggestions: one card, the "while you were away" card (step 4) |
| "Why did the digest fail?" | The run record's failure in words, with "Try again" and "Open in Swift" |
| "Change it to Sundays" | A card showing the change as before → after, and any permission change first |
| "Make that a workflow" | A draft card: the steps in plain words, the trigger, the permissions, "Save" |

**The Swift window** (a second Tauri window, handoff step 7), for inspection. A **Workflows** tab:

- a list grouped by state (needs attention, active, paused, suggestions, retired), each row a sentence: name, trigger in words, last run and its outcome;
- a workflow page: what it does (from `SKILL.md`), when it runs, what it may do (each permission with its risk in words), its setting values as fields, its history (runs, each opening its record with "Why?"), its versions with "Restore";
- steps as a numbered list once there are recipes; never a node graph;
- every edit writes through the same backend messages voice uses, so there is one source of truth.

"Combine these two workflows" and "what would happen if I changed this step" are recipe-era features: they need steps Swift understands and a dry run. Until then, the honest answer is a draft playbook that calls both, shown as a draft.

## 8. Discovery and suggestions

Three sources, in order of trust and of when they're possible:

1. **The library itself** (now): descriptions are the ~100-token skill summaries. Give them to the agent as a catalogue in agent runs, so "can you do X?" finds a workflow, and match descriptions on the sentence model for offers.
2. **Run records** (after groundwork): a local, counts-based review job (product-direction §5.6) finds the same request repeated, the same correction twice, a workflow failing or unused. Evidence attached, at most one suggestion a day, "stop suggesting this" permanent. Nothing sent to a cloud model without the owner's yes.
3. **New capabilities** (with the registry): when a tool arrives, check which workflows' playbooks could use it and *suggest* a new version. Never auto-upgrade.

Desktop observation (L3) stays off unless the owner opts in on a consent screen by click (ADR-011 §12 Q4, decided).

## 9. Roadmap

This follows the order already agreed in handoff §4 and shows what each step gives the workflow lifecycle. It doesn't jump the queue: the reliability work, daily use and the owner's open decisions come first, and the two weeks of use are what should confirm the order after phase 1.

| Phase | Build | Lifecycle it unlocks | Classification after |
|---|---|---|---|
| **0. Now (no new behaviour)** | Finish handoff §4 a–e. Add two cheap things: the library catalogue in the agent's prompt, and a test that `CAPABILITIES`, `POLICY` and `TOOLS` agree (and that an owner's package can't widen a built-in's `needs` without being told) | Discovery by ordinary questions; closes a silent permission widening | Discovery P→P+ |
| **1. Groundwork** (handoff §4 "3") | Split workflow routing out of `session.py`. **Run records** (one append-only log per run; journal and interaction log become views). **One store** for installations, setting values and memory, one writer, versioned, every record with its source. **The store records links between workflows from the start** (gap G3): an installation may name another workflow it calls, and the store knows who uses what. **A task id on every run record from day one** (§9.2): a task is the owner's goal ("apply to these five internships"), outlives a parked thread's 24 h, and groups the conversations, runs and deliverables that serve it; the store keeps its state. **Run records are ADR-020's conversation record and its event log, not a second record beside it** (§9.3). `WorkerTask` contract | History, "why did it fail", last-used, per-owner settings, "remember / forget"; the record that composition and safe removal need later | Observability N→I; Memory N→P |
| **2. Away and back** (step 4) | The "while you were away" card | A place for scheduled results and suggestions to land safely | — |
| **3. Triggers** (step 5) | `schedule` in the manifest and installation, as scheduler rows; watchers for the owner's top two (decision 22). Scheduled runs read, then hold consequential cards. **A model for unattended runs** (gap G4): their own budget and no-progress limit instead of the interactive $1.00 and 90 s; a checkpoint in the run record after each tool call; after a restart, the run goes on as a new conversation from its record, never repeating a side effect the journal doesn't mark undone | Recurring and proactive work that survives a restart | Scheduled N→I; Event N→P; Restart P→I for playbook runs |
| **4. Made from runs** (step 6) | "Make that a workflow", "do that every Friday": an agent drafts the package from a run record; draft card; dry run; save as a new installation. Edits by voice as re-drafts with a permission diff. Versions kept (git in the owner's folder, as ADR-011 §6.1, or the store's versions). **Matching at scale** (gap G6), before the library passes ~10 workflows: description matches scored on the local sentence model, and parity cases per workflow in `eval/parity` that a new workflow must not break. **"Combine these two"** drafts a workflow that calls both, using the links from phase 1 | Creation, modification, versioning, restore, composition | Creation N→I; Modification P→I |
| **5. The Swift window** (step 7) | Workflows tab as §7; enable, pause, retire, restore. Retiring or deleting a workflow another one calls says so first | Inspection, management, retirement with dependencies | UI N→I; Removal P→I |
| **6. Capabilities** (step 8, ADR-011 W2) | One capability registry with scopes; file tools with folder permissions; the taint rule (ADR-011 §7.3). **Worker capabilities** (gap G1): `code.edit`, `code.run` and the like, mapped to the worker's own tools the way `web.search` is today (`PROVIDER_TOOLS`), each call behind its confirm card, so engineering and administration work can be a workflow. **Health checks** (gap G5) on load, on every registry change and before each scheduled run: every capability in `needs` exists, a worker can fill it, `tests/` replay; a failing workflow goes to *needs attention* and never runs half-broken | New tools reach workflows without code in three places; workflow categories that write or run things; broken workflows found before they run | Tool discovery N→P; Broken components P→I |
| **6b. Outside tools** (ADR-005 Phase 7, gap G2) | The plugin host: approved MCP servers on an allow-list, Swift-assigned risk per tool, pinned versions, outputs treated as untrusted; Windows' agent connectors once out of preview. Each server approved on its own card | The integrations most of the brief's categories need (sales, finance, project tools) | Integrations N→P |
| **7. Recipes, when earned** (ADR-011 W3 + W5 hardening) | Only once run records show workflows that repeat the same way. Step runtime, resume from the last finished step, read-step retries, `tests/` replay, hardening offers after N similar runs | Cheap, testable, resumable runs; "what if I change this step" | Durable execution P→I |
| **8. Learning** (ADR-011 L1–L2, product-direction §5.6) | The review job over run records, after a month of real data | Suggestions from patterns, stale workflows offered for retirement | Learning N→P |
| **Later** | More workers with role-based choice, which needs decision 27 (gap G7); sharing and import of skills | Multi-agent coordination | — |

**What to measure at each phase** (so "closer to the vision" is evidence, not opinion): per-workflow parity cases in `eval/parity` before the library passes ~10 workflows; runs per workflow per week and last-used from run records; suggestions accepted vs dismissed; how many workflows were made by the owner's words vs by hand. **From now, in the usage report** (§9.2): requests whose target was unclear or wrong ("make it shorter" with two things on screen, a follow-up that went to the wrong thread), as counts, never words.

### 9.2 Two additions from an outside review (2026-11-10)

A review of the README (ChatGPT, 2026-11-10) proposed much that is already built or decided (threads, mid-run redirect, artifact kinds, the four surfaces, `WorkerTask`, the memory kinds) and some that conflicts with the product rules (autonomy levels that act without a card). Two points were new and are taken:

- **Tasks that outlive a conversation.** Nothing today groups several runs under one goal or keeps it past a parked thread's 24 h. Cheap to design into run records and the store now, expensive to retrofit: a task id on every run record from phase 1. The task's own lifecycle and screen come later, with the Swift window.
- **References resolved from context, measured first.** Follow-ups are matched by phrase rules (`routing/fast.py`, `routing/rules.py`). Before building anything, the usage report counts requests whose target was unclear or wrong; daily use decides whether a fix is worth it. The direction is already decided in ADR-020 §6.1 ("A, then B where the grammar fails"); this count is what shows where the grammar fails.

The review's "intent continuity" and "unified interaction state" are ADR-020's `goal`, `intent` and `state` (§9.3).

### 9.3 How this fits ADR-020 (2026-11-10)

ADR-020 (accepted 2026-11-10) gives every request one `Conversation` record owned by the backend: `goal`, `intent`, `heard` (each utterance with its source: said, typed, clicked, agent, read), `question`, `plan`, `state` and `outcome`. It's the same foundation this audit calls run records, seen from the conversation side. Building them separately would make two owners of "what happened in this request", which is exactly the fault ADR-020 was written to remove.

**So the two become one design:**

| This audit | In ADR-020 terms |
|---|---|
| Run record | The `Conversation` record plus an append-only event log of it: steps, tool calls, approvals, artifacts, worker and why. The journal stays the side-effect part, with its rules unchanged |
| Task (§9.2) | Above conversations: a goal that several conversations serve, kept past the stack's expiry. A conversation names its task, if any |
| Installation (§6) | Unchanged: a workflow run is a conversation whose `intent` is that workflow |
| Provenance for memory and learning | `heard`'s sources. "Only the owner's words write memory" reads the same field the permission check reads: one owner, one test |
| Correction feedback (phase 8) | ADR-020 §4's weekly pass over corrections is the first review job; it proposes on a card and applies only on approval |

**Two things the owner should know:**

- **ADR-020's step 1 was dropped on 2026-11-10** because it added more lines than it removed (64 / 13), under the `CLAUDE.md` rule that structural steps delete code. Run records will face the same test. They add capability, so they delete code only if the interaction log, `Parked.said/words`, `RunScope.said/answers` and the stack's titles become views of them. If they can't, whether new capability is exempt from that rule is the owner's call, not an assumption.
- **ADR-020 revisits step 1 "if a new finding has the same cause".** Phase 1 of this roadmap is that trigger by design: building run records means building the record ADR-020 describes. The order stays as agreed (reliability, the checks 201–211, daily use, then groundwork).

### 9.1 Gaps between the first roadmap and the brief (added 2026-11-10)

A check of the first version of this roadmap against the brief found seven things it wouldn't have delivered. G1–G6 are now in the phases above. G7 waits on the owner.

| Gap | Without it | Now in |
|---|---|---|
| **G1. Workflows can't write or run things.** In a workflow run, Claude Code's Edit, Write and Bash are refused, and only Swift tools and web search can be granted | Software engineering, IT administration and most data work can't be workflows | Phase 6 |
| **G2. Too few integrations.** Swift's tools cover Gmail, Calendar, contacts, the desktop and system settings | Most of the brief's categories stay out of reach | Phase 6b |
| **G3. Workflows can't combine or depend on each other** | "Combine these two" and safe removal get retrofitted onto a store not built for them | Phases 1, 4, 5 |
| **G4. Unattended runs don't survive a restart.** Resuming came only with recipes; background runs hit the interactive watchdog and budget | Scheduled work stays short and is lost on restart | Phase 3 |
| **G5. Broken workflows aren't spotted.** "Needs attention" had no checks behind it | A workflow runs half-broken after a tool changes | Phase 6 |
| **G6. Matching doesn't scale.** It was a measurement, not a phase | Each new workflow makes routing worse, quietly | Phase 4 |
| **G7. One worker.** Multi-agent coordination needs a second worker | Decision 27 | Later, on the owner's decision |

**Two limits remain:**

- **Phases 7 and 8 depend on daily use.** Recipes and learning need weeks of real runs. Without them, those phases don't happen, and the lifecycle stays playbook-only, which is still useful.
- **Breadth comes from G1 and G2, not from the lifecycle.** The lifecycle makes workflows manageable. What a workflow can reach decides whether Swift goes beyond the workflows its developers anticipated.

## 10. How close is Swift

- **Trust and control:** close. The hardest part to retrofit is already the best part.
- **Running one workflow, interactively:** there.
- **Workflows as managed, persistent, evolving objects:** far. Roughly phases 1, 3, 4 and 5 above stand between today and the brief's lifecycle. None needs a new architecture, all need the run record and the store.
- **Breadth of workflow categories:** far, and not a lifecycle problem. It needs phases 6 and 6b (§9.1, G1 and G2).
- **Learning the owner:** furthest, and rightly last. It needs weeks of real runs that don't exist yet: the usage report shows 150 requests on 4 days, mostly testing.

**Not checked for this audit:** the test suites weren't run; the overlay's tray panel and Rust side were only skimmed for workflow features (none found); the five example workflows' recipes weren't validated; Hermes and Codex are documented, not built, so multi-worker claims come from ADRs.
