# Swift: handoff (2026-11-10)

Read this first when picking Swift up in a new session or account. It holds everything still open: what's built, what's left, what the owner must run and decide, and in what order. The working rules are in [`CLAUDE.md`](../../CLAUDE.md).

## In one minute

- **Swift works in tests, and has barely been used for real.** Since 2026-10-29 it was used on 4 days, and 119 of the 150 requests were one testing day. The roadmap was meant to be decided by two weeks of daily use, which hasn't happened yet.
- **Reliability work is the current focus.** Nearly all commits since 2026-11-04 went on it. The review's items 1 to 8 are committed, and the latest ones reach real causes. Most of them have no real-PC evidence yet.
- **The product roadmap hasn't started.** None of the groundwork in §4 exists yet.
- **The Deck's Step 1 is on `main` (merged 2026-11-07) and hasn't been run on the real PC** ([ADR-018](../decisions/ADR-018-the-deck.md) §4.1). The owner asked for it before the short checks. Two things wait on them: whether to keep it (it adds more lines than it removes, and undoing it now means reverting it on `main`), and what the review of its backend change left for them (ADR-018 §4.1): a request said beside a working card now stays behind it, which changes what a plain "stop" reaches.
- **Log privacy is fixed in the code and unproven on the PC.** X-03, X-04, X-05 and X-19 are on `main`. Swift needs a restart to use them.
- **Next:** restart Swift, run the short real-PC checks, then use Swift daily for two weeks (§3 and §4). X-17 is fixed, so the cards you approve show the whole change.

- **The owner's check 185 (2026-11-07) found six problems in voice and side-by-side requests.** Causes and fixes are in [`2026-11-07-voice-and-requests.md`](../audit/2026-11-07-voice-and-requests.md), merged to `main` and not run on the real PC. Swift's replies are off by default, apart from "Hello". Why checks 191–197 still failed is in [`2026-11-08-interaction-investigation.md`](../audit/2026-11-08-interaction-investigation.md), which led to [ADR-020](../decisions/ADR-020-one-record-per-conversation.md). A branch is trialling whether Swift gets a dedicated wake model (§6).
- **§6 lists the work that isn't on `main` yet, and the next free owner check number (216).** Every session reads §6 before it starts, and adds its own branch there.

## 1. Where things stand

**Local `main`** (not pushed anywhere) has all of this:

| Area | What | Where it's described |
|---|---|---|
| Lanes | Fast local answers, the system lane (timers, volume, display, radios, windows…), the light model lane, workflows, the agent | ADR-007 §10, ADR-016 §13–14 |
| Speech | Local speech-to-text (parakeet), wake listening, the room-relative noise gate, Swift speaks (Windows voices) | `docs/stt-*.md`, ADR-016 §15 |
| Actions | Gateway with confirm cards and undo; calendar (look, change, cancel, Meet links); Gmail drafts written as the owner; Google Contacts | ADR-010, ADR-011 |
| Attention | Up to 3 requests at once, presence, held cards, the waiting stack, typing to Swift | ADR-013, ADR-014, ADR-015 |
| Overlay | Capsule redesign (dark and light, tray panel, pause listening, speaking state), live view | ADR-017, `docs/design/swift-overlay/` |
| Dialogue | Swift asks for what's missing, the question card, carry-over, end of speech | ADR-016 §16, `phase-c-status.md` |
| Recordings | Saved recordings that improve hearing (7-day loop) | `recordings-status.md` |
| Sign-ins | Google's and Claude Code's sign-ins checked at start-up, daily and when refused, with a card to sign in again | `swift/signin.py`, owner checks 120–123 |
| Confirming | Swift's own "Turn off Wi-Fi?" is a Yes/No card; a plain "yes" or a click works only while it's on screen | §5, owner checks 128–131, 163–164 |
| Offline | An agent request is answered at once with what still works; "turn it back on" follows the last switch | `swift/network.py`, owner checks 132–134, 150–153 |
| Seams audit | One window per question, what's on screen resent on every connection, lane capabilities and a run watchdog, one set of intake rules, the report can say FAIL | [`2026-11-seams-audit.md`](../audit/2026-11-seams-audit.md), owner checks 139–162 |
| Reliability review | Items 1–8 of the review's list (below) | [`2026-11-reliability-audit-review.md`](../audit/2026-11-reliability-audit-review.md) §7 |
| Log privacy | `swift.log`'s interaction line is an allow-list. Failures and denials log a type or a code, tracebacks have no messages, and a recipient's domain stays in the journal. Older lines in `swift.log` are unchanged | Seams audit X-03, X-04, X-05, X-19; owner check 123 |

