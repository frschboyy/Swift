# Halo as a system: assessment and direction (2026-11-07)

*Companions: [`SPEC.md`](SPEC.md) (the build reference), [`tokens.css`](tokens.css), [`halo.pen`](halo.pen) and [`boards/`](boards/), and the decision record [ADR-019](../../decisions/ADR-019-halo-design-system.md) (proposed).*

The owner chose Halo as the design baseline and asked for a step back: is the design robust, adaptable and fluid enough for where Swift is going, not only for what it does today? This document answers from the code on `main` (`b78c5a4`), the ADRs and the product direction, the handoff pack, and outside research. It does not redesign anything yet. It proposes the structure the next designs should be drawn in.

## 0. The short answer

- **The interaction model is sound and should stay.** One body per request, three places (in front, behind, in the corner), amber only for an OK, presence that never hides the privacy state, and the trust rules on the confirm card. These already scale to any number of requests and any capability.
- **The card layer will not scale.** Every card is shaped around one request the owner just made ("your words" head row), and every capability has had its own card and its own artifact kind. Watchers, recipes, reminders, suggestions, memory proposals and the Swift window all arrive through things the owner didn't just say. Today they would each need a new card, a new pane or a new hack. Timers already are one: a due timer is a `result` whose run id starts with `due-` (`session.py:3579`).
- **The direction: one object, one anatomy, a fixed set of blocks.** Everything Swift shows is a *run* with an **origin**, a **state**, a **body** built from a small catalog of blocks, and **actions** from a fixed set of verbs. The state decides the visual treatment, the blocks carry the content, and the zoom level decides the size: a count on the orb, an edge, a card, the expanded card, and a record in the Swift window. A new capability adds data, not UI.
- **Five things are cheap now and expensive later** (§7): the card anatomy and block catalog, an `origin` on every run, presence as independent axes, the approval ladder (designed, not built), and one component set shared by the overlay and the future window.
- **On drawing the missing states:** yes, but in the new anatomy, not the current one. Most of them (timer, failed, stopped, the asking state, away, shrunk, hover, "+N") are exactly the states the anatomy collapses into one card with different states. Drawing them first in the old shape would mean drawing them twice. They become the test that the anatomy works (§8).

## 1. What this is based on

| Source | What it gave |
|---|---|
| `docs/explorations/product-direction.md` (adopted 2026-10-28) | Where Swift is going: the owner's own operator, recurring work, watchers and recipes, memory with consent, the Swift window, any agent behind it |
| `docs/handoff/README.md` §4 | The order of work: groundwork (run records, settings and memory store, `WorkerTask`), then notifications at rest, watchers, recipes from runs, the Swift window, file tools |
| ADR-011 (workflow ecosystem) | Capabilities, workflows (playbook → recipe), workers; the owner's eleven workflows, five of which are watchers |
| ADR-013, ADR-015, ADR-017, ADR-018 | The presenter, the capsule, the Deck: today's attention model |
| `overlay/src/protocol.ts`, `main.ts`, `presenter.ts`, `deck.ts` | What the screen can express today: 4 result statuses, 6 artifact kinds, run rows shaped around a request, a 2,236-line `main.ts` that renders each card kind |
| The pen.dev handoff pack and the Halo board, states 1–17 | The current look and its checks, including Halo's tightest fit |
| Outside research (sources at the end) | How desktop agents, voice assistants, automation tools and accessibility software handle long tasks, approvals, proactivity, discovery and agent-made UI |

## 2. Where Swift is going

From the documents, in the order the owner adopted:

1. **Groundwork:** run records (one event log per run), a settings and memory store with provenance, a neutral `WorkerTask`, quiet modes and call detection.
2. **Notifications at rest** and one "while you were away" card, sized to the gap.
3. **Watchers:** boss emails, news digests, opportunities. They run without a request, remember what they've seen, and report only what's new.
4. **Recipes from runs:** "do that again every Friday", "make that a workflow".
5. **The Swift window:** Activity with "Why?", What Swift knows, Workflows and automations, What Swift may do, Look and read.
6. **File tools with folder permissions.**
7. **Later:** a second worker, suggestions from patterns, more desktop adapters, the web lane.

