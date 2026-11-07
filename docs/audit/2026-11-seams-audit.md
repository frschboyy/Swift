# Swift audit, November 2026: the seams

An audit of the places where Swift's parts meet: speech and the dialogue, the dialogue and the router, the backend and the overlay, the session and its executors, and Swift and what it depends on. The owner asked for it after owner checks on the real PC on 2026-11-04. The checks kept failing between the backend and the overlay, while every test suite passed.

Done on branch `claude/seams-audit-a0b7bf`, from `main` at `ab09f51`. This is **report first: no product code was changed.** The branch adds this report and tests that reproduce the findings. Each test is marked as an expected failure until its fix lands (§9).

The October audit ([2026-10-audit.md](2026-10-audit.md)) is the baseline. Its A-01 to A-12, B-01 to B-10 and H-01 to H-07 are not reported again here. They are re-checked in §3.8. Severities and labels follow that audit:

- **Critical:** a broken safety or privacy rule, or a real-world action without a card.
- **High:** a core flow fails.
- **Medium:** usability, latency, maintainability.
- **Low:** polish.

Labels:

- **confirmed:** reproduced in a test or the harness, or shown by the owner's log together with the code.
- **suspected:** follows from the code, not reproduced.
- **design concern:** works as designed, but the design has a gap.
- **unverified:** couldn't be checked here.

Times are local (+03:00) on 2026-11-04 unless another date is given. `session.py` line numbers are at `ab09f51`.

**Update, 2026-11-05.** The owner chose "S0, T-07, then A+C". Done on this branch:

| Step | What | Commit |
|---|---|---|
| S0 (Q-01) | The owner-check report prints PASS, FAIL, NOT SEEN or LOOK. On 2026-11-04 it now says FAIL for 130, as found here | `43c8077` |
| T-07 | Nothing heard acts after a lock, however late it arrives. Owner check 139 | `32e03c0` |
| Layer A (O-06) | Protocol examples both ways, checked by `protocol.py`, by `tsc` against `protocol.ts`, and against every frame the backend sends in the suite | `0da3295` |
| Layer C | `swift/clock.py` (the clock seam), a virtual-time event loop, and a Hypothesis model of the dialogue | `dec1a43` |
| S3 | One window per question (`swift/answer_window.py`): its own deadline, counted from the end of Swift's speech, waiting for an answer still being said, restarted by every re-ask with the deadline sent; a lane question from the owner's new request is asked first and the one it displaces comes back with a whole window. Fixes T-01, T-02, T-03, T-11, T-13. Owner checks 141–145. Decision 9 taken as recommended (25 s from the end of speech; ADR-016 updated) | `f918be9` |
| S1 | One owner of what is on screen. On every `ready` (now sent on every connection) the backend sends the rows, the request in front with its card and the time it has left, a lane's question card, Swift speaking, and the reply window; a card counts down only once the new overlay draws it, and stops when the overlay goes. `hello.ok` carries the backend's instance: a new one clears the old screen. A card behind another isn't sent (`Run.cards`). `bad_message` never reaches a card, and the server logs it. Due cards leave the schedule on `due.shown`; not drawn in 10 s, they go back in line. A question's close always reaches the overlay. Fixes O-01, O-02, O-05, O-07, O-08, O-15. Checked in the harness (a reload and a backend restart with a card up). Owner checks 146–149. **Not done:** absolute deadlines (T-08) and the heartbeat (H-06) | `e602d8d` |
| S4 | Nothing waits for ever. Lanes declare what they need (`LANE_NEEDS`): offline, a request that needs the internet is answered before the light model or an offer is tried. `online()` also asks Windows' Network List Manager (a connection without the internet is offline). Only the agent takes a slot. Two CLI retries with the internet gone end the request (offline, kept in the stack). A run watchdog: 90 s with no word from the CLI, paused while a card or one of Swift's tools waits for you, ends it with "took too long" and keeps it in the stack (decision 1 as recommended). Connect, query and the warm CLI are bounded. Sign-in offers are throttled on the last offer; "couldn't confirm model" online offers the sign-in. A voice that can't start never leaves Swift "speaking". One deadline (45 s) for a Google call and its retries. Fixes R-01 to R-06, R-11, V-01, X-10, X-12. Owner checks 150–155. **Not done:** decision 2 (the light lane) | `eeb3335` |
| S2 | One set of rules for every input (`swift/intake.py`): the steps in one declared order, and each rule once. One approval table (`intake.approves`) used by typing, hands-free, the lane's yes; nothing with no words is an answer (D-06); an unsure answer while a question listens is asked again on its card (T-06); a mid-run control is never an answer to any question during a run (D-08); a click on a lane question goes to it, never through the text box (D-07); a wordy yes is a yes and "hold on" keeps the question with a whole window (D-02); the device named "back on" is in the grammar (D-03, 16 parity cases); a system change and a local answer are kept apart, a radio for 30 min (D-04); "turn it back on" during a run starts beside it (D-05); an utterance during a transcription waits for it (D-09); D-10, D-11. Owner checks 156–162. **Not done:** the entry points still exist as functions that call these shared steps, not one `intake()` function; an aside question during a lane question still drops it (part of D-02) | the commit after `eeb3335` |

Layer C found two new findings (§3.9): **T-13** and **O-15**. It also re-found T-01 and T-03 by itself. Each known open finding is replayed in `tests/unit/test_dialogue_model.py` (`KNOWN`), and the main model steers around its trigger, so a fix shows up there.

---

## 1. In one page

The owner's own summary is right: *"a collection of individual features that work independently but occasionally interfere with one another."* Each feature was built and tested on its own, and each new one was added at the point where it was first needed. Where two features meet, nothing owns the meeting. Five problems explain most of what the owner hit.

### P1. Every way in has its own copy of the steps

A spoken answer, a hands-free request, the hotkey, typing, a click and a follow-up should all pass the same checks in the same order:

- Is a question waiting?
- Is this an approval, and is it allowed from this source?
- Is it "turn it back on"?
- Is it a mid-run command?
- Which lane takes it?

In fact the checks are spread over about six functions (`_interaction`, `_start_typed`, `_midrun_text`, `_hear_transcribed`, `_hear_busy`, `_answer_text`), and each decides for itself which checks to run. For example:

- question matching has three implementations;
- the approval rule has five copies;
- "turn it back on" exists in one path only;
- the confidence gates run in a different order per path.

Each fix so far, such as `cd3f97b` for "Swift, yes" going to Claude Code, closed one path and left the others open.

**Explains:**
- "Swift, yes" went to the agent (fixed for the open mic only);
- "Turn it back on" and "What can I do when the Wi-Fi is off?" went to the agent;
- a wordy "yes" or "hold on" drops the question;
- "turn it back on" typed during a run gets a hint;
- a click on a lane question is routed as typed text;
- an unsure answer is dropped without a word.

**Findings:** D-01 to D-08, T-06.

### P2. One window, several clocks

What the owner experiences as one thing, "Swift is waiting 25 s for my answer", is two to four separate timers in the backend, plus the overlay's own countdowns:

- `_ask_timer` and `_answer_window`;
- the park timer `_question`;
- the reply window `_followup`;
- `Ask.until`, `followupUntil` and `confirmDeadline` in the TS.