**The review's items, all committed:**

| Item | What | Commit |
|---|---|---|
| 1 | A plain "yes" answers only the question on screen | `dde1105` |
| 2 | The overlay holds one state, the presenter's | `34b9395` |
| 3 | No lost answers: a question's card ends in order | `b653549` |
| 4 | Report check 149 fails when a due card was sent and not drawn | `6ae9672` |
| 5 | `fragment` refuses hesitations only; the one-word confidence bar is off until measured | `d5fa03f` |
| 6 | A seam test: real backend frames through the real presenter | `2610e71` |
| 7 | Swift's own questions belong to a live request (prototype kept: `session.py` +110, −385) | `79c3318` |
| 8 | A due item is never refused: it waits in the stack | `fdfdb23` |

**Measured on `main` at `9c07c33` (2026-11-06):**

| Suite | Result |
|---|---|
| Python | 1,539 passed, 1 skipped, 12 expected failures (open findings, §2) |
| Overlay | 89 passed, 1 todo (O-03); `tsc` clean |
| Routing parity | 413/423 (97.6%), 0 harmful; the 10 misses are the web lane |
| Rust | Not rerun; 30 passed at `ab09f51` |

**Measured on the Deck's branch before it merged (2026-11-07):** Python 1,599 passed, 1 skipped, 12 expected failures; overlay 112 passed, 1 todo (O-03), `tsc` clean; Rust 29 passed; routing parity 413/423, 0 harmful.

**Measured with X-17's fix (2026-11-07):** Python 1,637 passed, 1 skipped, 12 expected failures; overlay 115 passed, 1 todo (O-03), `tsc` clean. Rust and routing parity not rerun: neither is touched. One earlier full run had a single failure that didn't come back and wasn't identified, so a flaky test is possible.

**Limit of these tests:** the seam test reaches the real presenter and the Deck's order but not the DOM or Tauri, and it replays one way only (`test_seam_replay.py`). The harness now draws other requests as the app does, so frames replayed there show the same edges, but it still has no pane windows. Green tests have coexisted with bad days on the real PC before.

## 2. What's open in the code

No work is in progress on `main`. These are the known problems, most serious first.

### Product-rule and safety gaps

X-17, X-07, X-18, X-01 and X-08 are fixed (2026-11-07 and 2026-11-10), each reviewed by someone other than its author. What each left is in its audit entry. Owner checks 183–184 and 212–215 cover them on the real PC.

- **X-08's window:** an approved email waits 5 seconds ("Say “stop” to keep it"). A stop then keeps it; after that it goes. Unproven on screen: whether "You stopped it in time" shows over the run's "Cancelled" card (check 215).
- **X-01's limits:** only the word right after the searched name is compared, so "Chianu Francis" isn't caught. A surname that is also a common word ("Francis Will"), or typed lowercase among capitalised words, gets through without asking. Some typed lowercase requests still ask ("email francis budget numbers"). Where Swift can't ask (no `ask_fn`), a guessed contact is still resolved, as before.
- **Path spellings:** this PC's own drive shares (`\\localhost\c$`) and `\\?\C:\…` now get the same never-read verdict as `C:\…`. Unproven: whether `\\127.0.0.2\c$` or `\\<PC>.local\c$` make the check raise and refuse the read.
- **A flaky test:** `test_parked.py::test_finish_the_named_task` fails about one run in three, alone or in the full suite. Nothing changed on 2026-11-10 touches it.

The X-05 entry in the audit lists what that fix left: `workflow skipped` can quote a workflow file, `redact` doesn't recognise a bare `sk-ant-…` key, the backend's stderr is unchecked, and a failed action's text is kept nowhere on disk.