Read together, these change what Swift's screen has to carry:

| Today | Where it's going |
|---|---|
| Work starts when the owner speaks | Work also starts on a schedule, on an event, from a watcher or from Swift's own review job |
| A run lasts seconds to minutes | Runs last hours (research), recur (recipes) or never end (watchers) |
| One approval per tool call | Multi-step plans with several consequential steps; grants for a run; standing rules in settings |
| One worker (Claude Code) | Several workers, chosen by policy, with a reason the owner can ask for |
| Memory is a few fragments | Preferences, facts, patterns and unfinished threads, each with a source, editable |
| Everything is on the overlay | The overlay for now, the window for over time, and toasts or a digest for while away |

## 3. What the outside research says

### 3.1 Existing tools, and what makes them work or not

| Category | Examples | What works | What limits them |
|---|---|---|---|
| Desktop agents | Copilot Actions on Windows; Claude Cowork; ChatGPT's former agent mode | Visible step history; take over at any time; approval at sensitive steps; scope set once ("you choose the folders and tools") instead of approving every step; work in a separate desktop or the background | A separate app or a sandboxed desktop the owner must go and look at; approvals are each vendor's own; little continuity between tasks |
| Voice assistants | Alexa+, Siri AI (iOS 27), Copilot voice | Context carried across turns; deterministic paths for basics (timers, lights) kept separate from the model path; personal context and on-screen awareness | Reliability on simple things; chatty filler after simple requests; memory that doesn't carry across apps; uneven rollout of agentic features |
| Voice-only devices | Humane AI Pin, Rabbit R1 | Narrow, reliable jobs (record and summarize) | Voice alone doesn't cover tasks people need to see, compare or re-read; cloud latency; basics missing |
| Launchers and automation | Raycast AI extensions, ChatGPT scheduled tasks, n8n, Zapier | Capabilities exposed as tools and found by `@` or search; a list of scheduled tasks to pause, resume and edit; a card that pauses the chat for approval | Node-graph editors are a product of their own; automations drift away from where the work happens |
| Accessibility software | Windows Voice Access, Talon, macOS Voice Control | "What can I say", a searchable command catalog, per-app commands, number overlays that make targets visible, hints when a command doesn't quite match | Long cheat sheets; numbers that reset each time, so nothing is learned |

### 3.2 Where things are heading

