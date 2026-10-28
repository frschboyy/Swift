# Swift: product direction (assessment, 2026-10-28)

The owner asked for a critical look at Swift as a product, not only as code: what makes it different, what to build next, what to drop, how it should adapt to its user and be configured, and whether it needs a dashboard. This document answers from the code on `main` (`32ec68b`), the ADRs, and the owner's own interaction log (counts only, no transcripts).

It is a proposal. Nothing here changes the agreed order in the handoff until the owner says so.

## 0. The short answer

- **Today Swift is a careful shell around one agent.** Everything that needs a model goes through Claude Code, including the light lane. Swift's own value is everything around that: local speech, instant local lanes, the dialogue, the approval and undo rules, presence, several requests at once. That shell is real and good work. On its own it is not a reason for someone to choose Swift over Copilot.
- **Voice is not the differentiator.** Copilot has a wake phrase, voice, screen vision and an agent. Matching Siri or Copilot feature by feature (ADR-016's framing) is a race Swift can't win and shouldn't run.
- **What can make Swift different** is being *the owner's own operator*: it does the owner's recurring work (watchers, recipes), under rules the owner sets and can inspect, with any agent behind it, and it gets better at that owner's work over time, with everything about the owner kept on the PC. None of the big assistants offers this combination, because their business is their own model and cloud.
- **The evidence says Swift hasn't been used for real yet.** 332 logged interactions over 6 days, 236 of them on one owner-check day. Before adding breadth, Swift needs a few weeks of daily use with numbers (§9).
- **Next:** finish the owner checks, then build the substrate that every differentiator needs: a Swift-owned run history, memory and settings store, and a worker contract that isn't Claude-shaped. Then watchers and recipes for the owner's own workflows, then one Settings and Activity window. Defer screen vision, the phone, voice ID, offline and parity polish.

## 1. What exists today (audit)

### 1.1 Built, on `main`

| Area | What is built | Where |
|---|---|---|
| Input | Wake phrase (openWakeWord), hotkey, typing; local STT (parakeet) with learned word fixes and the 7-day recordings loop | `wake.py`, `stt/`, `audio/` |
| Routing | Tier 1 rules; fast lane (time, dates, units, maths, spelling); system lane (timers, volume, display, radios, windows, lock…); light lane; a local embedding classifier for demand (light or standard) | `routing/`, `system/` |
| Agent | Claude Code over the Agent SDK, with a pre-started spare, model escalation (Haiku → Sonnet → Opus), confirm cards on Edit/Write/Bash, settings files ignored | `executors/claude_code.py` |
| Swift's own tools | An in-process MCP server: contacts, `ask_owner`, email drafts, send, calendar (look, add, change, remove, Meet), desktop (context, write in Word/Gmail/Outlook, open), present, undo | `workflows/tools.py`, `calendar.py`, `desktop_tools.py` |
| Trust | The action gateway (validate, resolve recipients from contacts, policy, confirm bound to a digest, journal, verify, audit), undo, the product rules | `security/` |
| Attention | Up to 3 requests, the waiting stack, held cards while away, presence (locked, asleep, idle), parked threads for 24 h | `attention.py`, `presence.py`, `parked.py`, `stack.py` |
| Dialogue | Slot questions, carry-over, end of speech, `ask_owner`, confirm cards read aloud | `dialogue.py`, `endpoint.py` |
| Workflows | Packages (`SKILL.md` + `swift.yaml`), trigger phrases and intents, grants per run. Three built in: `calendar-event`, `email-draft`, `research-into-word` | `workflows/library.py` |
| Overlay | The Capsule, cards, live view, follows Windows' dark or light theme, tray menu | `overlay/` |
| History | `interactions.jsonl` (full, local), the action journal (metadata only), `swift.log` (redacted) | `runlog.py`, `security/journal.py` |

Size: about 21,000 lines of Python, of which `session.py` is 4,401 (21%). Tests: 1272 Python, 78 overlay, 29 Rust.

### 1.2 Partly there

- **Several providers.** `Providers` holds an ordered list and falls back when one is unavailable. `ProviderInfo.capabilities` exists, but **nothing reads it to choose**. The only choice is a workflow's `provider:` field (`session.py:2530`). `backend/__main__.py` builds exactly one executor from `executor.kind`. So multi-agent is an interface, not a behaviour.
- **Model choice.** Real and dynamic, but inside Claude Code only: demand picks the starting model, escalation moves up mid-run.
- **Memory.** Only fragments: learned word fixes, approved demand examples, the previous exchange prepended to a follow-up (`session.py:4252`), parked threads (24 h), contacts typed into `config.yaml`. No store of the owner's preferences, no long-term recall.
- **Settings.** `config.yaml` (hand-edited, "Settings (config.yaml)" in the tray opens it) and `overlay.json` (position, smart placement). Swift never writes `config.yaml`. No settings screen. Theme follows Windows; no override, no text size, no contrast setting.

### 1.3 Proposed only (ADRs, not code)

Watchers and digests, recipes, a scheduler for workflows (the system scheduler exists for timers only), notifications at rest, the web lane, file tools with permissions (W2), learning levels L1–L3 (ADR-011 §8), a personal index, screen awareness, quiet modes and call detection, offline, voice ID, the phone companion, a connector host, other providers.

### 1.4 What the usage log says

From `%LOCALAPPDATA%\Swift\interactions.jsonl` (counts only):

| Measure | Value |
|---|---|
| Interactions logged | 332, over 6 days (2026-10-23 to 28) |
| On the busiest day | 236 (2026-10-27, an owner-check day) |
| Sent to the agent | 65% (217) |
| Answered by Swift locally (fast, system, control) | 25% (83) |
| Agent run, median, press to result | 13.6 s |
| Local answer, median | 2.9 s |
| Not done (error, rejected, cancelled) | 22% (73) |
| Agent cost, all runs | $2.43 |

Read honestly: almost all of this is testing. There is no evidence yet of which features the owner reaches for on an ordinary day, and that is the most important missing input to every question below.

## 2. Does Swift have a reason to exist?

### 2.1 What the others already do

Checked against what each offered as of mid-2026; details change fast, so treat specifics as approximate.

| Product | Strong at | Weak at, for this owner |
|---|---|---|
| **Copilot on Windows** | Wake phrase, voice, screen vision, Copilot Actions (agentic, step-by-step view), connectors (Outlook, OneDrive, Gmail, Google Calendar and Contacts), taskbar search | Cloud-only voice and vision; Microsoft's model only; no owner-defined rules for what may act; no recurring workflows the owner owns; little memory the owner can inspect and edit |
| **ChatGPT / Claude desktop apps** | Best-in-class models, voice mode, connectors and MCP, scheduled tasks, agent modes, project memory | A chat window, not part of the desktop; one vendor's model; approvals are per-app, not the owner's policy |
| **Claude Code, Codex and similar** | Real work on files and code, tools, subagents | Developer tools; no voice, no presence, no everyday lane, no consumer trust model |
| **Personal-agent projects** (Hermes Agent, OpenClaw-style assistants) | Memory, self-written skills, messaging channels, scheduled jobs | Broad permissions by default, weak approval models, little desktop integration |
| **Voice Access, Windows settings** | Dictation and control, offline | No intelligence, no tasks |

### 2.2 What is commodity, and what isn't

**Commodity, don't compete on it:** chat, a voice front end, "explain what's on my screen", generic agentic tasks, generic connectors. Copilot and the chat apps will always be ahead on these, for free, with better models.

**Swift's real candidates, from what it already has:**

1. **Trust you can set and inspect.** Recipients only from contacts, a bare "yes" never approving, typing never approving, a digest-bound card, a journal, undo, nothing written into an app unless asked. These are the owner's rules, enforced by Swift, whatever agent is working. Nobody else lets the user own this layer. This is the strongest asset in the codebase.
2. **Local first.** Audio never leaves the PC, a quarter of requests never touch a model, logs are content-free. Copilot is the opposite by design.
3. **Attention.** Requests side by side, cards held while away, unfinished conversations kept. This is what makes an assistant you leave running, rather than one you open.
4. **The owner's own work.** Five of the owner's eleven workflows (ADR-011 §13) are watchers: boss emails, news, opportunities, offers, lectures. No assistant does those well today, because they need standing permission, memory between runs, and a trustworthy way to interrupt.

None of these is a feature someone would switch for on day one. Together, aimed at recurring work, they are a product: **an operator on your PC that does your recurring work, under your rules, with whichever agent is best, and learns how you like it done.**

### 2.3 Are we assembling existing tools behind another interface?

Partly, yes, and that is fine if the right part is Swift's. A browser is built on web engines; what users choose is the browser. Swift's mistake would be to spend its effort where the agent already is good (reasoning, research, editing) or where the platform owner is good (screen vision, OS voice). Its effort belongs in what no agent vendor will build for one person: the policy, the memory, the recurring work, the attention, all owned locally.

The test (§9): if Claude Code were swapped for another agent tomorrow, the owner should notice a change in quality, but nothing about their rules, history, memory, workflows or habits should be lost.

## 3. The remaining roadmap, assessed

| Item (handoff §4 and ADR-016) | Verdict | Why |
|---|---|---|
| Owner checks 50–116 and fixes | **Essential, now** | Nothing since the audit has been run on the real PC |
| ADR-014 L3: quiet modes, call detection | **Essential, small** | Required before Swift ever speaks or interrupts unprompted |
| Watchers and digests (ADR-011 §13.3) + notifications at rest | **Core, highest impact** | Half the owner's workflows; the clearest gap in other products |
| W3 recipes (fixed-step workflows) | **Core, redesigned** | Build them from recorded runs ("do that again every Friday"), not hand-written YAML; ADR-011 §9 already found the expression language growing |
| W2 file tools with permissions | **Core** | Files are a top owner workflow and where a PC beats a phone |
| A Swift-owned run history, memory and settings store | **New, essential** | Every item above needs it; see §4.4, §5, §7 |
| Proactive Swift (ADR-016 D) | **Core, after watchers** | The same engine as watchers; start with the owner's top two (decision 22) |
| The web lane (weather, news, "open now") | **Incremental** | Parity; fixes the 10 misses. Do the cheap version (one search tool) when it is in the way, not as a phase |
| ADR-012 D3: Word, Explorer, Chrome/Gmail | **Incremental, selective** | Only the adapters the owner's workflows call for; a Chrome extension for Gmail web is likely the one that matters |
| Other providers (Codex, Hermes) | **Redesign** | Not for their own sake. Make the worker contract neutral now (§4.4); add a second worker when a task needs one (a cheap or local model for the light lane, an API research agent for watchers) |
| Personal index (ADR-016 §6.1) | **Defer, scope down** | Useful for adaptation; start with Swift's own history and journal, not mail and folders |
| ADR-016 F screen awareness; ADR-012 D4/D5 vision | **Defer or drop** | Copilot's ground; D5 breaks the local-first promise |
| Offline with Ollama | **Defer** | Low value while real work needs a strong model |
| Voice ID, phone companion | **Drop for now** | Large, and not what makes Swift different |
| Messaging, smart home connectors | **Defer** | Until a watcher or recipe needs one |
| Timer pause and resume, stopwatch, repeating reminders | **Distraction for now** | Parity polish; do them on request |
| Splitting `session.py` | **Essential, ongoing** | 21% of the code in one file is the main risk to everything above |

## 4. Swift's architecture, and how independent it is

### 4.1 What Swift is

**Both, unevenly.** Swift is a user-facing assistant with its own local intelligence (rules, classifier, fast and system lanes, dialogue) and its own execution shell (tools, gateway, journal, attention, workflows). For anything needing a language model it delegates to one agent, and today that is always Claude Code:

```
 owner ──voice/typing──▶ input (wake, local STT, endpointing)
                           │
                           ▼
                    router: rules → fast → system → light → classifier → agent
                     │          │         │          │                    │
                Swift itself (no model)          one model call     a worker run
                                                 (via Claude Code)   (Claude Code)
                                                                          │
              Swift's tool host (MCP) ◀── tool calls ─────────────────────┘
                 │
                 ▼
              gateway: resolve → policy → confirm card → journal → do → verify → undo
                 │
              connectors (Gmail, Google Calendar, Contacts), desktop (Word, Outlook, UIA)

 alongside every run: dialogue, attention (presence, held cards, stack), parked threads, overlay protocol
```

### 4.2 What happens with several agents connected, today

- The session starts each agent run with `Providers.start`, which takes the first executor that is available. A workflow can prefer one (`provider:` in `swift.yaml`).
- The overlay already names whoever works ("Claude Code is reading"), and the protocol carries `agent` on every step, so the experience would stay consistent.
- Swift's tools are an MCP server, so any MCP-capable agent gets the same contacts, drafts, calendar and gateway, with the same approvals.
- Provider-native tools are not neutral. Claude Code's Edit/Write/Bash approvals go through its own `can_use_tool` hook; another agent's file or shell tools would need their own interception, or must be turned off so that only Swift's tools act.
- A run never moves between providers (ADR-008 §4), which is right: a half-finished run may have changed things.

### 4.3 How Swift decides, and what it can't yet

| Signal | Used today? |
|---|---|
| Task complexity | Yes, inside Claude Code: demand classifier + escalation |
| Capabilities | Declared on `ProviderInfo`, never read |
| Latency | Only by lane (local before model) |
| Cost | Only by model tier; a budget cap per run |
| Privacy | No. Every model request goes to Anthropic's cloud |
| Owner preference | Only "use opus" and a workflow's `provider` |

### 4.4 What must belong to Swift, and the change to make now

For agents to be replaceable workers, Swift has to own:

1. **Identity and conversation.** Already (ADR-008).
2. **Policy, approvals, journal, undo.** Already, for Swift's tools. Make it the only way to act: workers that bring their own side-effecting tools get them off, or intercepted.
3. **Tools and connectors.** Already an MCP host. Keep every new capability (files W2, watchers, the web) there, not in a worker's prompt.
4. **Context.** Partly: the previous exchange and parked threads are Swift's text, prepended to the request. Make it a structured *context pack* that Swift assembles (thread, relevant memory, desktop context) and any worker receives.
5. **Memory, preferences, run history.** Not yet (§5).
6. **Workflows and their run records.** Packages are Swift's; runs are only logged. Make runs replayable (§7).
7. **Choosing the worker.** A small policy table, not a model:

   | Order | Rule |
   |---|---|
   | 1 | The request's privacy class (local-only data, e.g. a file the owner marked) rules out cloud workers |
   | 2 | The capabilities the plan needs (files, shell, web, long run) filter workers |
   | 3 | The owner's preference for this kind of task ("research with X") |
   | 4 | Then demand, latency and cost pick the model |

   The choice is logged with its reason, so "why did you use that?" has an answer.

**The change now:** a `WorkerTask` that every executor takes (request, context pack, grant, budget, privacy class) instead of the current `start(request, demand, override)`, and a contract test that runs the same task suite against the mock executor and Claude Code. This is cheap while there is one real provider and expensive after a second one exists.

## 5. How Swift adapts to its owner

### 5.1 The pattern Swift already has

Two pieces already adapt well: learned word fixes and approved demand examples. Both follow the same steps: Swift notices, proposes on a card, the owner approves, and the result is a plain record the owner can see and remove. Make that the rule for every kind of learning.

### 5.2 Four kinds of memory, kept apart

| Kind | Example | Lifetime | Source | Exists? |
|---|---|---|---|---|
| **Now** | "the second one", "make it four" | minutes | the conversation | Yes (dialogue, previous exchange) |
| **Unfinished** | the email to Ada left half done | days | parked threads | Yes, 24 h; extend, with a cap |
| **Preferences and facts** | "sign emails 'Best, Francis'", "drafts go in Word", "my manager is Janet", "speak less" | until changed | **said** by the owner, or **approved** from a suggestion | No |
| **Patterns** | "asks for tech news most mornings", "always moves the meeting card to 3 pm" | decays when unused | counted from the interaction log and run records | No |

Rules that keep them apart:

- **Temporary vs lasting** is decided by the owner's words: "for now", "today", "this time" are temporary; "from now on", "always", "never" are lasting. Ambiguous means temporary, with at most one "Should I remember that?".
- **Patterns never act.** They only produce suggestions, at most one a day (ADR-011 §8). "Stop suggesting this" is permanent.
- **A correction is evidence, not a rule.** The same correction twice becomes a suggestion: "You've changed the sign-off twice. Always use 'Best, Francis'?"
- **Nothing learned can widen autonomy.** Learning may change what Swift proposes, never what it may do without asking. Approval rules change only in settings, by the owner.
- **No inferences about sensitive things** (health, money, relationships, politics), and none about other people beyond what contacts hold.

### 5.3 Coming back after hours or days

Presence already knows when the owner was away and for how long. On return after a long gap, one short card: what waited (held cards, the stack), what watchers found, the one unfinished thing worth picking up. Today the stack and the "Unfinished" line do parts of this; they should merge into one "while you were away", sized to the gap, so that Swift doesn't greet a return with three separate offers.

### 5.4 Continuity across agents without oversharing

- Memory lives in Swift, in plain local files the owner can read: never in a provider's memory feature.
- A worker gets a **context pack**: only the memories that match the request (by the classifier's sentence model, already on the PC), redacted like the logs. Never the whole profile.
- Every memory has a source ("you said, 28 Oct", "you approved, 2 Nov") and a last-used date. "What do you know about me?", "forget that", "forget everything about Ada" work by voice and in settings.
- Retention per kind: patterns decay, unfinished threads expire, preferences stay until changed.

## 6. Configuring Swift

### 6.1 Where settings live

Today a setting is either in `config.yaml` (owner's file, Swift never writes it) or in `overlay.json`. To change settings by voice or from a screen, Swift needs its own store: **defaults → config.yaml (advanced, wins when set) → Swift's settings (written by voice and the settings window)**, with the settings window showing when `config.yaml` overrides something. This is the second piece of groundwork, with memory.

### 6.2 What is worth configuring

Grouped by what the owner thinks about, not by module:

| Group | Settings |
|---|---|
| **Look and read** | Dark, light or follow Windows; text size; high contrast (respect Windows' contrast themes first); reduced motion; card position; how long cards wait (decision 3) |
| **Listening and speaking** | Wake phrase on or off; follow-up window; read answers aloud: never, when spoken to, always; voice and speed; how much Swift says (short, normal, detailed); what interrupts Swift; quiet hours and calls (L3) |
| **What Swift may do** | Per kind of action: do it, ask first, never (sending, calendar changes, writing in apps, files, system changes); which folders; spending cap per day; which apps Swift may write in |
| **Agents and models** | Which worker for which kind of task, default model, "ask before using the strongest model" |
| **Workflows and automations** | List, run once to test, pause, resume, edit inputs, see each run, delete; suggestions Swift made, with accept, change, reject |
| **What Swift knows** | Preferences, patterns, contacts, unfinished conversations; edit and forget each |
| **Accounts and privacy** | Connected accounts and their scopes, what leaves the PC (only model work), how long recordings, history and patterns are kept, what else is listening (Copilot, Voice Access) |
| **Activity** | Every request: what was heard, which lane or worker took it and why, what it did, what was approved, undo where possible |

Settings to leave out: internals the owner shouldn't need (thresholds, buffer sizes, model ids). Those stay in `config.yaml` for development.

## 7. Does Swift need a dashboard?

Not a dashboard in the usual sense: there are no metrics an owner needs to watch. But voice and cards alone can't do inspection (history, memory, permissions, automations), and inspection is what the trust differentiator rests on. So: **four surfaces, each for what it is good at.**

| Surface | Good for | Not for |
|---|---|---|
| **Voice and typing** | One setting at a time: "speak less", "stop reading answers aloud", "always draft in Word", "pause the news digest". Swift answers with a card showing the change and Undo | Anything with a list, or several fields |
| **On the cards** | The moment it matters: "Why?" on a result (lane, worker, reason), "Don't suggest this again", "Remember this" on a correction, "Edit workflow" on a workflow's card | Changing what Swift may do without asking: that stays in settings, on purpose |
| **The tray** | Pause listening, type, quiet mode for an hour, open Swift's window, quit | Anything else |
| **One window: "Swift"** (opened from the tray or by "open Swift settings") | Activity, What Swift knows, Workflows and automations, What Swift may do, Accounts and privacy, Look and read, Listening and speaking | Being open all the time |

Comparison:

| | Voice only | Cards only | Classic dashboard | **The four surfaces** |
|---|---|---|---|---|
| Discoverable | Poor (you must know what to say) | Partial | Good | Good: the window lists everything; voice and cards are shortcuts |
| Accessible | Good for some, impossible for others | Timed, which hurts | Good if built well | Good: every setting has a keyboard path and a spoken one |
| Screen space | None | Small | Large | Small except when the window is open |
| Complexity for the owner | Hidden rules | Scattered | Everything at once | Low: simple things are one sentence |
| Maintenance | Low | Medium | High | Medium: one window, one settings store, voice writes the same store |

**Workflows:** no node-graph editor; that is n8n's product and a large maintenance cost. A workflow shows as a list of steps in plain words, with its inputs as fields and its schedule as a sentence. It is created by describing it or by "make that a workflow" after a run, and edited the same way or in the window.

**Building it:** the window is a second Tauri window in the existing overlay, using the same protocol. Swift's backend owns the settings and memory stores, and the window and voice both write through the same messages, so there is one source of truth.

## 8. The recommendation

### 8.1 The vision in one paragraph

Swift is the owner's own operator on their PC. It handles everyday requests instantly and locally, hands real work to the best agent available, and does the owner's recurring work as watchers and recipes. Whatever does the work, Swift enforces the owner's rules, remembers their preferences with their consent, and can always say what it did and why. Voice is how you usually talk to it, not what it is.

### 8.2 Order of work

**Now (2–3 weeks)**

| # | Work | Why now | Size |
|---|---|---|---|
| 1 | Owner checks 50–116 and fixes | Nothing recent is validated on the real PC | Owner-run; fixes M |
| 2 | **Two weeks of daily use, with the metrics in §9** | The roadmap lacks its most important input | Owner time; a report script S |
| 3 | Split `session.py`: run launching, follow-ups, workflows, local lanes into modules | Every later item edits it | M |
| 4 | **Run records**: one append-only event log per run (steps, tool calls, approvals, artifacts, the worker and why), generalizing the journal | History, "Why?", recipes from runs, watchers and the Activity view all need it | M |
| 5 | **Settings and memory store** with provenance (said, approved, inferred), plus "remember", "forget" and "what do you know about me" | Conversational settings, adaptation and the window all need it | M |
| 6 | **`WorkerTask` contract** + context pack + a contract test against mock and Claude Code | Cheap now, expensive after a second worker | S–M |
| 7 | ADR-014 L3, quiet modes and call detection | Before anything proactive | S |

**Next (4–8 weeks)**

| # | Work | Depends on |
|---|---|---|
| 8 | Notifications at rest and "while you were away" | 4, 7 |
| 9 | **Watchers v1**: the owner's top two (likely boss emails, which needs the `gmail.metadata` decision, and a tech-news digest), with memory of what was already seen | 4, 5, 8; decision 22 |
| 10 | **Recipes from runs**: "do that again every Friday", "make that a workflow" | 4 |
| 11 | **The Swift window v1**: Activity (with Why), What Swift knows, Workflows and automations, What Swift may do, Look and read | 4, 5 |
| 12 | Conversational settings ("speak less") writing the same store | 5 |
| 13 | W2 file tools with folder permissions | 6 |

**Later, each only when its trigger appears**

- The cheap web lane, when watchers or daily use show it is in the way.
- A second worker, when a task needs it (a local or cheap model for the light lane; an API research agent for watchers).
- L1 suggestions from patterns, after a month of real data.
- A Chrome extension for Gmail web, if daily use shows it.

**Deferred or dropped:** screen vision (F, D4/D5), offline, voice ID, the phone companion, smart home, Apple Calendar, timer polish.

### 8.3 Changes to make now, to avoid an expensive redesign later

1. Run records as the single history (item 4); the interaction log becomes a view of it.
2. Settings and memory in a Swift-owned store, separate from `config.yaml`, with provenance on every record (item 5).
3. Executors take a `WorkerTask`; context is a structured pack built by Swift, not text prepended to the request (item 6).
4. Every side effect only through Swift's gateway: worker-native write tools off, or intercepted, for any new provider.
5. Autonomy as data: a per-action policy table (do, ask, never) that the gateway reads, instead of rules spread through code. The product rules stay hard-coded floors that no setting can lower.
6. `session.py` split before watchers land, since watchers start runs without a request from the owner.

## 9. How to tell Swift is getting better

Measured weekly from run records, counts only. Today's values are from the log above, which is mostly testing.

| Question | Measure | Today | Target after 6 weeks |
|---|---|---|---|
| Is it used? | Days used per week; requests per real day | Unknown | 5 days; 15 a day |
| Is it useful? | Share of requests done with no retry, rejection or correction | 78% | 90% |
| Is it fast? | Share answered locally; agent median | 25%; 13.6 s | 35%; under 10 s |
| Does it do recurring work? | Watchers and recipes in weekly use; runs they did without being asked | 0 | 3; 20 a week |
| Does it learn? | The same correction made twice; suggestion acceptance | Not measured | Falling; over 30% accepted |
| Is it trusted? | Product-rule breaches; approvals reversed by undo | Not measured | 0; falling |
| Is it independent? | The task suite passing against a second worker with no session change | No second worker | Passes |
| Is it affordable? | Agent cost per real day | ~$0.40 (testing) | Tracked, with a cap |

If after six weeks of daily use the owner still reaches for Copilot or a chat app for most things, that is the answer to "does Swift have a reason to exist", and it is better learned then than after another six phases of features.