**What a separate review found:** on X-05, each of the first three rounds caught a real fault, two of them added by the follow-up commit under review. X-17 went the same way: the first two rounds each blocked it (agent text could pass for Swift's own, first by quotes, then by a wrapped row), and the third passed it. Keep sending product-rule fixes, and their follow-ups, to a reviewer who didn't write them.

**What X-17's review left, all low:**

- Dropping the "Blocked" note: an approved call to another file also counts as working around a refused one, and it counts when approved rather than when it succeeds. It needs the agent to misreport, and nothing unapproved is written. The fix is to match on the path and clear on a successful result.
- The file name in a card's title is still the agent's text, unmarked. The marked path is below it.
- Lines of U+2800 aren't collapsed as blank. A card reopened after a hold may start at the top.
- The generic card for other tools still shows 60–300 characters. The default `confirm_tools` don't reach it.
- Not seen on the real PC: the mouse wheel on the card and the "More below" sign hiding itself as you scroll. The Claude browser pane was hidden, so it drew no frames. Owner check 183 covers both.

### Root causes still open

- **The overlay can still refuse a frame silently.** `presenter.ts:273–277` declines frames and the backend isn't told. Only due cards have an acknowledgement. Frames also go out through two doors (`_send`, `_raw_send`) and fire-and-forget tasks, and each countdown runs on both sides (T-08). The planned fix is review item 9, in §4.
- **Speech acceptance is tuned incident by incident.** The review's M4 counts eight commits with no proven cause. Nothing stops a change from making a correct sentence wrong (W-03), and unsafe word fixes can still be proposed (W-01, W-02). Saying "no" over Swift's voice has four failing tests (V-02). A misheard single word reaches the agent again until a bar is scored on saved clips (item 5).
- **`session.py` is 4,824 lines**, up from 4,401 when the split was agreed. New work goes in small modules.

### Not understood yet

Say "unproven" about these until they're reproduced:

- **Wake reliability after idle:** three rounds of fixes, no proven cause. The `short_wake` counter in the "wake listening" log line shows how often the short "Hey Swift" rule fires.
- **Gmail "couldn't put the cursor in the body":** comes from a focus check in `desktop/windows.py`. Not investigated.
- **False-wake rate:** not measured.
- **B-05:** the first request after start is 8–25 s slower. Not rechecked.

### The rest of the seams register

Details are in the register, [`2026-11-seams-audit.md`](../audit/2026-11-seams-audit.md) §3. Findings there with no "fixed" mark are open, except as noted here. Those without a test or code reference above weren't rechecked on 2026-11-06.

- **Timers and state:** T-04 and T-05 (expected-failure tests), T-09, T-10, T-12.
- **Overlay:** O-03 (todo test), O-09 to O-14. O-04's card scroll landed in `ab09f51`; confirm with owner check 137.
- **Speech:** V-03, V-04, W-04 to W-07.
- **Routing and measurement:** R-07 (the light lane; 0% of requests in the usage report), R-08, R-09, R-10, Q-02 (partly addressed by the seam test), Q-03.
- **Executors and privacy:** X-02, X-06, X-09, X-11, X-13, X-14.
- **Not done from S1 and S2:** the heartbeat (H-06), and an aside question during a lane question still ending it (the rest of D-02; since `79c3318` it goes to the stack).

## 3. What the owner runs next

The owner tests on the real PC with [`docs/testing/owner-checks.md`](../testing/owner-checks.md), then pastes the report.

1. Restart Swift: Tray → Quit Swift, then in `overlay`:
   ```bash
   npm run tauri dev
   ```
2. Note the time, and run the **short set** below (the estimate is about 30 minutes; these target the fixes most likely to break):
   - **Questions and approval:** 128, 131, 141, 144, 156, 160, 161, 163, 164.
   - **What's on screen:** 146, 147, 149, 165.
   - **Requests side by side:** 152, 158.
   - **The Deck:** 168, 173, 179 and 181 first, then the rest of 169–182. The Deck is on `main`, so these checks run with it: a failure anywhere in this set may come from either the reliability work or the Deck.
   - **The whole change on the card:** 183, 184.
   - **Lock:** 139.
   - **Items 3 and 7, and the safety fixes of 2026-11-10:** 212 (item 3; check 106 covers item 7), 213 (X-07), 214 (X-01), 215 (X-08).
3. Paste the report:
   ```bash
   uv run python spikes/owner_checks/report.py --since HH:MM
   ```
   The next session diagnoses it against `%LOCALAPPDATA%\Swift\logs\swift.log` and fixes what failed, using the rules in `CLAUDE.md`: prove the cause first, one finding per commit.
4. **Then use Swift for real, every day, for two weeks:** the requests you'd make anyway, not test phrases. Once a week, paste the usage report (counts only, nothing you said), with the date you started:
   ```bash
   uv run python spikes/usage/report.py --since YYYY-MM-DD
   ```
   Add `--exclude YYYY-MM-DD` for a day spent testing; the report flags days with over 100 requests.
   - From a Claude Code session, the sandbox shows an old copy of `%LOCALAPPDATA%\Swift`. Pass `--interactions //localhost/c$/Users/frchi/AppData/Local/Swift/interactions.jsonl` to read the real log.
   - **So far (2026-10-29 to 11-06):** 150 requests on 4 days, 38% answered by Swift, 0% by the light model, 69% done cleanly, agent p50 22.0 s, $0.82. Most of this is testing. Targets are in product-direction §9.

**The rest of the checks** (50–165) stay in the file. Run a section when its area misbehaves or changes; a full pass waits for the checks rewrite (§4). Notes for those sections:
- **110–116:** remove `save_audio: true` first.
- **120–123:** in Google Cloud Console → Google Auth Platform → Audience, **publish the app** (In production, unverified), if that hasn't been done. In Testing, Google ends the sign-in every 7 days.
- **ADR-016 A2** isn't in the checks file: "turn off Bluetooth" → yes → "undo that"; "turn on airplane mode" → no; "turn on do not disturb"; "turn the volume down and write a haiku about tea".

## 4. The order of work

Set on 2026-11-06 from the seams audit, the reliability review and the product direction. The product steps keep their numbers from [`product-direction.md`](../explorations/product-direction.md), adopted 2026-10-28, which explains each choice. In short: Swift should be the owner's own operator (recurring work, the owner's rules, any agent behind it, learning with consent), not a match for Copilot or Siri feature by feature.

