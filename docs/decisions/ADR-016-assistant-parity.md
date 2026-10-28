# ADR-016: Closing the gap with a built-in assistant (proposal)

- **Status:** Proposed; **Phases A and B are built** (A1 §13, A2 §14, B §15; approved 2026-10-28). The rest needs the owner's go-ahead per phase and the decisions in §11.
- **Date:** 2026-10-27
- **Builds on:** ADR-007 (lanes), ADR-010 (gateway, artifacts), ADR-011 (workflows, connectors), ADR-012 (desktop), ADR-013 (attention), ADR-014 (presence)

## 1. Context

Asked how Swift differs from Siri, the answer was seven gaps. The owner's reply: all of them matter, **system actions without a model (3) most**, and the goal is to make the gap *virtually non-existent*. The owner then asked that the plan be checked against the **latest Siri** and the **latest repository**; §1.1 and §1.2 record that check.

### 1.1 Siri as it is today (checked 2026-10-27)

The benchmark moved. Siri is no longer a command-and-control assistant: **Siri AI** (Gemini-based Apple Foundation Models, on device and on Private Cloud Compute) shipped with iOS 27 / macOS 27 on 2026-09-14 and is **still a beta**: English first (French, Japanese, Korean, Portuguese and Spanish added 2026-10-26), a waitlist on first enrolment, daily usage limits on server-side features, newer devices only, not in the EU on iOS/iPadOS/watchOS, not in China.

What Apple lists for it:

| Area | Siri AI | Source |
|---|---|---|
| **Conversation** | Extend almost any answer into a chat; a dedicated Siri app with searchable, pinnable, resumable history synced by iCloud; *Siri Recap* (title and key points, beta later in 2026) | Apple newsroom, Sep 2026 |
| **Personal context** | A semantic Spotlight index across Messages, Mail, Photos, Notes, Reminders, Calendar and Files, extended to third-party apps ("find the hotel confirmation number") | Apple newsroom, Jun and Sep 2026; Apple Support |
| **On-screen awareness** | Answers about, or acts on, what is on screen ("add these home games to my calendar"); on Mac a keyboard shortcut selects part of the screen and asks; Control-click "Ask Siri" on text, files and images | Apple newsroom |
| **App actions** | Systemwide actions (draft an email from scratch, edit and share photos), actions in third-party apps such as WhatsApp and Audible, with Outlook, Notability and Tripsy "soon"; add or change calendar events from a description; build Shortcuts by describing them | Apple newsroom |
| **World knowledge** | Current web answers (sports scores, travel, local recommendations) | Apple newsroom |
| **Writing** | Write/rewrite in almost any text field, tone matched per recipient in Mail and Messages, proofreading as you type, smarter dictation (capitalisation, punctuation) | Apple newsroom |
| **Voice** | More expressive voices with pace and expressiveness controls; better speech understanding | Apple newsroom |
| **Visual intelligence** | Camera mode, screenshots, Mac selection; image generation in the Siri app | Apple newsroom |
| **Proactive** | Call Context (confirmation numbers when calling a business), a Smart Stack suggestion to resume a conversation | Apple newsroom |
| **Invocation** | "Hey Siri", side button, Dynamic Island, Spotlight; typed "Search or Ask" as well as voice | Apple newsroom, iGeeksBlog |

What Apple's Siri AI pages do **not** describe: timers, alarms, volume, Wi-Fi and similar device controls. Those are the older Siri's strength and are assumed to persist, so gap 3 stays the most important for *daily* use, but the bar for "feels like an assistant" is now the conversational, context-aware rows above. Claims in secondary coverage about third-party models such as Claude or ChatGPT inside Siri were **not** confirmed by Apple's pages and are ignored here.

