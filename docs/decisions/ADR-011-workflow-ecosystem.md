# ADR-011: A workflow ecosystem for Swift (exploration)

- **Status:** Exploration, being decided question by question (§12). Decided so far: Q1, Q2 (2026-10-26).
- **Date:** 2026-10-24
- **Builds on:** ADR-005 (connectors), ADR-007 (routing), ADR-008 (providers), ADR-010 (workflow foundations, "show me")
- **Examples:** [`docs/explorations/workflows/`](../explorations/workflows/): five workflows written in the format proposed here, to test it

## 1. Context

ADR-010 made one workflow work: emailing a contact, with Swift's own tools, a gateway, artifacts and "show me". The owner's goal is wider. Swift should be a productivity system in which workflows can be:

- **discovered** in a built-in collection;
- **created** by describing them, by configuration or in an editor;
- **learned**: Swift notices recurring behaviour and suggests or automates it, with consent;
- **modified** step by step;
- **updated** and versioned as apps and tools change;
- **deleted** and managed as a library;
- **shared** where appropriate;
- **executed** by Swift or by external agents (Claude Code, Codex, Hermes, others).

Covered tasks: email and calendar, research, files, applications, repetitive tasks, and coordinating agents.

This ADR explores how to architect that and what to adopt rather than build. It ends with a proposed order of work and the decisions the owner needs to make.

## 2. Where Swift starts from

What exists and carries over:

| Piece | From | Role in an ecosystem |
|---|---|---|
| `Executor` / `ProviderInfo`, normalized activity steps | ADR-008 | Agents as interchangeable workers |
| Routing: rules, local classifier, provider with model escalation | ADR-007 | Picking a workflow from what was said |
| `ToolHost`, `RunScope`, tools served over MCP | ADR-010 | The capability layer, and the runtime's core |
| `ActionGateway`, journal | ADR-010 | One trust boundary for every workflow and agent |
| Artifacts, `view`, mid-run voice | ADR-010 | "Show me" for any workflow, not just email |
| Interaction log (`interactions.jsonl`) | ADR-006 | The first data source for learning (§8). It has 22 entries today, so too little to learn from yet. |

What's missing:

- workflow definitions and a library;
- a runtime for multi-step runs that survive a restart;
- triggers other than voice;
- a capability registry that covers external MCP servers;
- authoring, learning and versioning.

## 3. The core idea: two forms on one spectrum, agents as workers

The question was: should workflows be **definitions Swift executes**, **capabilities external agents provide**, or a combination? The proposal is a combination, built from three separate concepts.

```
           CAPABILITIES                     WORKFLOWS                          WORKERS
 (what can be done, with what risk)   (what to do, packaged)          (who does the thinking)

 Swift tools (email, files, present)   playbook ── harden ──► recipe   Claude Code
 approved MCP servers                    (agent      (Swift runs        Codex
   (Windows connectors, n8n, ...)         follows)    the steps)        Hermes, local models
 Windows actions (open, UI Automation)            │                       ...
            │                                     ▼                        │
            └──────────────► Swift runtime: run scope, gateway, ◄──────────┘
                             artifacts, journal, triggers, "show me"
```

- **Capabilities** are tools: Swift's own, approved MCP servers, and Windows actions.
  - Swift assigns every capability a risk class: read, none (Swift-internal), reversible, external or destructive.
  - It also gives every capability a **scope**, such as "files.move from Downloads to these folders".
  - Nothing a tool says about itself is trusted (ADR-005).
- **Workflows** are packages with two possible bodies:
  - A **playbook** is plain-language instructions an agent follows, using only the capabilities the workflow declares. It is easy to write, flexible, slower and costlier, and less predictable.
  - A **recipe** is explicit steps Swift runs itself. A step is a tool call, an agent step (a bounded task with a JSON output schema), a question to the owner, or something to show. It is fast, cheap, testable and repeatable.
  - A workflow can have either body or both. **Hardening** turns a playbook into a recipe once its runs settle into a pattern (§5.3). Agents stay inside recipes only where judgment is needed.