They start at different moments: when a message is sent, when Swift finishes speaking, or when a transcription ends. Each restart point (a re-ask, a hint, the end of Swift's voice, an answer still being said) touches only some of them. One timer slot serves every question.

**Explains:**
- the question that went to the stack 2 s before the owner's answer;
- the window not restarted after "say 'Swift, yes'";
- the microphone not listening after "Sorry, was that a yes or a no?";
- a reply window gone by the time a long spoken answer ends;
- "Unanswered" in the stack while the card still counts down;
- a run that hangs because a later question replaced its timer.

**Findings:** T-01 to T-05, T-08, T-11.

### P3. Two owners of what's on screen, and no resync

The backend decides which card, question or answer is in front: `_cards[0]`, `_focus` and `dialogue.pending`. The overlay keeps its own copy (`pendingConfirm`, `asked`, `card`, `typing`, the stack) and changes it by its own rules. Rust keeps a third copy (pane windows). Nothing reconciles them:

- no snapshot;
- no acknowledgement;
- no epoch;
- no resync when the overlay reconnects.

The overlay sends `ready` once per page load. **The owner runs the Vite dev server, so every merge into `main` reloads the overlay while the backend keeps running.** The log shows reloads at 16:47:26, 17:23:17 and 18:59:16, the exact times of the merges. After each reload, the open card is not drawn and not in the stack, yet the backend counts it as seen and lets it expire.

**Explains:**
- #14: a card in the stack not coming back;
- #4 and #16b: the text box state saying "open" when no box is shown;
- cards vanishing after a merge or Restart Swift;
- a due timer card dropped while a run is in front, but removed from `schedule.json`;
- two cards from one run, where the backend and the overlay disagree on which is shown.

**Findings:** O-01 to O-03, O-05, O-07, O-08, T-12.

### P4. Swift assumes what it depends on is there

No lane declares what it needs (network, the Claude CLI, Google, the microphone, the voice), and nothing watches whether a dependency is alive:

- **Offline:** the check exists once, at the agent hand-off. It comes after the light lane (which calls the CLI and waits up to 20 s) and after the workflow offer.
- **Run slots:** a slot is taken before Swift knows the lane, so "volume up" waits behind three agent runs.
- **Hung runs:** a run has no watchdog. A silent CLI keeps "working" (4.7 min at 18:21–18:26), and losing the internet mid-run shows "Connection hiccup, retrying…" for 45 s.
- **Voice:** if SAPI fails, Swift is "speaking" forever and the open microphone goes deaf.
- **Sign-ins:** a Claude sign-in refused soon after start-up gets no sign-in card.
- **Echo:** there is no echo cancellation and no ducking. While Swift speaks, the microphone hears Swift's voice and the owner's together, so "No" is lost.

**Explains:**
- the Wi-Fi-off requests that went online, including "turn the Wi-Fi back on";
- #7 and #8 ("No" not heard);
- the expired sign-ins taking a refused request before Swift offered to sign in again.

**Findings:** R-01 to R-06, V-01, V-02, X-10.

### P5. Contracts are kept by convention, and the checks can't see the seams

- **Redaction is a deny-list:** a new interaction field reaches `swift.log` by default. That is how three content fields got past `test_redaction` until `cd7eec8`, and two more (`transcript_raw`, a model-written escalation reason) still can.
- **Truncation is decided by heuristics in each layer:** "more than 8 newlines", "6 bullets of 120 characters". That is why the email draft can't be scrolled (#15), and why research was cut.
- **No contract test** ties `protocol.py` to `protocol.ts`.
- **The fakes hide the seams:**
  - no test drives the backend and the overlay together;
  - the fake overlay never answers like the real one;
  - timers are shortened instead of raced;
  - every utterance "ends now" and transcribes instantly.
- **The owner-check report itself can't print FAIL.** A failed check shows as "NOT SEEN", and every on-screen check prints PASS unconditionally (Q-01).

**Explains:**
- why 1,344 + 79 + 30 green tests coexist with a day of failures;
- the privacy leak;
- clipped text;
- reports that looked better than the session was.

**Findings:** X-03, O-04, O-06, O-11, Q-01 to Q-03.

### Speech recognition: adapting to the owner (the owner's addition)

The owner is right that word-for-word fixes are the wrong tool:

- 7 of the 9 fixes the improvement pass proposed were common English words, including "text → Test" and "four → noon". The owner says "four" 20 times in the log.
- The pass never tests a fix on sentences that are right today.
- The 2026-11-04 errors ("tea" → "T here", "Test Me" → "Plectomy") are confident mishearings of ambiguous sounds, not low-confidence ones. A low-confidence trigger would see about 25% of errors.

The fix is context: the owner's contacts where a name is expected, the expected answers while a question is open, and the model's close alternatives passed as text to the model that reads the request (§7).

### What to do first

Structural fixes, each removing a class (§8):

1. One screen state owned by the backend: a snapshot on every connect, and absolute deadlines.
2. One intake pipeline for every input.
3. A `Window` object that owns each question's deadline and defers to speech in progress.
4. Lane capabilities, with a run watchdog.
5. Contracts as tests: allow-list logging, protocol fixtures, a no-truncation scan, and a report that can say FAIL.

Speech: make word fixes safe and gate them per sentence (cheap), then contact-aware name slots.

---

## 2. Seam map

### 2.1 The request lifecycle, across the processes

```
 OVERLAY (Tauri)                         IPC (WS, loopback, token)          BACKEND (one asyncio loop)
 ───────────────                         ─────────────────────────          ─────────────────────────
 Rust lib.rs: hotkeys, tray, ──┐
   pane windows (panes.rs),    │ events
   placement.rs, win.rs, hit   │
                               ▼
 TS main.ts ── presenter.ts ── panes.ts   ── text / ask.reply / ──────►  OverlayServer (server.py)
   (pendingConfirm, asked,   ask.ts          confirm.reply / card.seen     │ decode (protocol.py)
    card, typing, stack)     stack.ts        stack.action / ready (once!)  ▼
   ▲                                                                       Session.handle ──────────────┐
   │ ◄── runs / state / step / result / confirm.request / confirm.hold ─── Session._send                │
   │     ask / followup / speech / stack / presence / artifact / error                                  │
   │                                                                                                    │
   │                                    MIC (WASAPI shared, raw: no AEC)                                │
   │                                      │                                                             │
   │                                      ▼                                                             │
   │                     recorder ─► WakeListener (noise gate, endpoint) ─► hear_wake ─► STT (parakeet, │
   │                                      ▲ wants_short / wants_peek         local) ─► word fixes ──┐   │
   │                                      │ (False while Swift speaks)                          │   │
   │                     SAPI Speaker ────┘ speaking flag, TAIL_S 0.6 s                         ▼   ▼
   │                         ▲                                         ┌─ _hear_transcribed ─┬─ _hear_busy (run working)
   │                         │                                         │   gates G (order    ├─ question branch (window open)
   │                         │                                         │   differs per path) ├─ _hear_reply (reply window)
   │                         │                                         │                     └─ _wake_launch
   │                         │   hotkey ─ _start_voice ─┬─ _answer_by_voice (card open)
   │                         │                          ├─ _midrun_by_voice (run working) ─ _midrun_text
   │                         │                          └─ _launch ─ _interaction
   │                         │   typed / click ─ _start_typed ─┬─ _answer_text (card) ─┬─ _midrun_text (run)
   │                         │                                 └─ _launch ─ _interaction
   │                         │
   │                         │   _interaction: slots.acquire (MAX_RUNS 3, before routing!) ─ capture ─
   │                         │     offers ─ lane question (Q) ─ carry-over (C) ─ router ─ ~20 rewrites ─
   │                         │     quick lane (CLI, 20 s) ─ workflow offer ─ offline check (O) ─ dispatch
   │                         │                                                                  │
   │                         └──── _speak_reply ◄── result ◄── fast / system / local lanes ◄────┤
   │                                                                                            ▼
   │                               ClaudeCodeExecutor (SDK) ─ claude.exe (spare, quick) ─ can_use_tool=_ask
   │                                  no stall timeout ─ cards via Session._ask_card ─ Attention countdown
   │                                  mcp__swift__* ─ ToolHost ─ ActionGateway ─ Google (threads, 60 s × 3)
   └──────────────────────────────────────────────────────────────────────────────────────────────────┘
 Persisted: schedule.json, parked.json, journal.jsonl, interactions.jsonl, overlay.json.
 In memory only: runs, cards (_cards, _aside), questions, windows, the overlay's whole state.
```

**Contracts per seam**

| Seam | Contract | Late | Duplicated | Lost | Out of order |
|---|---|---|---|---|---|
| Mic → wake → STT | One utterance at a time (`_hearing`); `started_at` per clip | an answer transcribed after its window closes is lost (T-02) | n/a | an utterance during a transcription is dropped (D-09); a "no" under 0.4 s while Swift speaks never arrives (V-02) | n/a |
| STT → session | text, word probabilities, peak; word fixes applied globally | n/a | a repeated mishearing is skipped as "asked again", so it never gets a label (W-04) | empty text taken as an answer (D-06) | n/a |
| Session → overlay (`_send`) | fire-and-forget; dropped silently with no client (`server.py:62-66`) | the overlay's countdowns run from arrival (T-08) | `stack` is deduplicated; cards aren't | everything on screen at a reload (O-01, O-02) | two `confirm.request` from one run: the overlay shows the last, the backend the first (O-07) |
| Overlay → session | `ready` once per page; `card.seen` after drawing; `confirm.reply`, `ask.reply` by id | `ask.reply` after a timeout is "ignored", with no feedback (T-03) | the second `confirm.reply` is ignored (ok) | 25 of 27 sends ignore failure: Approve while reconnecting does nothing (O-10) | n/a |
| Backend `error` → overlay | answers with a run id | n/a | n/a | n/a | `bad_message` with no run id wipes the open card (O-05) |
| Session → executor | `run()` until it returns; cancellation by task cancel | no stall timeout (R-06) | the same words are one run (A-11) | n/a | parallel tool calls ask cards concurrently (O-07) |
| Gateway → Google | thread per call, 60 s × 3 retries; idempotent ids (A-05, A-06) | no per-call deadline (X-10) | n/a | a stop while sending journals FAILED though it may have gone (X-08) | n/a |
| Speaker → session | `speaking` flag; `speech_done` is the only restart point for windows | windows not restarted (T-03, T-04, T-05) | n/a | SAPI dead: the flag is never cleared (V-01) | n/a |

### 2.2 State machines and timers

| State or timer | Owner | Started by | Restarted by | Cancelled by | When two fire close together |
|---|---|---|---|---|---|
| Question timer `_ask_timer` (25 s; 25 + 30 s while speaking) | **backend + overlay** (`Ask.until`) | `_ask_lane` 2909, `_show_question` 3094, `_listen_for` 3113 | lane reask 2965 (from the reask's **start**) | `_question_done` | **one slot for all questions:** a question queued behind cancels the on-screen one's timer, and the run hangs (T-01); the fire ignores speech in progress (T-02) |
| Answer window `_answer_window` | backend | `_listen_for` | run reask only (3214); never by the lane reask | `_question_done` | stale after a lane reask: `speech_done` doesn't reopen it (T-03) |
| Lane yes/no expiry `asked_at` + 45 s | backend (a third clock) | `_ask_lane` | `system_yes_unnamed` 2937 (only `asked_at`) | lazy | the 25 s timer always fires first; ADR-016 §16.2 says 45 s (T-11) |
| Reply window `_followup` (8 s; 25 s after an answer that asks) | **backend + overlay** (`followupUntil`) | `_open_followup` when the answer **starts** being said | `speech_done`, only if not already past | `_close_followup` on every new interaction | gone after a spoken answer over 8 s (T-05) |
| Park timer `_question` (an answer that asks) | backend | `_expect_answer`, when the answer is sent | never | `_drop_question` (any speech) | parks into the stack while the card still listens (T-04) |
| Confirm countdown (`Attention`, 45 s Swift, 120 s Claude Code) | **backend + overlay** (`confirmDeadline`) | `wait_answer` | `set_seen`, `set_held`, `RETURN_S` | answer, expiry → aside | runs as "seen" across an overlay reload (O-01); queued vs shown mismatch (O-07); pauses on different signals per side (T-08) |
| Card queue `_cards`, `_aside` | backend (the overlay: only `pendingConfirm`) | `_ask_card` | n/a | `_card_done`, `_skip_card` | `Run.card` keeps only the latest card (O-07); lost on a backend kill (T-12) |
| Held cards (away) | **both** | `hold_cards(True)` | n/a | `hold_cards(False)` | the overlay ignores `held:false` if it cleared `pendingConfirm` meanwhile (#14 member, O-07); lock and unlock run as concurrent tasks (T-10) |
| Stack | backend → overlay | `_send_stack` on change | `ready` resets `_stack_sent` | n/a | the overlay keeps the old backend's ids after a restart; opening one does nothing (O-02) |
| Presence and listening paused | backend | `Lifecycle.handle` (one task per change) | n/a | unlock | the held utterance still acts after the lock (T-07, Critical) |
| Speaking | backend `Speaker` | `speak()` sets True before SAPI starts | n/a | `_ended`, `stop()` | never cleared if SAPI failed to start (V-01) |
| Held utterance (end of speech, ≤ 3 s, +6 s) | backend | `_hold` | `_flush_held` every 0.3 s | the next utterance | not cancelled on lock (T-07); not known to the question timer (T-02) |
| Transcription `_hearing` | backend | `hear_wake` | n/a | `finally` | a second utterance is dropped, not queued (D-09) |
| Due items (`schedule.json`, `DUE_WAIT_S` 120 s) | backend + file; overlay `renderDue` | scheduler | n/a | `scheduler.shown` after the **send** | the presenter drops it while a run is in front, but it is marked shown (O-08) |
| Run lifecycle (`MAX_RUNS` 3) | backend → overlay rows | `_launch` (slot taken **before** routing) | n/a | `_ended` | local requests queue behind three runs (R-03); a hung CLI holds a slot forever (R-06) |
| Typing box `typing` | **TS + Rust** (`PaneSync.shown`, real window) | `toggleTyping`, Change | n/a | `toggleTyping` | a failed open leaves `typing` set: Change does nothing, the hotkey *closes* it (O-03) |
| Live view pane size | TS `fit` + Rust `fit_pane` | `ResizeObserver` | every fit | close | monitor scale vs window scale: it can ratchet narrower (O-09) |

### 2.3 Entry points

Each entry point should pass the same steps:

- **G:** the confidence gates.
- **Q:** matching against a waiting question.
- **A:** the approval rules (Swift's name hands-free; typing never approves; the reversible-change exception).
- **M:** the mid-run grammar (stop, show me).
- **C:** carry-over ("turn it back on").
- **D:** the duplicate check.
- **R:** routing.
- **O:** the offline check.

Marks: ✔ runs, ✘ skipped, **own** means the entry point has its own copy of the rule.

| Entry point | Path | G | Q | A | M | C | D | R | O |
|---|---|---|---|---|---|---|---|---|---|
| Hotkey, at rest | `_start_voice` → `_interaction` | `assess` only | ✔ lane | ✔ | ✘ | ✔ | ✘ | ✔ | ✔ (after quick, R-01) |
| Hotkey, run working | `_midrun_by_voice` → `_midrun_text` | `assess` | run ✔, **lane ✘** | n/a | ✔ | **✘** (D-05) | ✔ | `_new_request` | ✔ |
| Hotkey, card open | `_answer_by_voice` → `_answer_text` | `assess` + `_approval_doubt` | ✘ (card first) | **own** | ✔ | ✘ | ✘ | own call | ✘ |
| Wake, at rest | `hear_wake` → `_hear_transcribed` → `_wake_launch` | `wake_min_p` → `assess` | ✔ | ✔ | ✘ | ✔ | **✘** | ✔ | ✔ |
| Wake, run working | `_hear_busy` | `wake_min_p` | via `_midrun_text`; **lane ✘** | **own** (name) | ✔ | **✘** | ✔ | `_new_request` | ✔ |
| Open-mic answer | question branch 1909 | `wake_min_p` **first** (unsure answers dropped silently, T-06) | ✔ (`cd3f97b`) | ✔ | a lane question takes "stop" as an answer (D-08) | ✘ | ✘ | ✔ | ✔ |
| Reply window | `_hear_reply` → `_start_followup` | `wake_min_p`, `_reply_doubt`, SNR | ✔ | ✔ | ✘ | ✔ | ✘ | ✔ | ✔ |
| Typed | `_start_typed` | ✘ | run ✔; **lane ✘ while another run works** | **own** | ✔ busy | **✘ during a run** | ✔ busy | ✔ | ✔ |
| Click Approve/Reject | `_confirm_reply` | ✘ | ✘ | a click | ✘ | ✘ | ✘ | ✘ | ✘ |
| Click Change | `_start_typed` → `_answer_text` | ✘ | ✘ | **own** (typed) | ✔ | ✘ | ✘ | own call | ✘ |
| Click on a question card | run: `_take_answer`; **lane: `_start_typed`** | ✘ | ✔, but an open confirm card takes the click first (D-07) | ✔ | ✔ | ✘ | ✘ | ✔ | ✔ |
| Offers (workflow, fix, unfinished) | `_answer_offer`, `_answer_fix`, before Q | as the entry point | **before Q** | a bare yes accepts (typed too, for the fix offer) | — | — | ✘ | ✔ | ✔ |
| Answer by voice, mic closed | `_capture_answer` | `assess` | ✔ | — | ✘ | ✘ | ✘ | ✘ | ✘ |
| Over Swift's voice | `_said_over_speech` | own filter | **✘ for questions** (V-02) | never a yes | cards ✔ | ✘ | ✘ | — | — |
| Swift's own runs (improve, sign-in) | `start_own` | — | — | — | — | — | — | **✘** | **✘** |

**Gaps:**
- **Q** has three implementations, and four entry functions decide whether to call one.
- **C** exists only in `_interaction`, and only when no lane question waits.
- **A** has five copies. They agree today, but nothing enforces it.
- **G** runs in a different order per path.
- **D** exists only beside a run.
- **O** comes after the quick lane.

### 2.4 Protocol drift (`protocol.py` ↔ `protocol.ts`)

All 23 outbound types have a `case` in `main.ts:onMessage`, and all 21 inbound types are in the TS `Outbound` union. No type is sent and never handled, or handled and never sent, in production. The drift is in behaviour and in what isn't checked:

| Item | Python | TS | Issue |
|---|---|---|---|
| `ready` | `startup_ms` required | sent **once per page load** | no resync after any reconnect (O-02) |
| `error` from the server | `bad_message`: `code, message, hint`, no run id; not logged | rendered as the answer | wipes the open card (O-05) |
| TS `decode` | — | checks only `v`, `type`, `data` | a bad field throws inside a handler with no try/catch, silently |
| `text`, `ask.reply` | clipped to 2,000 silently | the box has `maxlength`; the `window.prompt` fallback doesn't | Low |
| A frame over 64 KiB | `websockets max_size` closes the socket (1009) | not guarded | none today; a future large field would drop the connection |
| A contract test | none | only `stack.test.ts` imports a protocol type | O-06 |

---

## 3. Findings register

IDs by area:

| Prefix | Area |
|---|---|
| D | dialogue and entry points |
| T | timers and backend state |
| O | overlay and IPC |
| V | voice and half-duplex |
| W | words, speech recognition |
| R | routing and fallback |
| X | executors, gateway, privacy |
| Q | verification |

"Test" names the reproduction on this branch (`xfail(strict)` until fixed; §9). The full working notes, with every line reference, are in the shared notes folder for this session group, listed in §10.

### Summary

| ID | Sev. | Label | Area | Dimension | Finding |
|---|---|---|---|---|---|
| **T-07** | **Critical** | confirmed (test); **fixed 2026-11-05** | backend | security | An utterance held mid-thought still acts after the screen locks |
| D-01 | High | design concern; **partly fixed 2026-11-05 (S2)** | backend | reliability, testability | Each entry point has its own copy of the steps (the root of D-02 to D-08) |
| D-02 | High | confirmed (test, log 17:37:09); **partly fixed 2026-11-05 (S2)** | backend | effectiveness | A wordy yes, "hold on" or an aside drops the question and goes to the agent |
| D-03 | High | confirmed (test); **fixed 2026-11-05 (S2)** | backend | effectiveness, fallback | "Turn the Wi-Fi back on" is refused offline as "I'm offline" |
| D-04 | High | confirmed (test); **fixed 2026-11-05 (S2)** | backend | reliability | Any local answer in between forgets the switch ("turn it back on" lost) |
| D-06 | High | confirmed (test, log 17:43:39); **fixed 2026-11-05 (S2)** | backend | reliability | An utterance with no words counts as an unclear answer and spends the re-ask |
| T-01 | High | confirmed (tests); **fixed 2026-11-05 (S3)** | backend | reliability | One timer slot for every question: a question behind cancels the on-screen one's timer, and the run hangs |
| T-02 | High | confirmed (tests); **fixed 2026-11-05 (S3)** | backend | reliability | A question times out while the answer is being said or transcribed |
| T-03 | High | confirmed (tests, log 17:43:39–17:44:04); **fixed 2026-11-05 (S3)** | backend | reliability | After a re-ask, the old window stands, and the timer runs from the re-ask's start |
| T-04 | High | confirmed (test) | backend | reliability | An answer that asks is parked while its reply window and countdown still run |
| O-01 | High | confirmed (harness, tests, log); **fixed 2026-11-05 (S1)** | IPC | reliability | An overlay reload (every merge) loses the open card, question and answer; the card expires unseen |
| O-02 | High | confirmed (code, harness log); **fixed 2026-11-05 (S1)** | IPC | reliability, fallback | `ready` once per page load: after Restart Swift there is no stack, due cards wait, and stale stack ids open nothing |
| O-03 | High | confirmed (test) | overlay, Rust | reliability, fallback | A failed text-box open isn't retried, and `typing` stays set (#4, #16b) |
| O-04 | High | confirmed (harness) | overlay | effectiveness | The Send card shows 3 lines of the email with no scroll (#15) |
| O-07 | High | confirmed (test); **fixed 2026-11-05 (S1)** | backend, overlay | reliability | One run asking two cards: the backend and the overlay disagree on which is shown (#14 class) |
| O-08 | High | confirmed (code, both sides); **fixed 2026-11-05 (S1)** | backend, overlay | reliability | A due card the overlay drops while a run is in front is still marked shown |
| V-01 | High | confirmed (test); **fixed 2026-11-05 (S4)** | speech | fallback | With SAPI unavailable, Swift is "speaking" forever and the open mic goes deaf |
| R-03 | High | confirmed (test); **fixed 2026-11-05 (S4)** | backend | effectiveness, fallback | A local request waits behind three agent runs |
| X-01 | High | confirmed (test) | backend | effectiveness | A single contact match isn't checked against the name said (#15 still possible) |
| X-03 | High | confirmed (test, log); **fixed 2026-11-06** | backend | security | `swift.log` redaction is a deny-list over the whole interaction record |
| X-08 | High | confirmed (test) | gateway | reliability | A stop during "Sending…" journals FAILED, though the email or event may go out |
| X-17 | High | design concern; **fixed 2026-11-07** | executor | security | Edit and Write approval cards show 60–70 characters of what will be written (A-12's class) |
| D-05 | Medium | confirmed (test); **fixed 2026-11-05 (S2)** | backend | effectiveness | "Turn it back on" during a run (typed or named) gets a mid-run hint |
| D-07 | Medium | suspected; **fixed 2026-11-05 (S2)** | backend | reliability | A click on a lane question's No can reject another request's confirm card |
| D-08 | Medium | confirmed (code); **fixed 2026-11-05 (S2)** | backend | effectiveness | A lane question takes "stop" as an answer during a run |
| D-09 | Medium | confirmed (code, log); **fixed 2026-11-05 (S2)** | speech | effectiveness | An utterance that arrives during a transcription is dropped, not queued |
| T-05 | Medium | confirmed (test) | backend | effectiveness | No reply window after a spoken answer longer than 8 s |
| T-06 | Medium | confirmed (test); **fixed 2026-11-05 (S2)** | backend | effectiveness, diagnosability | An unsure answer to an open question is dropped without a word |
| T-08 | Medium | design concern | backend, overlay | reliability | Every countdown runs separately in Python and TS |
| T-09 | Medium | confirmed (code) | backend | reliability | About 10 fire-and-forget tasks; timers not cancelled on disconnect |
| T-12 | Medium | confirmed (code) | backend | fallback, diagnosability | A backend kill or restart loses Later cards, questions and unfinished runs, with nothing logged |
| T-13 | Medium | confirmed (layer C); **fixed 2026-11-05 (S3)** | backend, IPC | reliability | A question replayed when its request comes back to the front restarts the overlay's countdown, not the backend's |
| O-05 | Medium | confirmed (test); **fixed 2026-11-05 (S1)** | IPC | reliability, diagnosability | A protocol error with no run id wipes the confirm card |
| O-06 | Medium | confirmed (code); **fixed 2026-11-05 (layer A)** | IPC | testability | No contract test between `protocol.py` and `protocol.ts` |
| O-09 | Medium | suspected | Rust, overlay | reliability | The live view can ratchet narrower with mixed DPI (#10) |
| O-10 | Medium | confirmed (code) | overlay, Rust | diagnosability | Overlay and Rust failures never reach `swift.log`; failed sends are ignored |
| V-02 | Medium | confirmed (tests) | speech | effectiveness | No echo cancellation; the "no over Swift's voice" rule has four gaps (#7, #8) |
| V-03 | Medium | design concern | speech | reliability, diagnosability | The confidence model is three measures tuned case by case; the logged number isn't the deciding one |
| W-01 | Medium | confirmed (test, owner data) | speech | effectiveness | Word-fix proposals swap common words without context ("text → Test") |
| W-03 | Medium | confirmed (test) | speech | testability | The speech regression gate is aggregate-only |
| W-04 | Medium | confirmed (owner data) | speech | testability | The owner test set misses systematic mishearings (2 labelled clips) |
| W-06 | Medium | confirmed (experiment) | speech | effectiveness | Contacts aren't used when recognizing a name ("Test Me" → "Plectomy") |
| R-01 | Medium | confirmed (test); **fixed 2026-11-05 (S4)** | backend | fallback, efficiency | Offline, the light lane (20 s) and the workflow offer come before the offline answer |
| R-02 | Medium | suspected; **fixed 2026-11-05 (S4)** | dependency | fallback | `online()` means "has a connection", not "reaches the internet" |
| R-04 | Medium | confirmed (log, test); **fixed 2026-11-05 (S4)** | executor | fallback, diagnosability | Internet lost mid-run: "Connection hiccup" until the CLI or the owner gives up |
| R-05 | Medium | confirmed (test, log 15:15); **fixed 2026-11-05 (S4)** | backend | fallback | A Claude refusal within 10 min of any sign-in check gets no sign-in card |
| R-06 | Medium | confirmed (test, log 18:21–18:26); **fixed 2026-11-05 (S4)** | executor | reliability | No watchdog: a silent CLI "works" forever and holds a slot |
| R-07 | Medium | confirmed (log) | routing | effectiveness, efficiency | The light lane never answered a real request, yet a CLI is kept warm for it |
| R-08 | Medium | confirmed (code, data) | measurement | diagnosability | The agent-time metric includes the owner's speaking and card waits |
| R-09 | Medium | design concern | backend | testability | About 20 order-dependent rewrites in one 230-line dispatch function |
| X-02 | Medium | design concern | gateway | security | Every `find_contact` candidate counts as resolved |
| X-04 | Medium | confirmed (test); **fixed 2026-11-06** | gateway | security | B-07 still open: a denied address goes into `swift.log` |
| X-19 | Medium | confirmed (X-04 review); **fixed 2026-11-06** | gateway | security | A recipient's domain reaches `swift.log` |
| X-06 | Medium | confirmed (code) | executor | security | B-10 is wider: "Claude is busy, retrying…" on the working card |
| X-07 | Medium | design concern | executor | security | `%LOCALAPPDATA%\Swift` (recordings, transcripts) isn't on the never-read list |
| X-09 | Medium | confirmed (code) | gateway | reliability | B-08 still open: after an "unknown" outcome the same action can be done again |
| X-10 | Medium | suspected; **fixed 2026-11-05 (S4)** | gateway | reliability | No deadline on a Swift tool call (Google 60 s × 3 retries) |
| X-11 | Medium | suspected | dependency | reliability | Google API clients shared across threads |
| Q-01 | Medium | confirmed (code, report); **fixed 2026-11-05** | testability | diagnosability | The owner-check report can't print FAIL; on-screen checks always print PASS |
| Q-02 | Medium | confirmed (survey) | testability | testability | The fakes hide every seam; nothing drives the backend and the overlay together |
| D-10 | Low | confirmed (log); **fixed 2026-11-05 (S2)** | backend | diagnosability | Unclear-speech rows show no request text (17:33:22, 17:38:15) |
| D-11 | Low | confirmed (log); **fixed 2026-11-05 (S2)** | backend | diagnosability | A click on a question card is logged as "typed request" |
| T-10 | Low | design concern | backend | reliability | Lock and unlock are handled as concurrent tasks |
| T-11 | Low | design concern; **fixed 2026-11-05 (S3)** | backend | reliability | The lane yes/no window has two clocks, and ADR-016 disagrees with the code |
| O-11 | Low | confirmed (code) | backend | effectiveness | Content capped with no marker ("6 timers: a; b; c; d.", lists, calendar text) |
| O-12 | Low | design concern | overlay | effectiveness | Answers fade after at most 20 s, whatever their length |
| O-13 | Low | confirmed (harness) | IPC | reliability | Two overlay clients replace each other about twice a second, forever |
| O-14 | Low | confirmed (harness) | overlay | fallback | The fallback live view loses its header in a short window |
| O-15 | Low | confirmed (layer C); **fixed 2026-11-05 (S1)** | backend, IPC | reliability | A question closed while its request isn't in front never reaches the overlay |
| V-04 | Low | confirmed (owner data) | speech | effectiveness | A quiet "Yes." below the fixed −50 dBFS gate never reaches the model |
| W-02 | Low | confirmed (owner data) | speech | effectiveness | Two enabled fixes rewrite rare real words ("tori", "distal") |
| W-05 | Low | confirmed (measured) | speech | effectiveness | A low-confidence trigger sees about 25% of the real errors |
| W-07 | Low | confirmed (experiment) | speech | effectiveness | Boosting expected answers by a score bonus inserts them ("Yes." six times) |
| R-10 | Low | suspected | workflows | efficiency | Calendar workflows on Haiku take 3–6 turns; time to first card is about 15 s |
| R-11 | Low | suspected; **fixed 2026-11-05 (S4)** | backend | fallback | An expired login reported as "couldn't confirm model" isn't treated as a sign-in |
| X-05 | Low | confirmed (log); **fixed 2026-11-06, except the lines listed in its entry** | backend | security, diagnosability | Exception and connector texts go into `swift.log` and the journal (none with content yet) |
| X-18 | Medium | confirmed (X-05 review) | gateway | security | A selected file's name goes into the journal as a receipt |
| X-12 | Low | confirmed (code); **fixed 2026-11-05 (S4)** | executor | efficiency | Waiting for the spare CLI is outside every timeout |
| X-13 | Low | confirmed (code) | executor | diagnosability | A cancelled or killed run reports no cost |
| X-14 | Low | confirmed (code) | backend | effectiveness, fallback | Sign-in hints disagree with the card; no card while away or for "absent" |
| Q-03 | Low | confirmed (data) | testability | testability | Routing parity (97.5%) measures a synthetic set, not the owner's mix |

### 3.1 Dialogue and entry points

#### T-07 · Critical · confirmed (test) · An utterance held mid-thought still acts after the screen locks
- **Area:** backend (`session.py` wake, lock). **Dimension:** security.
- **Evidence:**
  - `_hold` (`session.py:1851-1863`) parks an utterance that ends mid-thought ("…and", "…for twenty") on `call_later(…, _flush_held)`.
  - `Lifecycle.handle` and `hold_cards` never cancel it, and `_flush_held` → `_hear_transcribed` never checks `listening_paused`.
  - With a card open, "Swift, approve and…" followed by Win+L reaches `_hear_busy` → `_answer_text`, which has no held or away check.
  - Test: `test_seams_audit_state.py::test_s08_…`.
- **Root cause:** the rule "nothing heard acts while locked" is checked where input enters (`hear_wake`, and after its transcription, A-09), not where it acts.
- **Class:** checked at entry, acted on later. A-09 was the first member.
- **Other members:**
  - `_capture_answer` finishing after a lock;
  - any future deferred path.
  - The hotkey paths are the owner's own act and are fine.
- **Fix:**
  - Return early in `_hear_transcribed` and `_flush_held` when `listening_paused`.
  - `hold_cards(True)` cancels `_held_utterance` and `_answer_task`.
  - `_hear_busy` refuses `approve` while `attention.held`.
  - Better: the intake pipeline (§8 S2) checks presence as its first step, for every source.
- **Would have caught it:** a model-based test with lock as an event (layer C).
- **Owner check:** with a calendar card open, say "Swift, approve and…", stop, press Win+L within a second, and unlock after 10 s. The card is still waiting.

#### D-01 · High · design concern · Each entry point has its own copy of the steps
- **Area:** backend. **Dimension:** reliability, testability.
- **Evidence:** the table in §2.3.
  - Question matching: `_lane_answer` 2913, `_take_answer` 3185, the question branch 1909.
  - Approval: `_answer_text` 4227, `_hear_busy` 2140, `_start_typed` 1432, `_lane_answer` 2934, `OVER_SPEECH`.
  - Carry-over: `_interaction` 2482 only.
  - The X-2 table in the notes (15 approval paths) found no bypass today.
- **Root cause:** features were added at the entry point where they were first needed.
- **Class:** this is the class itself. D-02 to D-08, T-06 and `cd3f97b`'s case are its members.
- **Fix:** one intake pipeline (§8 S2).
- **Would have caught it:** a parametrized test that sends the same utterance through every source and asserts the same decision, or a declared difference (for example, typing never approves).
- **Owner check:** none by itself; check 130 and the checks named under D-02 to D-08 cover the members.

#### D-02 · High · confirmed (test, log) · A wordy yes, "hold on" or an aside drops the question and goes to the agent
- **Area:** backend (`dialogue.resolve`). **Dimension:** effectiveness.
- **Evidence:**
  - `dialogue.py:280-313`: a yes followed by more than four words is `unclear`, and then `_new_request` (3+ words, no pronoun) makes it `elsewhere`.
  - So "Yeah, turn it off for now, thanks", "I'm not sure" and "Hold on a second" drop the question.
  - At 17:37:09, "What commands will be available if the Wi-Fi is turned off?" dropped "Turn off Wi-Fi?" (`turn='elsewhere'`). It still does after `ab09f51`, which only answers it locally.
  - Tests: `test_seams_audit_speech.py::test_s12_…`, `::test_s12b_…`.
- **Root cause:** "is this a new request?" is a length-and-pronoun heuristic, and it is asked before "is this a wordy answer?".
- **Class:** answer vs new-request arbitration. D-05 is a member.
- **Fix:**
  - A yes/no opener plus words that restate the action is still an answer.
  - A question, "wait" or "I'm not sure" keeps the question open: answer the aside, then show the card again.
  - Only "never mind…" or a clear request that doesn't start with yes or no drops it.
- **Owner check:** "turn off the Wi-Fi", then "Yeah, turn it off for now, thanks". Wi-Fi goes off and nothing goes to Claude Code. Then, with the card open, "What can I do when the Wi-Fi is off?": the list shows, and the card stays.

#### D-03 · High · confirmed (test) · "Turn the Wi-Fi back on" is refused offline
- **Area:** routing, system grammar. **Dimension:** effectiveness, fallback.
- **Evidence:**
  - `route("turn the wifi back on")` returns `agent` with no parse, and so do "switch wifi back on", "turn bluetooth back on", "airplane mode back off" and "connect to wifi".
  - Offline, `session.py:2559` turns the agent route into "I'm offline…". The offline list itself advertises "turn it back on".
  - `elide` covers "turn **it** back on" only, with a fresh carry.
  - Test: `test_s01_…`.
- **Root cause:** the grammar has no "back on / again" form with a named device, and the offline check never asks whether the system lane nearly claims the words.
- **Class:** recovering from a disruptive reversible change by naming the device. D-04 and D-05 are members.
- **Fix:**
  - Add `back`/`again`/`reconnect` forms to `system/intents.py`.
  - Offline, try a relaxed `system.claims` before the offline answer.
  - When a radio is off, the offline answer offers "Turn Wi-Fi on?" as a Yes card.
  - Add parity cases.
- **Owner check:** Wi-Fi off (yes), wait 70 s, "Hey Swift, turn the Wi-Fi back on". It comes on at once.

#### D-04 · High · confirmed (test) · A local answer in between forgets the switch
- **Area:** dialogue carry-over. **Dimension:** reliability.
- **Evidence:**
  - `Dialogue._carry` is one slot (`dialogue.py:428`), and `_local_answer` (4404) overwrites it with every time or date answer.
  - "Wi-Fi off" → "yes" → "what time is it" → "turn it back on" goes to the agent.
  - Test: `test_s02_…`.
- **Root cause and class:** last-context-wins state shared by unrelated features. `exchange` and `moment` are overwritten the same way.
- **Fix:**
  - Separate slots (`last_change`, `last_moment`, `last_exchange`), each with its own expiry.
  - A disruptive switch is kept until it is undone.
- **Owner check:** Wi-Fi off, "what time is it", "turn it back on". Wi-Fi comes on.

#### D-05 · Medium · confirmed (test) · "Turn it back on" during a run gets a hint
- **Evidence:**
  - `_start_typed` 1458 and `_hear_busy` 2165 go to `_midrun_text`.
  - `_new_request` refuses a short pronoun fragment (3562), so the owner gets "Say 'show me', 'stop'…".
  - Test: `test_s03_…`.
- **Class:** D-01 (carry-over exists only in `_interaction`).
- **Fix:** S2. A carry hit counts as a new request beside the run.
- **Owner check:** during a research run, turn off Wi-Fi by voice, then type "turn it back on". Wi-Fi comes on.

#### D-06 · High · confirmed (test, log) · An utterance with no words is taken as an unclear answer
- **Evidence:**
  - At 17:43:39.845, `question answered | turn='reask' source='answer'`, and the interaction row has `transcript: ""`.
  - The airplane-mode question then timed out at 17:44:04.
  - The question branch (`session.py:1909`) has no empty-text check (the rest path, 1938, does).
  - Test: `test_s04_…`.
- **Class:** missing empty-transcript guards in paths added later. `_take_answer("")` and `_capture_answer` → `_hear_answer` are members.
- **Fix:** drop empty text before 1909, and make `Dialogue.answer("")` return None.
- **Owner check:** "turn on airplane mode", then cough once while the card is open. No "Sorry, was that a yes or a no?".

#### D-07 · Medium · suspected · A click on a lane question's No can reject another request's card
- **Evidence:**
  - `ask.reply` for a lane question goes to `_start_typed(source="click")` (1543), which answers an open confirm card first (`_open_confirm`, 1442).
  - The `ask_id` already matched, so the click was meant for the question.
- **Fix:** `ask.reply` calls `_lane_answer` directly.
- **Owner check:** none safe. Use a harness scenario.

#### D-08 · Medium · confirmed (code) · A lane question takes "stop" as an answer during a run
- **Evidence:** `_for_question` (2089) is True for any non-run question, so "stop" re-asks instead of stopping the run.
- **Fix:** apply the mid-run exemption to every question.
- **Owner check:** during research, "Swift, set a timer", then "stop". The research stops.

#### D-09 · Medium · confirmed (code, log 16:53) · An utterance during a transcription is dropped
- **Evidence:** `hear_wake` 1768 (`skipped_hearing`). TV speech being transcribed can swallow "hey Swift".
- **Fix:** keep the latest pending utterance in a one-slot queue.

#### D-10 · Low · confirmed (log) · Unclear-speech rows show no request text
- **Evidence:** the 17:33:22 and 17:38:15 `voice … error` rows are `unclear_speech` refusals of "turn off the Wi-Fi", heard as other words (stored as `transcript_heard`). `_refuse_unclear` raises before `record["transcript"]`.
- **Fix:** keep `transcript` with `refused: unclear`, or have the report read `transcript_heard`.

#### D-11 · Low · confirmed (log 17:34:13) · A click on a question card is logged as "typed request"
- **Fix:** log the source.

### 3.2 Timers and backend state

#### T-01 · High · confirmed (tests) · One timer slot for every question
- **Evidence:**
  - `_question_timer` (`session.py:2985`) cancels `self._ask_timer` whoever owned it.
  - `_ask_lane` (2898-2911) arms it even when the new question only waits behind.
  - Result: the run's "Paris or Rome?" never times out, its `ask_owner` future never resolves, and the run holds a slot until Esc.
  - The Wi-Fi card is never shown, and a later "Swift, yes" is matched against the run's question.
  - Tests: `test_seams_audit_state.py::test_s01_…`, `::test_s01b_…`, `test_seams_audit_speech.py::test_s14_…`.
- **Class:** several questions, one timer. `_answer_window`, `_answer_task` and the park timer are single slots too.
- **Fix:** the timer lives on the `Question`, started when it becomes pending (§8 S3).
- **Owner check:** "draft an email to Sam…"; at "Which Sam?", say "turn off the Wi-Fi". Either the Wi-Fi card shows, or Sam's question is kept in the stack, and nothing still waits after 25 s.

#### T-02 · High · confirmed (tests) · A question times out while the answer is being said
- **Evidence:**
  - `_question_timeout` (2991) ignores `in_speech()`, `_hearing` and `_held_utterance`.
  - `_listening_for()` (3129) compares the time when the transcription *finished*.
  - An answer begun after about 21 s of 25 is lost. This is the owner's "two seconds before my answer".
  - The reply window's `_in_followup(started_at)` already does it right.
  - Tests: `test_s02_…` (state), `test_s06_…` (speech).
- **Class:** one window, several clocks (P2).
- **Fix:**
  - Accept an utterance whose `started_at` is before the deadline.
  - At the deadline, if speech is in progress, re-arm for 0.5 s, capped at +6 s.
- **Owner check:** "set a timer"; when the card shows about 3 s left, say "ten minutes". The timer is set.

#### T-03 · High · confirmed (tests, log) · After a re-ask, the old window stands
- **Evidence:**
  - The lane re-ask (`_lane_turn`, 2949-2965) restarts the timer *before* the re-ask is spoken and never clears `_answer_window`, and `speech_done` (3320) reopens only if it is None.
  - Log:
    - 17:43:15.4: listening for 25 s;
    - 17:43:39.8: the re-ask;
    - 17:43:45.3: the window reopens on the card;
    - 17:44:04.84: unanswered, exactly 25.0 s after the re-ask began and 5.5 s before the card's countdown ended.
  - `system_yes_unnamed` (2937), the old "say 'Swift, yes'" hint still used for typing, refreshes `asked_at` only (16:49:35 → 16:50:00).
  - Tests: `test_s03_…` (state), `test_s05_…` (speech).
- **Other members:**
  - the run re-ask, where the old timer runs while the re-ask is spoken;
  - the unclear-reply branch;
  - `read_confirms: true`, where the pill never gets a countdown.
- **Fix:** one `reprompt(q, text)` that clears the window, speaks, and restarts the window and timer on `speech_done` (§8 S3).
- **Owner check:** "turn off Bluetooth", "purple", wait for the re-ask to end, wait 20 s, "yes". Bluetooth goes off.

#### T-04 · High · confirmed (test) · An answer that asks is parked while its window still runs
- **Evidence:** `_expect_answer` (3953) arms the park timer when the answer is sent, while `speech_done` restarts `_followup` and the overlay's countdown. Test: `test_s05_…` (state).
- **Fix:** derive the park from the reply window's end: one deadline.
- **Owner check:** "add lunch with Test Me to my calendar" and don't answer. The stack item doesn't appear before the card's countdown reaches 0.

#### T-05 · Medium · confirmed (test) · No reply window after a long spoken answer
- **Evidence:**
  - `_open_followup` runs when the voice starts (4504), and `speech_done` reopens only if the window hasn't passed (3326).
  - A 220-character spoken answer takes 12–15 s.
  - Test: `test_s13_…`.
- **Fix:** start the window on `speech_done`, unconditionally.
- **Owner check:** "Hey Swift, what can you do?", then straight after it ends, "and what about timers?" with no wake phrase. It is taken.

#### T-06 · Medium · confirmed (test) · An unsure answer to an open question is dropped silently
- **Evidence:**
  - `wake_min_p` (0.5) runs before the question branch (1897-1907), so the answer is counted `unsure` and dropped.
  - The 17:42 and 17:47 wake reports show `unsure=20` and `unsure=17` against `answer=2`.
  - Test: `test_s06_…` (state).
- **Fix:** while a question listens, an unsure clip gets the re-ask on the question's card.
- **Owner check:** mumble "yeah" to "Turn off Wi-Fi?". Swift asks again.

#### T-08 · Medium · design concern · Every countdown runs twice
- **Evidence:**
  - confirm: `Attention` vs `confirmDeadline`;
  - question: `_ask_timer`/`_answer_window` vs `Ask.until`;
  - reply: `_followup` vs `followupUntil`.
  - They pause on different signals, and are restarted from message arrival.
- **Fix:** the backend sends absolute deadlines (`closes_at_ms`) and the overlay only draws them (§8 S1).

#### T-09 · Medium · confirmed (code) · Fire-and-forget tasks and uncancelled timers
- **Evidence:**
  - `create_task` with no reference kept at `session.py:1124, 1150, 1174, 2983, 3963, 3325, 3327, 3339, 3889`.
  - `_forget_row` and `_held_utterance` handles are never cancelled.
  - Nothing is cancelled on overlay disconnect.
  - The 35-minute idle run showed no growth (§5), so this is a correctness risk, not a leak today.
- **Fix:** route them through `_background`, and add an architecture test forbidding a bare `create_task` in `session.py`.

#### T-10 · Low · design concern · Lock and unlock are handled as concurrent tasks
- **Evidence:** `lifecycle.py:86-90`. Not reproduced.
- **Fix:** an `asyncio.Lock` in `Lifecycle.handle`.

#### T-11 · Low · design concern · The lane yes/no window has two clocks
- **Evidence:** 45 s on `asked_at` (2895) against the 25 s timer that always fires first. The card shows 25, and ADR-016 §16.2 says 45.
- **Fix:** one deadline on the `Question`, and update the ADR.

#### T-12 · Medium · confirmed (code) · A restart loses in-memory cards and questions, with nothing logged
- **Evidence:** `_cards`, `_aside`, pending questions and unfinished runs are memory-only. `close()` parks runs and `_question`, but not lane questions or Later cards.
- **Fix:**
  - Park those threads as "unanswered" in `close()`.
  - Write an "in flight" marker per run, so that start-up logs "N requests were interrupted" and offers them.

### 3.3 Overlay and IPC

#### O-01 · High · confirmed (harness, tests, owner log) · An overlay reload loses what is on screen
- **Evidence:**
  - Harness: a card on screen, then a reload. The frames after reconnect are `hello.ok`, `presence` and `stack` only, so there is no card.
  - The card isn't in the stack either: `_stack_items` lists `_cards[1:]`.
  - Its countdown keeps running as seen, because `attention._seen` is unchanged.
  - Owner log: `overlay disconnected/connected/ready` at 16:47:26, 17:23:17 and 18:59:16, which are the `main` fast-forward times. The Vite dev server reloads on each merge.
  - Code: `session.py:1494-1500`, `server.py:107-112`.
  - Tests: `test_seams_audit_ipc.py` (2), `test_seams_audit_state.py::test_s07_…`.
- **Class:** no resync on (re)connect (P3). Also not resent: the open `ask`, the answer, `followup`, `speech`, `runs` (`_rows_sent` isn't reset) and `confirm.hold`.
- **Fix:** §8 S1. A `resync.snapshot(session)` sent on every authenticated connect; every card unseen until the overlay reports it drawn.
- **Owner check:** with a card up, merge or press Ctrl+R in the overlay's devtools. The same card is back within a second, with its countdown, and nothing expired into the stack.

#### O-02 · High · confirmed (code, harness log) · `ready` once per page load
- **Evidence:**
  - `main.ts:2109-2114` (`readyReported`), and `ipc.ts:72-80` reconnects after any close.
  - `session.py:720` sets `_stack_sent = []`, so an empty stack counts as already sent.
  - `_due_blocked` waits for a `ready` that never comes.
  - After Restart Swift:
    - no stack;
    - a timer that came due waits until a lock and unlock;
    - the old backend's stack ids open nothing (`_open_card` finds no index). This is a #14 cause.
  - The harness log shows dozens of `overlay connected` with no `ready`.
- **Fix:**
  - `OverlayServer(on_connect=…)` tells the session about each connection.
  - `hello.ok` carries a backend instance id. The overlay resets its stack, rows, live views and presenter when the id changes, and sends `ready` on every `hello.ok`.
- **Owner check:** set a 1-minute timer and press Restart Swift just before it rings. The card shows once Swift is back, with no lock needed, and the stack's unfinished items are still there.

#### O-03 · High · confirmed (test) · The text box: a failed open isn't retried, and the state says "open" (#4, #16b)
- **Evidence:**
  - `panes.ts:276-286` says "tried again on the next change", but nothing schedules one.
  - In `main.ts:545-564`, `toggleTyping` *closes* the box when `typing` is set, and `changeByTyping` (1230) acts only `if (!typing)`.
  - #4 traced: Change sets `typing`, and the open fails or opens behind the card (the part `ab09f51` fixed). A second Change does nothing. Reject changes `pres`, which re-syncs the panes, and the box opens.
  - Test: `overlay/tests/seams-audit.test.ts` "O-03".
- **Every path:**
  1. The hotkey Ctrl+Alt+Space (three keys, and AltGr on many layouts).
  2. The native tray item.
  3. The tray pane.
  4. Change on a card.
- **Shared failure modes:**
  - no retry;
  - one error matching the `noPaneWindows` regex (`panes.ts:236`) turns pane windows off for the session, and the fallback is `window.prompt`, which never shows;
  - `open_pane` returns `Ok` while a same-label window is still being destroyed (`lib.rs:404`, suspected);
  - `set_focus` is denied to a `WS_EX_NOACTIVATE` window (unverified);
  - placement clear of the card depends on `.card--in` at open time.
- **Fix:**
  - `PaneSync` retries (300 ms, 1.5 s) and exposes `isShown`.
  - Change always opens; the hotkey closes only a box that is shown.
  - A capability probe at start-up replaces the regex.
  - Pane failures are logged (O-10).
  - **A one-gesture way to open the box** (decision 4 in §9).
- **Owner check:** with a card up, click Change. The box opens at once beside the card, with the caret in it, and typing goes into it. Press the hotkey twice, slowly: open, then closed.

#### O-04 · High · confirmed (harness) · The Send card hides most of the email (#15)
- **Evidence:**
  - A 1,885-character body in two paragraphs: `.mail-body` is 65 px of 672, `overflow: hidden`, with no "Show the whole email".
  - The expander appears only when the body has more than 8 newlines (`main.ts:1168`).
  - The stock `confirmEmail` design state is clipped too.
  - `ab09f51` made the card scroll, but the draft is inside a fixed 66 px box (`styles.css:553-565`).
- **Class:** clipping decided from the data's shape instead of measured overflow (P5).
- **Fix:** `overflow-y: auto`; show the expander when `scrollHeight > clientHeight`; toggle it locally.
- **Owner check:** email a contact a 300-word, two-paragraph message. Every word can be read on the Send card before Send.

#### O-05 · Medium · confirmed (test) · A protocol error wipes the confirm card
- **Evidence:**
  - `server.py:100-102` replies `error bad_message` (not logged).
  - `main.ts:1978` → `presentAnswer("error")` with no run id → `noConfirm`.
  - It is triggered by version skew after a dev reload (new TS, old Python).
  - Test: "O-05".
- **Fix:** route `bad_message` to the log, never to the card, and log it on the server.

#### O-06 · Medium · confirmed · No protocol contract test
- **Fix:** §6 layer A.

#### O-07 · High · confirmed (test) · One run, two cards: the backend and the overlay disagree
- **Evidence:**
  - `_ask_card` (1177-1202) queues card 2, but `_send` (943-972) forwards its `confirm.request` because the run is in front.
  - The overlay shows card 2 and reports it seen, while the backend keeps card 1 "on screen", frozen, and not in the stack.
  - `Run.card` keeps only the latest card (550), so opening card 1 from the stack replays card 2.
  - It happens with parallel tool calls (`can_use_tool` has no lock), or a gateway card beside a provider card.
  - The owner log at 18:15:55.8 → 18:16:55.8 shows a card opened from the stack expiring again exactly 60.000 s later. `card.seen` isn't logged, so whether the owner saw it can't be told.
  - Test: `test_s04_…` (state).
- **Class:** two owners of screen state (P3, #14).
- **Fix:**
  - `_send` holds back a `confirm.request` that isn't `_cards[0]`.
  - `Run.cards[request_id]`.
  - Longer term, the backend's `cards` snapshot (S1).
- **Owner check:** "use Bash to list the files in this folder and in the parent folder at the same time". If two command cards come, answer one; the other then shows.

#### O-08 · High · confirmed (code, both sides) · A due card dropped by the overlay is marked shown
- **Evidence:**
  - `_wait_due` sends after 120 s even with a run in front (3367-3376), and `scheduler.shown` removes the item from `schedule.json`.
  - The presenter drops it (`notInFront`, the "stale answer" rule, `presenter.ts:255-257`).
- **Class:** B-03's "kept until shown" trusts the send, not the drawing (P3).
- **Fix:** the overlay acknowledges due cards (`due.shown`), or they always show as a notice.
- **Owner check:** "research the history of tea in detail", then "set a timer for 1 minute", and keep the research running over 3 minutes. The timer card shows.

#### O-09 · Medium · suspected · The live view can ratchet narrower (#10)
- **Evidence:**
  - `lib.rs:476-489` `fit_pane` uses the scale of the monitor under the top-left corner.
  - `open_pane` (408) uses the monitor under the cursor.
  - `.live { width: 420px; max-width: 100% }`.
  - With mixed DPI, each fit can narrow it. It held its width on one monitor in the harness.
- **Fix:** `window.scale_factor()`; fixed-width panes fit their height only; a `min-width`.
- **Owner check:** two monitors at different scaling. Drag a live view across and back: it keeps its width.

#### O-10 · Medium · confirmed (code) · What the overlay knows never reaches `swift.log`
- **Evidence:**
  - `console.warn` only (`panes.ts:281`, `main.ts:381, 2103`); Rust `eprintln!` (lost in release).
  - 25 of 27 `client.send` calls ignore `false`: Approve while reconnecting disables the buttons and does nothing (`main.ts:1188-1192`).
  - The server drops frames with no client silently.
- **Fix:**
  - An inbound content-free `log` message, written as `overlay: <event>`.
  - A Rust `overlay.log`.
  - Dropped frames counted.
  - Buttons re-enable when a send fails.
- **Owner check:** open the text box; `swift.log` shows `overlay: pane opened kind=type`.

#### O-11 to O-14 · Low
- **O-11:** caps with no marker:
  - `present` (lists 100 × 300 characters, tables 8 × 100 × 120, `workflows/tools.py:481-486`);
  - "how long left" lists 4 timers of 6 (`system/lane.py:267`);
  - "and N more" with no way to see them (299);
  - calendar description and location cut in what is *written* (`calendar.py:167-168, 455-456`).
- **O-12:** answers fade after at most 20 s (`answer.ts:17,33`). An answer with Read more should stay, or go to the stack as unread (decision 6).
- **O-13:** two clients replace each other forever on close 4409. Stop reconnecting on 4409, and say so.
- **O-14:** the fallback inline live view's header goes off-screen at 720×480.

**Where content is clipped, and who owns "the whole answer is readable".** The full truncation table (40 sites) is in the overlay notes. The ones that lose what the owner reads or approves:

| Where | Cap | Content | Status |
|---|---|---|---|
| `main.ts:1168` + `.mail-body` 66 px | 3 visible lines | the email on the Send card | **not scrollable** (O-04) |
| `claude_mapping.py:confirm_card` | Edit 70 / Write 60 / generic 60–300 characters | what the owner approves | **lost** (X-17) |
| `claude_mapping.py` DETAILS_MAX | 24,000 characters | answer body | lost past 24k |
| `workflows/tools.py:481-486` | lists, tables | what Swift shows | lost, no marker (O-11) |
| `system/lane.py:267, 299` | 4 or 5 items | timers and reminders | lost (O-11) |
| `calendar.py:167, 455` | 200 / 2,000 characters | text written to the calendar | lost in the event |
| `session.py:3047` | 300 characters | Swift's own question | lost (Low) |
| `answer.ts` READ_MAX_MS | 20 s | every answer | gone from the screen (O-12) |

Fixed already: research bullets (`0bf901d`), card height (`ab09f51`). Readable today: long answers (Read more), confirm details (scroll), the stack, live view bodies.

**Ownership:**
- **The overlay owns readability.** Every content surface fits, scrolls or has an expander, checked by one harness scan over every design state (layer E).
- **The backend never cuts content the owner reads or approves.** It cuts only to keep a frame under 64 KiB, and then says so (`truncated: true, total`).
- **Rust only keeps windows inside the work area.**

### 3.4 Voice and half-duplex

#### V-01 · High · confirmed (test) · With SAPI unavailable, the open mic goes deaf
- **Evidence:**
  - On an init error the speech worker returns (`speech.py:186-192`), but `speak()` still sets `_speaking = True` (160-164), and nothing clears it.
  - `hear_wake` then drops everything as `own_voice`, `speech_done` never runs, and no window reopens.
  - Test: `test_s10_…`.
- **Class:** a dead worker leaves a state flag set (P4).
- **Fix:**
  - `speak()` returns early if the worker is dead.
  - Fall back to the silent speaker.
  - A watchdog: speaking for more than `len/8 + 5` s ends it.

#### V-02 · Medium · confirmed (tests) · No echo cancellation, and the "no over Swift's voice" rule has gaps (#7, #8)
- **Evidence:**
  - The mic is a raw WASAPI shared stream (`recorder.py:81-88`), with no AEC and no ducking.
  - `ab09f51` accepts an utterance of 2 s or less that is exactly "no"/"stop"/… and not a word Swift is saying. Its gaps:
    1. **The commonest real case:** Swift's voice opens the same utterance, so it is longer than 2 s and dropped.
    2. Swift's own sentences contain "no" (`CARD_HINT`, the re-ask), so the owner's "no" counts as echo (`test_s07_…`, `test_s07b_…`).
    3. A clip under 0.4 s never arrives, because `wants_short` is False while speaking (`test_s08_…`).
    4. A "no" over a question being said stops the voice but answers nothing, because the window isn't open yet (`test_s09_…`).
  - "Yes" over speech isn't even queued for after the voice ends.
- **Class:** a lexical filter standing in for echo cancellation (P4).
- **Fix:** §8 S5:
  - the Windows communications capture path (built-in AEC), or an AEC on the loopback;
  - the answer window open while the question is said;
  - the words Swift is saying *now*, by SAPI word events.
- **Owner check** (needs speakers): with `read_confirms` on, say "no" while Swift reads "…or 'no'". The card is rejected.

#### V-03 · Medium · design concern · The confidence model isn't one principle
- **Evidence:** three measures (mean word probability, min word probability, loudness), plus length and name closeness, with about 30 constants (listed in the speech notes §5).
  - Only `REJECT_P` 0.7 and `UNCLEAR_P` 0.4 were calibrated on a corpus.
  - `ANSWER_MIN_P`, `PTT_NAME_CLOSE`, `OVER_SPEECH_MAX_S` and `phrase_min_p` were each tuned to one owner report.
  - The log's `stt_confidence` is the min, while the gates decide on the mean: 17:34:23 was accepted at 0.243, 17:33:22 refused at 0.487.
- **Fix:**
  - One score per clip, with context (an open question's answers, contact names, the wake phrase) as priors.
  - The bar set by the decision's cost: approve > disruptive > answer > control.
  - Log the deciding score.
  - Interim: log `mean_p` and the gate that decided.

#### V-04 · Low · confirmed (owner data) · A quiet "Yes." never reaches the model
- **Evidence:** the test-set "Yes." peaks at −53.7 dBFS, below `SILENCE_DB = −50` (`transcriber.py:34`).
- **Fix:** set the silence gate relative to the room and the owner's recent voice level, as the noise gate already is.

### 3.5 Words: speech recognition (see §7)

| ID | Sev. | Finding | Evidence | Fix |
|---|---|---|---|---|
| W-01 | Medium | Word-fix proposals swap common words without context | 7 of 9 proposals were common words ("text → Test", the owner says "text" 10 times; "four → noon", 20 times). `improve.py:137-150` filters only words in the test-set references; `fixes.py:43-46` replaces whole words everywhere. Tests: `test_seams_audit_stt.py::test_common_word_…`, `::test_text_to_test_…` | §7 step 1 |
| W-02 | Low | Two enabled fixes rewrite rare real words ("tori → Tauri", "distal → distil") | `word_fixes.json` | review them on the new rules; `test_word_fixes_do_not_rewrite_…` |
| W-03 | Medium | The regression gate is aggregate-only | `improve.py:40, 203`: a WER rise over 0.02. One sentence going from right to wrong moves it by about 0.002. Test: `test_improvement_pass_reports_…` | a per-sentence gate (§7.3) |
| W-04 | Medium | The owner test set misses systematic mishearings | 2 labelled clips after a day of failures. An identical repeat is skipped as "asked again" (`recordings.py:236`) | label identical repeats and spoken corrections; a labelling card |
| W-05 | Low | A low-confidence trigger would see about 25% of errors | 29 of 39 wrong clips were "clear" | context, not confidence |
| W-06 | Medium | Contacts aren't used when recognizing a name | "Test Me" → "Plectomy"/"Testby"/"Testme"/"TEST" (17:46–17:56). A contact boost fixed 2 of 5; Whisper with hotwords fixed 4 of 4 | §7 step 2 |
| W-07 | Low | Boosting expected answers by a bonus inserts them | yes/no bonus 4 turned "Yes." into six "Yes." | closed-set scoring with a margin, never a bonus |

### 3.6 Routing and fallback

#### R-01 · Medium · confirmed (test) · Offline, the light lane and the workflow offer come first
- **Evidence:**
  - `session.py:2540` (`_quick_answer`, up to 20 s, `quick.py:31`) and the offer (2547-2551) run before the offline check (2559).
  - `start_own` runs aren't checked at all.
  - Test: `test_r01_…`.
- **Class:** a capability check attached to one lane's hand-off instead of to the dependency (P4).
- **Fix:** S4: lanes declare `needs`, and the check runs before the first lane that needs the network.
- **Owner check:** Wi-Fi off, "Swift, what's the capital of Peru?". "I'm offline" within a second.

#### R-02 · Medium · suspected · `online()` reads "has a connection"
- **Evidence:**
  - `network.py:33-45` uses `InternetGetConnectedState`, which is True for any LAN, virtual adapter or captive portal.
  - No `action: offline` row exists in the owner's log yet.
- **Fix:**
  - Keep it as the fast path for False.
  - When it says True, use `INetworkListManager::GetConnectivity` (still local).
  - Treat the run's first `api_retry` as evidence (R-04).
- **Owner check:** Wi-Fi connected with the router's internet off; ask a research question. "I'm offline" within about 5 s.

#### R-03 · High · confirmed (test) · A local request waits behind three agent runs
- **Evidence:**
  - `_slots.acquire()` (`MAX_RUNS` 3) at `session.py:2428-2435` is taken before routing (2454).
  - "Turn the volume up" gets "That's waiting: 3 requests are running".
  - Offline, three runs stuck on "Connection hiccup" block "turn the Wi-Fi back on".
  - Test: `test_r03_…`.
- **Fix:** route first; take a slot only for the agent route.
- **Owner check:** start three research requests, then "Swift, volume up". It changes at once.

#### R-04 · Medium · confirmed (log, test) · Internet lost mid-run
- **Evidence:**
  - 17:34:23: cancelled after 45.4 s with 6 retry steps. 17:38:55: 22.3 s, 4 retries.
  - `claude_mapping.py:195-197` maps a retry to a step only, and no `swift.log` line counts them.
  - Test: `test_r04_…`.
- **Fix:**
  - Count consecutive `api_retry`. After the second with `online()` False (or N in all), end the run with the offline answer and park it, resumable.
  - Log the count (content-free).
- **Owner check:** start a research request, turn Wi-Fi off. Within about 10 s Swift says it's offline and keeps the request in the stack.

#### R-05 · Medium (High in the week-away case) · confirmed (test, log) · A refusal soon after a check gets no sign-in card
- **Evidence:**
  - `signin.py:96` sets `_last` on every check, and `refused()` returns silently within 600 s (114-117).
  - `claude_status` reads the local login, so a refresh token revoked on the server reads `ok`.
  - The owner's case: 15:15:08 and 15:15:49, "OAuth refresh token is no longer valid".
  - Google's listener has the same throttle (`connectors/google.py:205-207`).
  - Test: `test_r05_…`.
- **Fix:** throttle on the last *offer*, not the last check; always offer when the check said ok but a run was refused.
- **Owner check:** the next real refusal shows "Sign in to Claude again?" on the first refused request.

#### R-06 · Medium · confirmed (test, log) · No watchdog on a run
- **Evidence:**
  - `claude_code.py:665-722` has no timeout on `connect`, `query` or `receive_response`.
  - At 18:21:49–18:26:32, run cc-19's question expired into the stack, the owner's click was "ignored", and the run sat for 4.7 min.
  - The quick lane (20 s) and sign-in (300 s) are bounded; the agent isn't.
  - Test: `test_r06_…`.
- **Class:** no liveness bound on external processes (P4). R-04, X-10 and X-12 are members.
- **Fix:** a stall timer reset on every SDK message and paused while a card or question waits. On a stall (90 s), end with `timeout`, kill the tree and park the request (§8 S4; decision 1).
- **Owner check:** in debug mode, a hanging mock scenario. Swift ends it by itself and offers it in the stack.

#### R-07 · Medium · confirmed (log) · The light lane never answered a real request
- **Evidence:**
  - 0 `quick answer` lines since `c6f0420`, and `light.kind()` matches 0 of 463 real transcripts.
  - A second warm `claude` is kept for it (`backend/__main__.py:497-500`).
  - Meanwhile, "can you hear me", "try again" (spoken) and "do you remember my last request?" go to the agent.
- **Fix:** retarget it at thread questions, retry and small talk from the owner's own usage, or turn it off and drop the warm CLI (decision 2).
- **Owner check:** "Swift, can you hear me?" and "what did I just ask?" are answered at once.

#### R-08 · Medium · confirmed · The agent-time metric includes the owner's own time
- **Evidence:** `spikes/usage/report.py:84-85` uses `interaction_ms`, which includes hotkey speaking (median 6 s), card waits (up to 369 s) and question waits. `asks` have no timings, and offline answers count as "answered by Swift".
- **Fix:** record `first_output_ms` and `owner_wait_ms`, give `asks` timings, add `wanted: agent` to offline answers, and report "to first output, minus owner wait".

#### R-09 · Medium · design concern · The dispatch is a chain of about 20 order-dependent rewrites
- **Evidence:** `session.py:2452-2577`. R-01 and R-03 are ordering bugs in it.
- **Fix:** `routing/dispatch.py` with declared steps (S2, S4).

#### R-10, R-11 · Low · suspected
- **R-10:** calendar-event on Haiku took 3–6 turns and 30–90 s on 2026-11-04, with many rejections (mostly the contact problem `ab09f51` fixed). Re-measure with `first_output_ms`.
- **R-11:** `failures.py:56-63` classifies "couldn't confirm model" as `models` before `auth`, so an expired login shown that way never offers a sign-in. On a `models` failure, run `claude_status`.

### 3.7 Executors, gateway, privacy

#### X-01 · High · confirmed (tests) · A single contact match isn't checked against the name said (#15)
- **Evidence:**
  - `names.narrow` acts only on two or more matches (`workflows/names.py:84`).
  - If the search finds only Francis Muthoni (the owner is probably not his own contact), "Draft an email to Francis Chianu" returns "Found Muthoni, Francis".
  - Every recipient path (draft, send, attendees, `fill_in_email`) goes through `find_contact` and `scope.resolved`, so the fix covers them all.
  - Tests: `test_seams_audit_privacy.py` (2 xfail).
- **Fix:** compare every candidate, a single one included, with the words said. A non-match gets "the closest is…; ask the owner".
- **Owner check:** "Draft an email to Francis Chianu" with the real contacts. No card for another Francis.

#### X-02 · Medium · design concern · Every candidate counts as resolved
- **Evidence:** any address `find_contact` returned may be drafted to. Only the card's recipient line protects the owner.
- **Fix:** resolve only the candidate the owner confirmed or the one that matched the whole name. Keep the card line.

#### X-03 · High · confirmed (test, log) · `swift.log` redaction is a deny-list over the whole record
- **Evidence:**
  - `logging_setup.py:32-39` and `backend/__main__.py:76-83`: the whole interaction record is logged as `extra`, and only listed keys are redacted.
  - That is how `cd7eec8`'s three fields got through: `test_redaction` checks only the names it lists.
  - Open when this was written:
    - `transcript_raw` (`session.py:2366`; latent);
    - a model-written `escalations[].reason` (1 real line restates the request);
    - `addressed_as` (1).
  - After `cd7eec8`, 0 lines carry the three fixed fields.
  - Test: `test_the_interaction_summary_keeps_words_out_of_swift_log`.
- **Class:** a content-bearing field added without touching `logging_setup` (P5). X-04 and X-05 are members.
- **Fixed 2026-11-06:** an allow-list (`SUMMARY_FIELDS`) for the `interaction finished` line only. A field nobody has classified stays out of the line. Two guards ask someone to decide on a new field: `tests/conftest.py` checks every record a test's session finishes, and `test_every_field_written_in_the_source_is_classified` scans `session.py`, `backend/__main__.py` and executor `meta`. A field written in a form the scan doesn't know, on a path no test reaches, passes both, and still stays out. Lines already in `swift.log` are unchanged.
- **Owner check:** "Swift, use opus: write a two-page letter about <topic>". No line in `swift.log` holds the topic.

#### X-04 · Medium · confirmed (test) · B-07 still open
- **Evidence:** `gateway.py:163-166, 230-231` log the reason text, with the address. A second route: the draft check's "Not an email address: …" goes through the same line (`tools.py:412-413`). The owner's log had no `action denied` lines when this was fixed, so no address has been written this way.
- **Fixed 2026-11-06:** every denial logs a code (`run_ended`, `invalid`, `already_done`, `no_recipient`, `not_a_contact`, `no_policy`). The agent still gets the full reason. Report check 123 fails on the old form.
- **Not changed:** the recipients' `domains`, filed as X-19.

#### X-19 · Medium · confirmed (X-04 review) · A recipient's domain reaches `swift.log`
- **Evidence:** `action done` logs `domains` (`gateway.py:227`). An email or event to someone on their own domain writes that domain to `swift.log`, and it can identify who was written to. Reproduced with fakes. The owner's log has 43 `action done` lines with 2 distinct domains.
- **Documented?** For the journal, yes (ADR-010: "recipient domain, metadata only"). For `swift.log`, no decision was recorded.
- **Fixed 2026-11-06, the owner's decision:** `domains` is out of the `action done` line and stays in the journal. Nothing read it from `swift.log`. Report check 123 fails on the old form. Lines already in `swift.log` are unchanged.

#### X-05 · Low · confirmed (log) · Exception texts in `swift.log` and the journal
- **Evidence:** `detail=str(exc)[:300]`, `google._failure` HttpError text with request URLs. 11 real values, no content.
- **Wider, found in the X-03 review (2026-11-06):**
  - When an open fails, `open failed` (`session.py:2828`) logs `target=target.name` and `error=str(exc)`, and `failure shown` (`session.py:4581`) logs `detail`. A selected file's name and path reach `swift.log`. Reproduced with fakes. This touches the product rule, so Low may be too low.
  - A model's error text can reach `failure shown` through `claude_mapping.py:216-233`. Read in the code, not run through a session. Whether real CLI errors restate the request is unproven.
  - Report check 123 gave PASS on both lines.
- **Fixed 2026-11-06:** `open failed`, `failure shown`, `claude run failed` and `action failed` log a type or a code, and the journal's FAILED and UNKNOWN reasons are codes. A traceback keeps frames and types, never a message. When a request fails, `error_detail` in the local interaction log keeps the text, secrets masked. Report check 123 fails on all four old forms.
- **Not changed, each with no known route for what the owner said (read in the code; `speech failed` also probed with a muted voice):** `error=str(exc)` on Swift's own files (`parked`, `scheduler`, `runlog`, `journal`) and on the microphone and presence; `heard signal failed`; `overlay frame refused`; `speech unavailable`; `speech failed` and `wake listening can't transcribe`; `detail=` on `claude warm-up failed` (before any request) and on `speech model failed to load`; `skipping a demand example`.
- **Still logs text the owner wrote:** `workflow skipped` (`library.py:553`). A YAML error can quote a line of a workflow file, and `folder` has the full path (reproduced). It isn't speech, and it only happens at start-up, so it's left as it is.
- **Lost for diagnosis:**
  - A failed gateway action's text (email, calendar, desktop) goes to the card and the agent, and is stored nowhere on disk: the gateway has no record to put it in. The journal and `swift.log` keep only the code.
  - A stopped run's exception text is kept nowhere: the session doesn't read a cancelled run's result (the same gap as X-13).
  - An unknown model error has no `detail`: its text is in the card's message only, as before.
  - Other `logger.exception` lines keep the frame and type only.
- **Known limit of the masking:** `redact` doesn't recognise a bare `sk-ant-…` key, so one in a failure's text would reach `error_detail` as it is. Not new, but that text now lands on disk. Whether real errors ever carry a key is unproven.
- **Not checked:** the backend's stderr, which Tauri inherits (`backend.rs:171`). An error logged by Python's own logging, such as an unretrieved task exception, would still print its message there. Whether that output is kept anywhere is unproven.

#### X-18 · Medium · confirmed (reproduced in the X-05 review; no test in the repo yet) · A selected file's name goes into the journal as a receipt
- **Evidence:** `desktop_open` returns `Path(path).name` as its receipt (`workflows/desktop_tools.py:227`), and the gateway journals it as `DONE` (`security/gateway.py:218`). On a selected `visa interview notes.docx`, the journal says so. Other receipts are ids, counts or intent names.
- **Fix:** return a receipt with no name. Check what undo reads first.

#### X-06 · Medium · confirmed (code) · B-10 is wider than recorded
- **Evidence:** the working-card step "Claude is busy, retrying…" (`claude_mapping.py:61`), "Claude Code stopped…", "Claude asked for a stronger model", and the error title "Claude Code isn't signed in".
- **Fix:** "Swift" in every owner-facing text; the provider only in the byline. This touches the product rule "status labels generic".

#### X-07 · Medium · design concern · Swift's own data folder is readable with one card
- **Evidence:** `%LOCALAPPDATA%\Swift` (recordings, `interactions.jsonl`) isn't on the never-read list. One approved Read card would send audio or transcripts to the model provider.
- **Class:** B-01's class. It touches "audio never leaves the PC".
- **Fix:** add it to `never_read`.
- **Owner check:** "read my Swift interaction log" is refused without a card.

#### X-08 · High · confirmed (test) · A stop during "Sending…" journals FAILED
- **Evidence:** connectors run in `asyncio.to_thread` and continue after the stop, while `gateway.py:192` writes FAILED "interrupted". Test: `test_a_stop_while_the_service_is_sending_is_unknown_not_failed`.
- **Fix:** shield an approved send so it finishes and is journaled as it ends (decision 3), or journal UNKNOWN.
- **Owner check:** in debug mode with the fake mail delay, press Esc during "Sending…". The card doesn't just say "Cancelled".

#### X-09 to X-14
- **X-09 (Medium, B-08 open):** after an "unknown" outcome, the same action can be approved and done again.
- **X-10 (Medium, suspected):** no deadline on a Swift tool call. One `find_contact` can take minutes (60 s × 3).
- **X-11 (Medium, suspected):** Google API clients shared across threads; their HTTP library isn't thread-safe.
- **X-12 (Low):** waiting for the spare CLI is outside every timeout.
- **X-13 (Low):** a cancelled or killed run reports no cost.
- **X-14 (Low):** the sign-in hints still say "run `claude`" in a terminal, beside the new card; the sign-in card times out while away; there is no card for "absent" Google; `"401" in text` is a loose match.

#### X-17 · High · design concern · Edit and Write cards show a fragment
- **Evidence:** `claude_mapping.py:confirm_card`: Edit shows `replace "<70 chars>" with "<70 chars>"`; Write shows the line count and 60 characters of the first line. A-12's rule, "the owner approves only what they can read", was applied to commands only. The October audit listed it as a remaining risk.
- **Fix:** send the whole old/new text, or a diff, as an artifact the card scrolls (`facts-text` already scrolls).
- **Owner check:** ask Claude Code to change a paragraph in a file outside the working folders. The card shows the whole old and new paragraph.
- **Fixed 2026-11-07:** Edit, MultiEdit, Write and NotebookEdit cards carry the whole change in the card's scrolling box, and a change over 12,000 characters is refused without a card, as a long command is. A review of that fix found the agent's text could pass for Swift's own, so all of it, path and cell included, now has a bar down its side that wrapped rows keep, characters that hide or reorder text show as escapes (on command cards too, for showing only), long blank runs collapse, and a sign says when there's more below the box. A refusal for length doesn't escalate the model, and reads as "Blocked" unless a smaller call was then approved. Not changed: the generic card for any other tool (60–300 characters), which the default `confirm_tools` don't reach. Owner checks 183–184.

### 3.8 Verification, and the October findings re-checked

#### Q-01 · Medium · confirmed (code, real report) · The owner-check report can't say FAIL
- **Evidence:**
  - `spikes/owner_checks/report.py:514` prints `PASS` or `NOT SEEN`, and nothing else.
  - On 2026-11-04 from 16:00, check 130 printed "NOT SEEN … (2 sent to the agent)": its failure condition was met.
  - Seventeen checks are hard-coded `True`, most of them with "check on screen", for example "18-20 … nothing cut off", printed PASS on a day when text was cut off, and 137, 138.
  - "123 swift.log kept your words out" scans only the three field names `cd7eec8` fixed.
- **Fix:**
  - Three outcomes: PASS (evidence present and the failure condition absent), FAIL (the failure condition seen) and NOT SEEN.
  - On-screen checks print `LOOK` with what to look for, never PASS.
  - Check 123 uses the X-03 allow-list.

#### Q-02 · Medium · confirmed (survey) · The fakes hide the seams
- See §6.

#### Q-03 · Low · confirmed · Routing parity is a synthetic set
- **Evidence:** 97.5%, but 0 of the owner's 463 transcripts match the light lane, and 79 of 247 agent-bound requests are fragments or corrections that parity has no category for.
- **Fix:** add a scrubbed, owner-approved sample of real requests (counts only in CI) as a second parity set.

**October findings, re-checked:**

| ID | Holds? | Did the fix cover the class? |
|---|---|---|
| A-01, A-02 | yes | yes |
| A-03 | yes | yes for fetches. Search queries remain, as recorded |
| A-04 | yes | yes, and `cd3f97b` changed the rule by the owner's decision (a plain yes or a click on Swift's own reversible question) |
| A-05, A-06 | yes | the class is wider: a stop *during* the send (X-08), and unknown outcomes repeatable (X-09 = B-08) |
| A-07 | yes | yes |
| A-08 | yes: `_close_scope` and `_drop_questions` are per run | the class "one request's end touching another's state" is also T-01 (one timer slot) |
| A-09 | yes for in-flight transcriptions | **no**: T-07 is a second member (held utterances) |
| A-10, A-11 | yes | A-11's duplicate check exists only beside a run (D-01 gap D) |
| A-12 | yes for commands | **no**: Edit and Write cards (X-17) |
| B-01 | yes | **no**: Swift's own folder (X-07) |
| B-02 | yes | yes |
| B-03 | yes for restarts | **no**: "shown" means sent, and the overlay can drop it (O-08) |
| B-04 | yes | partly: after a restart the overlay doesn't resync (O-02) |
| B-05 | partly | the spare still connects beside the speech model at start-up (median 9.8 s vs 15.6 s), but the first agent request after start was warm in all 13 starts with one. `warm=True` also hides a wait for a spare still connecting: log `waited_ms` |
| B-07, B-08, B-10 | still open when this was written; B-07 fixed 2026-11-06 (X-04) | B-10 is wider (X-06) |
| H-06 (no heartbeat), H-07 | still open | H-06 belongs with S1 |

---

### 3.9 Found by layer C (2026-11-05)

#### T-13 · Medium · confirmed (layer C) · A replayed question restarts the overlay's countdown
- **Evidence:** a run asks "Paris or Rome?" and listens for 25 s. Two seconds later a request with a card takes the front. "Swift, plan the trip…" said on that card is a change to the card, so the card closes and the front goes back. `Run.replay()` then resends the stored `ask` frame, still `seconds: 25`. The overlay counts 25 s again; the backend's timer has 22.75 s left.
- **Test:** `test_dialogue_model.py`, `KNOWN["T-13"]`.
- **Class:** deadlines sent as relative seconds (P2). T-03 is the other side of it: a restart with no new deadline sent.
- **Fix:** §8 S3. The question's one deadline is absolute, and every frame about it carries that deadline. Until then, `replay()` recomputes `seconds` from the timer.

#### O-15 · Low · confirmed (layer C) · A question closed out of sight stays on the overlay
- **Evidence:** a run's question waits, and another request takes the front ("what time is it", or one started a moment before). When the question times out, `_close_ask` goes through `_send`. `ask` is in `FOCUS_ONLY`, so for a run not in front the close is only remembered. The overlay keeps the question (`asked` in `main.ts`) until another question replaces it, or a result for that run arrives in front.
- **Effect today:** small. The overlay shows a question only for the request in front, and a replayed result clears it. It is the state the backend and the overlay disagree on (P3).
- **Test:** `test_dialogue_model.py`, `KNOWN["O-15"]`.
- **Fix:** §8 S1. The backend owns what is on screen; a closed question is removed from every copy, in front or not.

## 4. Failure-injection results

Fakes, debug mode and the dev harness only; nothing real. "Recovers" means without the owner doing anything.

| Condition | What the owner sees and hears | What is logged | Recovers? |
|---|---|---|---|
| No internet from the start | Local, system and fast lanes work. Agent request: "I'm offline…" and the list, at once. A light-lane request: working for up to 20 s first (R-01); a workflow offer card can come first. "Turn the Wi-Fi back on": "I'm offline" (D-03) | `quick answer failed TimeoutError`; nothing names offline before `action=offline` | per request |
| No internet, `online()` wrongly True | "Connection hiccup, retrying…" until the CLI gives up (minutes) or the owner stops | nothing about the retries | only when the CLI gives up (R-02, R-04) |
| Internet lost mid-run | "Connection hiccup" (45 s and 22 s seen, then cancelled); nothing said; with 3 runs, local requests queue too (R-03) | nothing until the end, then `failure shown code=offline` | **no** (R-04) |
| Claude Code signed out, or a refused token | Error card "Claude Code isn't signed in… open a terminal" (provider named, X-06), said aloud; the sign-in card **only if** 10 min passed since the last check (R-05) | `claude run failed`, `failure shown code=auth`, `sign-in refused` when not throttled | partly: the card, then a console sign-in |
| Google token expired or revoked | Inside a run, the model says the sign-in expired; "Sign in to Google again?" (seen 16:48:33); start-up and daily checks find `expired` | `action failed`, `sign-in checked status=expired`, `sign-in offered` | with the owner's click; same throttle |
| CLI hangs | "Working" forever (4.7 min seen) | nothing until the stop | **no** (R-06) |
| CLI slow (30 s+) | steps as they come; no "still working" unless the owner repeats the request | nothing until the end | finishes |
| CLI crashes mid-tool-call | error card with Try again; a gateway action already done stays done and journaled | `claude run failed`, `failure shown` | no auto-retry; Try again repeats the request (the journal and digest limit repeats) |
| Backend killed or restarted mid-run | engine-stopped card, Restart. Runs, Later cards and questions vanish; parked items and timers survive; after Restart: no stack, due cards wait, old stack ids open nothing (O-02, T-12) | nothing for the lost items | partly |
| Overlay reloaded (every merge) | the open card vanishes and isn't in the stack; it expires unseen 45–120 s later | `overlay disconnected/connected/ready` | **no** (O-01) |
| WebSocket dropped and reconnected | "Reconnecting…", then the card is cleared; no resync (no `ready`) | `overlay connected` | partly (O-02) |
| Two overlays on one backend | the card cleared twice a second | `overlay connected` ×2/s | **no** (O-13) |
| Mic busy or missing (hotkey) | "Microphone unavailable" card | the failure code | yes: the next press retries; the wake stream reopens |
| Mic missing, answering a question with wake off | the card says "listening"; nothing happens; it times out | only `question unanswered` | **no** |
| SAPI missing | silence, and the open mic deaf after the first reply (V-01) | one `speech unavailable` at start-up; `own_voice` climbing | **no** |
| SAPI busy (COM hiccup) | the speech is cut | `speech failed` | yes |
| Speech model still loading | hotkey: "transcribing" until loaded; wake: utterances dropped while one is transcribed | `stt_timeout` | yes, but the lost utterances are lost |
| Swift speaking while the owner answers | dropped, except a short exact "no" with four gaps (V-02); the reply window may not reopen (T-05) | `own_voice`, `over_speech` counters only | the owner repeats |
| 3 requests + a timer + a card open | the card stays in front; the timer chimes, and its card waits, then is sent after 120 s and **not drawn** if a run is in front (O-08); a 4th request, even local, waits (R-03); a lane question beside a run question hangs the run (T-01) | `due shown` (although not drawn) | **no** for O-08 and T-01 |
| Lock during a question | run question: into the stack; lane: shelved; card held; a held utterance **acts after the lock** (T-07) | `question kept for later`, `held while away` | yes, except T-07 |
| Lock during a run, unlock | the run goes on; its card is held, then replayed | `held while away`, `confirm card back`, `listening again` | mostly; #14 when the overlay had cleared its card |
| Sleep and resume | as lock; due items fire as missed; the mic reopens | `due missed=True` | yes |
| 100% vs 150% (720×560 vs 720×480 CSS) | cards fit and scroll, buttons visible (`ab09f51`); the email draft shows 3 lines (O-04); an open long answer is 186 px tall | — | yes, except O-04 |
| Multiple monitors | panes open on the cursor's monitor; with mixed DPI the live view may narrow (O-09) | nothing | suspected |
| A very long answer (6,443 characters) | 6 faded lines; Read more scrolls; fades after 20 s if untouched (O-12) | — | readable while up |
| A 2,000-character draft | 3 lines, no scroll, no expander, Send enabled | — | **no** (O-04) |
| A frame the backend can't read | "Something went wrong" replaces the card | nothing | **no** (O-05) |
| The text box window fails to open once | the box never appears; the next hotkey press closes it | `console.warn` only | only after an unrelated change (O-03) |

---

## 5. Measurements

The sources are `interactions.jsonl` (463 records, 2026-10-23 to 2026-11-04) and `swift.log` (7,140 lines). Debug sources are excluded. The two test days (10-27, 11-04) dominate, so these are testing numbers, not daily use.

### 5.1 Against the targets (product-direction §9)

| Question | Measure | Before (10-28) | Now, all weeks | 2026-11-04 | Target |
|---|---|---|---|---|---|
| Is it useful? | done cleanly | 78% | 75% | 66% (W45) | 90% |
| Is it fast? | answered locally | 25% | 28% (report); 31% of routed | 35% (report); 40% of routed | 35% |
| Is it fast? | agent median (report method) | 12.3 s | 12.9 s (p90 37.3) | 20.2 s (p90 49.6) | under 10 s |
| Is it fast? | agent median, the owner's own time removed | — | 9.6 s (p90 23.8) | 15.9 s (p90 44.1) | under 10 s |
| Is it trusted? | product-rule breaches | not measured | 1 found here (T-07, narrow); the log leak fixed in `cd7eec8` | — | 0 |
| Is it affordable? | cost | $2.43 | $3.08 over 243 runs; median $0.006, mean $0.013 | $0.65 | tracked, capped |

The "agent median" in the usage report includes the owner's speaking, card waits and question waits (R-08). The 28.9 s p50 on 10-29 was two runs (3.4 s, and a 54.3 s calendar workflow with 22 s of speaking and its card). It wasn't model choice, a cold spare or escalation.

On 11-04 the agent was slower because of:

- **the model:** Sonnet started 20 of 23 runs (model p50 14.9 s);
- **the task mix:** 13 of 54 requests were research or writing with 2–4 tool steps;
- **an unanswered question:** about 50 s;
- **an escalation to Opus:** one.

The CLI's own overhead stays at about 1–1.5 s, and all runs were warm.

### 5.2 Latency per lane (`interaction_ms`, done)

| Lane | All: n / p50 / p90 | 2026-11-04 |
|---|---|---|
| local | 86 / 0.0 s / 5.7 s | 15 / 0.0 / 6.1 |
| fast | 12 / 0.0 / 0.0 | 3 / 0.0 / 0.0 |
| system | 15 / 0.0 / 4.2 | 15 / 0.0 / 4.2 |
| control | 13 / 0.5 / 2.0 | 3 / 0.0 / 0.4 |
| light | 0 | 0 (R-07) |
| agent (no workflow) | 133 / 11.0 / 29.9 | 22 / 19.5 / 49.1 |
| workflow | 71 / 16.0 / 50.3 | 8 / 34.9 / 51.8 |

To the first card or answer: agent p50 8.3 s, workflow 8.4 s (all); 15.9 s and 8.5 s on 11-04.

### 5.3 Start-up

| Measure | p50 | p90 | max | Notes |
|---|---|---|---|---|
| Backend ready → speech model loaded | 15.6 s | — | 28.2 s | 26 starts; 8.1–16.2 s on 11-04 |
| Backend ready → spare CLI ready | 9.8 s | — | 29.4 s | |
| `claude ready` connect time | 2.73 s | 8.67 s | 29.4 s | 310 samples |
| Speech to text (`stt_ms`), November | 436 ms | 939 ms | 1,480 ms | |

Start-up to the first answer is 21 s to 25 min, driven by when the owner first speaks. B-05: §3.8.

### 5.4 Error and cancelled rates per entry point (all dates)

| Source | n | Error | Cancelled | Rejected |
|---|---|---|---|---|
| voice (hotkey) | 154 | 19% (mostly `unclear_speech` and `no_speech`) | 11% | 7% |
| wake | 116 | 2% | 6% | 6% |
| followup | 133 | 8% | 5% | 9% |
| stack | 14 | 0% | 28% | 7% |

From 10-29:
- the agent lane was cancelled 31% of the time;
- workflows: 7 of 22 cancelled, 6 of 22 rejected.

Error codes: `unclear_speech` 27, `no_speech` 12, `crashed` 3, `auth` 2.

### 5.5 Agent requests that could have been local

Re-scored with today's `rules.route`: 23 of 270 (8.5%) now route locally. That is approve 6 (`cd3f97b`), resume 6, undo 5, answer 2, date 2, show_last 2 and offline_help 2.

Of the 247 still agent-bound:

| Kind | Count |
|---|---|
| Workflows | 91 |
| Fragments and corrections | 79 |
| Research, writing and web | 55 |
| Small talk or "can you hear me" | about 12 |
| Calendar or email outside a workflow | 10 |
| System-lane requests | 0 |

The owner's agent mix isn't made local by more rules. The levers are R-07 (thread questions, retry), §7 (fewer mishearings, which cause most of the fragments and corrections) and D-02.

### 5.6 Resources (debug backend, echo executor, 35 minutes idle)

| Measure | Result |
|---|---|
| CPU | 0.17% of one core on average; 0.09% in the quiet last 15 minutes |
| Private memory | 729.8 → 731.2 MB (+1.4 MB), flat after 10 minutes. About 730 MB is the speech model |
| Handles | 448 → 435 |
| Threads | 36 → 31 |
| Leaks | none |
| `claude.exe` | none from the harness (echo executor). The 21–22 counted belong to the Claude desktop app |
| Not measured | an idle backend with the real executor and its two warm CLIs; repeat on the owner's PC |

---

## 6. The verification gap

### 6.1 Why green tests and a red day coexist

About 929 Python test functions (1,344 with parametrization), 81 overlay tests and 30 Rust tests. None of them crosses a seam:

| Fake | What it hides |
|---|---|
| `test_session.Recorder` as the overlay | Never yields, so interleavings at `await send` are invisible. Never behaves like the presenter: no `card.seen` unless a test sends it, no overwrite of `pendingConfirm`, no `notInFront` drop. O-01, O-07 and O-08 pass every test |
| Tests calling `session.handle(...)` and internals (`speech_done`, `_question_done`, `hold_cards`) directly | The real triggers aren't exercised. `speech_done` is called right after `finish()`, so Swift's speaking time is near zero (T-03, T-05) |
| `say()` = `hear_wake(SHORT, now)` and an instant `FakeTranscriber` | Every utterance "ends now" and transcribes instantly. `started_at` and `in_speech()` are never realistic (T-02) |
| Shortened windows (0.05–0.4 s) | Timers are shrunk, never raced against an event at the boundary |
| One card per fake run | O-07 |
| `Attention(require_seen=False)` in most tests | Production is True |
| Overlay tests | Pure functions over hand-written message sequences, not the backend's real ones |
| Routing parity | A synthetic set (Q-03) |
| The owner-check report | Can't say FAIL (Q-01) |
| The dev harness | The only place backend and overlay meet over the real protocol, and it is manual |

Answers:
- **A test driving the backend and the overlay together over the real protocol:** none. `test_server.py` tests the socket alone.
- **A replay of `interactions.jsonl`:** none.
- **Model-based or timer-race tests:** none. Hypothesis is used only for decoding and redaction.
- **A contract between `protocol.py` and `protocol.ts`:** none.

### 6.2 The proposed test layers

| Layer | What it is | Effort | Would have caught |
|---|---|---|---|
| **A. Protocol contract + sequence invariants** | One example frame per message type in `tests/fixtures/protocol/`, decoded by `protocol.py` and type-checked by `tsc` (`satisfies Inbound`). CI fails on an outbound type with no `case`. Invariants on the session's message sequences: at most one open `confirm.request`; every `ask open:true` gets a later `open:false`; every timer restart sends a deadline | S, 1–2 days | O-05, O-06, O-07, the T-03 member, future drift |
| **B. The real session + the real presenter** | Drive `presenter.ts` and `ask.ts` under node from the session's real messages (a small stdin bridge), answering like the overlay (`card.seen` on draw, clicks by id). Assert "the backend's front = the overlay's front" after every step, and after a reconnect | M, 3–5 days | O-01, O-02, O-07, O-08, #14, A-08 |
| **C. Model-based dialogue test on a virtual clock** | Hypothesis `RuleBasedStateMachine`. Rules: ask, speak for d, speech_done, utterance (start, length, STT delay, confidence), click, card, lock, unlock, run end, tick. Invariants: a pending question has exactly one live deadline, and the mic listens until it; overlay deadline = backend deadline ±0.2 s; nothing acts while paused; every run ends. **Needs a clock seam in `session.py` first** (it uses `time.monotonic()` and `call_later` directly) | M–L, 4–7 days | T-01 to T-07, D-06, T-06 |
| **D. Replay `interactions.jsonl` through the real session** | Text, not audio, on the owner's PC only (his words stay local, never committed): each record's source, transcript and timing through `hear_wake`/`text` with a scripted mock executor; compare route, dialogue turn and status | M, 3–4 days | check 130, D-02, D-03, D-04, routing regressions |
| **E. No-truncation** | A harness scan over every `__design` state: any element with `overflow: hidden/clip` or an ellipsis whose content overflows must have an expander or be on an allow-list. Plus a property test: what the presenter renders = the backend's whole text | S, 1–2 days | O-04, the research cut, check 57 |
| **F. A harness scenario per owner check** | Playwright or the built-in browser against vite on 1431 and `backend-harness` on 8765, scripted with `debug.ask` and `__shim.inject` | L, 8–12 days (about 50 scenarios) | every check marked H below |
| **G. STT regression set** | `stt_corpus` + `stt_noisy` + the owner set: WER and exact sentences per clip, and the decision each gate makes. Fails if any previously right sentence goes wrong (§7.3) | S–M, 2–3 days | W-01 to W-03, checks 124, 125 |

**The smallest set that would have caught most of 2026-11-04:**
- A + C caught 8 of the 9 confirmed state findings.
- With B, the screen-state class (#14, #4, reloads).
- With E, the clipping.

About 10 days of work. Do Q-01 (the report saying FAIL) first: it is an hour.

**Order:** Q-01 → A → C (with the clock seam, which the `session.py` split needs anyway) → B → G → D → E → F.

### 6.3 Which owner checks could be automated

Checks 1–16, 50–62 and 100–138 (62 rows):

| Class | Count | Checks |
|---|---|---|
| U: a unit test (session + fakes, or presenter) | about 29 | 2–4, 6–8, 51, 53, 56, 62, 100–106, 108, 110, 115, 116, 128, 130–135 |
| H: a harness or replay scenario | about 16 | 5, 15, 16, 16b, 54, 57, 61, 111–114, 124, 125, 129, and the logic of 1, 14, 120, 127, 136–138 |
| P: the real PC as a whole | 12 | 9 (Google Calendar), 10 (Word, foreground), 11 (sleep, devices), 12 (lock-screen mic), 13 (latency after unlock), 50 (a real chat app), 58 (150% drag), 59 (speakers), 60 (a real ambiguous outcome), 107 (real TTS), 121, 122 (Google OAuth) |
| H+P: logic H, a residual part P | 5 | 1, 14, 127, 136, 137–138 |

---

## 7. Speech: adapting to the owner

The owner asked for this section: *"correcting words is not the way, for example "text" -> "test" when text is also a valid word in a different sentence makes no sense."*

### 7.1 The current approach, assessed

**The pipeline:**
- Parakeet-TDT 0.6B v2 (int8, onnx-asr 0.12.0, greedy decoding).
- Then `WordFixes.apply` over the whole transcript (`stt/transcriber.py:343`): a case-insensitive whole-word replacement with no context, no confidence check and no idea what kind of request it is (`stt/fixes.py:43-46`).
- That one text feeds routing, dictation into apps, email bodies, contact search and memory.

**Where fixes come from.** The improvement pass (`stt/improve.py:137-150`, the tray's "Improve speech recognition", and weekly while idle) aligns each test-set clip's transcript with its known words. Every differing run of 1–3 words becomes a proposal. A proposal is dropped only if the heard words appear in the test-set references. There is no dictionary check, no check against the owner's other sentences, and no test of what the fix would do to sentences that are right today. The owner approves each one on a card.

**Counted on the owner's `word_fixes.json`.** "Common" means a single whole-word token in the GPT-2/Whisper vocabulary on disk (an offline, frequency-ranked proxy), plus how often the owner says the word.

| | Proposals | Common English word |
|---|---|---|
| Enabled | 3 ("tori → Tauri", "distal → distil", "fleven → F eleven") | 0. But "tori" and "distal" are rare real words (W-02) |
| Rejected by the owner | 9 | **7**: sessions, improved, bean, lack plot, break down, width, **text → Test** (the owner says "text" 10 times), **four → noon** (20 times) |

About 78% of proposals were unsafe, and only the owner's judgement stopped them. Approved, "four → noon" would have rewritten every "Friday at four".

Measured on 77 labelled clips, the 3 enabled fixes made 3 sentences right and none wrong, all in the clips they were learned from.

**Verdict: keep word fixes only in a narrow form.** A fix is allowed only when all of these hold:

1. the heard phrase is not a dictionary or common word;
2. the owner has never said it in a correct sentence (the whole local interaction log, not just the test set);
3. it isn't a contact or app name;
4. simulated on every known-right sentence, it changes none.

Everything that needs context ("tea" vs "T", "bean size" vs "beam size", names) moves out of word fixes.

### 7.2 Methods that use context

What the installed stack can do, checked in `.venv`:

- **onnx-asr** decodes greedy only (`onnx_asr/asr.py:192-226`): no beam, no hotwords, no n-best, no language model. But the decoder's scores at each step are reachable (`spikes/stt/boost_bench.py` rebuilds the loop exactly), so custom decoding needs no new dependency.
- **sherpa-onnx, NeMo and kenlm** are not installed (each needs a download).
- **faster-whisper 1.2.1** with `hotwords` is installed, and Whisper base.en (282 MB) is on disk.

Measured on this laptop (i7-10610U, 16 GB):

- Parakeet: about 690–740 MB; `stt_ms` p50 436 / p90 939 ms in November. The decoder is about 5% of the time, so rescoring is cheap.
- Whisper base.en with beam 5: 1.5–2.3 s per 5–8 s clip.

What the 2026-11-04 failures show:

- **"tea" → "T here":** 6 takes, mostly rated "clear". The model prefers the token "T" (p 0.54–0.82). It is a confident mishearing of an ambiguous sound, so a low-confidence gate never fires (W-05).
- **"Test Me" → "Plectomy"/"Testme"/"Testby"/"TEST":**
  - a contact boost inside Parakeet fixed 2 of 5;
  - Whisper with hotwords got 4 of 4 slots right, but garbled the start of sentences.
  - The hotword list knew the answers, which flatters it, though a contact list is known in advance in exactly that way.
- **A yes/no bonus of 4 turned "Yes." into six "Yes."** Expected answers must be scored as a closed set with a margin, never given a bonus (W-07).

| Method | Accuracy gain (evidence) | Latency | Memory | Local | Effort |
|---|---|---|---|---|---|
| **A. Contacts and app names, only inside a name slot** ("meeting with ___", "email ___"): match after recognition with `names.close()`, then a small Parakeet boost (bonus ≤ 2) inside the slot if no contact is close | 2 of 5 by boost; the match after recognition also catches "Testme", "Testby", "TEST" | +5–15 ms | none | yes | low–medium |
| **B. Re-recognize the name slot with Whisper + the contacts as hotwords**, only when A fails | 4 of 4 slots | +1.5–2.3 s on those turns only | +300 MB while loaded | yes, on disk | medium |
| **C. Closed-set scoring of the expected answers while a question or card is open** (yes/no, the card's options, the contacts offered), accepted only if they beat free decoding by a margin | avoids the insertion failure; can't help a clip the silence gate drops (V-04) | tens of ms | none | yes | medium |
| **D. Pass the decoder's close alternatives as text** to the model that already reads the request ("T/tea", with "speech may be misheard; ask if it matters") | the only method here for common-word confusions like "T here" | +0 locally, a few tokens | none | audio stays local; text already goes | low |
| E. Whole-sentence correction only at low confidence | weak: it sees about 25% of errors | — | — | yes | — |
| F. Beam search with an owner language model | unmeasured; 2.7k words of owner text is too little | +100–300 ms | small | yes | high |
| G. Speaker adaptation (LoRA/adapters) | unmeasured; needs NeMo + torch (GBs of download), an fp32 checkpoint and 1–2 h of labelled audio (11 min exist). The errors are words, not accent (every model had them, `stt-models.md`) | 0 | 0 | yes, after downloads | very high |
| H. Another main engine | measured before (`stt-models.md`): no better | — | — | — | — |

### 7.3 Training data and measurement

What exists:

| Set | Clips | Labelled | Notes |
|---|---|---|---|
| `stt_corpus` | 51 | 51 | October: 40 read prompts, 11 real requests |
| `stt_noisy` | 30 | 30 | TV, music, far |
| `stt_testset` (the 7-day loop) | 2 | 2 | — |
| `audio` (7 days) | 123 | 2 with known words | flags: missed_wake 31, unsure 18, say_again 11, repeated 10 |

Word error rate, measured now with the real fixes (77 labelled clips, about 3 min):

| Set | Without fixes | With fixes | Sentences exactly right |
|---|---|---|---|
| Clean corpus | 0.118 | 0.109 | 26/51 |
| TV | 0.475 | 0.475 | — |
| Music | 0.068 | 0.068 | — |
| Far | 0.085 | 0.085 | — |
| Owner set | 0.700 | 0.700 | 0/2 |
| **All** | **0.152** | **0.146** | **38/77** |

Command success isn't scored: the sets have no intent labels.

**Building the owner set properly:**

1. **Label from the owner, not from the model's repeat.** A systematic mishearing repeats itself, so today it is skipped as "asked again" (W-04). Two ways to label:
   - **the weekly pass:** a labelling card shows a flagged clip's transcript, and the owner types or says the right words. Typing is fine: labelling isn't approving anything (decision 7);
   - **a spoken correction:** "I meant tea" labels the clip before it.
2. **Keep identical repeats** as `repeated_same`: they are the most useful clips.
3. **Freeze a held-out set.** Every 4th owner clip is never used to propose fixes, so gains are measured out of sample. The 2026-11-04 failures ("tea", "write … here", "Test Me", the short yes/no answers) go in first.

**The regression gate:**
- No change ships if it makes any previously right sentence wrong, on the frozen corpus or the owner set. A change is a fix approval, a boost list, a threshold or a model.
- The fix card shows "would change N sentences that are right today", and is refused when N > 0.
- It runs as a script (`spikes/stt/model_compare.py --sets kept` + the corpus) before any merge touching `src/swift/stt`.
- Command success is added once clips carry an intent label.

### 7.4 Recommendation

1. **Cheap, now (S, 1–2 days):** make word fixes safe and gate everything.
   - Filter proposals by a bundled common-word list and the owner's own log.
   - Simulate each proposal on known-right sentences.
   - Add the per-sentence gate.
   - Label identical repeats and spoken corrections.

   This would have removed 7 of the 9 bad proposals. No download, no run-time cost.
2. **Context from what Swift knows, at the slot level (M, 3–5 days):**
   - contact matching after recognition in name slots, then a slot-only boost, with the Whisper fallback;
   - while a question or card is open, closed-set scoring of the expected answers.

   This must not weaken the approval rules: a bare "yes" still approves only Swift's own reversible-change question.
3. **Close alternatives as a text hint (S–M, 2 days):** for common-word confusions, pass the decoder's low-margin alternatives with the transcript. Logs keep them redacted like transcripts.

**Not now:** speaker fine-tuning, beam search with an owner language model, a new engine.

**Docs to update with each step:** `docs/stt-vocab.md`, `docs/stt-models.md` §Recordings, `docs/stt-noise.md` (the confidence gate sees about 25% of errors), plus owner checks and report lines.

---

## 8. A ranked plan

The structural fixes come first: each removes a class. Sizes: S up to 2 days, M 3–5, L more. "Fits" names the groundwork already agreed in the handoff (§4 step 3): splitting `session.py`, run records, the `WorkerTask` contract.

### Structural fixes

| # | Fix | Removes | Size | Risk | Fits |
|---|---|---|---|---|---|
| **S0** | **The report says FAIL** (Q-01) and on-screen checks say LOOK | false PASSes in every owner session | S (hours) | none | — |
| **S1** | **One owner of screen state.** The backend is the only owner: `resync.snapshot()` on every authenticated connect (server `on_connect`, backend instance id in `hello.ok`, `ready` per connection); every card unseen until drawn; a `cards` snapshot with absolute deadlines (`closes_at_ms`) for cards, questions and the reply window; the overlay draws idempotently and acknowledges due cards; `Run.cards` per request; `card.seen` logged. A heartbeat (H-06) rides on it | O-01, O-02, O-05, O-07, O-08, T-08, #14, H-06 | M (4–5 days) | medium: touches the presenter; covered by layer B | the `session.py` split (a new `resync.py`); run records (the snapshot is a view of them) |
| **S2** | **One intake pipeline.** `intake(input, source, context)` with declared steps in one order: presence (paused?) → empty or unsure (dialogue-aware) → pending question (one matcher for run and lane questions; clicks never through typed text) → approval policy (one function with the source table: name hands-free, typing never, the reversible-change exception) → carry-over (separate slots) → mid-run grammar → duplicate → dispatch. Each entry point only builds the input | D-01 to D-08, T-06, T-07, D-09 (with the one-slot queue), the five approval copies | L (6–8 days) | high: the core of the dialogue; needs layer C first | the `session.py` split ("follow-ups" and "local lanes" modules); `routing/dispatch.py` (R-09) |
| **S3** | **A `Window` per question.** It owns one deadline, starts when its question comes to the screen, counts from the end of Swift's speech, defers to speech in progress (`started_at` before the deadline, re-arm while speaking, cap +6 s), and is restarted by one `reprompt()` used by every re-ask and hint. Its deadline goes to the overlay (S1). The reply window and park timer are derived from it. Needs a clock seam (inject `now` and `call_later`) | T-01 to T-05, T-11 | M (4 days) | medium; covered by layer C | the split; the clock seam serves layer C |
| **S4** | **Lane capabilities and liveness.** Each lane declares `needs` ({network, claude_cli, google, voice, mic}); one `Capabilities` snapshot (online via NLM, CLI signed in, Google signed in, SAPI alive) checked before the first lane that needs it; slots only for the agent route; a run stall watchdog (reset per SDK message, paused while a card or question waits); `api_retry` counted as offline evidence; per-tool-call deadlines; sign-in offers throttled on the last offer; SAPI failure clears `speaking` | R-01 to R-06, R-11, V-01, X-10, X-12 | M (4–5 days) | low–medium | the `WorkerTask` contract (budget, deadline, needs) |
| **S5** | **A listening state while Swift speaks.** First the cheap part: the answer window opens when a question is shown; `wants_short` while an answer is awaited; the echo filter uses the words Swift is saying *now* (SAPI word events). Then try the Windows communications capture path (built-in AEC) behind a setting, or duck Swift's voice when speech energy doesn't match it | V-02, #7, #8; enables "yes" queued for after speech | S (cheap part) + M (AEC trial, real PC) | AEC: medium (it can change mic processing; decision 5) | — |
| **S6** | **Contracts as tests.** Allow-list logging for the interaction line and reason codes in the gateway (X-03, X-04, X-05); protocol fixtures (layer A); the no-truncation scan (layer E) with the rule "the overlay owns readability; the backend never cuts what the owner reads or approves" | X-03 to X-05, O-04, O-06, O-11, X-17 (with the card artifact) | S–M (4 days for all) | low | run records (the allow-list becomes the record schema) |
| **S7** | **Speech adapted by context** (§7.4) | W-01 to W-07, V-04, part of the fragments and corrections | S (step 1), M (step 2), S–M (step 3) | low (step 1); medium (step 2, needs the gate) | — |

### Point fixes, in order

| # | Fix | Size | Risk |
|---|---|---|---|
| 1 | T-07: drop held utterances on lock; refuse approve while held (do this even before S2: Critical) | S (hours) | low |
| 2 | X-01: narrow a single contact match by the whole name | S | low |
| 3 | O-04: the email body scrolls; the expander by measured overflow | S | low |
| 4 | O-03: retry pane opens; Change always opens; a capability probe; and one-gesture typing (decision 4) | S | low |
| 5 | D-03, D-04: "back on" grammar; separate carry slots; a disruptive switch kept until undone | S | low |
| 6 | D-06, D-10, D-11, T-05: empty-text guard; logging fixes; the reply window from the end of speech | S | low |
| 7 | X-08: shield an approved send (decision 3) | S | low |
| 8 | X-17: whole Edit/Write text on the card | S | low |
| 9 | X-06, X-07: Swift's name in owner-facing texts; `%LOCALAPPDATA%\Swift` never read | S | low |
| 10 | R-07: retarget or retire the light lane (decision 2); R-08 metrics | S–M | low |
| 11 | O-09, O-12, O-13, O-14, T-09, T-10, T-12, X-09, X-11, X-14, R-10 | S each | low |

**Suggested order:**
1. **This week:** S0, point fix 1, then layers A and C (with the clock seam).
2. **Then:** S1, S3, S4.
3. **Then:** S2 on that footing, with S6 alongside.
4. **Speech:** S7 step 1 can go at any time; S5's cheap part comes with S3.

The groundwork (`session.py` split, run records, `WorkerTask`) should be done *as* S1–S4, not before them. Each of those modules is a piece of the split.

Each fix ships with its reproduction test turned from `xfail` to a plain test, and with the owner check named in §3. The new owner checks are 139 onward, to be written into `docs/testing/owner-checks.md` with report lines when the fixes land.

---

## 9. Decisions for the owner

Only what I can't settle myself. One line each, with a recommendation.

| # | Decision | Recommendation |
|---|---|---|
| 1 | End a run by itself after 90 s with no progress (not counting card or question waits), and keep it in the stack? | Yes |
| 2 | The light lane has answered nothing in 463 requests: retarget it at thread questions, "try again" and small talk, or turn it off and drop its warm CLI? | Retarget, and turn it off until then |
| 3 | When you stop during "Sending…" an email you approved, should Swift let the send finish and tell you, or try to stop it and say it may have gone? | Let it finish and tell you |
| 4 | One gesture to open the text box: click the capsule, or double-tap the push-to-talk key? | Click the capsule (keep the hotkey) |
| 5 | Try Windows' communications microphone path (its echo cancellation) behind a setting, accepting it may change how the mic sounds? | Yes, as a trial |
| 6 | Answers with "Read more" stay on screen until dismissed, or go to the stack as unread? | Stay until dismissed |
| 7 | A weekly labelling card for misheard clips, where typing the right words is allowed (it labels, never approves)? | Yes |
| 8 | Daily use runs the Vite dev server, so every merge reloads the overlay. Keep that after S1, or use a built app for daily use? | Keep it; S1 makes reloads harmless |
| 9 | The lane yes/no window: 25 s from the end of Swift's speech, and ADR-016 §16.2 updated (it says 45 s)? | 25 s from the end of speech |

**Tests on this branch.** Every reproduction is committed as `pytest.mark.xfail(strict=True, reason="seams audit <ID>…")` (Python) or `{ todo }` (overlay), so the suites stay green. A strict xfail turns red the moment its finding is fixed, so the marker comes off with the fix:

| File | Tests | Expected failures |
|---|---|---|
| `tests/unit/test_seams_audit_speech.py` | 15 | 15 |
| `test_seams_audit_state.py` | 9 | 9 |
| `test_seams_audit_routing.py` | 7 | 5 |
| `test_seams_audit_ipc.py` | 2 | 2 |
| `test_seams_audit_stt.py` | 4 | 4 |
| `test_seams_audit_privacy.py` | 10 | 5 |
| `overlay/tests/seams-audit.test.ts` | 2 | 2 (todo) |

The rest are controls that pass.

---

## 10. Coverage

### Read

| What | Depth |
|---|---|
| Rules and context: `CLAUDE.md`, `docs/handoff/README.md`, the October audit (all six files), ADR-007, ADR-013 to 017, ADR-016 §15–16, `phase-c-status.md`, `owner-checks.md`, `report.py`, product-direction §9 | read |
| Dialogue: `session.py` entry, dialogue, question, card, timer and dispatch paths; `dialogue.py`, `attention.py`, `stack.py`, `parked.py`, `presence.py`, `lifecycle.py` | traced line by line in those paths; `session.py` not read whole |
| Speech: `speech.py`, `wake.py`, `endpoint.py`, `stt/*` (transcriber, fixes, improve, recordings), `audio/recorder.py` | traced |
| Routing: `routing/*`, `system/intents.py`, `system/lane.py`, `system/scheduler.py`, `network.py`, `signin.py`, `failures.py` | traced |
| Executors and gateway: `executors/claude_code.py`, `quick.py`, `claude_mapping.py`, `web_scope.py`, `read_scope.py`, `signin.py`, `improve.py`; `security/gateway.py`; `workflows/tools.py`, `names.py`, `calendar.py`; `connectors/google.py`, `gmail.py` | traced |
| Logging: `logging_setup.py`, `backend/__main__.py` | read in full |
| IPC: `ipc/protocol.py`, `ipc/server.py`, `overlay/src/protocol.ts`, `ipc.ts` | read in full |
| Overlay TS: `main.ts` (message handling, cards, typing, panes), `presenter.ts`, `ask.ts`, `panes.ts`, `pane.ts`, `answer.ts`, `live.ts`, `styles.css` (every clip) | traced |
| Rust: `lib.rs` (panes, hotkeys, tray), `panes.rs`, `placement.rs`, `win.rs` | traced |
| Recent commits: `cd7eec8`, `d651996`, `0bf901d`, `cd3f97b`, `ab09f51` | read |
| Owner data, read-only through `//localhost`: `swift.log` (7,140 lines, 2026-10-23 to 11-04 19:15); `interactions.jsonl` (463 rows, counts only; a few words quoted where a finding needed them); `journal.jsonl` (48 actions: 46 DONE, 2 FAILED); `word_fixes.json`; the saved audio index and clips | read |

### Ran

| What | Result |
|---|---|
| Python tests (baseline at `ab09f51`) | 1344 passed (193 s) |
| Routing parity | 397/407 (97.5%), 0 harmful; the 10 misses are the web lane |
| `tsc --noEmit` | clean |
| Overlay `npm test` | 79 passed (81 with the 2 new todo tests) |
| Rust `cargo test` | 30 passed, in the worktree's own `target` |
| Audit tests | 47 Python: 40 strict xfail, 7 pass; 2 overlay todo |
| `report.py --since 16:00` (11-04) and `spikes/usage/report.py` | on the owner's real logs |
| Re-scoring agent-routed requests through today's router | counts only |
| The speech model offline over 77 labelled clips | WER table, §7.3 |
| Whisper base.en with hotwords on the 11-04 failure clips | on disk, nothing downloaded |
| Dev harness | vite on 1431 + `backend-harness` on 8765 (debug, echo executor): reload with a card open; a 1,885-character draft; a 6,443-character answer; 720×560 and 720×480; a skip and open from the stack; the clipping scan over the design states |
| Idle sampling | the debug backend, 35 minutes, 60 s samples |

The temporary `.claude/launch.json` entry and the `overlay/node_modules` junction were removed afterwards.

### Reproduced

- In tests: every finding marked "confirmed (test)" above.
- In the harness: O-01, O-04, O-13, O-14, and the card scroll from `ab09f51` (verified as working).

### Couldn't check, and why

- **Anything on the real mic, speakers, screen, Google account or apps:** the ground rules. That covers V-02's echo, O-03's focus and O-09's mixed DPI. Each has an owner check.
- **A real Claude Code run:** it costs money and acts for real. R-04 and R-06 rest on the owner's log plus fakes.
- **An idle backend with the real executor and its two warm CLIs:** the owner's Swift was in use. Repeat it on the PC.
- **The OI-02 restart in the harness:** skipped to keep the sampled backend running. It rests on code plus the harness log of reconnects without `ready`.
- **D-07 (a lane click rejecting another card):** depends on overlay timing; not reproduced.
- **R-02 (`online()` with a virtual adapter):** no offline row exists in the owner's log yet.
- **150% scaling:** checked as a CSS viewport (720×480), not with real DPI scaling.

**Working notes.** The full notes, with every line reference and probe, are in the session group's notes folder (`side-session-notes\…\seams-audit\`, outside the repo): `speech-dialogue.md`, `state-verification.md`, `overlay-ipc.md`, `routing-fallback.md`, `executors-privacy.md` and `speech-adaptation.md`.