Sources: [Apple, "Siri AI … is here"](https://www.apple.com/newsroom/2026/09/siri-ai-a-profoundly-more-capable-and-personal-assistant-is-here/) (2026-09), [Apple, "Apple introduces Siri AI"](https://www.apple.com/newsroom/2026/06/apple-introduces-siri-ai-a-profoundly-more-capable-and-personal-assistant/) (2026-06-08), [Apple Support, How to get Siri AI](https://support.apple.com/en-us/127893), [Apple, "Siri AI is available in more languages"](https://www.apple.com/newsroom/2026/10/siri-ai-is-available-in-more-languages-starting-today/) (2026-10-26), [iGeeksBlog](https://www.igeeksblog.com/siri-ai-ios-27-features/), [Let's Data Science](https://letsdatascience.com/news/apple-releases-ios-27-with-siri-ai-f9735042).

New gaps this adds to the original seven (answered in §4, §5.2, §5.3, §6.1, §6.2, §7.3 and §7.4):

| # | New gap | Today |
|---|---|---|
| 8 | **Personal context search**: find things across mail, calendar, files, notes by meaning | Gmail/Calendar tools search by keyword inside an agent run; no index; Files only via Claude Code |
| 9 | **Write anywhere, in the owner's voice and tone** | `desktop_write` types into Word, Gmail compose and fields; no per-recipient tone, no proofreading, no "rewrite this" without an agent run |
| 10 | **Current web answers** (scores, travel, opening hours) | Light lane deliberately excludes "latest/today"; goes to the agent (7–18 s) |
| 11 | **Conversation history and recap** | ADR-014 L2 has resumable conversations; no searchable history view or recap |
| 12 | **Describe an automation** ("every Friday, tidy Downloads") | ADR-011 plans workflow creation; W1 built only calendar |
| 13 | **Typed "Search or Ask"** alongside voice | Voice and hotkey only |
| 14 | **Expressive, adjustable voice** | No voice at all (gap 1) |

### 1.2 Swift as it is in the repository (checked 2026-10-27, `main` at `09f5fcf`)

- No branch is unmerged into `main`; the working tree was clean except this ADR.
- Since the first draft of this plan, `main` gained the calendar lifecycle (look, change, cancel, Meet links, a gateway `undo`). That already matches Siri's "add or modify events from simple descriptions", and the gateway undo is what the system lane's reversible intents (§3.1) build on.
- Built and relevant: lanes through fast and light (ADR-007 §10), held cards and resumable conversations (ADR-014 L2), several requests side by side (ADR-013 B), presence and lock handling (ADR-014 L1), desktop context and writing in Word/Gmail/Outlook (ADR-012 D1–D2), wake phrase and hotkey, spoken approvals during a run. Not built: any speech output (`[tts]` is a config stub), a system lane, a scheduler, a connector host, a browser extension, semantic search, typed input.

Two corrections to the first answer, from reading the code:
- Calendar already exists (`workflows/calendar.py`, `connectors/google_calendar.py`: look, add, change, remove, behind the confirm card). So gap 4 is about breadth, not "email only".
- "This" already works for the selected text, the selected file and the focused window (`desktop_context`, ADR-012 D1–D2). Gap 5 is about going past that: what's on a page, which email is open, what an element is.

| # | Gap | Today | Target |
|---|---|---|---|
| 1 | Talks back | Voice in, screen out. `[tts] engine = "piper"` is a config stub; nothing speaks. | Spoken answers, hands-free and eyes-free |
| 2 | Conversation loop | One request per press. A 6 s follow-up window, spoken approvals and held cards exist. | Swift asks, listens, resolves "the second one", takes corrections |
| 3 | System actions, no model | Fast lane (time, dates, units, maths, spelling) and "open X". Everything else is a 7–18 s agent run. | Everyday device and app control answered in well under a second, offline |
| 4 | Accounts and OS breadth | Gmail, Google Calendar, Word/Outlook/Gmail compose, File Explorer | Reminders, weather, music, messaging, smart home, Outlook, more through a connector host |
| 5 | Knows the screen | Focus, selection, caret, files | Pages, open emails, events, any control by structure; vision only as a permissioned fallback |
| 6 | Offline, devices, voice ID | One PC; STT local; real work needs the cloud | Honest offline mode, a phone companion, owner voice recognition |
| 7 | Proactive | Only responds | Opt-in nudges within an interruption budget |

### 1.3 The platform difference: Siri is first-party iOS, Swift is a third-party Windows app

The owner pointed out that this is not like for like. It changes the target from "copy Siri" to **"be the assistant a Windows PC owner would want, matching Siri's quality where the platform allows and exceeding it where a PC is the stronger device."**

**What Siri has because Apple owns the platform (Swift cannot copy it, only approximate it):**

| Siri advantage | Why Swift can't match it | What Swift does instead |
|---|---|---|
| Always-on wake word in low-power silicon, works with the screen locked or in a pocket | Swift runs its speech model on the CPU; the development laptop has no NPU. Wake listening costs CPU and is off while locked (ADR-014, T7). | Keep the wake phrase efficient and gated by presence; add the phone companion (§8.3) for "away from the PC" |
| System-level hooks: the Phone app, Messages/iMessage, Camera, Health, Wallet, Home, CarPlay, Watch, AirPods, Find My | Windows has no such first-party apps or no automation surface for them. Phone Link has none. | Connectors to the services themselves (Slack, WhatsApp/Telegram bots, Google, Microsoft Graph, Home Assistant); phone calls and SMS stay out of reach until the phone companion |
| App Intents: apps declare actions Siri can run, with no integration work | No equivalent adoption on Windows. Microsoft's agent connectors/MCP-on-Windows are early (ADR-012 §3). | UI Automation, Office object models and a browser extension per app (ADR-012); a connector host (§6) that can also register as an MCP server for the Windows agent platform when it matures |
| An OS-wide semantic index of the owner's data (Spotlight) | Windows has the Windows Search indexer (filenames, content, Outlook items) but no semantic layer that third-party apps can use, and Windows Recall is limited to specific hardware with no app API | Swift's own local index (§6.1), built from the services the owner connects and from chosen folders; querying the Windows Search index is a candidate source to verify |
| On-device Apple Foundation Models plus Private Cloud Compute | Swift sends model work to Claude Code, a cloud service. This is a privacy difference, not only a capability one. | Say so plainly in settings; keep everything local that can be (system lane, fast lane, STT, TTS, index); redact before any model call (ADR-012 §7); local Ollama fallback (§8.1) |
| Deep ecosystem sync (iCloud: conversations, reminders, settings across devices) | Swift has one PC and no cloud account of its own | Sync only through accounts the owner already has (Google, Microsoft); optional phone PWA (§8.3) |
| A voice, a microphone and speakers designed for it (AirPods, HomePod, a phone in the hand) | PCs have inconsistent mics, speakers and echo conditions | Half-duplex gating, headset detection, per-device calibration (§4) |

**What does not carry over and is out of scope:** Camera "Siri mode", Health, Wallet/Apple Cash bill splitting, Call Context in the Phone app, CarPlay, Apple Watch. The phone companion may later cover a small part (photo of a document or label for the agent), but these are not goals.

**Where a Windows PC is the stronger device, and Swift should lean in:** files and folders, many windows and two monitors at once, Office documents, a real keyboard (typed "Search or Ask" is natural, §5.3), long agent runs, code. Siri on a phone is a short-answer tool; Swift's agent path (ADR-006/013) already goes much further. "Parity" therefore means the same *feel* for the same everyday requests, not the same feature list.

**Other Windows-specific constraints to design around:**
- Windows' own voice features exist (Voice Access, Copilot). Swift must not conflict with their hotkeys or capture of the microphone; the settings page should show what else is listening.
- Many Windows apps are Win32/Electron/legacy with weak accessibility trees (ADR-012 §3), so "act on what is on screen" will be less uniform than on iOS; OCR and vision are the fallback chain.
- The Windows microphone privacy switch and exclusive-mode apps (calls) can take the microphone away; Swift already has a watchdog for this (ADR-014).
- No code signing means SmartScreen warnings on distribution; irrelevant for the owner's own machine, relevant if Swift is ever shared.

Swift's own strengths (agent work, concurrent requests, gateway, journal) stay. This ADR adds the everyday layer beneath them.

## 2. What "virtually non-existent" means

Not a feature checklist: measurable exit criteria (§9). In short, for the things people actually ask a built-in assistant, Swift answers the right way, at the right speed, in the right modality, without the owner noticing which path ran. The headline numbers:
- ≥ 95 % of a fixed Siri-class request set (built from §1.1 and Apple's published examples) handled correctly (§9.1);
- ≥ 80 % of the owner's real daily requests served without an agent run, measured from the interaction log;
- local intents: transcript → effect in ≤ 400 ms (excluding STT), first spoken word ≤ 700 ms after the answer is known.

## 3. Gap 3 first: the system lane (largest value, foundation for 1, 2, 7)

### 3.1 Design

A new lane between *fast* and *light* in ADR-007 §10:

```
control → local → fast → SYSTEM → light → agent → workflow
```

- **`swift/system/`**: a `SystemControl` protocol in the style of `desktop/base.py`, with a Windows implementation and a fake for tests. One module per family; each declares its intents, its slots, and its risk class.
- **Intent grammar** (`routing/system.py`): table-driven, tolerant phrasing like `fast.py` (leading "and/so/Swift,", number words, synonyms), returning a typed `Intent(name, slots)` or `None`. **A wrong action is worse than a slow one**: ambiguous phrasing returns `None` and goes on to the light lane or the agent.
- **Same actions for the agent.** Each intent is also exposed as a tool in the in-process `swift` MCP server, so compound requests ("set dark mode and mute, then open Spotify") still work: the agent calls the same code, through the same gateway.
- **Gateway classes** (ADR-010 policy table): *read* (no card), *reversible* (volume, theme, media: has an `undo`, so "undo that" works), *disruptive* (lock, sleep, restart, Wi-Fi/Bluetooth/airplane off: spoken or card confirm), *destructive* (shutdown with unsaved work, empty Recycle Bin: always the card). A voice-heard "shut down" is never executed on the transcript alone.
- **Compound utterances** ("volume to 30 and pause the music"): split on "and/then" only when both halves parse as intents; otherwise the whole thing goes on.
- **Carry-over** ("and 20 more", "a bit lower", "what about Tokyo?"): the last system or fast intent is kept for ~60 s so a fragment can edit it (shared with §5).

### 3.2 Families (in build order)

| Family | Examples | Windows route |
|---|---|---|
| **Timers, alarms, stopwatch** | "timer for 10 minutes", "wake me at 7", "how long is left", "cancel the timer" | Swift's own scheduler (§3.3) |
| **Reminders** | "remind me to call Sam at 5", "remind me when I get home" is out (no location trigger on desktop) | Scheduler; list in a local store, optional sync (§6) |
| **Sound and media** | volume up/down/to N, mute, next/previous/pause, "what's playing" | Core Audio (`pycaw`); System Media Transport Controls for the current player |
| **Display and appearance** | brightness, dark/light mode, night light | Registry, WMI brightness, Night Light setting |
| **Connectivity and power** | Wi-Fi, Bluetooth, airplane mode, battery saver, "battery level", "which Wi-Fi am I on" | `Windows.Devices.Radios`, WMI, `powercfg` |
| **Focus** | Do Not Disturb / Focus assist on/off for N minutes | Focus-assist state |
| **Windows and apps** | switch to X, minimize, maximize, close this window, snap left/right, show desktop, new virtual desktop | Win32 + virtual-desktop hotkeys; extends `desktop/windows.py` |
| **System info** | battery, disk space, CPU/RAM, IP, uptime, "what's on my clipboard" | WMI/psutil, clipboard (clipboard content is untrusted and never read aloud if marked private) |
| **Settings and shortcuts** | "open Bluetooth settings", "take a screenshot", "open the calculator" | `ms-settings:` URIs, Snipping Tool, existing `local` names |
| **Power actions** | lock, sleep, sign out, restart, shutdown | Disruptive/destructive classes above |
| **Web** | "search the web for …", "open youtube.com" | Default browser; the URL carries only the query, never owner data |

### 3.3 The scheduler (shared by timers, reminders, alarms, proactive nudges, §7)

- Persistent (`%LOCALAPPDATA%\Swift\schedule.json`), survives restarts and sleep; on resume, anything missed fires once, marked "missed".
- Firing = sound + card + spoken line (once §4 lands), repeating until acknowledged for alarms; honours presence (ADR-014): locked/away means a toast and a held card, not speech.
- Runs in the core loop; no new thread.

### 3.4 Keeping it honest

- Intent coverage grows from evidence: `spikes/owner_checks/report.py` gains a "should have been a system intent" section (agent runs whose transcript the grammar nearly matched, or whose tool calls were a single system tool). Each week's misses become grammar cases.
- Every intent ships with ≥ 15 phrasing variants and ≥ 5 near-miss negatives in the eval set (§8).

## 4. Gap 1: Swift speaks

- **Engine:** Piper, as configured (local, no network, ADR-006's privacy stance), with the Windows built-in voices as a zero-download fallback while the Piper voice license is recorded (§9 decision). Synthesis runs on the worker pool; the first sentence is spoken while later ones are still being made.
- **What is spoken:** a *spoken form*, not the card. Fast and system lanes already produce short spoken-style answers. For agent runs the final result gets a one-to-two sentence spoken summary (the card still shows everything); long outputs are never read out unless asked ("read it to me").
- **When:** auto = speak if the request was voice-initiated and presence is *here*; never when locked, away, in DND, or when another app is using the microphone (a call); typed requests stay silent. Settings: `speech.replies = auto | always | never`, volume, rate, voice.
- **Echo and barge-in (the hard part):**
  - Wake listening and push-to-talk capture are **half-duplex** while Swift speaks: the wake matcher ignores audio during playback plus a short tail, so Swift cannot hear itself.
  - Pressing the hotkey, or saying "stop" once speech is ending, cuts speech immediately (a few ms, playback is on a stoppable stream) and opens the mic.
  - Full duplex "interrupt by voice" needs echo cancellation; first version uses headset detection: with headphones, voice barge-in is on, otherwise hotkey only.
- **Latency budget:** the TTS model is loaded at startup and released on long idle like the others (ADR-014 §6); first audio ≤ 700 ms for a cached voice.
- **Tests:** a fake audio sink records what would be said; unit tests on the spoken-form rules; the half-duplex gate tested with injected audio; owner check on real speakers and headphones.

## 5. Gap 2: a real conversation

### 5.1 Dialogue manager (`swift/dialogue.py`)

A small state holder owned by the session, on top of ADR-013's attention threads:

- **Pending question:** a run (or a lane) can ask: `ask_owner(question, kind=yes_no|choice|free, options?)`. Swift shows the card, speaks the question (§4), and as soon as speech ends **opens the mic with endpointing** (no hotkey), with a time limit and a visible state. The answer goes to the pending question, **not** to the router as a new request. A new, clearly unrelated request still wins ("never mind, what time is it?").
- **Resolution of answers:** yes/no and approvals (extends the existing voice approvals), ordinals and names ("the second one", "John Smith, not Jon"), numbers and times, corrections ("no, make it four"), and cancel. Ambiguous or inaudible answers get one re-ask, then a held card.
- **Disambiguation and slot filling built into the common tools:** `find_contact` with several matches asks "Which Sam: Sam Lee or Sam Okoro?"; "remind me to call Sam" with no time asks "When?"; "set a timer" with no length asks "For how long?". Slots live in the intent, so the grammar of §3 and the dialogue share one mechanism.
- **Carry-over and ellipsis:** the last intent/answer is kept as context so "and tomorrow?", "what about in Tokyo?", "make it louder", "send it" resolve against it. Held ~60 s, cleared by presence loss.
- **Better endpointing:** today `end_silence_s = 0.8` cuts people off mid-thought. Add a punctuation-aware end-of-turn check (a trailing "and", "uh", number mid-way continues listening up to a cap) and a slightly longer window when the pending question expects free text.
- **Open question for the owner:** continuous "conversation mode" (mic stays open after each answer until you stop) versus always one exchange at a time. Proposed: a 6 s follow-up window as now for answers; the pending-question mic opens only when Swift asked something.

### 5.2 History and recap (new gap 11)

ADR-014 L2 already keeps resumable conversations. Add a searchable history list in the tray/overlay (title, time, pin, resume) and a *recap* line per finished conversation: a title and key points written by the light lane, never a transcript, with `log_content = false` respected (recap stored only if the owner enables history). No cross-device sync; the phone companion (§8.3) can read the same list.

### 5.3 Typed "Search or Ask" (new gap 13)

A PC has a keyboard, so a typed entry is a first-class path, not an accessibility feature: a hotkey opens a small input in the overlay, goes through the same router, lanes, gateway and dialogue as speech, and is never spoken back unless asked. It also gives a quiet way to use Swift in meetings and open offices. Drag-in of a file or screenshot attaches it as untrusted context.

## 6. Gap 4: breadth through connectors

The multiplier is the connector host the backlog already lists (ADR-005, Phase 7). Build it once, then add connectors cheaply.

**Phase E1: host and wave 1** (each follows ADR-005: Swift's own capability mapping, untrusted output, gateway for side effects):

| Connector | Why first | Route |
|---|---|---|
| **Weather and location** | The most common non-system question | Open-Meteo (no key); location from Windows Location API with a configured home/work fallback; a fast-lane family |
| **Tasks / reminders sync** | Reminders must outlive this PC | Google Tasks and Microsoft To Do; the local store of §3.3 stays the source for firing |
| **Music** | "Play X" is a top request | Local player control via SMTC (E0, no account) plus Spotify Web API (play/queue, needs Premium and OAuth) |
| **Outlook / Microsoft 365 calendar and mail** | Parity with Gmail/Google; many people use it | Microsoft Graph, same tool shapes as `calendar.py`/`gmail.py` so workflows are provider-neutral |
| **Smart home** | Siri's home strength | Home Assistant REST/MCP (covers Hue, Matter, etc.) rather than N vendor APIs |
| **Messaging** | "Text Sam" | Per platform, not SMS: Slack, Teams, WhatsApp Business/Telegram bot where the owner has accounts. The confirm card, recipients only from `find_contact`, as email |
| **Notes** | "Add to my shopping list" | Local markdown/OneNote list store with voice add/read |
| **Maps and travel time** | "How long to X", "leave by" nudges | A routing API (needs a key; owner decision) |

**Known limits (stated up front, not pretended away):** phone calls and iMessage/SMS have no supported Windows API. Phone Link has no automation surface, so the phone companion (§8.3, Phase H) is the honest route for calls and SMS later.

### 6.1 Personal context index (new gap 8, Siri's Spotlight-level search)

Siri's headline is "find the hotel confirmation number in my mail". On Windows there is no system semantic index apps can use (§1.3), so Swift builds a small one:
- **Sources, opt-in per source:** Gmail and Outlook mail headers and bodies (read-only scopes), calendar, chosen folders, notes. Photos and chat apps are out until a connector exists.
- **Local and private:** embeddings computed locally (a small sentence-embedding model, CPU, run while idle and charging), stored encrypted under `%LOCALAPPDATA%\Swift\index`, wiped from settings. Nothing is uploaded to build it.
- **Query path:** a `search_personal(query, kinds?, since?)` tool, exposed to the agent *and* answered directly in the system lane for simple finds ("when is my flight", "what's the Wi-Fi password email"). Retrieved text is untrusted external content (ADR-005), is shown in the result card with its source, and the model sees only the top few snippets.
- **Candidate source to verify:** the Windows Search indexer for file names and content, as a cheap first version before our own embeddings.
- **Honest limit:** quality will lag a first-party index with access to every app; coverage grows only with connectors.

### 6.2 Describe an automation (new gap 12)

"Every Friday afternoon, tidy my Downloads" becomes a workflow package (ADR-011) created from the description: Swift drafts the workflow, shows it as an artifact for review, and only then saves it; scheduling uses §3.3. Uses the workflow editing foundations already planned in ADR-011; it adds the spoken front end and the scheduler.

## 7. Gap 5: knowing the screen; Gap 7: proactivity

### 7.1 Screen awareness (completes ADR-012 §4 levels 3–4 for read)

- **Typed referents.** One resolver turns "this / it / that / here" into a typed referent: selection text, selected file, focused control, **current page (URL, title, readable text)**, **open email/event**, or "unknown, ask". Resolution order is in the dialogue state first (what Swift just said), then the screen.
- **Browser.** A small extension with native messaging gives tab URL, title, selection and readable page text from the owner's real session ("summarize this page", "add this to my calendar", "who is this from"); private windows stay refused (ADR-012 §7). This is the single biggest screen-awareness win for the effort.
- **Structured snapshot** (ADR-012 §5 [2]): pruned UIA subtree with short refs, redacted, for "click the second Send button" and "what does this error say".
- **Fallback chain:** structure → Windows OCR (local) → screenshot to a vision model, per-use permission. The never-read list is enforced before any of it.
- **Privacy is unchanged:** screen text is untrusted, nothing on it can choose a recipient or path.

### 7.2 Proactive engine (`swift/proactive.py`)

- **Triggers** are small rules over data Swift already has: schedule due, calendar event in N minutes (with a join link: "Join?"), time-to-leave from travel time, battery low, an email from a configured VIP, end-of-day wrap-up, the morning brief, a long-open downloads folder (existing tidy-downloads workflow).
- **Interruption budget** (ADR-013 attention + ADR-014 presence): max nudges per hour/day, quiet hours, never while locked/away/DND/screen sharing or when the owner is mid-dictation; every nudge is a held card first, spoken only if the owner allowed it for that category.
- **Opt-in per category**, a visible list in settings, and **dismissals teach**: three dismissals of a category halve its rate and offer to turn it off. Nudges never act; they ask.
- Uses the scheduler (§3.3) and speech (§4); it cannot ship before them.

### 7.3 Write anywhere, in the owner's voice (new gap 9)

Builds on `desktop_write` (ADR-012): a "rewrite this" on the selected text (shorter, friendlier, formal, fix grammar) answered by the light lane in place and undoable, no agent run. Replies to an email or chat get tone from the owner's past sent messages with that recipient (local, from the index of §6.1, with a short style note instead of raw mail sent to the model). Proofreading as you type is **not** planned: it needs a keystroke hook in every app, which is invasive on Windows; a "proofread this" on the selection gives most of the value.

### 7.4 Current web answers (new gap 10)

A *web lane* between light and agent: a single search plus a tool-free summarisation call for "who won last night", "is X open now", "what's the weather", "how long is the drive". Only the query leaves the PC (no owner data in it); sources are named in the card. Weather and sports use plain APIs for speed (§6, Open-Meteo first). Excluded as today: anything about the owner's own data, which stays local.

## 8. Gap 6: offline, other devices, voice

### 8.1 Offline resilience

- **Connectivity monitor.** When the cloud is unreachable, say so at once and route what can be answered locally; queue what cannot ("I'll send it when you're back online") instead of waiting 20 s and timing out.
- **Local light model.** Optional Ollama small model (the original v2.0 spec) as the light lane's offline fallback for definitions, rewrites, and short replies. Agent work with tools stays cloud.
- Everything in §3–§5 (system lane, fast lane, speech, scheduler) is local by construction.

### 8.2 Voice recognition (owner voice)

- A local speaker-embedding check (a small ECAPA-style model) enrolled in a 30-second session. Used as: (a) a gate for the wake phrase (fewer false wakes from TV/other people), (b) a requirement for *disruptive+* intents and approvals ("send it" must be the owner's voice), (c) never as sole authentication for anything the gateway treats as destructive.
- Embeddings stay on this PC; enrolment can be wiped from settings.

### 8.3 Phone companion (largest, last)

- Version 1 is a **phone web app (PWA)** talking to the backend through a tunnel the owner controls (Tailscale or similar), authenticated with a per-device token and the existing WebSocket protocol: push-to-talk from the phone, the same cards, notifications for timers and nudges, "ask my PC from anywhere".
- This widens the attack surface and needs a threat-model update (`docs/threat_model.md`) *before* any code: pairing, token rotation, which intents are allowed remotely (no disruptive/destructive by default).
- Not a native iOS/Android assistant. If the owner wants that, it is a separate project.

## 9. Evaluation: how we know the gap is closed

1. **Parity set** (`eval/parity/`): ~400 utterances in the categories above, written as a Siri-class list drawn from §1.1 and Apple's own examples, translated to a PC (timers, reminders, messages, music, weather, home, settings, maths, facts, calendar, directions, "find the confirmation number", "add these dates from this page", "rewrite this", "what's on my screen"). Phone calls, Camera, Health, Wallet and CarPlay are excluded (§1.3); each excluded case is listed with the reason so the exclusion is a decision, not an omission. Each case has the expected lane, intent and slots, whether a card or speech is expected, and a latency ceiling. Variants with filler words, STT-style errors (use `stt-noise.md`), and near-misses that must *not* trigger.
2. **Real-use metric.** `report.py` reports, per week: share of requests by lane, median time to first response per lane, and the "should have been local" list. Target: agent+workflow share for everyday requests < 20 %.
3. **Owner checks** (REQUIRES-HW) per phase, as in ADR-012 §12: real speakers and headphones, real accounts, real lock/sleep/unlock cycles.
4. **Safety tests:** every disruptive/destructive intent has a test proving it cannot run without its confirmation; `test_architecture.py` extends its AST rule to the system module (no direct side effect outside the gateway).
5. **Latency budgets** asserted in CI for the offline lanes (fake audio/system) and measured on the laptop for real paths.

## 10. Phasing

Sizes are relative (S ≈ days, M ≈ 1–2 weeks, L ≈ several weeks), not promises. Each phase ends with tests, a docs/ADR section, and an owner-run check list, and needs its own go-ahead.

| Phase | Content | Size | Needs |
|---|---|---|---|
| **A: System lane and scheduler** | §3 (families 1–6 first: timers/reminders, sound/media, display, connectivity, focus, windows), parity eval set, report additions | L | none |
| **B: Voice out** | §4: Piper/fallback, spoken form, half-duplex, barge-in, settings | M | A optional; wants A's timers to demo |
| **C: Dialogue** | §5: pending question with auto-listen, disambiguation, slots, carry-over, endpointing | M | B |
| **D: Proactive** | §7.2 | M | A (scheduler), B |
| **E: Connector host + wave 1** | §6: host, then weather, tasks, music, Outlook, smart home, messaging, notes, maps | L, incremental | A; C for disambiguation |
| **F: Screen awareness** | §7.1: browser extension, typed referents, structured snapshot | L | ADR-012 D3 |
| **G: Offline** | §8.1 | S–M | A |
| **H: Voice ID and phone** | §8.2–8.3 | M + L | B; threat-model update |
| **I: Context and writing** (the "Siri AI" layer) | §5.3 typed Search or Ask, §7.4 web lane, §7.3 rewrite/proofread/tone, §5.2 history and recap, §6.1 personal context index, §6.2 describe an automation | M each, L for §6.1 | A (lanes, scheduler); E for the sources §6.1 indexes; §5.3 and §7.4 are independent and cheap, so they can go early |

**Parallelism.** A and B can run side by side (system lane under `routing/` and a new `system/`; speech under `audio/`), but both need small hooks in `session.py` (2.6k lines): the system lane's route, and the speak call after an answer. Land those hooks first in a tiny shared change to avoid conflicts, or run them in sequence. Later phases touch the dialogue and attention code and should be serial.

**Suggested order:** A → B → C (the core "assistant feel") → I's cheap parts (typed input, web lane, rewrite) → G → E → D → F → I's index and automations → H. The index waits for E because it can only be as good as the connectors feeding it.

## 11. Decisions needed from the owner

1. **Speech voice.** Record a Piper voice license (quality, local) or start with the built-in Windows voices (no download, lower quality)? Proposed: Windows voices first, Piper next, per your listening test.
2. **Spoken replies default.** `auto` (voice in → voice out, never when away/locked/in a call) as proposed, or always on?
3. **Hands-free dialogue.** Mic opens automatically after Swift asks a question: yes? (§5.1)
4. **Power actions by voice.** Lock and sleep with a spoken yes; restart/shutdown always on the card. OK?
5. **Music.** Spotify, YouTube Music, local files, or just whatever player is running (SMTC)?
6. **Messaging.** Which platforms do you actually use? (WhatsApp/Telegram/Slack/Teams/SMS.)
7. **Smart home.** Do you have a Home Assistant, Hue, or Matter setup, or is this out of scope?
8. **Maps key.** A routing/travel-time API needs a key. Acceptable, despite "no separate API key" for models (ADR-007 §9)?
9. **Local LLM.** Install Ollama and a small model for offline fallback, or keep offline to the local lanes only?
10. **Voice ID.** Enrol your voice for wake gating and sensitive actions?
11. **Phone companion.** Tailscale-style tunnel from a phone PWA acceptable, or do you want it left out for now?
12. **Proactivity.** Which nudge categories do you want on first (e.g. meeting soon, timers/reminders, low battery, morning brief)?
13. **Personal index.** Index your mail, calendar and chosen folders locally for "find the confirmation number" style questions? Which sources first? (§6.1)
14. **What counts as parity on a PC.** Agree that §1.3's out-of-scope list (calls, SMS, Camera, Health, Wallet, CarPlay, Watch) stays out until the phone companion, and that "same feel for everyday requests" is the target rather than Siri's feature list?
15. **Typed entry.** Add a hotkey-opened text box (§5.3)?
16. **Privacy statement.** Swift's model work goes to Claude Code in the cloud, where Siri's goes to Apple's Private Cloud Compute. Are you comfortable with the plan to say this plainly in settings and keep the index, system lane and speech fully local?

## 12. Risks

| Risk | Mitigation |
|---|---|
| A misheard command does something wrong (Wi-Fi off, mute at the wrong time) | Conservative grammar, `None` on ambiguity, reversible intents with "undo that", confirm classes for disruptive ones, owner-voice gate later |
| Swift hears itself speak and wakes itself | Half-duplex gating; headset detection before voice barge-in |
| Proactive nudges become annoying | Opt-in categories, budget, quiet hours, dismissal learning; speech off by default for nudges |
| `session.py` keeps growing | Each new lane/dialogue gets its own module with a narrow interface; only the wiring touches the session |
| Connector sprawl and token handling | One host, Swift-owned capability mapping (ADR-005), tokens in Credential Manager only |
| Phone companion widens the attack surface | Threat-model update first; remote intents allow-listed; no destructive actions remotely |
| Scope: fourteen gaps at once | Phased; A–C deliver the "feels like an assistant" core before the long tail |
| Siri keeps moving (it is a beta with a roadmap: Recap, Outlook actions, more languages) | The parity set is dated and rebuilt from Apple's newsroom each quarter; this ADR's §1.1 is refreshed then |
| Platform gap makes a target unreachable (no always-on low-power wake, no private index, no phone hooks) | §1.3 names each one with a substitute and an owner decision, instead of promising parity |
| The personal index leaks private data | Local embeddings and storage, opt-in per source, encrypted at rest, wipe control, retrieved text treated as untrusted, snippets only to the model |

## 13. Phase A1: built (2026-10-28)

The owner approved Phase A and asked for sensible defaults for the open decisions. This is the first slice of it: the system lane and Swift's clock, end to end, with tests. What is **not** in A1 is listed at the end.

### 13.1 What exists

| Piece | Where | Notes |
|---|---|---|
| Intent grammar | `swift/system/intents.py` | Timers, alarms, reminders; volume, mute, media keys; dark mode, brightness; lock; battery, disk, CPU, memory, uptime; Windows settings pages; window moves, show desktop, snap; screenshot; web search. Compounds split only when every part is an intent. |
| The device | `swift/system/control.py` | `SystemControl` base (refuses with a sentence), `FakeSystem` for tests and debug mode, `WindowsSystem` for the real thing: Core Audio through `comtypes` (volume, mute, "is anything playing"), the registry (theme), WMI (brightness), `keybd_event` (media keys, Win-key shortcuts), `ShowWindow`, `psutil`. No new dependency. |
| Swift's clock | `swift/system/scheduler.py` | Timers, alarms and one-off reminders in `%LOCALAPPDATA%\Swift\schedule.json`; survive restart; missed items fire once, marked missed. |
| The lane | `swift/system/lane.py` | Does the intent, says what was done in the fast lane's spoken style, keeps the inverse of the last utterance for 10 minutes ("undo that"). |
| Routing | `routing/rules.py` | After the fast lane: `local` / `system`. Eval rows moved from `agent` to `local` are tagged `system` (11 of them) and the classifier's built-in examples were regenerated. |
| Session | `session.py` | `_system_lane`, `notify_due` (a chime, then a card once nothing is on screen, waiting at most 2 minutes), "undo that" for system changes, fall-back to the agent when the lane is off or has nothing to act on. |
| Settings | `system:` in `config.yaml` | `enabled`, `schedule_file`, `chime`. Debug mode uses `FakeSystem` and an in-memory schedule, so the harness never touches the real volume. |

Measured on the development laptop, real device: reads and clock operations 0–1 ms; volume 11–140 ms; "is anything playing" 260 ms (it samples the meter); CPU usage 400 ms (a deliberate sample); brightness through WMI 0.8–1.5 s, the slowest path, because WMI starts a PowerShell. All well under the 18 s the agent took for the same requests.

### 13.2 Defaults chosen for the open decisions (all reversible, all revisit-able)

| §11 | Default in A1 |
|---|---|
| 4 Power actions | **Lock** works on a plain request (reversible by signing in). **Sleep, restart, shut down, sign out are not matched**: they go to the agent and its confirm card until the dialogue phase can ask "Are you sure?" by voice. |
| 5 Music | Whatever player is running, through the media keys. "Pause" and "play" check whether audio is actually playing first, so they never toggle the wrong way. Spotify and others wait for the connector host. |
| 8 Maps key | Not needed in A1. |
| Search engine | Google, only when the web is named ("search the web for…", "google …"). A bare "search for…" is never taken: it may mean files or code. |
| Reminders | One-off with an explicit time ("in 20 minutes", "at 5", "tomorrow at 9 am"). A reminder without a time is not guessed; a repeating one ("every weekday") is not a one-off; listing or cancelling reminders goes to the agent when none was set through Swift, because it may be a calendar event. |
| Time words | "At 5" with no am/pm is the next 5 o'clock, either one; "wake me at 7" is the morning. |

### 13.3 Safety checks done

- Everything in `control.py` is read-only or reversible; no power action exists in the code.
- False positives found by running the whole eval set through the new grammar, and fixed before landing: "Remind me every weekday at 9…" (repeating), "Search the codebase for every place…" (not the web), "Cancel the Friday reminder" (may be a calendar event). Each is a test in `tests/unit/test_system_lane.py`.
- The Windows paths were exercised for real on the development laptop: volume read, set (to the current value), mute, theme, brightness set (to the current value), battery, disk, CPU, memory, uptime, audio meter. Not exercised for real, because they are disruptive: lock, window moves, snap, screenshot, media keys, settings pages, web search. **Owner check (REQUIRES-HW):** say each once and confirm it does what the reply says.

### 13.3a Fixed before the A1 commit (review, 2026-10-28)

- **Trust boundary written down and journaled.** `docs/architecture.md` now names the system lane as the one exception to "every side effect through the gateway", with its limits. Each device change is written to the gateway's action journal (`system.<intent>`, metadata only, no query or reminder text).
- **Due items respect presence.** While the owner is away (ADR-014: locked, asleep, idle) a due timer, alarm or reminder still chimes, but its card is held; on return one "While you were away: …" card lists them with their times.
- **Short commands in the follow-up window.** "Louder", "next song", "unmute", "volume up" and other volume and media intents are kept as short clips like "stop" and "repeat that"; other short system clips are still dropped.
- **"What can you do?"** now lists the system lane.
- **Overlay checked** in the dev harness: the due card renders. The harness lacked the `#rows` and `#stack` elements that `index.html` has, which threw on every card change; added.

### 13.4 Not in A1 (done in A2, §14, except where §14.4 says)

- **Wi-Fi, Bluetooth, airplane mode and Focus assist** (`Windows.Devices.Radios` needs a WinRT bridge; no packaged one is installed). Next.
- **The same actions as agent tools**, so a compound with one non-system part ("turn the volume down and write a haiku") can use them. They are still only reachable from the lane.
- **Asking** when a slot is missing ("for how long?"): Phase C.
- **Speaking** the reply and the alarm: Phase B. A due item is a chime and a card for now.
- **The "should have been local" section in `report.py`** and the 400-case parity set (§9).
- Timers do not pause or resume; no stopwatch; no recurring reminders.

## 14. Phase A2: the rest of Phase A (2026-10-28)

### 14.1 What was added

| Piece | Where | Notes |
|---|---|---|
| Wi-Fi, Bluetooth, airplane mode | `system/control.py` (`radios`, `set_radio`), `intents.py` (`radio`, `radio.get`, `airplane`) | `Windows.Devices.Radios` through PowerShell's WinRT bridge: no new package, about 1 s a call (measured: read 1.2 s, set 0.9 s). Windows' own airplane switch has no app API, so "airplane mode" switches every radio and says so. |
| Do Not Disturb / Focus | `intents.py` (`dnd`), `lane.py` | Windows keeps it in a private settings store with no supported API. Swift opens the setting and says why, rather than pretend. |
| Asking first | `lane.py` (`Outcome.pending`, `question`, `confirmed`), `session.py` (`_system_answer`) | Wi-Fi or Bluetooth off, airplane mode on: "Turn off Wi-Fi?" Yes (or "go ahead", "do it") within 45 s does it; no drops it; anything else drops the question and goes on as said. "Okay, what's…" with more than five words is a new request, not a yes. |
| Agent tool | `workflows/system_tools.py` (`system_action`) | Same grammar; only intents found, with the same details, in a clause of the owner's own request. Through the gateway: reversible, or the confirm card for disruptive ones. Workflow capability `system.action`. |
| Report | `spikes/owner_checks/report.py` | Requests and median time per lane; agent runs Swift could now answer itself ("now local") or partly ("partly system"). |
| Parity set | `eval/parity/` (`build.py`, `parity.jsonl`, `score.py`, `passing.txt`) | 397 requests from §1.1 translated to a PC, each with its *ideal* lane, phrasing variants, `must_not` for harmful lanes, and 22 excluded rows with the reason. `tests/unit/test_parity.py` is a ratchet: what passes stays passing, nothing harmful. |

### 14.2 Where parity stands (router, 2026-10-28)

`uv run python eval/parity/score.py`: **365 of 375 (97.3%)** take the lane they should, 0 harmful. All 10 misses are current-information questions ("what's the weather", "who won last night") that need the Phase I web lane; today the agent answers them in 7–18 s.

Read this number with care: the set was written by the same person as the grammar, so it measures coverage of the phrasings we thought of. The real test is the owner's own requests: the report's "Agent runs Swift could answer itself" list, after a day of normal use, is the next source of cases.

### 14.3 Checked, and not

- Real device: radios read (1.2 s) and set to their current state (0.9 s) on the development laptop. Not switched off for real (it would cut this session's connection).
- **Owner check (REQUIRES-HW):** "turn off Bluetooth" → the question → "yes" → Bluetooth off; "undo that" → back on. "Turn on airplane mode" → question → "no" → nothing changes. "Turn on do not disturb" → Settings opens on Notifications. A mixed request, "turn the volume down and write a haiku about tea", with Claude Code: the volume changes and the haiku comes back.

### 14.4 Still not done

- Timers don't pause or resume; no stopwatch; no recurring reminders (the agent can set those up in the calendar).
- Asking for a missing detail ("For how long?") waits for Phase C; speaking replies and alarms for Phase B.

## 15. Phase B: Swift speaks (2026-10-28)

### 15.1 What exists

| Piece | Where | Notes |
|---|---|---|
| Voice | `swift/speech.py` (`WindowsSpeaker`) | The Windows voices through SAPI (`pywin32`, already a dependency): no download, about 50 ms to create. Desktop and OneCore voices both work (`speech.voice: "Mark"`). One worker thread owns the voice; `stop()` cuts it off within about 0.3 s. Piper can replace it behind the same `speak` / `stop` / `close` once its voice license is recorded (§11 decision 1). |
| Spoken form | `speech.spoken` | The first sentence or two, at most 220 characters, cut at a sentence end; headings, markdown, code, links and emoji removed. The card always shows everything. |
| When | `Session._speak_reply` | `speech.replies: auto` (default): a request spoken to Swift (hotkey, wake phrase, follow-up, correction) gets its answer and any failure said aloud; a typed request stays silent. `always`, `never`. **Never while the owner is away** (locked, asleep, idle). A timer, alarm or reminder going off is said unless replies are `never`. |
| Barge-in | `Session.handle` | The hotkey, Esc, and typing stop Swift mid-sentence. |
| Half-duplex | `Session.hear_wake`, `wants_short`, `wants_peek` | What the open microphone hears while Swift talks, and for 0.6 s after, is dropped (`own_voice` counter in the wake log line), so Swift never wakes itself or takes its own words as a reply. |
| Reply window | `Session.speech_done` | The follow-up window ("Listening for your answer") opens again when Swift finishes talking, so the owner has the full window after the voice, not under it. |
| Settings | `speech:` in `config.yaml` | `enabled`, `replies`, `voice`, `rate`, `volume`. Debug mode records instead of speaking. |

### 15.2 Decisions taken by default (§11)

- **1 Voice:** Windows voices now; Piper later, after a listening test.
- **2 Replies:** `auto`.
- **Barge-in by voice:** not in B. Saying "stop" while Swift talks is dropped by the half-duplex rule; the hotkey or Esc stops it. Voice barge-in needs echo cancellation or headset detection (§4), which is a follow-up.

### 15.3 Checked, and not

- Mechanics on the development laptop at volume 0: the voice starts, finishes, and stops on demand (0.3 s). 18 unit tests cover the spoken form, the policy, barge-in, half-duplex and the reply window.
- **Not heard by anyone yet.** **Owner check (REQUIRES-HW):** with speakers, "Hey Swift, what time is it?": the answer is said; then speak again straight after: the reply is heard (not Swift's own voice). Press the hotkey while Swift talks: it stops at once. Type a request: no voice. Lock the PC with a 1-minute timer: chime only; back: the card, and no speech for it. Try `voice: "Mark"` and `rate: 1`.

### 15.4 Not in B

- Confirm cards are not read out yet ("Send this email to Ada?"): the card's title should be said for eyes-free approval. Next, with the dialogue phase.
- "Read it to me" for a whole long answer.
- Voice barge-in and echo cancellation; Piper voices.

## 16. Phase C: dialogue (2026-10-28)

### 16.1 What exists

| Piece | Where | Notes |
|---|---|---|
| Questions and answers | `swift/dialogue.py` | `Question`, `Answer`, `resolve`: yes/no, ordinals, names (with "not X"), numbers, durations, times, corrections ("no, make it four"), cancel, "never mind, <new request>". `Dialogue`: one question on screen, the others wait; one re-ask, then shelved. |
| Slots | `system/intents.py` (`SLOTS`, `missing`), `system/lane.py` (`Outcome.ask`) | "Set a timer" asks "For how long?"; "remind me to X" with no day or time asks "When should I remind you?". |
| A request asks the owner | `workflows/tools.py` (`ask_owner`, `RunScope.ask_fn`) | Shown on the working card (overlay `ask.ts`; options as buttons, an answer and never an approval) and said for a spoken request. `find_contact` asks "Which Sam: Sam Lee or Sam Okoro?". |
| Answers | `Session` ("the dialogue" block) | From the open microphone (wake on), a recording that ends when the owner stops talking (wake off), the hotkey, typing or a click. Never while away: questions go to the stack and carry-over is forgotten. A confirm card on screen goes first. |
| Carry-over | `Dialogue.carry`, `Session._carry_over` | 60 s or the same thread: "make it louder", "20 more", "no, make it four", "and tomorrow?". |
| End of speech | `swift/endpoint.py` | `more_coming` (a trailing "and", "uh", "the", "twenty"…; but "forget that", "turn it on" are whole), `EndOfTurn`: 0.8 s, 1.3 s for free text, +1.2 s while more is coming, 3 s cap. Wake utterances held and joined; a recording checks its words at a pause. |
| Confirm cards read aloud | `speech.card_speech`, `Session._read_card` | For a spoken request. Approving still needs "Swift, yes" or the hotkey; typing never approves. |
| Protocol | `ask` out, `ask.reply` in | Phases `asking`, `listening`, `again`, `heard`; `open: false` closes it. |

### 16.2 Defaults taken (reversible)

- **§11 Q3:** the microphone opens by itself only after Swift asked something, for `wake.question_s` (25 s). A typed request's question is answered by typing.
- One exchange at a time; no continuous conversation mode (decision 13).
- A bare number answering "For how long?" means minutes; the reply says so.
- A reminder with a day but no time, or "remind me about…", still goes to the agent.
- Lane yes/no questions keep the 45 s window; slot questions use the question window.
- Questions never show over a confirm card.

### 16.3 Checked, and not

- 1240 Python tests, 78 overlay tests, `tsc`. Routing parity 397/407, 0 harmful (the 10 misses are the web lane, step 4).
- End of speech over the owner's 51 corpus clips (`spikes/endpointing/measure.py`, counts only): a fixed 0.8 s pause would cut 6 short (12%), 1.3 s 2, 2.0 s none. These are read-aloud clips; rerun once the recordings loop has saved live ones.
- **Not on the real PC yet:** owner checks 100–108. The question card was checked by unit tests, not yet in the dev harness.

### 16.4 Not in C

- "Remind me to buy food for 5 people" reads "for 5" as a time (an older grammar bug).
- Voice barge-in (§15.2) and a continuous conversation mode.
