# UI reach: does the surface limit what the owner can do with Swift? (2026-11-12)

- **Status:** analysis only, not decided. Nothing is built and no code changed.
- **Question:** the owner asked why Swift feels rigid. The harness side (follow-ups get the conversation, full calendar titles, `read_workflow`) is on `claude/harness-takeaways`. This document covers the other half: whether the UI, its planned direction and the interaction model are themselves the limit.
- **Read with:** [`interaction-layer.md`](interaction-layer.md), [`desktop-choreography.md`](desktop-choreography.md), [`assistant-ux-research.md`](assistant-ux-research.md), ADR-017, ADR-018, ADR-019, handoff §4.

## 0. The short answer

**What the evidence shows**

1. **Swift's surface is built for the moment, not for coming back.** An answer stays on screen for 4 to 20 s (`answer.ts` `READ_MAX_MS`). A finished request behind the card says "Ready to read" for 20 s (`FINISHED_ROW_S`). After that the only way back is "show me", which reaches the **last** result alone (`session.py` `_show_last`). Nothing lists earlier answers. Every product compared here (§3) does the opposite: each request becomes a lasting item in a list, marked unread until seen, and voice is one way into it.
2. **What's put aside mostly stays put aside.** In the log, 81 requests went to the stack and 26 came back: **55 of 81 (68%) never returned**. Of 46 the owner stopped, 11 came back. Of 30 questions Swift asked that went to the stack, 13 were answered later.
3. **Swift's own questions expire with the card.** 31 questions went unanswered. 18 were "Turn off Wi-Fi?" or "Turn on airplane mode?" during check runs, and most of those were probably left on purpose. The other 13 were real clarifications: a misheard word, or which contact was meant. Each could be answered only while on screen, inside a 25 s window.
4. **Voice is the only repair path that gets used.** Of 595 requests with words, **1 was typed**. Speech failed 75 times (62 unclear, 13 no speech), and 44 more captures ended in silence. When Swift mishears, the owner says it again; nothing on screen lets them fix the words.
5. **Long work has no place to land.** 34 runs took over a minute (15 over two). Only 3 of them were watched. 19 wrote into Word, the one place long output can go today. Research phrased as "summarize it in detail" appears 20 times, all testing, and the answer on the card is clipped at six lines.
6. **Most of the log is testing,** so these are upper bounds on friction and lower bounds on real need (§2.1). The overlay doesn't log what it draws, so "an answer left before it was read" can't be counted at all.

**My judgment**

- **The limit is durability, not reach.** Swift can already do more than the owner can return to. The planned directions (the Deck, Halo, the interaction layer, desktop choreography) mostly improve how things look and move *in the moment*. Only the Swift window (step 7) and "while you were away" (step 4) make things last, and both come late.
- **Expand the direction in three ways, none of them a new surface before daily use:**
  1. **Things last** until the owner has seen or ended them: answers, questions, stopped work.
  2. **A second channel for repair:** the heard words can be fixed by typing. Typing a request is already allowed. This never touches approving.
  3. **A place for long output** before the interaction layer's Space: the reader stays until it's closed, and the answer can open as a file.
- **Don't expand** into a phone companion, continuous conversation or more choreography yet. The log shows no demand for them, and each adds a place where a frame can be refused silently (handoff §2).

## 1. Method

- **Read:** the documents listed above, handoff §1, §4 and §5, owner checks 191–212 and their ledger status, and the overlay's source (`overlay/src/`: `answer.ts`, `deck.ts`, `presenter.ts`, `panes.ts`, `protocol.ts`, `main.ts`), plus `session.py` for "show me".
- **Counted:** the owner's `interactions.jsonl` (716 records, 2026-10-23 to 2026-11-12), with throwaway scripts outside the repo. Only short transcript fragments are quoted.
- **Compared:** Copilot on Windows, ChatGPT desktop, Claude desktop and Cowork, the Codex app, and Claude Code's desktop app, from web sources (§3). Most were secondary, and none of the products were used by hand except the last.

### 1.1 What the owner checks say