- **Workers** are providers: Claude Code, Codex, Hermes, a local model.
  - A workflow names a **role** ("code", "review", "write", "research") and Swift picks the provider (§7.2).
  - Agents don't own workflows. A workflow written for Claude Code runs on Codex unchanged.

Why not the alternatives on their own:

| Option | Why not alone |
|---|---|
| Workflows **only** as Swift definitions | Every new task needs a recipe written first. That loses agents' strength on fuzzy tasks, and the library grows slowly. |
| Workflows **only** as agent capabilities (skills or prompts the agent runs) | No determinism, testing or cost control. Approvals and "show me" depend on each agent's own UI. Swift becomes a voice front end to someone else's system. |
| **Combination** (proposed) | Playbooks give breadth on day one. Recipes give reliability where it matters. Swift keeps one trust boundary and one "show me" across both. |

## 4. The package format

### 4.1 Proposal: an Agent Skill plus Swift's manifest

A workflow is a folder:

```
tidy-downloads/
├── SKILL.md       # the playbook, in the Agent Skills format: any skills-capable agent can use it
├── swift.yaml     # Swift's manifest: triggers, inputs, settings, needs (capabilities + scope), shows, version
├── recipe.yaml    # optional: the hardened steps Swift runs
└── tests/         # optional: example runs with fake tools
```

**Why Agent Skills for the playbook.**
- It is an open format (`agentskills.io`): a `SKILL.md` with YAML front matter (`name`, `description`, optional `license`, `compatibility`, `metadata`, and an experimental `allowed-tools`) plus optional `scripts/`, `references/` and `assets/`.
- Agents load skills progressively: only the name and description at first, then the whole body when the skill is used.
- Claude Code supports it. Codex documents skills built on the same standard and uses plugins to distribute them. Hermes creates and uses skills in this format (`docs/spikes/hermes-agent.md`).
- So a Swift workflow's playbook is also a working skill for each of these agents, and the large existing collections of skills become importable starting points.

**Why a separate `swift.yaml`.** Agent Skills deliberately say nothing about:
- triggers;
- typed inputs;
- scoped permissions (`allowed-tools` is experimental and unscoped);
- risk;
- versions;
- what the workflow shows.

Swift needs all of these. The spec's `metadata` is a map of strings, too thin for this, so it carries only a pointer: `swift-manifest: swift.yaml`.

**Alternatives considered:**
- **Only `SKILL.md`, with Swift fields in `metadata`.** Strings only: no structure for inputs or scopes.
- **n8n's workflow JSON.** Rich, but tied to n8n's node types. It isn't readable as instructions by an agent.
- **CNCF Serverless Workflow DSL (1.0) as the recipe language.** A real, versioned standard for steps, branches, loops and waits. It is worth reusing in part. On its own it is built for service orchestration and has no notion of agent steps, artifacts or owner approval.
- **Arazzo (OpenAPI).** Sequences of API calls; too narrow.
- **Recipes as Python code.** The most powerful, but a workflow becomes untrusted code (T13). It can't be shown, checked or edited by voice, and can't be shared safely.

### 4.2 The manifest (`swift.yaml`, sketch)

| Field | Meaning |
|---|---|
| `schema`, `name`, `version` | Format version; the name matches the folder; semantic version of the workflow |
| `triggers` | `say` phrases with slots (`"email {person} {message}"`), `schedule` (cron, with `notify` vs `act`), later `event` (a file appears, a calendar event starts) |
| `inputs`, `settings` | Typed: `text`, `choice`, `contact`, `folder`, `project`, `date`. Inputs come per run; settings are per-owner defaults. |
| `needs` | Capabilities plus scope. This is the permission list shown when installing or enabling. |
| `run` | `recipe`, `playbook`, or both (recipe first, playbook as fallback); `provider` or `role` preference; `budget` (minutes, cost) |
| `shows` | Artifact kinds it produces, so "show me" knows what to expect |
| `undo` | Whether reversible steps can be undone ("undo that") |
| `history` | Short changelog per version (§6.5) |

### 4.3 The recipe language (`recipe.yaml`, sketch)