**Now: close the reliability work**

- **a. Product-rule and safety gaps** (§2): done 2026-11-10, X-17 to X-08.
- **b. Owner checks for items 3 and 7:** done 2026-11-10, checks 212 and 106.
- **c. The short real-PC checks,** then fixes for what fails (§3).
- **d. Two weeks of daily use** (§3 step 4). Its numbers decide what comes after the groundwork.
- **e. The light lane (R-07):** retire it unless the owner wants it retargeted (seams decision 2).

**While the owner uses Swift**

- **f. Speech:** add the per-sentence check (W-03) before any more tuning, then make word-fix proposals safe (W-01, W-02, seams audit §7.4 step 1). Any change to a confidence bar is scored on the owner's saved clips. Prove the cause of wake after idle before another fix.
- **g. Review item 9: one versioned screen snapshot,** derived from the existing owners and acknowledged when drawn. Decide on the ledger here: build it only if new failures still come from holders disagreeing, so use what daily use shows. Prototype on a branch and keep it only if it removes more than it adds.
- **h. Review item 11:** one table of lifetimes. Cheap; no reproduced failure depends on it.
- **The Deck ([ADR-018](../decisions/ADR-018-the-deck.md)),** the owner's chosen direction for how requests share the screen (2026-11-06). **Step 1 is on `main` (merged 2026-11-07).** It's overlay only apart from what takes the front (ADR-018 §4.1), and the owner approved it going before g, a deliberate departure from the review's order. The owner first timed it after the short checks (c). On 2026-11-07 they asked for it before them, since they couldn't run the checks then, so the checks no longer test the reliability fixes alone. Daily use (d) still happens on the screen that stays. Step 2 needs g.
- **Halo ([ADR-019](../decisions/ADR-019-halo-design-system.md)),** the owner's chosen look and design system (2026-11-07), replacing the Capsule's look and keeping the Deck. Design only so far: [`docs/design/halo-system/`](../design/halo-system/). The task is [`brief-halo.md`](brief-halo.md). **Step A** (a dev-only look switch, so the owner can check Halo on the real PC) is small and may go early if the owner wants. **Step B** (one card renderer, no new features) waits for the owner's go-ahead, by default after d. N2 (`origin` in the protocol) goes with run records in the groundwork. ADR-019 also added a product rule to `CLAUDE.md`: deleting a file always asks.
- **The interaction layer** ([`interaction-layer.md`](../explorations/interaction-layer.md), 2026-11-10): an exploration, not decided, of Swift as several surfaces beside Windows rather than one overlay. It has nine decisions for the owner before an ADR, and nothing in it should be built before g and d.
- **i. After g:** the timer widget and the Deck's Step 2. **Last:** the owner-checks rewrite, as a fresh baseline.

