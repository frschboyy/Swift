# Swift: what established assistants and agents teach about the experience (research, 2026-11-07)

The owner asked for broader research, so that Swift's direction is informed by what mature products do rather than by fixing features one at a time. They were thinking aloud: everything here is a recommendation, and nothing is adopted until they say so.

**Extends** [`DIRECTION.md`](../design/halo-system/DIRECTION.md) §3 and [`product-direction.md`](product-direction.md) §2. **Out of scope:** wake word and concurrency, which another session is researching on `worktree-voice-reliability`. **Nothing in the product changes** with this document, and the handoff's order of work stands unless the owner changes it.

## 0. The short answer

**What the evidence shows**

1. **The market moved towards Swift's plan, and part of Swift's claimed gap has closed.** ChatGPT now has [email-triggered tasks that filter by sender](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt). Gemini has [Gmail and topic monitors](https://support.google.com/gemini/answer/17094710?hl=en&co=GENIE.Platform%3DAndroid). ChatGPT's new "dot" lets the user set [per-action rules](https://help.openai.com/en/articles/20001530-getting-started-with-your-dot). Those are the owner's top two watchers, and a version of "rules you set". [`product-direction.md`](product-direction.md) §2.2 item 4 ("no assistant does those well today") and §2.1's Copilot row are now out of date.
2. **"Feeds failed" is too strong.** `DIRECTION.md` §3.2 and §9 say the industry tried the feed and retired it. OpenAI did retire Pulse, but [reportedly said](https://www.digit.in/news/general/openai-is-retiring-chatgpt-pulse-and-replacing-it-with-scheduled-tasks-here-is-why.html) the lesson was that proactive features work best when personalised, action-oriented and steerable. Since then Google launched [Daily Brief](https://blog.google/innovation-and-ai/products/gemini-app/next-evolution-gemini-app/) and OpenAI launched dots, which [research and form memories without being asked](https://help.openai.com/en/articles/20001530-getting-started-with-your-dot). The form is unsettled, not the idea.
3. **Approving is much weaker than it looks.** In [Anthropic's own study](https://claude.com/resources/articles/auto-mode-default-in-claude-code), people caught a planted dangerous command 13.6% of the time, falling from about 17% early in a session to about 5% after 50 or more prompts. This is coding, run by a vendor with a stake in the result, but it is the best number found, and it bears directly on Swift's strongest asset.
4. **Products keep converging on the same management shape:** a list of standing work with Active, Paused and Completed, plus run now, pause, edit and delete. ChatGPT, Gemini, Cowork and Copilot Tasks all have one.
5. **The makers of agents are pulling deterministic work back out of the model.** [Zapier folded its standalone Agents into a step inside a workflow](https://zapier.com/blog/zapier-agents-is-now-ai-by-zapier/). Hands-on reports say Alexa+ made once-reliable routines less dependable (§3.5, anecdotal). Both support ADR-011's playbook-to-recipe path and Swift's local lanes.

**My judgment**

- **The direction holds, but its reason has to shift.** "Does recurring work" is no longer different on its own. What remains different: rules that no setting can lower and that you can see; one trust boundary across any worker; Swift drawing every consequential fact itself; the owner's data kept on their PC (metadata-only mail, matched locally); and sitting on top of the owner's own Windows session.
- **Swift's biggest gaps relative to these products are not features.** They are small and mostly cheap: nothing says why a run did or didn't happen, nothing manages watchers until the window arrives (step 7, after watchers at step 5), help is one fixed paragraph, and Swift can't be operated without a mouse or a working microphone.
- **Fewer cards matters as much as better cards.** Keep every product-rule floor, and treat every other card as a cost to be justified.

Prioritised recommendations are in §7, decisions for the owner in §9.

## 1. How to read this

- **Evidence** means what a source says. **Judgment** means my reading of what Swift should do. They're kept apart under those headings.
- **Nothing here was tried by hand.** No product was used: everything comes from documentation, vendor posts and reported reviews. Vendor pages say what's meant to happen, not how well it works.
- **Depth of reading varies,** and each source in the list at the end says how it was read. Most help pages went through a summarising fetch, not a line-by-line reading. The two OpenAI pages were read as page text, and both were cut off before their end. Details such as plan limits may be wrong in small ways.
- **These products change monthly.** All facts are as of 2026-11-07. Copilot is the least stable: its consumer Tasks page says accounts [will move to Copilot Cowork "over the next few weeks"](https://support.microsoft.com/en-us/microsoft-365-copilot/using-copilot-tasks), and [Ask Copilot on the taskbar was temporarily disabled in August 2026](https://learn.microsoft.com/en-us/windows-insider/release-notes/apps/copilot-on-windows). I found no date for its return.
- **Scale:** Swift has one owner, and most of this evidence comes from products with millions of users. Anything aimed at strangers, such as onboarding, sharing or galleries, counts for less here.

## 2. Comparison

As documented, not as tested. "Not found" means I didn't find it, not that it doesn't exist.

| Product | Creating standing work | Where it's managed | Consent for actions | Proactive | Runs when PC is off? |
|---|---|---|---|---|---|
| **ChatGPT tasks** | Ask in chat; review Trigger, Condition, Prompt | Scheduled page; 3 to 15 active by plan | Actions needing approval may pause the task | Monitoring and event tasks | Yes, except tasks that run only on your computer |
| **ChatGPT dot** (Nov 2026) | Give it a goal | Profile: In progress, Scheduled, Completed | Rules: do without asking, do if pre-approved, ask, hand off | Researches and forms memories unasked | Yes, own cloud computer |
| **Gemini** | Describe in a thread; form on web | Active, Paused, Completed; up to 50; run now to test | "Ask you first" before high-stakes actions (Spark) | Daily Brief (opt-in); monitors | Yes |
| **Claude Cowork** | `/schedule` or sidebar | Scheduled | Manual, Auto, Skip; permanent delete always asks | Not found | Yes; local files only while the desktop app is open |
| **Copilot Tasks** (consumer) | Describe a goal | Tasks view: steps, sites, interim results | Asks for money, personal data, other people, account changes, sensitive acts | Only when you start it | Not stated on the page read |
| **Copilot Actions** (Windows) | Describe; experimental | Separate agent workspace | Off by default; admin enables; approve sensitive steps | No | Not stated; it runs in a local session |
| **Alexa+** | Say it; saved in the app | Alexa app | Reports success or errors; screen shows fares before booking | Not established | Cloud |
| **Siri AI** (beta) | Via Shortcuts; App Intents | Shortcuts | Not found in Apple's release | Not found | n/a |
| **Shortcuts** | List of actions; model step | App | Per automation: Ask Before Running, Notify When Run | Automations only | On device |
| **Raycast** | `@` an extension; not a scheduler | Settings | Ask, Auto, Always Allow; per-chat override | No | n/a |
| **Zapier** | Describe, or build steps | Zap history | Per-tool approval; review with edit; timeouts | Triggers | Yes |
| **n8n** | Graph editor | Executions; separate version history | Per-tool human review via a channel | Triggers | Yes (self-hosted server) |
| **Voice Access / Talon** | Custom shortcuts / `.talon` files | Files, settings | Not relevant | No | Local |
| **Swift today** | Files; "make that a workflow" planned | "What workflows do I have?" | Cards; product-rule floors; digest-bound | None yet | **No: only while the PC and Swift run** |

## 3. Workflows: creating, managing and showing them

### 3.1 What they do well

**Evidence**

- **Describe, then review the written form.** [Workspace Studio](https://support.google.com/workspace-studio/answer/16448469?hl=en) turns a description into steps to edit, reorder, delete or add to, then offers a **Test run** before **Turn on**. [ChatGPT's event tasks](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt) ask you to review Trigger, Condition and Prompt. This is the same shape as ADR-011 §5.1.
- **Try it before relying on it.** Gemini can [run a schedule immediately to test it](https://support.google.com/gemini/answer/17094710?hl=en&co=GENIE.Platform%3DAndroid). OpenAI [advises](https://learn.chatgpt.com/docs/automations) testing the prompt by hand first, then reviewing the first few outputs.
- **A findings inbox.** Codex's scheduled view [calls itself "your inbox"](https://learn.chatgpt.com/docs/automations): runs with findings show up there with an unread mark, and the prompt should define how to decide whether anything is worth reporting.
- **Says why nothing happened.** [Home Assistant's traces](https://www.home-assistant.io/docs/automation/troubleshooting/) distinguish no trace at all (the trigger didn't react), stopped by a failed condition, stopped on an error, and stopped because a previous run was still going. Traces [survive restarts](https://www.home-assistant.io/docs/automation/testing/). This is the best model found for "why didn't it run?"
- **Re-run a failure against the fixed version.** [n8n](https://docs.n8n.io/workflows/executions/debug/) copies a failed run's data into the editor to fix and re-run it, and keeps runs apart from version history.
- **Replays don't reuse approvals.** A [Zapier](https://help.zapier.com/hc/en-us/articles/38838306755981-Special-step-run-statuses-in-Human-in-the-Loop-actions) run that stopped on a declined or timed-out review can only be replayed whole, and reviewers review every step again.
- **AI inside fixed steps.** Zapier [folded Agents into a step](https://zapier.com/blog/zapier-agents-is-now-ai-by-zapier/) because standalone agents couldn't use triggers, filters or run history, and now says agents work best inside deterministic workflows. Shortcuts' [Use Model](https://support.apple.com/guide/shortcuts-mac/mchl91750563/mac) is a step in a list, with a **Follow Up** option to review the answer before it passes on.
- **Sharing without secrets.** A ChatGPT [shared task](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt) carries the title, instructions and schedule, but no memories, results, files or credentials. The recipient uses their own permissions.

### 3.2 Where they fall short

**Evidence**

- **Conversation alone isn't enough to manage.** [Alexa's page](https://digprjsurvey.amazon.com/csad/help/node/TR10VgRL0uV9H384FM) offers voice edits "immediately after" creation, then points elsewhere. Gemini's non-time triggers [can be changed only in their thread](https://support.google.com/gemini/answer/17094710?hl=en&co=GENIE.Platform%3DAndroid). *(The Alexa page came from an odd Amazon host; amazon.com's own copy returned an error.)*
- **Too many words for one idea.** Google's help has to warn that "schedules for tasks" [differ from "scheduled actions"](https://support.google.com/gemini/answer/17094710?hl=en&co=GENIE.Platform%3DAndroid). Microsoft has Actions, Tasks, Cowork and Autopilot. Zapier renamed Agents.
- **Hidden side effects of off and delete.** Deleting a Gemini thread [deletes its schedules](https://support.google.com/gemini/answer/17094710?hl=en&co=GENIE.Platform%3DAndroid). Pausing a dot [doesn't stop its separate tasks](https://help.openai.com/en/articles/20001530-getting-started-with-your-dot).
- **Quiet cost.** A ChatGPT task can [use your allowance even when it posts nothing](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt).
- **Timing isn't reliable.** Gemini says monitors [aren't well suited to time-critical actions](https://support.google.com/gemini/answer/17094710?hl=en&co=GENIE.Platform%3DAndroid) and run times are approximate. The honest version of "boss email alerts" has to say the same.
- **The approval path breaks too.** An [n8n community report](https://community.n8n.io/t/human-review-before-ai-tool-works-in-n8n-2-6-0-but-does-not-execute-the-tool-in-2-27-5-hitl/304110) says approved calls stopped returning results after an upgrade (one thread; unconfirmed by n8n).

### 3.3 Take

**Judgment**

- **One word for the owner.** Playbook, recipe and watcher are ADR-011's engineering terms, and should stay there. The owner sees one thing (§9 decision 3), with its origin mark from ADR-019 saying whether it's on a schedule or watching.
- **The record, in plain words:** a sentence ("Every Friday at 6, summarise the lecture notes I added"), the steps as a list, what it may touch, and its last outcome. Voice edits this record at any time, not just straight after creating it.
- **Run once, then on,** with the first few runs reviewed (ADR-011 §5.1's dry run, plus OpenAI's advice).
- **Outcomes with reasons,** after Home Assistant: found something, found nothing, skipped (why), missed because the PC was off, waiting for your OK, failed at step N. Swift's local scheduling makes "missed while off" common, so it has to be first-class (ADR-011 §9 already offers missed runs on start).
- **Say what off means.** Pause, disable and delete each state what keeps going and what stays stored.
- **Show cost per item** in the record, as the usage report does overall.
- **A seam test for the approval path of standing work,** so an upgrade can't quietly break it.

### 3.4 Avoid

- **A node graph.** Confirms product direction §7. n8n and Zapier serve integrators, and the owner's workflows are short lists.
- **A timeout that continues.** Zapier lets a review [skip and carry on when it times out](https://help.zapier.com/hc/en-us/articles/38731463206029-Request-approval-to-keep-your-workflow-running-with-Human-in-the-Loop). In Swift a countdown never answers, and that stays.
- **Silent side effects.** Shortcuts lets some automations [run without asking or notifying](https://support.apple.com/guide/shortcuts/apd602971e63/ios). A Swift run that did something always reaches the record and at least the digest (§9 decision 7).
- **Plan-style caps as a design.** ChatGPT's 3 to 15 are pricing. For sprawl, ADR-011 §10's last-used date and an offer to archive are better.

### 3.5 Why this matters for reliability

**Evidence (weak).** Hands-on reports and forum posts say Alexa+ made routines, timers and batch commands less dependable. WIRED's reviewer reportedly found Alexa+ lacked basic reliability after a month; I could only read [a copy of that review](https://drwebdomain.blog/2026/03/08/why-is-alexa-so-bad-wired), not the original. [One analysis](https://smartscope.blog/en/blog/alexa-weaknesses-us-complaints-it-still-cannot-2026/) blames variable model output, which is a guess, not a finding. Others found it useful once configured.

**Judgment.** This is the cautionary case for Swift. Keep timers and other basics out of the model path, as Swift's lanes already do, and harden repeated work into recipes.

## 4. Discovery: learning what the assistant can do

### 4.1 What they do well

**Evidence**

- **Ask it, and the answer depends on where you are.** Voice Access has ["What can I say"](https://support.microsoft.com/en-us/topic/voice-access-command-list-dac0f091-87ce-454d-8d57-bef38d3d8563). Talon's [`help active`](https://talon.wiki/Basic%20Usage/basic_usage) shows what's available right now, and `command history` shows what it just heard.
- **Teach at the moment of failure.** Voice Access now [suggests commands based on your last words](https://support.microsoft.com/en-us/accessibility/windows/voice-access/history-of-voice-access-updates) when it doesn't recognise one. It also [accepts varied phrasing](https://blogs.windows.com/windowsexperience/2025/10/16/making-every-windows-11-pc-an-ai-pc/), with filler words and synonyms, on Copilot+ PCs. Its fixed command list stays as the reference.
- **Type a character, get a list.** [Raycast's `@`](https://manual.raycast.com/ai/ai-extensions) lists installed extensions and lets you chain them; Cowork has `/schedule`.
- **Explained by goal, with sentences to say.** Amazon's [feature guide](https://www.aboutamazon.com/news/devices/new-alexa-top-features) groups by questions like "How can I control my smart home?", with example commands.
- **Practice without consequences.** The Voice Access [guide](https://support.microsoft.com/en-US/Accessibility/windows/voice-access/get-started-with-voice-access) has instructions on the left and a practice area on the right.
- **Research.** Microsoft's [guidelines](https://www.microsoft.com/en-us/research/project/guidelines-for-human-ai-interaction/) open with making clear what the system can do, and how well. They end with telling people when it changes.

### 4.2 Where they fall short

**Evidence**

- **Memorising names.** NN/g's [2018 study](https://www.nngroup.com/articles/intelligent-assistant-usability/) found people had to remember exact skill names and phrases, that asking which skills were installed listed them one at a time, and that many users didn't know skills existed. It's old and predates today's models, but "you can't see what you can't see" hasn't changed.
- **Low expectations stick.** In the same study people kept to simple questions, and many felt finding the right phrasing wasn't worth the effort.
- **Long sheets.** Voice Access's list has [12 categories](https://support.microsoft.com/en-us/topic/voice-access-command-list-dac0f091-87ce-454d-8d57-bef38d3d8563). Talon's page calls its examples "a very small selection". Both suit dedicated users, not casual ones.
- **Silence from the biggest vendors.** Apple's [Siri AI release](https://www.apple.com/newsroom/2026/09/siri-ai-a-profoundly-more-capable-and-personal-assistant-is-here/) doesn't describe any way of learning what it can do. I also found nothing specific on Alexa+'s in-product discovery, so the gap may be mine.

### 4.3 Swift today

`what can you do` returns one fixed paragraph ([`session.py:222`](../../src/swift/session.py), matched at [`rules.py:76`](../../src/swift/routing/rules.py)). It can't say what's unavailable right now, and it doesn't mention workflows at all. ADR-019 has already decided the hint line: 3 times per hint, never on Needs your OK, and "What can you do here?" at any time.

### 4.4 Take

**Judgment,** in order of value for one owner:

1. **The nearest thing, when Swift can't do something.** "I can't read your email yet. I can draft one, or look at your calendar." It's the Voice Access lesson, and it teaches exactly when it's wanted. Daily use will show which refusals matter.
2. **Generate help from one source.** Each capability has a plain summary, two example sentences, and a live status (works now, needs sign-in, offline, not yet). Help, hints, offers and the window read that. This is a small early piece of ADR-011 §7.1's registry, and it stops help going stale.
3. **"What can you do here?"** answers for the card in front (already decided, not built).
4. **"What did you just hear?"**, after Talon. It explains a wrong result, and may help with the reliability work.
5. **A goal-grouped page in the Swift window,** with limits stated, including what Swift won't do and why.
6. **`@` in the typing box,** later: it lists workflows and capabilities with no new surface. It's only worth building once there are enough to list.
7. **One line when something changes** ("Swift can now…"), through the "while you were away" card.

### 4.5 Avoid

- **Tours and onboarding sequences.** One owner, and no evidence they'd help.
- **A skill store or gallery.** That's the Alexa skills problem at small scale.
- **Hints that interrupt or that sell.** ADR-019's limit of 3 stands.

## 5. Settings, accessibility and personalisation

### 5.1 What they do well

**Evidence**

- **Permission set beside the work.** Cowork's [selector sits in the message box](https://support.claude.com/en/articles/16761823-claude-cowork-and-chat-are-one-claude) and applies to the conversation. Raycast's [global setting can be overridden per chat](https://manual.raycast.com/ai/ai-extensions).
- **Per-action rules in plain words.** A dot's [custom rules](https://help.openai.com/en/articles/20001530-getting-started-with-your-dot) offer four behaviours: take action without asking, take action if pre-approved (meaning you asked for it in your prompt), ask first, or hand off to you. The closest parallel to Swift's planned policy table.
- **Asking the assistant what it knows.** Microsoft's [privacy page](https://support.microsoft.com/en-us/microsoft-copilot/microsoft-copilot-privacy-controls) suggests asking Copilot directly. ChatGPT has a [memory summary and saved memories you can edit](https://help.openai.com/en/articles/8590148-memory-in-chatgpt). Claude offers [a box to say what to change](https://support.claude.com/en/articles/12123587-import-and-export-your-memory-from-claude).
- **Style as a named choice.** Alexa+ offers [styles including Brief](https://www.aboutamazon.com/news/devices/new-alexa-generative-artificial-intelligence). Gemini has [instructions that apply to every chat](https://support.google.com/gemini/answer/16598625?hl=en&co=GENIE.Platform%3DAndroid).
- **Learnt from feedback on one item.** Daily Brief items have [Mark complete, Dismiss, Helpful, Not helpful](https://support.google.com/gemini/answer/17077455?hl=en&co=GENIE.Platform%3DAndroid).
- **Simple local customising.** Talon's [`customize` commands](https://talon.wiki/Basic%20Usage/basic_usage) open a CSV to edit, which is close to Swift's plain-file approach.

**Accessibility evidence**

- **Distinct, visible listening states.** Voice Access has [listening, sleep (ignores all but the wake-up) and microphone off](https://support.microsoft.com/en-US/Accessibility/windows/voice-access/get-started-with-voice-access), each reachable by voice, click or key. Talon has [modes and a mode indicator](https://talon.wiki/Basic%20Usage/basic_usage). Halo's presence axes already match this.
- **Adjusting to the speaker.** Voice Access has [a wait time before acting](https://support.microsoft.com/en-US/Accessibility/windows/voice-access/get-started-with-voice-access). Apple's [Vocal Shortcuts and Listen for Atypical Speech](https://support.apple.com/guide/mac-help/mchlf4548bb6) run on the device and suit people who can reliably say only certain sounds.
- **Targets you can say.** Voice Access's [numbers and grids](https://support.microsoft.com/en-us/topic/voice-access-command-list-dac0f091-87ce-454d-8d57-bef38d3d8563) make anything on screen addressable.
- **Standards.** WCAG [2.2.1 Timing Adjustable](https://www.w3.org/WAI/WCAG22/Understanding/timing-adjustable.html) asks that a time limit can be turned off, adjusted over ten times its default, or extended. [4.1.3 Status Messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html) asks that status reaches assistive technology without taking focus. WCAG is written for the web, with [guidance for applying it to other software](https://www.w3.org/TR/wcag2ict-22/), and Swift doesn't have to claim conformance. It's a useful checklist.

### 5.2 Where they fall short

**Evidence**

- **Off doesn't mean gone.** Turning off Copilot's saved memories [doesn't delete them](https://support.microsoft.com/en-us/topic/manage-copilot-memory-in-microsoft-365-copilot-b3231eae-9e60-4b3c-ac58-81fddbe56279). Disconnecting an app from a dot [doesn't delete what it learned](https://help.openai.com/en/articles/20001530-getting-started-with-your-dot), and clearing a dot's own memories means deleting the dot. In Gemini, deleting something remembered [means deleting the chats that hold it](https://support.google.com/gemini/answer/16598625?hl=en&co=GENIE.Platform%3DAndroid).
- **Memory from what it read.** A dot can [form memories from connected apps without being asked](https://help.openai.com/en/articles/20001530-getting-started-with-your-dot). **Swift's product rule forbids this,** and this is a clear difference to keep.
- **Settings scattered and uneven.** Microsoft's own Q&A shows people [unable to find the memory toggle](https://learn.microsoft.com/en-us/answers/questions/5529647/unable-to-find-personalization-and-memory-toggle-i). Paths differ by app.
- **A trust-everything switch.** Cowork's [Skip](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork) and Raycast's [Always Allow](https://manual.raycast.com/ai/ai-extensions) both exist with warnings attached.
- **Recall.** Microsoft had to [make it opt-in and tie it to Windows Hello](https://blogs.windows.com/windowsexperience/2024/06/07/update-on-the-recall-preview-feature-for-copilot-pcs/) after criticism, then [re-architect it](https://blogs.windows.com/windowsexperience/2024/09/27/update-on-recall-security-and-privacy-architecture/). It supports ADR-011 §12's strict L3 terms.

### 5.3 Swift today

- **Good:** `forced-colors` and `prefers-reduced-motion` are in the code ([`styles.css:957`](../../overlay/src/styles.css), [`:969`](../../overlay/src/styles.css)), live regions are declared on the card, deck and capsule ([`index.html:13`](../../overlay/index.html)), and every state mark has a word (`SPEC.md` §13).
- **Gap: no keyboard path to a card.** The overlay window is `focusable: false` ([`tauri.conf.json:25`](../../overlay/src-tauri/tauri.conf.json)), and only the typing box takes the keyboard (ADR-015 §10). So Approve needs a mouse or a spoken "Swift, yes". I read the code and didn't test it. An owner whose microphone misbehaves and whose hands are on the keyboard has to reach for the mouse.
- **Unverified on the real PC:** whether Narrator reads a non-activating overlay's live regions; whether Magnifier and screen tools show a capture-excluded window ([`lib.rs:2`](../../overlay/src-tauri/src/lib.rs)); whether Voice Access's numbers can reach it; and what happens with Voice Access listening at the same time. No owner check covers these. `SPEC.md` §13 covers only the visual side.
- **Timing:** a confirm card's 45 s isn't adjustable (handoff §5 decision 3, and the open X-17 question on long cards). Running out is safe, because the card goes to the stack. That protects the action, but a slow reader still loses the card from the screen.

### 5.4 Take

**Judgment**

- **Settings by voice first, for the few that matter.** "Speak less", "stop reading answers", "quiet for an hour". These are small, match the owner's principle, and each returns a card with Undo. The store comes from groundwork, so they needn't wait for the window (§9 decision 5).
- **Asymmetric voice on autonomy.** By voice, Swift can become more careful ("always ask before writing in Word"). Becoming less careful stays in the window, as product direction §7 says (§9 decision 4).
- **Show the floors.** In What Swift may do, product-rule rows appear locked: "Sending to someone not in contacts: never. Swift's rule." Vendors keep this kind of rule out of view; for Swift it's the differentiator.
- **Four behaviours rather than three.** Product direction §8.3's "do, ask, never" gains "do it if I asked in my own words", which is what Swift's writing rule already is. It's a useful level for writing into apps and for files.
- **Precise words for off.** "Forget" says what's removed. "Pause" says what still runs. Swift's one-file-per-memory store makes this easy where others can't.
- **A patience setting** for cards: as now, or don't time out (the card stays until answered). Halo's "Due" state already shows a card can stay.
- **Real-PC accessibility checks** added to the Halo look checks (R2).
- **A keyboard route to the card,** which touches a product rule: see §9 decision 2.
- **"Wait a little longer before acting"** as a plain setting, in the Listening group.

### 5.5 Avoid

- **Skip-style or Always Allow on a card.** One tap to trust forever defeats the ladder. Rung 4 stays in the window (ADR-019 §3 item 8).
- **Personality and characters.** Dots offer pets, Alexa+ has Sassy. Style beyond length isn't where Swift's value lies. "Brief" is the one worth having.
- **Showing internals as settings.** Product direction §6.2 stands.

## 6. Consent, proactive behaviour and long-running work

### 6.1 What they do well

**Evidence**

- **Vendors agree on what must ask.** Copilot Tasks [asks](https://support.microsoft.com/en-us/microsoft-365-copilot/using-copilot-tasks) for money, personal data to external sites, anything involving other people, account changes including deleting files, and sensitive submissions. Spark [asks before spending money or sending emails](https://blog.google/innovation-and-ai/products/gemini-app/next-evolution-gemini-app/). Cowork [always asks before a permanent delete](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork). This supports ADR-019's rule and Swift's other floors.
- **Read runs, write asks.** Microsoft [cut confirmation prompts for read-only actions](https://learn.microsoft.com/en-us/microsoft-365/copilot/release-notes). Claude's [Auto tiers](https://www.anthropic.com/engineering/claude-code-auto-mode) let reads run and treat project edits as reviewable through version control. [n8n](https://blog.n8n.io/human-in-the-loop-vs-human-on-the-loop/) advises gating only what's high-risk or irreversible.
- **Prefer a draft to a send.** [Zapier's advice](https://zapier.com/blog/safe-trustworthy-ai-agents/) is to create a draft rather than send. Swift's `email-draft` already works this way (ADR-011 §14).
- **Letting the reviewer edit.** [Zapier reviewers can change content](https://help.zapier.com/hc/en-us/articles/38731463206029-Request-approval-to-keep-your-workflow-running-with-Human-in-the-Loop) before approving. Swift's "Change" verb does this by voice (ADR-011 §15).
- **Pause for an OK while unattended.** ChatGPT says approval-needing actions [may pause the task](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt), and that a task that stops responding may have a pending approval. Copilot may [ask for approvals during setup](https://support.microsoft.com/en-us/microsoft-365-copilot/using-copilot-tasks) so a recurring task can run alone. Shortcuts offers [per-automation ask and notify switches](https://support.apple.com/guide/shortcuts/apd602971e63/ios) and limits which triggers can run without asking: a floor set by kind of trigger.
- **Trust at the right size.** [Anthropic's data](https://www.anthropic.com/research/measuring-agent-autonomy): experienced users auto-approve more (about 20% of sessions rising to over 40%) and also interrupt more (5% rising to 9% of turns). Its conclusion is that oversight doesn't require approving every step, and needs good visibility and simple ways to intervene.
- **Stops and scale limits built in.** Zapier [pauses for review at 75 tasks in one AI step](https://zapier.com/blog/safe-trustworthy-ai-agents/).
- **Long work you can check on.** Copilot Tasks shows [steps, sites and interim results](https://support.microsoft.com/en-us/microsoft-365-copilot/using-copilot-tasks) and lets you stop, take over, pause or edit. Microsoft 365 [shows long-running agents' status on the taskbar](https://learn.microsoft.com/en-us/microsoft-365/copilot/release-notes) and pushes approvals, questions and completions. Cowork shows [a plan and each step](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork), and lets you steer mid-task. OpenAI's Watch Mode [pauses when you look away from a sensitive site](https://deploymentsafety.openai.com/chatgpt-agent/watchmode) (2025 system card; the feature's status is unclear, see §10).
- **Digest as a shape.** Daily Brief is [opt-in, split into Top of mind and Looking ahead](https://support.google.com/gemini/answer/17077455?hl=en&co=GENIE.Platform%3DAndroid), with actions per item.

### 6.2 Where they fall short

**Evidence**

- **People approve nearly everything.** [93%](https://www.anthropic.com/engineering/claude-code-auto-mode) or [97%](https://claude.com/resources/articles/auto-mode-default-in-claude-code) of Claude Code prompts, in two Anthropic figures I can't reconcile. In its [study of 1,053 paid testers](https://claude.com/resources/articles/auto-mode-default-in-claude-code), people caught 13.6% of planted dangerous commands, against 89% for the classifier. Vigilance fell from about 17% to about 5% over a session. **Caveats:** the author sells the classifier, the setting was coding in a test environment, and I found no independent replication.
- **Automatic checks have limits too.** The same vendor reports [a 17% false-negative rate on real overeager actions](https://www.anthropic.com/engineering/claude-code-auto-mode), and that the classifier often sees the danger but misjudges whether an earlier approval covered it. It says this is no replacement for human review on high-stakes work.
- **Agent-written descriptions on the approval card.** Raycast [warns that its card's description is AI-generated](https://manual.raycast.com/ai/ai-extensions), and tells users to check it. Swift draws facts from the action itself, which is the better design.
- **Defaults moving to autonomy.** Auto is [the default on Claude's Pro, Max, Ultra and Team plans](https://support.claude.com/en/articles/16761823-claude-cowork-and-chat-are-one-claude). A dot [can review connected apps proactively](https://help.openai.com/en/articles/20001530-getting-started-with-your-dot), and enterprise admins can't separately turn off its proactive research.
- **Prompt injection remains open.** Microsoft [names cross-prompt injection as the main risk](https://support.microsoft.com/en-us/windows/ai/ai-features/experimental-agentic-features) of its agents, and warns of data theft and malware.
- **Heavy gates for enabling agents.** Copilot's agent workspace [needs an administrator and applies to every user on the device](https://support.microsoft.com/en-us/windows/ai/ai-features/experimental-agentic-features).
- **Time-outs that decide.** Zapier's "On timeout" can continue. See §3.4.
- **No word on Siri.** Apple's [release](https://www.apple.com/newsroom/2026/09/siri-ai-a-profoundly-more-capable-and-personal-assistant-is-here/) doesn't describe confirmation at all. A [secondary source](https://apple.gadgethacks.com/news/siri-ai-app-actions-on-iphone-still-need-developer-support/) says app actions still depend on developers adopting App Intents.

### 6.3 Take

**Judgment**

- **Treat cards as a limited budget.** The study's slope suggests each extra card lowers attention on the next. Keep the floors, and don't add cards for reversible or read-only steps. This supports the ladder (ADR-019) and the Yes/No for reversible changes that the owner already chose.
- **Measure attention locally.** Cards per real day, approval rate, seconds on a card before answering, and approved-then-undone, all counts only. A sudden rise in cards or a fall in seconds is a warning sign. I don't know what thresholds are right: this needs daily use first (R3).
- **Don't borrow a classifier as a replacement for consent.** A classifier could add a second check behind a card, never remove the card. The product rules aren't a tradeoff here, and 17% misses on overeager actions wouldn't justify it anyway.
- **Unattended means pause, then wait.** A standing run that reaches a consequential step stops at that step, saves what it did, and goes to Waiting for you. Setup-time grants follow rung 3 and only for narrow scopes (ADR-019). The floors still ask, including the delete rule. `digest.send_self` stays the one narrow exception already decided (ADR-011 §13.4).
- **Per-item "tell me how".** Each standing item has one setting in the words of ADR-019's urgency: at the next break, in the digest, or record only (for runs that found nothing). Runs that acted can't be record-only.
- **The digest card is a list of items, each answerable:** open, done, not interesting. Two sections at most, and "less like this" feeds the review job as a proposal, never a silent change.
- **A budget stop for watchers and long runs,** after Zapier: a limit per run and per day, pausing with a card rather than failing.
- **Toasts as doorbells only.** A Windows toast may say something waits, and opens the card. It never approves and shows no consequential content on a locked screen. I didn't find product evidence on this: it follows from Swift's own rules. Notifications at rest (step 4) should say so.
- **Plain limits for scheduled work.** "Swift works while your PC is on" should be said once when a watcher is created, and shown as "missed while off" afterwards. Rivals run in the cloud, so this is a real difference, and honest wording makes it a choice, not a surprise.
- **Evidence on the delete question (ADR-019 §7 item 2, decided at W2):** every vendor's page reviewed asks before a permanent delete, and Copilot lists deleting files among its asks. From general Windows knowledge, not checked here: very large files and network drives can skip the Recycle Bin. So if a Bin move ever counts as reversible, Swift must verify it reached the Bin. My suggestion is to keep asking, on one card covering the whole batch.

### 6.4 Avoid

- **Agents that decide on their own what to look at.** A dot's proactive review needs broad standing access and creates memory from content. Swift's watchers run only what the owner set up, and memory stays from the owner's words.
- **A separate agent desktop** (already in `DIRECTION.md` §3.3). Note the cost: without one, Swift needs the visible "Writing in Word" with Stop (§5.9 there), and Watch Mode suggests pausing when the owner takes over.
- **A chat transcript as the record.** Unifying everything in one chat list ([Claude](https://support.claude.com/en/articles/16761823-claude-cowork-and-chat-are-one-claude)) suits a chat product. Swift's unit stays the run.

## 7. Recommendations, in priority order

These add to the order of work. Only R9, R11 and R13 change timing, and they're marked. **P1** means cheap and useful now, **P2** arrives with the named step, and **P3** waits for its trigger.

| # | P | Recommendation | Mainly from | Where it fits (handoff §4) | Decisions it touches |
|---|---|---|---|---|---|
| R1 | P1 | **Refresh the case for Swift.** Add a dated note to product direction §2 and `DIRECTION.md` §3.2 and §9, with findings 1 and 2 of §0, and restate the six-week test against what rivals do now | §0, §6 | Docs, now | Updates product direction §2.1, §2.2 and `DIRECTION.md` §9; nothing built changes |
| R2 | P1 | **Accessibility checks on the real PC:** Narrator on a card, Magnifier and capture exclusion, Voice Access side by side, 150% and 200% scale. Check, don't fix yet | §5.3 | With Halo's real-PC checks (ADR-019 §5 step 2) and `SPEC.md` §13 | None |
| R3 | P1 | **Add approval counts to the usage report:** cards per real day, approval rate, seconds on a card, approved-then-undone. Counts only | §6.3 | Step d. Log only timings and counts | Keeps logs content-free. Check the fields against the allow-list |
| R4 | P1 | **The nearest thing when Swift can't,** and "what did you just hear?". Use refusals seen in daily use to choose wording | §4.4 | After d's first report, small | ADR-019 §7 item 3 (hints): these are answers, not hints, so they don't count towards its limit. Say if you disagree |
| R5 | P2 | **Outcome with a reason on every run record,** plus next run and cost for standing items. Goes with `origin` (N2) | §3.3 | Groundwork: run records | Extends ADR-019 §4. No conflict |
| R6 | P2 | **Policy table with four behaviours and locked rows for the floors** | §5.4 | Groundwork: settings store. Shown in step 7 | Refines product direction §8.3 item 5 (three levels). Floors unchanged |
| R7 | P2 | **One capability source:** summary, examples, live status. Help, hints and offers read it | §4.4 | Groundwork, small. A subset of W2's registry | Brings forward part of ADR-011 §7.1 and §11's W2. Risk classes and scopes stay in W2 |
| R8 | P2 | **Standing-work rules:** run once before on, pause at a needed OK, budget stop, plain "PC on" wording, "what off means" | §3.3, §6.3 | Step 5 | Matches ADR-011 §5.1, §9, §13. ADR-019 §5: run grants still arrive with W2, so a watcher can't use one yet |
| R9 | P2 | **A small Standing list from step 5:** by voice ("what's running on its own?", "pause the news") and a tray list, with pause, last outcome and run now. **Changes timing** | §3.2 | Moves part of step 7 into step 5 | ADR-011 §6.2 already has a tray list. `DIRECTION.md` §6.6 places Standing in the window, and this is only a stop-gap. §9 decision 6 |
| R10 | P2 | **Digest and "while you were away" as answerable items** | §6.3 | Step 4 | Fits ADR-019 §3 item 12 |
| R11 | P2 | **Three settings by voice before the window:** speech length, read aloud, quiet for an hour. **Changes timing** | §5.4 | Moves from "then" in step 7 to right after the store | Reverses product direction §8.2 items 11 and 12. §9 decision 5 |
| R12 | P2 | **A workflow's record:** sentence, steps, permissions, last outcome; voice edits at any time; one owner-facing word | §3.3 | Steps 6 and 7 | Keeps ADR-011's terms internally. §9 decision 3 |
| R13 | P2 | **Try rivals before building the digest.** A week of a tech-news digest in ChatGPT or Gemini, while doing daily use. **Could change step 5's scope** | §0 | During d | Handoff §5 decision 22, §9 decision 1 |
| R14 | P3 | **"What Swift knows" with exact words for forget and off,** and "less like this" as proposals | §5.2 | Step 7, review job (§5.6) | Fits product direction §5.5 |
| R15 | P3 | **Patience setting and keyboard route.** See §9 decisions 2 and 8 | §5.4 | Halo Step B or step 7 | **The keyboard route touches a product rule** |
| R16 | P3 | **Goal-grouped capability page; `@` in the typing box;** a line when something changes | §4.4 | Step 7 and later | None |
| R17 | P3 | **Replay a failed run's inputs on the fixed version, with tools faked,** and approvals never reused | §3.1 | W3 onwards | Matches ADR-011 §4 `tests/` and digest-bound approval |

## 8. Where this touches what's decided

### 8.1 Product rules

I don't recommend trading any of them. Three places come close, and they're for the owner and a second reviewer:

- **Typing never approves:** a keyboard route to Approve (§9 decision 2) is arguably a different thing from typing, but that's a judgment on the rule's edge, not mine to settle.
- **Memory only from the owner's words:** "less like this" and "not interesting" on digest items are the owner's own acts. They may tune ranking directly only if the owner accepts that as approval. As written, they become proposals on a card.
- **Deleting a file always asks:** per-item standing permissions must not cover it. R6's locked rows make that visible.

**Rivals do things these rules forbid:** forming memories from connected apps (dot), one-tap always-allow (Raycast), a skip mode (Cowork). I'd treat those as differences to keep, not gaps.

### 8.2 Decisions this partly reopens

| Decision | What changes | Recommendation |
|---|---|---|
| Product direction §2.1, §2.2 | "No assistant does watchers well", "no owner-defined rules", and the Copilot row are dated | Note it (R1). The adopted direction stands, with its reason restated |
| `DIRECTION.md` §3.2, §9 | "Unrequested feeds didn't stick" is overstated. The ADR-019 decisions built on it stand, since they rest on owner-defined work and timing | Note it (R1) |
| Product direction §8.3 item 5 | Three levels become four | R6 |
| Product direction §8.2 items 11, 12; handoff step 7 | Voice settings before the window | R11, §9 decision 5 |
| Handoff steps 5 and 7; `DIRECTION.md` §6.6 | A small Standing list before the window | R9, §9 decision 6 |
| Product direction §7 (autonomy only in settings) | Voice may lower autonomy, never raise it | §9 decision 4 |
| ADR-019 §7 item 3 (hints) | Failure suggestions aren't counted as hints | R4 |
| ADR-019 §5 (run grants arrive with W2) | Nothing changes; R8 is worded to respect it | None |

**Confirmed by this research, no change:** no node graph (product direction §7), thin runtime and n8n only as a capability (ADR-011 §12), playbook-to-recipe (ADR-011 §3), L3 only by strict opt-in (ADR-011 §12), workers never draw and Swift draws facts (ADR-019), plan card and ladder (ADR-019), the delete rule, and the 2-minute deferral, which the products reviewed neither support nor contradict.

## 9. Decisions for the owner

Each has a recommendation; "unsure" is a fine answer, and the default holds meanwhile.

| # | Decision | Why it's open | Recommendation | Until you choose |
|---|---|---|---|---|
| 1 | **Try a rival's digest during daily use?** A week of tech news in ChatGPT or Gemini before Swift builds its own | They already do it. If it's good enough, step 5 can concentrate on boss emails, where Swift's metadata-only, local matching is a real difference. Gemini's tasks aren't offered in some regions, including the UK and EEA | **Yes, tech news only.** Don't connect mail to try it. Choose the handoff's decision 22 (first watchers) afterwards | Step 5 as planned |
| 2 | **A keyboard route to Approve?** A separate shortcut brings the card forward, and a deliberate key press acts on it | Today Approve needs a mouse or a working microphone. **It touches "typing never approves."** The rule's concern (a stray "yes" or Enter) can be met by never using Enter or letters, but it's your rule | **Yes in principle, with a separate review of the design.** It needs a chord that can't happen while typing | Mouse or voice only |
| 3 | **One word for repeating and watching work** | ADR-011's words are internal. "Routines" is familiar from Alexa and Google, "Automations" sounds technical, "Scheduled" misses watchers | **"Routines"** | Internal terms only |
| 4 | **Voice may make Swift more careful, never less?** | Product direction §7 keeps autonomy in settings. Lowering it by voice can't cause harm beyond more cards | **Yes** | Settings only |
| 5 | **Voice settings before the window?** | They're small and they fit "Swift adapts to the user", but the order was adopted the other way | **Yes,** after the settings store | Step 7 order |
| 6 | **A small Standing list before the window?** | Watchers arrive at step 5 and management at step 7, so standing work would have no way to pause except voice phrases not yet built | **Yes.** Voice plus tray only | Step 7 |
| 7 | **May a run that acted ever be silent?** | Shortcuts allows it. Swift's trust story says no | **No.** A run that acted always reaches the record and the digest | No silent acts, as nothing like this exists yet |
| 8 | **A "don't time out" setting for cards?** | A card that runs out already moves to the stack safely, and this joins the handoff's decision 3 and the X-17 long-card question | **Yes, off by default,** and settle all three together | Unchanged |
| 9 | **Add the dated notes to the two documents?** | R1 edits adopted documents, so I've left them alone | **Yes** | Unedited; this document holds the corrections |

**One thing worth watching rather than deciding:** dots began rolling out this week. If "an always-on agent you give goals to" works, it's the closest thing yet to Swift's vision, from a vendor with far more reach. The test in product direction §9 ("do you still reach for something else?") is the right response, and the two weeks of daily use still come first.

## 10. Not established

Things I looked for and couldn't confirm. Say "unverified" about them.

- **How Siri AI confirms actions:** Apple's release doesn't say. Secondary sources were unreliable, and one had clear errors.
- **Alexa+'s in-product discovery, and its current confirmation behaviour.** Only example flows on a marketing page.
- **Whether ChatGPT agent is retired.** `DIRECTION.md` calls it "former". A [forum post](https://community.openai.com/t/agent-mode-missing-across-all-platforms-on-pro-account/1387374) quotes help text saying so. The help page timed out when I opened it, and the indexed copy is older. So Watch Mode's current status is unknown too.
- **What Pulse's retirement really shows.** OpenAI's words come through secondary reports. I didn't read its original post, and no usage figures are public as far as I found.
- **Whether the approval study applies to a voice assistant's cards.** Coding commands are harder to judge than "email Ada at 3". Swift's cards may do better, or may suffer equally. R3 gives a local signal, but not a measure of catching mistakes.
- **Copilot's voice consent and proactive behaviour.** Not found.
- **Academic work on voice discovery.** I confirmed that [Cowan et al. 2017](https://cora.ucc.ie/items/726c2474-9631-4cb8-94b7-a052f6c58f3d) and Luger and Sellen 2016 exist, but didn't read them, so I rely on neither. Worth reading if discovery becomes a focus.
- **How anything here behaves on Swift's own overlay with assistive technology.** That's R2.

## Sources

Read on 2026-11-07. **Text:** page text read directly, cut off before the end. **Fetch:** read through a summarising fetch. **Snippet:** seen only as search results. **Secondary:** not the vendor.

**OpenAI**
- [Scheduled tasks in ChatGPT](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt) (Text; "updated 7 days ago")
- [Getting started with your dot](https://help.openai.com/en/articles/20001530-getting-started-with-your-dot) (Text; "updated 18 hours ago")
- [Automations / Scheduled tasks in Codex](https://learn.chatgpt.com/docs/automations) (Fetch)
- [Memory in ChatGPT](https://help.openai.com/en/articles/8590148-memory-in-chatgpt) (Snippet)
- [ChatGPT agent system card: Watch Mode](https://deploymentsafety.openai.com/chatgpt-agent/watchmode) (Snippet; 2025)
- [OpenAI is retiring Pulse](https://www.digit.in/news/general/openai-is-retiring-chatgpt-pulse-and-replacing-it-with-scheduled-tasks-here-is-why.html) (Fetch; Secondary, quoting OpenAI, June 2026)
- [Forum post on agent mode's retirement](https://community.openai.com/t/agent-mode-missing-across-all-platforms-on-pro-account/1387374) (Snippet; Secondary)

**Anthropic**
- [Get started with Claude Cowork](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork) (Fetch)
- [Claude Cowork and chat are one Claude](https://support.claude.com/en/articles/16761823-claude-cowork-and-chat-are-one-claude) (Fetch)
- [Import and export your memory](https://support.claude.com/en/articles/12123587-import-and-export-your-memory-from-claude) (Snippet)
- [Measuring AI agent autonomy in practice](https://www.anthropic.com/research/measuring-agent-autonomy) (Fetch; Feb 2026)
- [How we built Claude Code auto mode](https://www.anthropic.com/engineering/claude-code-auto-mode) (Fetch; Mar 2026)
- [Auto mode is now the default](https://claude.com/resources/articles/auto-mode-default-in-claude-code) (Fetch; Aug 2026, updated Oct 2026; vendor's own study)

**Google**
- [Create and manage schedules for tasks](https://support.google.com/gemini/answer/17094710?hl=en&co=GENIE.Platform%3DAndroid) (Fetch)
- [The Gemini app becomes more agentic](https://blog.google/innovation-and-ai/products/gemini-app/next-evolution-gemini-app/) (Fetch; May 2026)
- [Get started with your daily brief](https://support.google.com/gemini/answer/17077455?hl=en&co=GENIE.Platform%3DAndroid) (Fetch)
- [Create a flow with Gemini](https://support.google.com/workspace-studio/answer/16448469?hl=en) (Fetch)
- [Manage what Gemini remembers](https://support.google.com/gemini/answer/16598625?hl=en&co=GENIE.Platform%3DAndroid) (Snippet)

**Microsoft**
- [Using Copilot Tasks](https://support.microsoft.com/en-us/microsoft-365-copilot/using-copilot-tasks) (Fetch)
- [Experimental agentic features](https://support.microsoft.com/en-us/windows/ai/ai-features/experimental-agentic-features) (Fetch; updated Dec 2025, may be dated)
- [Copilot on Windows release notes](https://learn.microsoft.com/en-us/windows-insider/release-notes/apps/copilot-on-windows) (Fetch; Aug 2026)
- [Microsoft 365 Copilot release notes](https://learn.microsoft.com/en-us/microsoft-365/copilot/release-notes) (Snippet; a different product from consumer Copilot)
- [Manage Copilot Memory](https://support.microsoft.com/en-us/topic/manage-copilot-memory-in-microsoft-365-copilot-b3231eae-9e60-4b3c-ac58-81fddbe56279) and [privacy controls](https://support.microsoft.com/en-us/microsoft-copilot/microsoft-copilot-privacy-controls) (Snippet)
- [Q&A: unable to find the toggle](https://learn.microsoft.com/en-us/answers/questions/5529647/unable-to-find-personalization-and-memory-toggle-i) (Snippet; anecdotal)
- [Recall update, June 2024](https://blogs.windows.com/windowsexperience/2024/06/07/update-on-the-recall-preview-feature-for-copilot-pcs/) and [Recall architecture, Sept 2024](https://blogs.windows.com/windowsexperience/2024/09/27/update-on-recall-security-and-privacy-architecture/) (Snippet)
- [Voice access command list](https://support.microsoft.com/en-us/topic/voice-access-command-list-dac0f091-87ce-454d-8d57-bef38d3d8563) and [Get started](https://support.microsoft.com/en-US/Accessibility/windows/voice-access/get-started-with-voice-access) (Fetch)
- [History of voice access updates](https://support.microsoft.com/en-us/accessibility/windows/voice-access/history-of-voice-access-updates) and [Making every Windows 11 PC an AI PC](https://blogs.windows.com/windowsexperience/2025/10/16/making-every-windows-11-pc-an-ai-pc/) (Snippet)
- [Guidelines for Human-AI Interaction](https://www.microsoft.com/en-us/research/project/guidelines-for-human-ai-interaction/) (Snippet; CHI 2019)

**Apple**
- [Siri AI is here](https://www.apple.com/newsroom/2026/09/siri-ai-a-profoundly-more-capable-and-personal-assistant-is-here/) (Fetch; Sept 2026)
- [Use Apple Intelligence in Shortcuts](https://support.apple.com/guide/shortcuts-mac/mchl91750563/mac) (Fetch)
- [Personal automations in Shortcuts](https://support.apple.com/guide/shortcuts/apd602971e63/ios) (Snippet; options vary by trigger and version)
- [Vocal Shortcuts and atypical speech](https://support.apple.com/guide/mac-help/mchlf4548bb6) (Snippet)
- [Siri AI app actions need developer support](https://apple.gadgethacks.com/news/siri-ai-app-actions-on-iphone-still-need-developer-support/) (Snippet; Secondary)

**Amazon**
- [About Routines by Voice with Alexa+](https://digprjsurvey.amazon.com/csad/help/node/TR10VgRL0uV9H384FM) (Fetch; an unusual Amazon host, since amazon.com's copy returned 503)
- [What can Alexa+ do?](https://www.aboutamazon.com/news/devices/new-alexa-top-features) (Fetch; undated)
- [Introducing Alexa+](https://www.aboutamazon.com/news/devices/new-alexa-generative-artificial-intelligence) (Snippet)
- [Copy of WIRED's review](https://drwebdomain.blog/2026/03/08/why-is-alexa-so-bad-wired) and [complaints analysis](https://smartscope.blog/en/blog/alexa-weaknesses-us-complaints-it-still-cannot-2026/) (Snippet; Secondary; anecdotal)

**Raycast, Zapier, n8n, Home Assistant, Talon**
- [Raycast AI Extensions](https://manual.raycast.com/ai/ai-extensions) (Fetch)
- [Zapier Human in the Loop](https://help.zapier.com/hc/en-us/articles/38731463206029-Request-approval-to-keep-your-workflow-running-with-Human-in-the-Loop) (Fetch)
- [Zapier Agents is now AI by Zapier](https://zapier.com/blog/zapier-agents-is-now-ai-by-zapier/) (Fetch; undated)
- [Safe and trustworthy agents with Zapier](https://zapier.com/blog/safe-trustworthy-ai-agents/) (Fetch; Aug 2026)
- [Zapier: special step run statuses](https://help.zapier.com/hc/en-us/articles/38838306755981-Special-step-run-statuses-in-Human-in-the-Loop-actions) (Fetch)
- [n8n human-in-the-loop for tools](https://docs.n8n.io/advanced-ai/human-in-the-loop-tools/) (Fetch)
- [n8n debug and re-run](https://docs.n8n.io/workflows/executions/debug/) (Snippet)
- [HITL vs HOTL](https://blog.n8n.io/human-in-the-loop-vs-human-on-the-loop/) (Fetch; Apr 2026)
- [n8n forum report on approvals](https://community.n8n.io/t/human-review-before-ai-tool-works-in-n8n-2-6-0-but-does-not-execute-the-tool-in-2-27-5-hitl/304110) (Snippet; unconfirmed)
- [Home Assistant: troubleshooting automations](https://www.home-assistant.io/docs/automation/troubleshooting/) (Fetch) and [testing automations](https://www.home-assistant.io/docs/automation/testing/) (Snippet)
- [Talon basic usage](https://talon.wiki/Basic%20Usage/basic_usage) (Fetch; community wiki)

**Standards and research**
- [WCAG 2.2.1 Timing Adjustable](https://www.w3.org/WAI/WCAG22/Understanding/timing-adjustable.html) (Fetch)
- [WCAG 4.1.3 Status Messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html) and [WCAG2ICT](https://www.w3.org/TR/wcag2ict-22/) (Snippet)
- [NN/g: Intelligent Assistants Have Poor Usability](https://www.nngroup.com/articles/intelligent-assistant-usability/) (Fetch; 2018, predates today's models)