Step kinds:
- `tool`: a capability call; the gateway applies its risk.
- `agent`: a bounded task with `input`, `tools` (often none), `output_schema` and `model`.
- `ask`: approve/reject, or a choice.
- `show`: an artifact.
- `let`, `when`, `for_each`, `finish`.

Outputs are referenced as `${steps.<id>.out}`.

## 5. Creating workflows

### 5.1 By describing them (first)

"Swift, every Friday at six, summarise the lecture notes I added this week."

1. An agent drafts the package: a `SKILL.md`, and a `swift.yaml` with the trigger, settings and needs.
2. Swift shows it as an artifact: the plain-language steps, **the permissions it asks for**, and the trigger.
3. The owner says "save it" or "change the time to five". Edits by voice are re-drafts, and the old version is kept.
4. A first **dry run** uses read-only tools for real and shows planned side effects instead of doing them. Then the workflow is enabled.

### 5.2 By file, then by editor

- The format is plain text in a folder, so editing files in VS Code works from the start. Swift validates the files on load (§6.5).
- A visual editor comes last, if ever.
  - The overlay's 720 × 560 window is the wrong place for one.
  - A separate window, or a page Swift opens in the browser, could show the steps, permissions and history, and edit a recipe as a list rather than a graph.
  - n8n-style graphs suit integrations people build once. Personal workflows are mostly short lists.

### 5.3 Hardening: from playbook to recipe

1. A playbook runs. Swift's run scope already records each tool call, its arguments, the artifacts and the approvals, as ADR-010 does for email.
2. After **N similar runs** (proposed: 3), Swift offers: "This went the same way three times. Make it faster and cheaper?"
3. An agent writes a recipe from the recorded runs:
   - deterministic steps become `tool` steps;
   - places where the runs differed become `agent` steps with an output schema;
   - the recorded runs become `tests/`.
4. The owner sees the recipe and a side-by-side replay on the recorded inputs. On approval, the recipe becomes the default and the playbook stays as the fallback.
5. If a recipe step fails because a tool changed or an input is unexpected, the run can **fall back to the playbook** from that point, asking first. The failure is flagged for repair (§6.5).

This is the most distinctive part of the design. Neither agent frameworks nor automation tools do it end to end. It is also where most of the engineering risk is (§10).

## 6. The library

### 6.1 Where workflows live