**3. Groundwork.** Not started. No behaviour change the owner should notice:

- split `session.py`: run launching, follow-ups, workflows and the local lanes into their own modules;
- **run records:** one append-only event log per run (steps, tool calls, approvals, artifacts, which worker and why), generalizing the action journal; the interaction log becomes a view of it;
- **a settings and memory store** owned by Swift, separate from `config.yaml` (which still wins), every record with its source (said, approved, inferred), plus "remember", "forget" and "what do you know about me". Keep it safe as in product-direction §5.5: only the owner's words or an approved card write memory, only Swift's backend writes it, every change versioned with its run. The review job that proposes patterns from run records is §5.6;
- **a `WorkerTask` contract:** executors take the request, a context pack Swift builds, the grant, a budget and a privacy class; a contract test runs the same tasks on the mock and on Claude Code. Today they still take `start(request, demand, override)`;
- **ADR-014 L3:** quiet modes and call detection;
- **B-05** is worth fixing here: it shows in daily use.

**Next**, in this order unless the usage report says otherwise:

4. Notifications at rest, and one "while you were away" card on return (held cards, stack, unfinished, watcher results), sized to the gap.
5. **Watchers v1:** the owner's top two of ADR-011 §13 (likely boss emails, with the `gmail.metadata` scope already decided in ADR-011 §13.4, and a tech-news digest), with memory of what was already seen. Needs decision 22.
6. **Recipes from runs** (ADR-011 W3, redesigned): "do that again every Friday", "make that a workflow", built from run records rather than hand-written YAML.
7. **The Swift window v1** (a second Tauri window, from the tray): Activity with "Why?", What Swift knows, Workflows and automations, What Swift may do, Look and read. Then settings changed by voice ("speak less"), writing the same store.
8. **ADR-011 W2:** file tools with folder permissions.

**Later, each only when its trigger appears**

- The cheap web lane (ADR-016 Phase I): when daily use or watchers show the agent's time is in the way.
- A second worker (decision 27): when a task needs one, e.g. a cheap or local model for the light lane, or an API research agent for watchers.
- Suggestions from patterns (ADR-011 L1): after a month of real data.
- A Chrome extension for Gmail web (ADR-012 D3): if daily use shows it.