- **Agents that run long and out of sight.** Copilot Actions and Cowork run multi-step work in the background and let the user check in, take over or stop. The pattern that holds up is: show the plan and the step you're on, keep Stop visible while it runs, and say "what changed", not just "done".
- **Risk-tiered checkpoints, not a dialog per step.** The consistent advice: reads run and are logged, consequential steps ask, and chains of approvals say how many remain ("step 2 of 4 needs your OK"). Scope is set once where possible.
- **Scheduled work the user owns, rather than a feed.** OpenAI retired its proactive Pulse feed in favour of scheduled tasks the user creates, pauses and edits (June 2026). Unrequested feeds didn't stick; owner-defined schedules did. This matches the product direction's watchers and recipes.
- **Agent-made UI, inside the host's components.** A2UI (Google, v0.9) and MCP Apps let agents return UI. A2UI's point is the important one for Swift: the host already has a design system, so the agent picks from the host's catalog instead of shipping its own UI. MCP Apps give more freedom at the cost of consistency and safety.
- **Interruption timing matters more than salience.** Long-standing research (Horvitz's bounded deferral, Bailey and Konstan on breakpoints) finds that holding a notification until a natural break lowers frustration and load, and that most busy periods end within one to two minutes. Changing when something arrives does more than changing how loud it is.

### 3.3 What Swift should take, and what it shouldn't

- **Take:** step history and "what changed"; Stop always visible while running; scope once, per run; the host-owned component catalog; owner-defined schedules over feeds; bounded deferral to breakpoints; "what can I say" and hints.
- **Don't take:** a separate agent desktop the owner has to go and watch (Swift's strength is that it's on top of the owner's own work); a chat transcript as the main structure (Swift's unit is the task, not the message); arbitrary agent UI (it would break the trust rules, which depend on Swift drawing every consequential fact itself).

## 4. What the current design already handles well

| Strength | Why it will last |
|---|---|
| **One body, three places** (ADR-018) | It's a model of attention, not of features. Any number of requests, from any source, fits in front, behind or in the corner. |
| **The card in front never moves because of something else** | The single most important rule for an always-on overlay; it survives every future capability |
| **Amber means an OK is waiting, and nothing else** | A one-meaning colour is what lets the owner trust a glance. It must survive plans, grants and watchers. |
| **The confirm card's facts** (recipient, time, Now → After, the whole command), Approve says what it does, typing never approves, a countdown never answers | This is Swift's strongest asset (product direction §2.2) and it is visual: the screen is where the owner's rules become visible |
| **Presence and the privacy state** | "Not listening" persists over everything; the orb is Swift's body. Halo makes both stronger. |
| **Held while away, countdowns only while present** | Already the start of an attention policy: Swift knows when the owner can't see it |
| **The live view's entries** (`doing`, `source`, `note`, `text`, `hint` in `protocol.ts`) | Already a generic activity stream, not tied to one capability. It's the seed of the block catalog. |
| **Generic result details** (`text`, `list`, `table`) | The other seed: content as data, rendered by the host |
| **No focus, click-through, fixed window** | Correct for an overlay over the owner's work; nothing in the future needs it to change |

## 5. Where it will struggle

Each item names the future case that breaks it and where in today's design the limit lives.

### 5.1 Everything is shaped around a request the owner just made

- Every card's head row is the owner's words (`RunRow.words`, the "You said" row in Halo). A watcher's finding, a scheduled recipe, a reminder, a suggestion from the review job and a memory proposal have no words to show.
- Due items are already squeezed in: a timer is a `result` with run id `due-timer-…` (`session.py:3579–3582`), and the overlay recognizes it by that prefix.
- **What breaks:** a boss-email alert arriving while a card is open, a Friday recipe finishing at 9 am, "You changed the sign-off twice. Always use 'Best, Francis'?". None of these has an honest head row, and each would invite a new card.

### 5.2 One card design per capability

- Today there are separate designs for answer (one line, text, table, long), working, failed, stopped, not done, confirm (add, change, email, command, file change), question (asking, waiting), timer, reminder, and the stack's rows, with six artifact kinds in `protocol.ts` and their rendering in `main.ts`.
- **What breaks:** files (W2), watchers, digests, recipes, memory and a second worker would each add a confirm variant, a result variant and an artifact kind. The design grows by one card per capability, and `main.ts` with it.

### 5.3 Approval is only per tool call

- The confirm card is one action at a time. That's right for "send this email". For a recipe that moves twelve files, or a research task that writes into Word and then emails a summary, it means a chain of amber cards.
- **What breaks:** approval fatigue (the owner starts approving without reading, which defeats the facts), a deck full of amber edges, and amber losing its meaning by being everywhere.

### 5.4 The time scale is seconds to minutes

- The rules are tuned for short work: a working card shrinks after 12 s, a ready row lasts 20 s, a confirm counts down from 45 s, an answer fades after its reading time.
- **What breaks:** a research run that takes 40 minutes, a recipe scheduled for tomorrow and a watcher that runs forever. None of them is "in flow now" (behind) or "put aside" (the corner). They need a home that isn't the overlay, and a quiet way back onto it when they have news.

### 5.5 Proactive work has no rules for when it may appear

- "What takes the front" is defined for requests the owner made. Nothing says when a watcher's finding, a digest or a suggestion may surface, or how it waits.
- **What breaks:** the first watcher either interrupts at the wrong moment (mid-sentence, on a call) or gets buried in the stack. The research says timing is the lever, not loudness.

### 5.6 Two windows that could become two products

- The Swift window (Activity, What Swift knows, Workflows, What Swift may do) is planned as a second Tauri window. Without a shared component set it becomes a settings app with its own look, rows and words. The overlay's run and the window's activity entry would be two drawings of the same thing.

### 5.7 Surfaces added one at a time

- Capsule, card, deck, stack, live view, reader, typing box, tray panel, and soon toasts, a "while you were away" card and the window. Each was added for a reason, but there's no rule for what a new one must reuse.

### 5.8 Presence is a closed priority list

- The capsule shows one of seven states, most urgent first (ADR-017). Quiet mode, call detection, "working in the background", a watcher with news and "Swift is working in Word" would each add a state to the list.

### 5.9 Acting in the owner's apps isn't visible

- Swift writes into Word, Gmail and Outlook in the owner's own session (ADR-012). The protocol carries `live.app`, but the design doesn't show where Swift is acting, or ask the owner to keep hands off while it types.
- **What breaks:** the owner types into the same document while Swift writes, and the result interleaves. Copilot avoids this by acting in a separate desktop; Swift chose not to, so it needs a visible "Swift is writing in Word" with Stop.

### 5.10 No consistent place for feedback and steering

- "Why?", "Remember this", "Don't suggest this again", "that's wrong" and "Undo" are planned (product direction §7), but cards have no slot for them. Each would be added to some cards and not others.

### 5.11 Failure is all or nothing

- The failed card ends the run. A multi-step run that did steps 1 and 2 and failed at 3 needs "steps 1–2 done, 3 failed", a retry of step 3 alone, and its partial work kept.

### 5.12 Halo's own limits

- **The tail** points at the orb at the bottom and top centre. At the four side anchors it has to move off centre, and that's unchecked.
- **Compact confirm** is required to pass the tightest fit (state 12). It's a second layout to build and test.
- **The bubble means "Swift is saying this".** That's right for answers, questions and findings, and the right metaphor for proactive items. A working card is less a thing Swift says than a thing it's doing. The state line (§6.2) has to carry that difference, not the shape.

## 6. The direction: one object, one anatomy, a fixed set of blocks

### 6.1 Everything is a run

A **run** is any unit of Swift's work the owner may see: a request, a reminder coming due, a watcher's finding, a scheduled recipe, a suggestion from the review job, a memory proposal. Run records (handoff §4 groundwork) are the backend side of this. The screen side is that every surface draws a run, and only a run.

Every run has:

| Field | Values | Replaces |
|---|---|---|
| **Origin** | You asked (said or typed) · Scheduled · Watching · Reminder · Swift noticed · Learned | The "your words" head row as the only origin; the `due-` run id prefix |
| **State** | Working · Done · Needs your OK · Waiting for you · Stopped · Failed · Due | Card kinds as separate designs |
| **Body** | Blocks from the catalog (§6.3) | Artifact kinds and bespoke card layouts |
| **Actions** | A subset of the verbs (§6.6), in a fixed order | Per-card button sets |
| **Meta** | Who did it ("via Claude"), when, why, and a link to its record | Byline only |

### 6.2 One card anatomy

Every card, whatever it shows, has the same slots, top to bottom:

1. **State line.** The state in words with its mark and time: "Working · 0:03", "Done", "Needs your OK · 0:44", "Waiting for you", "Failed". This is the Rail idea folded into Halo: what kind of card this is reads in the first line, in words, not only in colour. Close sits here. On Needs your OK this line is the amber band; on Waiting for you, the accent tag.
2. **Origin line.** Who started it, shown by side, like a conversation. Things the owner asked for sit on the **right**: their words, with how they asked (mic or keyboard), as Halo does today. Things Swift started sit on the **left** with their mark: "Every Friday · tech news digest", "Watching · emails from Janet", "Timer · you set it", "Swift noticed", "Learned · from 2 of your edits". Never missing, never invented.

*Changed while drawing N1 (2026-11-07): the state line moved above the origin line, so the first thing read is what kind of card it is, and the amber band stays at the top of a confirm card.*
3. **Body.** One or more blocks.
4. **Facts.** Only for a consequential action: what will happen, to whom, when, Now → After. Drawn by Swift from the action itself, never from a worker's text.
5. **Actions.** Primary on the right, others on the left, always in the same order.
6. **Meta.** Byline, "Why?", feedback, and the hint line (§6.8).

**The state decides the treatment; the blocks carry the content.** Amber band and amber halo come from "Needs your OK", whatever the action. The accent halo comes from "Waiting for you". "Failed" gets the bad mark. "Due" gets the solid card that never fades. Content never changes the treatment, so no worker or capability can make an ordinary card look like a confirm card, or the reverse.

What today's variants become:

| Today | In the anatomy |
|---|---|
| Answer: one line, text, table, long | Done + a display, text, table or long-text block |
| Working card, shrunk working card | Working + steps block; shrunk = the same card at edge size |
| Confirm: add, change, email, command, file change | Needs your OK + facts (+ change, preview or command block) |
| Question: asking, waiting | Waiting for you + choice or listening block; "asking" is the same state while Swift speaks |
| Failed, Stopped, Not done | Failed or Stopped + what happened, with partial results if any |
| Timer, reminder | Due, origin Reminder, + display block and Done / +5 min |
| Watcher finding, digest | Done, origin Watching or Scheduled, + list or sources block |
| Suggestion, memory proposal | Waiting for you, origin Learned, + facts ("You changed the sign-off twice") + Remember / Not now / Never |

About fifteen designs become one anatomy, seven states and a dozen blocks.

### 6.3 A small block catalog, owned by Swift

The A2UI lesson: the host has a design system, and capabilities pick from it. Swift's catalog starts from what already exists and grows only when two capabilities need the same new block:

| Block | Exists today as | Used by |
|---|---|---|
| Display line | One-line answer | Answers, timers, "It's 3:42 pm" |
| Text | Answer paragraphs | Answers, findings |
| Long text | Read more / Read less | Research, summaries |
| List | `details.list` | Digests, search results |
| Table | `details.table`, calendar | Calendar, comparisons |
| Steps | Working card's steps | Every multi-step run, plans (§6.5) |
| Facts | Confirm facts box | Every consequential action, proposals |
| Change | Now → After | Calendar change, settings change, file move |
| Preview | Email body | Email, document, message |
| Command | Full command text | Shell, file operations |
| Sources | Live view sources | Research, digests, watchers |
| Choice | The question's options and listening pill | Questions, plans, suggestions |
| Progress | Reading-time and countdown bars | Time left, long runs |

Rules for the catalog:

- **Workers never draw.** A worker returns data; Swift chooses the block. Agent-made UI (MCP Apps) can be accepted only by mapping it onto blocks, never by showing it as it comes.
- **A block has one look in every place:** the card, the expanded card, the Swift window, a digest.
- **A new block needs two users.** Otherwise the capability uses the closest existing block.

### 6.4 One run, many sizes

The same run, at five zoom levels, with the same marks, words and colours at each:

| Size | Where | Shows |
|---|---|---|
| **Badge** | On the orb | A count, amber if an OK waits (never a new capsule state) |
| **Edge** | Behind the card, or in the stack | Origin mark, title, state in words, time |
| **Card** | In front | The full anatomy, clipped |
| **Expanded** | The card opened in place (today's Read more, the live view and the reader) | The full anatomy with its whole body and step history |
| **Record** | The Swift window's Activity | The run as it ended, with "Why?", approvals and undo |

This merges the live view and the reader into "the card, expanded", as one idea, even while window limits keep them in separate windows (ADR-018 §6's one-window spike would merge them physically). It also makes the Swift window the overlay's long memory, not a second app.

### 6.5 Approval as a ladder, with the product rules as floors

| Rung | When | What the owner sees | Exists? |
|---|---|---|---|
| **One action** | A single consequential step | Today's confirm card | Yes |
| **A plan** | A run with several steps, some consequential | One card listing the steps. Starting it lets the safe steps run; a step whose facts aren't known yet (an email not yet written) still asks on its own card when it's ready. So the plan card is Waiting for you, not amber: nothing consequential is approved in advance | No |
| **A grant for this run** | Repetitive steps of one kind | "Move files from Downloads into Lectures, for this run": scope set once, the run then reports instead of asking | No |
| **A standing rule** | Only in the Swift window's "What Swift may do" | A per-action table: do, ask, never | No (product direction §8.3 item 5) |

- The product rules stay hard floors that no rung lowers: recipients only from contacts, a bare "yes" never approves, typing never approves. Sending stays "ask" unless the owner changes it in settings. Proposed as a new floor (not a product rule yet): deleting files always asks.
- Amber still means one thing: something here waits for your OK. A plan card with two consequential steps is one amber card, not two.
- Learning never climbs the ladder (product direction §5.2): patterns can propose, never grant.

### 6.6 Places by time, not by feature

Keep the Deck's three places for *now*, and add one place that isn't on the overlay:

| Place | Holds | Where |
|---|---|---|
| **In front** | The one thing you're dealing with | The card |
| **Behind** | In flow now | Edges |
| **Waiting for you** | Put aside: held approvals, unanswered questions, unfinished runs, findings that arrived while you were away | The corner stack, and the "while you were away" card on return |
| **Standing** | Watchers, schedules, long runs that don't need you | The Swift window; on the overlay only as a badge, and only when there's news |

A standing item comes onto the overlay through the same places as everything else, at the moment the attention policy allows (§6.7). No new surface is needed for watchers.

### 6.7 An attention policy

Each run, when it has something to show, gets an urgency. The policy decides when it may appear, using signals Swift already has (presence, the owner typing or talking) and those coming in groundwork (quiet modes, call detection):

| Urgency | Example | How it appears |
|---|---|---|
| **Now** | The answer you're waiting for; its OK; its question | Takes the front (today's rules) |
| **Soon** | A request you made finishing behind the card | An edge, "Ready to read" |
| **At the next break** | A boss email; a watcher finding | Waits for a breakpoint (you stop typing, a call ends, you come back), up to a limit, then an edge |
| **In the digest** | News, opportunities, suggestions | The "while you were away" card or a scheduled digest |
| **Silent** | Routine runs that changed nothing | The record only |

- The owner sets the urgency per source ("Janet's emails: at the next break; tech news: morning digest"), by voice or in the window.
- Bounded deferral: nothing waits past its limit. Most busy stretches end within a minute or two.
- Nothing proactive interrupts while the owner is speaking, on a call or in quiet mode, except a due reminder the owner set.

### 6.8 One set of verbs, everywhere

The same words work by voice, click and keyboard, on every card that can take them:

| Verb | Means | On |
|---|---|---|
| **Stop** | End this run | Working runs (always visible while running) |
| **Change** | Edit what's about to happen | Needs your OK, plans |
| **Show me** | Expand, or open the live view | Any run |
| **Later** | Put it in Waiting for you | Any run in front |
| **Undo** | Reverse what was just done | Done runs whose action can be reversed |
| **Why?** | Origin, worker, reason, rules applied | Any run |
| **Remember / Don't** | Turn a correction into a preference, or stop a suggestion | Done runs, Learned runs |

Cards show at most three buttons. The rest are reachable by voice and from the expanded card, so the card stays glanceable.

**Discovery through the same slot:** the meta line can carry one hint for the card in front ("Say 'put it in Word'", "Say 'every Friday' to repeat this"), shown the first few times and then dropped. "What can you do here?" answers for the card in front. The window lists every capability from the capability registry (ADR-011 §7.1). This follows Voice Access's "what can I say" and Voice Control's hints, without a cheat sheet.

### 6.9 Presence as independent axes

Instead of a priority list that grows, the orb shows three independent things:

| Axis | Values | How it shows |
|---|---|---|
| **Mic** | Listening for its name · Heard · Listening · Paused (mic off, locked, asleep) | The orb's rings; paused is the sleeping orb, which never fades |
| **Activity** | Idle · Working · Speaking · Working in an app | The orb's motion, the speaking bars, and "Writing in Word" with Stop when Swift acts in the owner's app |
| **Waiting** | A count of what waits for you | A badge on the orb: neutral, or amber with a shield when an OK waits (never amber alone) |

Activity "Working" with no card open is an orbit ring around the orb, so it combines with any mic state: a sleeping orb can carry the ring and an amber badge at once.

Quiet mode and call detection change what the attention policy lets through, not the orb's states.

## 7. What to do now, and what can wait

### 7.1 Necessary now (cheap now, expensive later)

| # | Change | Why now | Kind |
|---|---|---|---|
| N1 | **Card anatomy and block catalog**, drawn in Halo, with the states from §6.2 | Every next capability (files, watchers, recipes, the window) would otherwise add its own card | Design |
| N2 | **`origin` on every run** in the protocol and run records, replacing the `due-` run id prefix | Run records are being designed now (groundwork); adding origin after watchers exist means migrating them | Backend + protocol, small |
| N3 | **Presence as axes** in the capsule spec | The next three features (quiet mode, call detection, background runs) would each add a capsule state | Design, then overlay |
| N4 | **The approval ladder, designed but not built:** the plan card and the run grant drawn, with how they meet the product rules | W2 file tools and recipes will need them; designing them after the first chain of confirm cards ships is late | Design |
| N5 | **One component set for the overlay and the window:** tokens, blocks and the anatomy as a shared spec (and a shared CSS module when the window is built) | The window is next after watchers; it should start from these parts | Design system |
| N6 | **Halo's own risks:** the state line in the anatomy, the compact confirm rule, the tail at the four side anchors | They decide whether Halo works at all positions | Design |

### 7.2 Next (with notifications at rest, watchers, recipes and the window)

- The attention policy (§6.7), built with notifications at rest and the "while you were away" card.
- The Swift window drawn from the same anatomy: Activity as records, workflows as runs with origin Scheduled or Watching.
- The plan card and run grants, built with W2 file tools.
- Partial completion: "steps 1–2 done, 3 failed", retry a step, keep partial work.
- Hints in the meta line, and "What can you do here?".
- "Writing in Word" with Stop when Swift acts in the owner's app.

### 7.3 Later, only when the trigger appears

- Accepting agent-made UI (MCP Apps), mapped onto blocks only: when a second worker brings it.
- The one-window spike (ADR-018 §6): would let the stack, live view and reader be the same body as the card, with motion between them.
- Screen awareness and multimodal input: deferred by the product direction; if they come, they add an origin ("You showed me") and a block (image), not a surface.

## 8. Simplifications this allows

- **Fifteen card designs become one anatomy, seven states and about a dozen blocks** (§6.2).
- **The live view and the reader become "the card, expanded"** (§6.4).
- **The stack, the unfinished line and "while you were away" become one place, Waiting for you** (§6.6; product direction §5.3 already asks for this).
- **Timers and reminders stop being special:** a run with origin Reminder and state Due.
- **Watchers need no new surface:** Standing in the window, a badge on the orb, and the attention policy for when they surface.
- **The window is not a second app:** the overlay's runs as records, with the same blocks.

**The missing states from the Halo board** (edge hover, "+N", asking while speaking, away on a confirm, the shrunk card, failed, timers, the tray) are the first test: each one should come out of the anatomy without a new design. Draw them once N1 is agreed, not before.

## 9. Where Swift can be different

- **The unit is the task, not the message.** Chat apps keep a transcript. Swift should keep runs you can glance at, steer, put aside and audit. That's a better fit for an operator than a conversation log, and nobody in the list in §3.1 does it on the desktop.
- **Trust you can see.** Facts drawn by Swift, an origin on everything, "Why?" on everything, and treatments only the state can trigger. The owner's rules become visible structure, not a settings page.
- **Proactive on the owner's terms.** Findings from watchers the owner set up, arriving at breakpoints, never as a feed. The industry has just tried the feed and retired it.
- **Voice plus a glance.** The voice-only devices showed that voice needs a screen to look at. Swift's overlay is that screen: short cards readable at a glance, more on expand, everything in the record.
- **Agent-neutral down to the pixels.** If workers return data and Swift draws blocks, swapping Claude Code for another worker changes nothing on screen except the byline. That's the product direction's independence test (§2.3), applied to the interface.

## 10. Risks of this direction

- **Over-abstraction.** A generic anatomy can make every card look the same. Halo's character (the orb, the tail, the conversation layout) and the state treatments have to carry the difference. Test it by drawing the confirm, the question and a watcher finding side by side: they must be impossible to confuse.
- **A catalog that grows without limit.** The two-users rule (§6.3) is the guard.
- **Building ahead of use.** The handoff's rule stands: two weeks of daily use decide what comes after groundwork. N1–N6 are mostly design and a protocol field; nothing here asks for the ladder or the attention policy to be built before watchers exist.

## Sources

- [Copilot Actions begins rolling out to Windows Insiders](https://blogs.windows.com/windows-insider/2025/11/17/copilot-on-windows-copilot-actions-begins-rolling-out-to-windows-insiders/) (Windows Insider Blog)
- [Microsoft brings agentic AI to Windows 11 with Copilot Actions](https://pureinfotech.com/windows-11-copilot-actions-agentic-ai/)
- [Cowork, a research preview](https://websitemain.claude.com/resources/tutorials/claude-cowork-a-research-preview) (Anthropic); [Claude Cowork architecture overview](https://tensorlake.ai/blog/claude-cowork-architecture-overview)
- [ChatGPT agent](https://help-lb.openai.com/en/articles/11752874-chatgpt-agent) (OpenAI Help Center); [ChatGPT scheduled tasks, June 2026](https://ayinedjimi-consultants.fr/news/chatgpt-scheduled-tasks-openai-juin-2026); [ChatGPT now has a hub for scheduled tasks](https://www.pulse.bot/ai/news/chatgpt-now-has-a-hub-for-scheduled-tasks-601c4853-516c-4804-81d9-2bdb0a8fe976/)
- [Alexa+ review 2026](https://aisotools.com/blog/alexa-plus-review-2026); [Alexa+ gets smarter, but still stumbles](https://aichief.com/news/alexa-review-amazons-new-ai-assistant-tested/); [Amazon's agentic Alexa (Engadget)](https://www.engadget.com/2210614/amazon-is-reportedly-working-on-a-more-powerful-agentic-assistant/)
- [Apple introduces Siri AI with personal context and on-screen awareness](https://www.iclarified.com/101113/apple-introduces-siri-ai-with-personal-context-and-onscreen-awareness); [iOS 27 and Siri AI release date (MacRumors)](https://www.macrumors.com/2026/06/08/ios-27-and-siri-ai-release-date/)
- [AI product failures: Humane, Rabbit lessons](https://www.digitalapplied.com/blog/ai-product-failures-2026-sora-humane-rabbit-lessons); [HP acquires Humane, shuts down AI Pin](https://www.techspot.com/news/106833-humane-shuts-down-ai-pin-business-hp-buys.html)
- [A2UI v0.9: portable, framework-agnostic generative UI](https://developers.googleblog.com/en/a2ui-v0-9-generative-ui/) (Google); [The developer's guide to generative UI in 2026](https://www.copilotkit.ai/blog/the-developer-s-guide-to-generative-ui-in-2026); [MCP Apps, OpenAI Apps SDK and A2UI](https://www.telusdigital.com/insights/data-and-ai/article/accelerating-genui-ecosystem-mcp-apps-openai-apps-sdk-and-google-a2ui)
- [Agentic AI UX: human oversight and control patterns](https://uiux-atlas.pages.dev/lessons/emerging/agentic-ai-ux-human-oversight-and-control-patterns); [Agent UX patterns that work](https://inference.sh/blog/ux-agent-ux-patterns); [Agent UX design patterns: a 2026 checklist](https://www.agenticwire.news/article/agent-ux-design-patterns)
- [Raycast AI Extensions](https://manual.raycast.com/ai/ai-extensions) (Raycast manual)
- [Voice access command list](https://support.microsoft.com/en-us/topic/voice-access-command-list-dac0f091-87ce-454d-8d57-bef38d3d8563) (Microsoft); [Talon documentation](https://talonvoice.com/docs/); [Use Voice Control on your Mac](https://support.apple.com/en-gb/ht202584) (Apple)
- [Balancing awareness and interruption: notification deferral policies](https://www.erichorvitz.com/bdef_studies.htm) (Horvitz et al.); [Paying attention to interruption](https://hci.stanford.edu/seminar/abstracts/06-07/070406-bailey.html) (Bailey); [Intelligent notification systems: a survey](https://arxiv.org/pdf/1711.10171)

Most outside sources on agent UX are practitioner and vendor writing, not controlled studies; the interruption research is older lab work. Treat product details (rollout status, plans) as approximate: they change fast.