| Layer | Path | Notes |
|---|---|---|
| Built-in | `src/swift/workflows/library/` | Shipped with Swift, read-only, updated with Swift |
| The owner's own | `%APPDATA%\Swift\workflows\` | A git repository Swift commits to on every change, so history and undo are free |
| Installed from elsewhere | `%APPDATA%\Swift\workflows\installed\<source>\` | Pinned to a version; see §6.6 |

### 6.2 Discovering

- **By voice:** "what can you do with files?", "what workflows do I have?". Swift searches names and descriptions. These are the same ~100-token summaries skills use, so this is cheap.
- **Routing:** the router (ADR-007) gains a step between rules and the provider: match the request against workflow triggers and descriptions.
  - A slot match ("email Ada …") runs the workflow directly.
  - A description match is offered: "I have a workflow for that: Tidy my downloads. Use it?"
- **Tray:** a "Workflows" list with on/off toggles and last run.

### 6.3 Modifying

- "Change the digest to Sunday", "don't touch installers": an agent edits the package, and Swift shows the diff in plain words plus any **permission changes**.
- A permission that grows ("now also reads Documents") always needs explicit approval, and is shown first.

### 6.4 Deleting

- Disable, which keeps it, or delete.
- Deleted workflows stay in git history: "bring back the downloads one" works.

### 6.5 Versions and maintenance

- Semantic versions:
  - patch: wording;
  - minor: steps that don't widen permissions;
  - major: new permissions or changed inputs.
- **Health checks on load and after updates:**
  - the manifest validates;
  - every capability in `needs` exists with a compatible version (MCP servers report their tools, and schema drift is detected);
  - every provider role can be filled;
  - `tests/` replay with fake tools.
- A failing workflow is marked "needs attention" and never runs half-broken.
- **Pins:** an installed workflow pins its source version. Updates show the changelog and the permission diff before applying.

### 6.6 Sharing

- **Safe to share:** playbooks and recipes over approved capabilities. They are data, not code.
- **Not safe:** `scripts/` inside a skill, which is code from someone else (T13), and MCP servers that aren't installed.
  - Proposed: Swift ignores `scripts/` in installed workflows.
  - A new MCP server needs its own approval through the capability allowlist (§7.1). That is ADR-005's Phase 7 plugin host.
- **Sources:** a folder, a git URL, later a curated index. Importing an Agent Skill from any of the existing skill collections makes a playbook-only workflow with an empty `swift.yaml`, filled in by asking the owner which permissions to grant.

## 7. Capabilities and external tools

### 7.1 Capability registry

One registry for everything a workflow can use:

- **Swift's own tools** (`ToolHost`).
- **Approved MCP servers.** Each needs:
  - an entry in an allowlist with Swift-assigned risk per tool and a scope template;
  - pinning;
  - outputs treated as untrusted.

  Candidates:
  - **Windows' own agent connectors.** Windows has an on-device registry of MCP servers ("agent connectors"), with built-in File Explorer and System Settings connectors in preview (Microsoft Learn, "MCP on Windows"). Swift could become a client of that registry instead of writing its own file tools. It is preview, so verify before relying on it.
  - **n8n**, through its MCP Server Trigger, which exposes an n8n workflow as tools. That gives access to its hundreds of integrations without making n8n Swift's runtime (§9).
  - Community MCP servers, case by case.
- **Windows actions:** opening apps (already in `routing/local.py`) and UI Automation for apps without an API. UI Automation is brittle, so it is last in preference and always behind confirmation for anything but reading.

### 7.2 Agents as workers

- Agent steps name a `role` and optionally a `provider`.
- Swift's `Providers` set (ADR-008) chooses, using `ProviderInfo.capabilities`, availability, cost, and the owner's preferences per role.
- A step can require "a different provider than step X" (the second-opinion example).
- Every provider reaches Swift's tools over MCP:
  - in-process for Claude Code;
  - over the loopback HTTP server for Codex and Hermes (ADR-010 §3.3, phase B).
- Their own side effects still meet a confirm card: Claude Code's `can_use_tool`, Codex's approval requests, Hermes' approval events.
- **One limit to note:** Swift runs Claude Code with `setting_sources=[]`, so Claude Code won't load skills from disk itself. That is deliberate (ADR-006). Swift chooses the workflow and passes the playbook's text in the request, which keeps the selection in Swift's hands and gives every provider the same behaviour.

### 7.3 Data flowing between steps (prompt injection)

The examples kept hitting the same pattern: an agent step that reads untrusted content (web pages, slides, emails) should get **no tools** in that step.

Proposed runtime rules:
- Outputs from untrusted sources are **tainted**.
- An agent step with tainted input may not call side-effecting tools.
- Targets of external actions (recipients, folders) must come from the owner, from settings, or from untainted steps. This extends ADR-010's resolved-recipient rule to every workflow (threat model T1).

## 8. Learning and adapting

Levels, each a separate opt-in:

| Level | Source | Example | Privacy cost |
|---|---|---|---|
| L0 | Nothing: the owner asks | "Make that a workflow" after a run | None |
| L1 | Swift's own interaction log | "You've asked for the lecture digest three Fridays running. Schedule it?" | Low: data Swift already keeps locally |
| L2 | Run records of workflows | Hardening (§5.3); "you always change the subject line; update the template?" | Low |
| L3 | Observing the desktop (app usage, files, possibly screen) | "You copy this report into Excel every Monday" | High: a separate decision; comparable products (Microsoft Recall, task-mining tools) drew strong privacy concerns |

Rules for every level:
- Suggestions only, never silent automation.
- At most one suggestion a day.
- "Stop suggesting this" is permanent.
- Everything is computed locally.

L1 needs embeddings of past requests to group similar ones. ADR-007's local classifier already has a sentence model that could do this. With 22 logged interactions today, L1 is a later feature: the data has to accumulate first.

## 9. Build or adopt the runtime

| Option | For | Against | Verdict |
|---|---|---|---|
| **Thin runtime in Swift** (extend ADR-010) | Fits voice, approvals, artifacts and "show me"; no new services; small | Durability, scheduling and retries are Swift's to build | **Proposed**, kept small |
| **n8n as the runtime** | Mature editor, hundreds of integrations, AI and MCP nodes, self-hostable | A second runtime with its own permission model, as with Hermes. Node service plus database. Sustainable Use License, which is fair-code, not OSI open source; fine for personal use, but read before shipping. Not voice-first; no Swift gateway in front of its actions. | **Adopt as a capability** through MCP, not as the runtime |
| **Temporal** (durable execution) | Solves durability, retries and long waits properly | Server cluster for one desktop user | Borrow the ideas (event-sourced run log, deterministic replay); not the dependency |
| **LangGraph / CrewAI / agent SDK graphs** | Agent graphs, checkpoints | Developer frameworks; would wrap one provider's way of running agents; Swift already abstracts providers | Not needed |
| **Power Automate Desktop** | Windows UI automation, ships with Windows | Microsoft account and cloud flows; hard to drive programmatically | Maybe as a capability later; not now |

What "thin" means:

- **Run records.** The journal grows into an append-only event log per run: step started, step output, approval, artifact. A run can then resume after a restart from its last finished step. Side-effecting steps are never re-run unless their journal entry says they didn't happen. This is the T10 rule, generalized.
- **Scheduling.** A scheduler in the Swift process for `schedule` triggers. It only runs while Swift runs; missed runs are offered on next start. A Windows Task Scheduler entry that starts Swift is an option for later.
- **Expressions.** Writing the examples showed recipe expressions growing toward a programming language: list comprehensions in `tidy-downloads`, fallbacks in `email-someone`. Pick a small, sandboxed, existing language (candidates: CEL or JSONata) rather than inventing one. Anything more complex becomes an agent step or a reviewed Swift tool.
  - YAML and `${...}` mix badly: one example failed to parse until its expressions were quoted, and others parse only by luck. Recipes therefore need a validator with clear errors (W1), and a voice or editor front end, so the owner rarely edits them by hand.

## 10. Prior art and gaps

| Area | Examples | Borrow | Gap Swift fills |
|---|---|---|---|
| Tool protocol | MCP | Capability plumbing; every target provider speaks it | Risk, scope and approval per capability |
| Playbooks | Agent Skills (Claude Code, Codex, Hermes, others) | The playbook format, progressive loading, existing skill libraries | Triggers, typed inputs, scoped permissions, versions, determinism |
| Automation platforms | n8n, Zapier, Make, Node-RED, Power Automate | Integrations (via MCP), editor ideas, trigger types | Voice-first, local-first, one approval layer, agent steps as first-class |
| Durable execution | Temporal, Prefect | Event log, replay, retries | Lightweight for one desktop user |
| Agent orchestration | LangGraph, CrewAI, agent SDKs | Roles, hand-offs | Provider-neutral, end-user facing |
| Personal automation | Apple Shortcuts and App Intents, Raycast and Alfred, Home Assistant blueprints | Shareable recipes, apps exposing actions, voice triggers | Windows; agent steps; learning |
| Windows platform | MCP on Windows, agent connectors (preview) | Built-in file and settings connectors, app-exposed actions | Still preview; Swift can be a client |
| Workflow formats | Serverless Workflow DSL 1.0, Arazzo 1.0.x, GitHub Actions | Step semantics, versioned schemas, reusable-workflow pinning | Agent steps, artifacts, owner approval |
| Learning | Task mining, Recall, demonstration recording | Turning demonstrations into steps | Consent-first, local, suggestion-only |

**What nobody combines, and is Swift's reason to exist:**
- voice as the front door;
- one trust boundary and one "show me" across every agent and tool;
- local-first on Windows;
- the path from playbook to recipe, with consent.

**Open problems:**
1. **Hardening quality.** Recovering the right steps and the right places for agent judgment from a few runs. Mitigated by showing the recipe, replaying the recorded inputs, and keeping the playbook as fallback.
2. **Brittleness.** UI Automation and changing third-party APIs. Mitigated by preferring MCP and APIs, by health checks, and by falling back to the playbook.
3. **Workflow sprawl.** A suggestion engine plus easy creation means many half-used workflows. Track last-used dates and offer to archive.
4. **Cost.** Playbooks call models every time; hardening is the cost control. Budgets per workflow cap runaway runs.
5. **Trigger ambiguity.** Many workflows with similar descriptions make routing harder. Slots and explicit names first; descriptions only as offers.

## 11. Proposed order of work

Each phase is small enough to use before the next, and each needs the owner's go-ahead.

| Phase | Scope | Useful on its own because |
|---|---|---|
| **W1: library and playbooks** | Package loader and validator; built-in `email-someone` and `research-brief` as playbooks; workflow matching in the router; Swift passes the playbook to the provider; "what workflows do I have?" | Workflows become a thing the owner can list, ask for and edit as files |
| **W2: capabilities** | Capability registry with scopes; files tools (list, read, move with undo) built in or via the Windows File Explorer connector; taint rule (§7.3) | `tidy-downloads` and `lecture-digest` become possible safely |
| **W3: recipes** | Recipe runtime (steps, agent steps with schemas, `ask` with choices, `show`); run event log and resume; tests replay | Fast, cheap, testable workflows; hand-written recipes work |
| **W4: creating by voice** | Draft, show, save; dry run; edits as re-drafts with permission diffs; git-backed history | The owner creates workflows without files |
| **W5: schedules and hardening** | Scheduler; hardening offers after N runs; fallback to playbook | Workflows improve themselves with consent |
| **W6: more workers and integrations** | ADR-010 phase B/C (Codex, Hermes) over loopback MCP; role-based provider choice; n8n via MCP as an optional capability source | `second-opinion`; access to n8n's integrations |
| Later | L1 learning; sharing and import from skill collections; an editor window | Once there is enough history and enough workflows to manage |

## 12. Questions for the owner

1. **The model:** playbooks and recipes as two forms of one workflow, agents as role-based workers, and Swift owning the runtime and trust boundary. Is this the direction?
   - **Decided 2026-10-26 (owner): yes, option A**, built in the order B → A: W1 playbooks first (behaving like option B), desktop D1–D2 alongside (ADR-012), recipes (W3) once there are playbooks or desktop tasks worth hardening. The ADR-012 probe supported this: most of the owner's apps can be operated precisely through their structure, which suits recipe steps, while WhatsApp, PowerPoint slides and VS Code's editor still need agent judgment.
2. **Format:** Agent Skills plus `swift.yaml`, so playbooks also work directly in Claude Code, Codex and Hermes?
   - **Decided 2026-10-26 (owner): yes.** A workflow is a folder with `SKILL.md` (Agent Skills format), `swift.yaml` (triggers, inputs, scoped permissions, version, what it shows), and optionally `recipe.yaml` and `tests/` (§4). Swift drafts these files when the owner describes a workflow; hand-editing is the exception.
3. **Runtime:** a thin runtime in Swift, with n8n reachable as an optional capability over MCP rather than as the engine? Or would you like a short n8n trial first, installing it locally and exposing one workflow over MCP to Swift, before deciding?
4. **Learning:** L0 to L2 only, with desktop observation (L3) out of scope unless decided separately?
5. **Sharing:** playbooks and recipes only, never bundled scripts, until there's a plugin host with an allowlist (ADR-005 Phase 7)?
6. **Which first workflows matter to you?** The five examples are guesses from the repo (lectures, downloads, email, coding). The real list should come from your week.

## Sources checked (2026-10-24)

- Agent Skills specification: agentskills.io/specification
- Codex skills: developers.openai.com/codex/skills
- MCP on Windows and agent connectors: learn.microsoft.com/windows/ai/mcp/overview; developer.microsoft.com/windows/agentic (preview)
- n8n MCP Server Trigger and license: secondary sources; check n8n's own docs and `LICENSE.md` before any trial
- Serverless Workflow DSL 1.0 (CNCF) and Arazzo 1.0.1 (spec.openapis.org/arazzo/v1.0)
- Hermes: docs/spikes/hermes-agent.md; hermes-agent.nousresearch.com (API server, MCP)