**Deferred** (not started without the owner's OK): screen awareness and the vision fallback (ADR-016 F, ADR-012 D4/D5, decision 26), offline with a local model (G, decision 19), voice ID and the phone companion (H, decisions 20, 21), smart home and messaging connectors (decisions 16, 17), Apple Calendar.

**Small leftovers, only on request:** timers that pause and resume, a stopwatch, repeating reminders (ADR-016 §14.4); the redesign's timer card details (decision 5).

**The test for all of this** (product-direction §9): if after six weeks of daily use the owner still reaches for Copilot or a chat app for most things, that answers whether Swift has a reason to exist.

## 5. Decisions waiting on the owner

**Open from the seams audit** (§9 there; its decisions 1 and 9 are taken). Recommendations are the audit's.

| # | Decision | Recommendation |
|---|---|---|
| Seams 2 | The light lane: retarget it at thread questions, "try again" and small talk, or turn it off and drop its warm CLI? | Turn it off until retargeted |
| Seams 4 | One gesture to open the text box: click the capsule, or double-tap the push-to-talk key? | Click the capsule, keep the hotkey |
| Seams 5 | Try Windows' communications microphone path (echo cancellation) behind a setting, accepting it may change how the mic sounds? | Yes, as a trial |
| Seams 6 | Answers with "Read more": stay until dismissed, or go to the stack as unread? | Stay until dismissed |
| Seams 7 | A weekly labelling card for misheard clips, where typing the right words is allowed (it labels, never approves)? | Yes |
| Seams 8 | Daily use runs the Vite dev server, so every merge reloads the overlay. Keep that, or use a built app? | Keep it |

**Open from X-17:**

| Decision | Why it's open | Default until you choose |
|---|---|---|
| The 12,000-character limit on a file change's card | Longer changes are refused and the agent goes on in pieces, each on its own card. A long document means several cards | 12,000 |
| Must you scroll to the end before Approve works? | The card says "More below", but Approve works anyway, and "Swift, yes" can't scroll | No, the sign only |
| Countdown on a long card | A full card can't be read in the 45 s it allows. It goes to the stack, which is safe | Unchanged |

**Open from the Deck's Step 1** (ADR-018 §4.1):

| Decision | Why it's open | Recommendation |
|---|---|---|
| Keep Step 1? | It adds more than it removes (+948, −366 in source, overlay and Rust), which `CLAUDE.md` asks the owner to weigh for a structural step | Keep it if 168 and 173 feel right on the real screen; the one-window spike is where the deletions would come from |

**Open from the reliability audits:**

- **Check 13's number:** counting transcription as the prime improves the number and makes nothing faster for the owner. The change was removed; the decision is still the owner's.
- **The short "Hey Swift" rule:** keep or remove once the `short_wake` counter shows how often it fires. It's unproven.
- **The ledger:** decided at item g in §4.
- **Older lines in `swift.log`:** lines from before the log fixes still hold words and domains. Log rotation will remove them in time. Deleting them sooner can't be undone.

**Still open from the checks of 2026-11-04:** when Swift speaks and how much; local models for offline questions; the Watch window shrinking (#10, seams O-09); a held card not coming back on screen (#14: fixes landed in S1, so confirm it's gone).

**Answered:**

- A stop during "Sending…" (seams decision 3): an approved email waits 5 seconds, when a stop keeps it; after that it goes, and a stop lets it finish (2026-11-10, X-08).
- Saved recordings: keep 7 days, and only if they serve a purpose.
- B-01 reads: allowed without a card in the working folders, Documents and Downloads.
- Confirming a reversible change: a Yes/No card; a plain spoken "yes" or a click does it, and typing doesn't. Emails, calendar changes and anything that can't be undone still need "Swift, yes" or a click on Approve. Confirmations aren't read aloud (`speech.read_confirms: false`).
- A plain "yes" counts only when the question is on screen (2026-11-05).
- A recipient's domain stays out of `swift.log` and in the journal (2026-11-06, X-19).
- How requests share the screen: the Deck; other requests stop being draggable on their own; a handoff to the corner, with a spike on one large window later (2026-11-06, ADR-018). Building it before the short checks (2026-11-07). A request said beside a working card stays behind it, and a plain "stop" asks which while the one just said is behind (2026-11-07, ADR-018 §4.1).
- "Say yes and I'll send a correction" follows the same rule as a question: only on screen, and typed only with Swift's name (2026-11-07).
- A run with no progress for 90 s ends by itself and stays in the stack (seams decision 1).
- The lane yes/no window is 25 s from the end of Swift's speech (seams decision 9).

**Running on a default** (change any time):

| # | Decision | Default |
|---|---|---|
| 2 | Idle capsule dot: tray option to hide it? | Shown; suggest adding the option |
| 3 | Pause card countdowns after 60 s without input? | No (a card that runs out goes to the stack) |
| 4 | "Show in Word" on long answers? | Later |
| 5 | Timer card with its length and "+5 min" snooze? | Not yet; suggest yes (small scheduler change) |
| 6 | Question window 20 s (design) or 25 s? | 25 s |
| 7 | Hotkey works while listening is paused? | Yes |
| 8 | Chime when a confirm card appears? | Not yet; suggest yes |
| 9 | "via Claude Code" line on confirm cards? | No |
| 10 | Voice: Windows voices or Piper? | Windows voices; Piper after the listening test (`spikes/tts/voice_test.py`, not run by the owner yet) |
| 11 | When Swift speaks | Only when spoken to (`speech.replies: auto`) |
| 12 | Mic opens by itself after Swift asks a question | Yes (Phase C) |
| 13 | Continuous conversation mode | No: one exchange at a time |
| 14 | Power actions | Lock by voice; sleep, restart and shut down only on a card |
| 15 | Music | Whatever player is running (media keys) |

Decisions 2–9 come from `docs/design/swift-overlay/IMPLEMENTATION.md` (owner questions). Decisions 10–15 come from ADR-016 §11.

**Open, needed before the step named:**

| # | Decision | Needed before |
|---|---|---|
| 16 | Messaging apps actually used (WhatsApp, Telegram, Slack, Teams, SMS) | Connectors (ADR-016 E) |
| 17 | Smart home (Home Assistant, Hue, Matter), or out of scope | Connectors |
| 18 | Maps/travel-time API key acceptable? | Travel-time answers |
| 19 | Offline: a local model (Ollama), or local lanes only | Offline (G) |
| 20 | Voice ID enrolment | H |
| 21 | Phone companion (tunnel), or leave it out | H |
| 22 | Which two watchers or nudges first (boss emails, tech news, opportunities, meeting soon, morning brief) | Step 5 |
| 23 | Personal index of mail, calendar and folders (local); which first | ADR-016 §6.1 |
| 24 | ~~Parity target~~: superseded by the product direction (2026-10-28): parity only where daily use asks for it | Answered |
| 25 | A plain privacy statement in settings (AI work in Claude's cloud; speech, system lane and index local) | Step 7 |
| 26 | Screenshots to a cloud model as a fallback (ADR-012 D5) | Deferred |
| 27 | Other AI providers (Codex, Hermes), and which tasks they'd take | A second worker (Later) |
| 28 | Learning by watching PC use (ADR-011 L3), a strong privacy decision | Never without a yes |

## 6. Branches, sessions and folders

**Checked 2026-11-10.** Keep this table current: a session that starts a branch adds a row, and the session that merges it removes the row.

| Branch | What | State |
|---|---|---|
| `claude/wake-porcupine-trial` | Wake trial: openWakeWord, ViolaWake, legacy Porcupine and an own-voice verifier as stage 2, scored on the owner's clips (`docs/spikes/wake-model-trial.md`) | Spike in progress, waiting for the owner's recordings. Takes in `claude/upbeat-mclaren-ac46da` (the rescore by ear) |
| `worktree-halo-step-a` | Halo Step A: a dev-only look switch, and checks 185–190 | Built, waiting for the owner's go-ahead to merge. It's far behind `main` and edits the handoff, the owner checks and `report.py`, so rebase it first |
| `claude/desktop-choreography-spike` | Spike: a card that comes from the thing it concerns (unfolds from the active window, rises from the taskbar's notification area, or arrives as the window makes room), read once and timed by Swift (`spikes/desktop/card_origin.py`). Native windows only; touches nothing in the app. The first version had a dot following dragged windows: the owner saw it trail, so that's dropped | Run by the owner 2026-11-10: all three motions felt right, no lag. `spikes/desktop/card_overlay/` draws the same motions in a webview (a small separate Tauri app): its self-test passes, the webview begins 2–9 ms after it's told, and the owner ran it 2026-11-10: the push read as one hit, the cards were as good as native, no side effects. Since then a window's card lets go while its window is dragged and re-settles when it's dropped, goes home to a stand-in for Swift's place when another window takes the front, and comes back with its window; a card waiting on an answer stays visible at home. The self-test covers those rules with events fed in by hand; the real event hook and how it looks wait for the owner's run. Nothing from it should be built before g and d |

**Next free owner check number: 216.** When two sessions add checks at the same time, they take their numbers here first.

**Docs added to `main` on 2026-11-10**, from branches that were never merged:
- [`2026-11-08-interaction-investigation.md`](../audit/2026-11-08-interaction-investigation.md)
- [`assistant-ux-research.md`](../explorations/assistant-ux-research.md)
- [`2026-11-10-workflow-lifecycle-audit.md`](../audit/2026-11-10-workflow-lifecycle-audit.md). It recommends run records first, which matches the groundwork in §4.
- The voice listening test script, `spikes/tts/voice_test.py` (decision 10).

**Moved out of the repo:** the old pen-dev pack from `b9ca8c3` is now in `C:\Users\frchi\Documents\Swift-design-screens\pen-dev-handoff-b9ca8c3`. The current pack is `docs/design/pen-dev-handoff/`.

Cleaned up on 2026-11-06 with the owner's OK: every `claude/*` branch and its worktree. `claude/reliability-audit-review` was force-deleted. Its two commits, ending at `43b1273`, added only the review document, which is on `main` unchanged.

Removed on 2026-11-10 with the owner's OK: every merged worktree and branch.

**Kept on purpose:** `mvp/overlay` and `phase0/scaffold` (both merged), and `C:\Users\frchi\Documents\Swift-design-screens` outside the repo (screenshots for the redesign brief).

A session that finishes and merges its work removes its own worktree and branch once the owner agrees:

```bash
git worktree remove <path>
```

```bash
git branch -d <branch>
```