- **191–197 failed on 2026-11-08.** Most failures were speech and turn ownership ([`2026-11-08-interaction-investigation.md`](../audit/2026-11-08-interaction-investigation.md)). Two were the surface: 194 (the first answer left before it could be read, unproven on screen because the overlay doesn't log draws) and 196 (a bare "Hey Swift" was taken as the answer to a question).
- **201–212 have never been run** (`owner-checks.md`, "Where every check stands"). They aren't failing, so they're no evidence either way.
- **233–239 (2026-11-12)** probe requests in the owner's own words, and haven't been run yet.

## 2. What the owner can't do today because of the surface

Ranked by how often the log shows it. "Surface" means the agent could have done it and the screen or interaction model was what stopped it.

| # | Limit | Log evidence | Where it comes from |
|---|---|---|---|
| 1 | **Come back to what was put aside.** The stack holds it, but returning is rare | 81 parked, 26 resumed (68% never came back); 46 stopped, 11 resumed; 57 resume offers, 26 resumed | The stack is a corner box you double-click (ADR-015 §9). It has no unread count, no voice listing, and nothing brings it up at a return |
| 2 | **Fix what Swift heard without repeating it** | 62 unclear-speech errors, 13 no speech, 44 silences; 104 records with unsure words; **1 typed request in 595** | The text box is a separate gesture (Ctrl+Alt+Space). The heard words on the card can't be edited, and seams decision 4 (one gesture to open the box) is still open |
| 3 | **Answer Swift's question later** | 31 unanswered: 13 real clarifications ("What does T stand for…", "Which Francis…", "Did you mean Alex Samia?"), 18 yes/no system questions in check runs; 13 of 30 parked questions answered later | A question lives on its card for 25 s (decision 6), then goes to the stack (limit 1) |
| 4 | **Find an earlier answer** | "Show me" said 11 times, `show_last` 5 times; "Do you remember my last request?" once; 42 done records whose last line was cut short with "…" | Answers fade after 4–20 s; "show me" reaches only the last result; nothing lists earlier ones |
| 5 | **Read and keep long output** | 34 runs over 60 s, 3 watched; 19 wrote into Word; 20 "summarize it (in detail)" requests; "make it shorter" twice | A long answer is clipped at six lines; Read more opens the reader; "Show in Word" on long answers is "later" (decision 4); seams decision 6 (does Read more stay until dismissed?) is open |
| 6 | **Decide on a card in time** | 16 approvals ended with no answer or cancelled; median 10 s to approve, 18 s to reject, 29 s to change; slowest 363 s | 45 s countdown, paused when away; a card that runs out goes to the stack safely (ADR-017 §2.5). X-17's long-card questions are open (handoff §5) |
| 7 | **Keep track of several requests at once** | 35 said beside another, 13 queued behind, 8 bare "Hey Swift" while busy | Answered by the Deck's Step 1 (on `main`, not run on the PC) and Step 2 (needs item g) |
| 8 | **Learn what Swift can do** | Rare but telling: "Um what do I do?", "…create new workflows", "Why can't you make my birthday repeat…" | Help is one fixed paragraph ([`assistant-ux-research.md`](assistant-ux-research.md) §4.3) |
| 9 | **Steer a running request** ("also include sources") | Not countable: a request said beside a running one starts a new one (35 beside). Check 197's long and short versions ran separately | Stop and Watch exist; nothing adds to a running run. Partly the agent: whether a running Claude Code run can take more input is unproven here |
| 10 | **See why Swift did what it did** | Not countable: 11 escalations to a bigger model and 113 workflow picks happen with no sign on screen | "Why?" belongs to the Swift window (step 7) |

### 2.1 Caveats

- **Most of the log is testing.** 2026-10-27 (236) and 2026-11-04 (119) were test days, and the repeated phrases ("research the history of tea…", "turn off the Wi-Fi") are check steps. Limits 3, 5 and 6 are inflated by checks that tell the owner to reject or wait. Limits 1, 2 and 4 are less so, since nothing in the checks asks the owner not to return.
- **"Never came back" may be fine.** A stopped request is often one the owner didn't want. The log can't tell abandonment from loss.
- **The overlay can't say what it showed.** Whether an answer was read before it faded is unmeasured. That's the interaction investigation's §3.1 item 4, still open.

## 3. How others let a person see, steer, review and come back

As documented or reported in late 2026, not tested except where it says so.

| Product | See | Steer | Review | Come back |
|---|---|---|---|---|
| **Copilot on Windows** | "Hey Copilot" with a mic icon and chime; Vision reads the screen; Ask Copilot on the taskbar | Voice or text in a chat; Copilot Actions works in a separate agent workspace | Approve sensitive steps in Actions | The Copilot app's chat history. Ask Copilot was temporarily disabled in August 2026 ([assistant-ux-research](assistant-ux-research.md) §1); current state unverified |
| **ChatGPT desktop** | Voice on Windows since about July 2026 (version 26.715, reported), across chat, Work and Codex | Start tasks, check status and give follow-up instructions **by voice**; only one voice chat active at a time | Projects and chats; an artifacts viewer | Every voice chat is kept in history, searchable with Ctrl+K; notifications; scheduled and long-running work |
| **Claude desktop / Cowork** | A Progress panel beside the chat, with working folders and context | Chat in the task | Files in the working folder | Phone notifications when a task finishes or needs input (reported). User reports through 2026 describe the Progress panel going stale against the backend |
| **Codex app** | Threads running in parallel, in a sidebar | Per thread; Plan mode; a goal | A review pane for diffs with inline comments; an artifact viewer | Unread marks on threads; an "Unread chats" section in the command menu; a Triage section for automation results, filterable to unread (third-party reports); a forum post asks for "mark completed" beyond the unread dot |
| **Claude Code desktop** (seen first-hand: this document was written in it) | A sidebar of sessions with their state; a task list under the latest message | Message any session; side sessions report back | Diff, PR, terminal and browser panes | Sessions stay in the sidebar until archived, with unread and waiting marks; a "next step" box ends each turn |

**What they share:** every request becomes a **lasting item** with a state, an unread mark and a place in a list, and voice is a way into those items rather than a separate world. ChatGPT's desktop voice is the closest to Swift: voice that starts, checks and steers tasks that then live in the app's history.

**What Swift keeps that they don't:** the product rules (a spoken approval needs the name, typing never approves, no listening while locked, logs without content); Swift drawing every consequential fact itself; and nothing leaving the PC except model work. None of the recommendations below trades any of these.

**A warning from Cowork:** its reported stale Progress panel is the same failure as Swift's silent frame refusals (handoff §2, review item 9). A lasting list is only trustworthy if it's one view of one source of truth, which is what run records and item g give.

## 4. Which limits the planned direction already answers

| Limit (§2) | The Deck | Halo | Interaction layer | Desktop choreography | Step 4: at rest and "while you were away" | Step 7: the Swift window |
|---|---|---|---|---|---|---|
| 1 Come back to the stack | Step 2: cards in line leave the stack and show as edges | §3.12: one "while you were away" card replaces the stack on return | Corner stack as an aggregate | — | **Yes**, on return only | Activity, partly |
| 2 Fix what was heard | — | — | Not covered | — | — | — |
| 3 Answer a question later | — | Plan card, not questions | "Question" facet, placed alone | Rule 5: a waiting card never hides | **Partly:** [assistant-ux-research](assistant-ux-research.md) R10 makes its items answerable | — |
| 4 Find an earlier answer | Step 2: ready answers come forward instead of fading after 20 s | — | "Recalling" mode, named only | — | — | **Yes:** Activity |
| 5 Long output | Step 1: Read more folds the deck | Long-answer block | **The Space** (weight 5) | — | — | — |
| 6 Decide in time | Step 2: a due card waits as an amber edge with no countdown | The approval ladder; the plan card | Decision 5 | — | Held cards on return | — |
| 7 Several at once | **Yes** | Edges drawn | Facets | — | — | — |
| 8 What Swift can do | — | Hints (3 per kind) | "Teaching" mode | — | — | "What Swift may do", Workflows |
| 9 Steer a run | — | — | "Steering" mode, named only | — | — | — |
| 10 Why | — | Origin line (N2) | "Why?" on every task | — | — | **Yes:** Activity with "Why?" |

**Answered by nothing planned:** 2 (repair by typing on the card) and 9 (adding to a running request). **Answered only late:** 4 and 10 wait for step 7, after watchers (5) and recipes (6). 1 and 3 are answered at return, not during the day. 5 waits for the Space, which has no date and comes after item g, daily use and an ADR.

## 5. Recommendation

**Keep the order.** Reliability and two weeks of daily use come first (handoff §4 c, d). Nothing here needs a new window, a dependency, or a change to a product rule. What changes is **when** durability arrives, and **what daily use measures** so the owner can decide.

| Gap | Smallest next step | When (handoff §4) | Product rules |
|---|---|---|---|
| **Measure it first** (all) | Add counts to the usage report from fields the log already has: parked and never resumed, questions unanswered, "show me" with nothing running, typed versus said, long runs watched. No content | During d, after its first report (`spikes/usage/report.py`, small) | Counts only: logs stay content-free |
| 4 Find an earlier answer | **By voice first, over run records:** "what did you say about the tea?" or "show me the answer before that" reopens a past result on the card. No new surface. Then, if daily use asks, a "Recent" list of the last ten results in the existing tray pane | Groundwork: run records, ahead of step 7. The "Recent" list is a stop-gap like [assistant-ux-research](assistant-ux-research.md) R9 | Results stay local and open only on the owner's PC. Reopening an old confirm never re-approves it |
| 1, 3 Come back to the stack; answer later | A count on the stack ("3 waiting") that the capsule shows at rest, and "what's waiting?" by voice. Parked questions answerable from the stack without reopening the request | With item g (the count must match what's drawn), then step 4 | A parked **approval** still needs Swift's name or a click on Approve when reopened; a parked question takes a plain answer only while it's on screen (as now) |
| 2 Fix what was heard | Click the heard words on the card to open the typing box with them filled in, and send the fixed request. Answer "what did you just hear?" ([assistant-ux-research](assistant-ux-research.md) R4) | After Halo's Step B (one card renderer), small; settle seams decision 4 with it | **Typing never approves:** this edits a request, never a card's answer. A fixed request that leads to a confirm card gets a fresh card. A second reviewer should check the edge |
| 5 Long output | Two owner decisions already open: seams decision 6, Read more **stays until dismissed** (recommended there); and decision 4, **"Show in Word"** (or Notepad) on a long answer, moved from "later" to after d | After d | Swift writes into an app only when the owner's words asked, so this opens a file Swift creates; it doesn't write into an open document. Whether a click on the button counts as the owner asking is for the owner and a second reviewer |
| 6 Decide in time | Nothing new: the Deck's Step 2 and the X-17 decisions cover it | After g | Unchanged |
| 9 Steer a run | First prove whether a running Claude Code run can take more words. If it can, "also …" said to the request in front adds to it, with an edge saying so | After `claude/harness-takeaways` merges, as a spike | A word added to a run can't approve anything the run then asks |
| 8, 10 Discover; why | As planned: one capability source (R7) and "Why?" in step 7 | Groundwork and step 7 | — |

### 5.1 Does the UI direction need to expand?

**Yes, in scope rather than in surfaces.** The directions so far answer "how should a request look and move while it's happening?" They need a fourth question beside the Deck, Halo and the interaction layer: **"what happens to it after it leaves the screen?"** Concretely:

1. **Add durability to the Deck's rules:** nothing the owner hasn't seen or ended disappears. It becomes an edge, the stack or the record, never nothing. ADR-018 Step 2 already does this for ready answers; extend it to faded answers and expired questions.
2. **Make Recalling a first-class mode**, by voice over run records, before the Swift window, rather than a row in the interaction layer's list of twelve.
3. **Give repair a typed path** on every card that shows heard words, held to "typing never approves".
4. **Give long output a home** (a reader that stays, then a file) before the Space.

**Not recommended now:** a phone companion (decision 21), continuous conversation (decision 13), or more desktop choreography before item g. The log shows none of them as a limit yet, and each adds a surface that can drift from the backend.

## 6. Unverified

- **Product facts in §3** come mostly from secondary sources: ChatGPT's desktop voice date and version, Codex's unread and Triage features, Cowork's notifications and bugs. OpenAI's Windows release notes refused the fetch (403). Copilot's late-2026 state isn't established.
- **Whether a running Claude Code run can take added words** through the Agent SDK isn't checked here.
- **The 13 "real" unanswered questions** were picked by reading the question text, not by asking the owner whether they meant to leave them.
- **Whether "never came back" is loss or choice** (§2.1).

## Sources

Read on 2026-11-12. **Fetch:** read through a summarising fetch. **Snippet:** seen only in search results. **Secondary:** not the vendor.

- OpenAI, [ChatGPT features](https://learn.chatgpt.com/docs/features) (redirected from the Codex app features page). Fetch.
- [Codex agent command center and session picker show unread results](https://www.remio.ai/post/openai-codex-rust-v0-167-0-adds-agent-controls-and-repairs-session-recovery). Snippet, secondary.
- [Codex app changelog: Unread chats in the command menu](https://www.gradually.ai/en/changelogs/codex-app/). Snippet, secondary.
- [Codex desktop automations and the review queue (Triage)](https://codex.danielvaughan.com/2026/04/08/codex-desktop-automations/). Snippet, secondary.
- [OpenAI forum: mark a thread completed in the Codex app](https://community.openai.com/t/mark-thread-completed-in-codex-app/1384026). Snippet.
- [ChatGPT Voice on the desktop app controls agents by voice](https://pasqualepillitteri.it/en/news/8825/chatgpt-voice-desktop-control-ai-agents), [Neowin](https://www.neowin.net/news/chatgpt-voice-experience-gets-a-massive-upgrade-on-desktop/). Snippet, secondary.
- [Getting started with Cowork](https://support.claude.com/en/articles/13345190-getting-started-with-cowork). Snippet.
- [Cowork Progress panel bug reports](https://claudeissues.com/issue/93910-feature-cowork-persist-a-chats-open-tasks-in-the-progress-panel-across-sessions). Snippet, user reports.
- [Claude Cowork comes to iPhone and web](https://www.igeeksblog.com/claude-cowork-iphone-web/). Snippet, secondary.
- Microsoft, [Making every Windows 11 PC an AI PC](https://blogs.windows.com/windowsblog/2025/10/16/making-every-windows-11-pc-an-ai-pc/) (October 2025). Snippet.
- [Windows Central on Hey Copilot](https://www.windowscentral.com/microsoft/windows-11/microsoft-dubs-windows-11-pcs-the-computer-you-can-talk-to-as-it-launches-new-agentic-ai-voice-input-mode-that-lets-your-pc-do-things-for-you). Snippet, secondary.
