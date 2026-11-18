# QA part 3: end-to-end proof of `main` at `e18af1b` (2026-11-14)

Branch `claude/qa-e2e-proof-a6650f`. Nothing in `src/` or `overlay/src` was changed. Speech gate not run: nothing under
`src/swift/stt` changed since its last run.

## Result in one minute

- **Every suite is green**, with no flakes beside 8 CPU burners (see Suites).
- **Every core flow passed in the dev harness**, except two the harness can't run: C3's web addresses, because the
  harness agent is the echo executor, and placement, because the harness has no Task Manager. Unit tests cover both.
  Screenshots of each flow in dark and light are in `qa-e2e-screens/`.
- **Two findings and one lead** go to the orchestrator, with steps to reproduce below:
  1. **The harness deletes the owner's recordings.** The debug backend, started from `overlay/dev/harness-config.yaml`,
     swept the owner's real recordings folder: 10 clips older than 7 days were deleted.
  2. **A typed "Swift, yes" answers "Turn off Wi-Fi?".** `intake.approves` allows this on purpose, but CLAUDE.md says
     "typing never approves". The owner needs to decide which is right (check 387).
  3. **Lead, not proven on real frames:** the overlay draws an agent's question only if the stage is "working" when the
     question arrives.
- Owner checks **380–389** are added for what only the real PC can show, with report lines and ledger entries;
  `plan.py --write` has been run.

## Suites

| Suite | Result |
|---|---|
| Python, alone | 2161 passed, 1 skipped, 34 xfailed in 198 s |
| Python, beside 8 burners (`python -c "while True: pass"`), run 1 | 2161 passed, 1 skipped, 34 xfailed in 391 s |
| Python, beside 8 burners, run 2 | 2161 passed, 1 skipped, 34 xfailed in 320 s |
| Known timing-sensitive tests, 25 runs each beside 8 burners | `test_parked.py::test_finish_the_named_task` 25/25 passed; `test_seam_replay.py::test_a_card_counts_down_on_the_backend_s_clock_seen_away_and_back` 25/25 passed. Failure rate 0/50 (both flaked in earlier sessions) |
| Routing parity (`eval/parity/score.py`) | 413/423 (97.6%), harmful 0; the 10 misses are the web lane, as before |
| Overlay `tsc --noEmit` | clean |
| Overlay `npm test` | 134 tests: 132 pass, 0 fail, 2 todo (O-03, counted at two levels) |
| Rust `cargo test` (short target `C:/t/qae2e`) | 38 passed, 0 failed (19 of them `placement::tests`) |

Python was run with `PYTHONPATH=src` and the main checkout's `.venv` interpreter, because `uv run` hangs in a worktree on
this PC. The burners were stopped by process ID after each run.

## Core flows (dev harness)

Setup: vite on **1450** and the debug backend on **8789**. 1431, 8765, 8781 and 8795 all refused to bind here
(WinError 10013), and 1420 was never touched. The backend ran from a copy of `harness-config.yaml` with every log and
recording directory moved to the session's scratchpad (finding 1). The page was driven by headless Chrome over CDP
(`qa-e2e-screens/e2e.mjs`). Each step is logged with the frames that came and the card's text (`e2e-log*.json`). Each
screenshot is clipped to the card and capsule, dark then light, and `X` below means `X-dark.png` and `X-light.png`.

How each flow was driven. **Backend** means the real backend's frames: `debug.ask` (hotkey speech), `debug.say` (speech
on a card), `text` (typing), `debug.run` (mock runs with the fake mail connector), and real mouse clicks.
**Injected** means a frame built from Swift's own code (`qa-e2e-screens/frames.py`: `outcome_for` / `split_answer`,
`confirm_card`, `command_purpose`, and the real `ClaudeCodeExecutor` for B2 and the delete). Those cards come only from
the agent, and the harness agent is the echo executor.

| # | Flow | How | Result | Screenshot |
|---|---|---|---|---|
| 1a | Quick answer "what time is it" | backend | PASS: "It's 23:45." from the local lane | `1a-quick-answer` |
| 1b | Long research answer (check 305/340) | injected (`outcome_for`) | PASS. Collapsed: the opening's first sentence, no "…". Read more: opens and stays, the opening appears once, no "…" anywhere. The mouse wheel reaches `THE-END-MARKER` (scroll 626/626). Read more doesn't scroll by itself (scroll stays at 0), which matches check 340, where the owner scrolls. | `1b-long-collapsed`, `1b-long-read-more`, `1b-long-read-to-end` |
| 2a | "Turn off Wi-Fi?" then "yes" | backend (fake radio) | PASS: "Wi-Fi off."; "turn on Wi-Fi" turned it back on | `2a-wifi-question`, `2a-wifi-yes` |
| 2b | … then "no" | backend | PASS: "Okay, I've left it as it is." | `2b-wifi-no` |
| 2c | … then the request said again (A+B) | backend | PASS: "Wi-Fi off." | `2c-wifi-said-again` |
| 2d | … then typed `yes` | backend | PASS: not done; the card says "Typing can't turn it off: click Yes, or say yes." | `2d-wifi-typed-yes` |
| 2e | … then typed `turn off Wi-Fi` | backend | PASS: not done ("Sorry, was that a yes or a no?") | `2e-wifi-typed-again` |
| 2f | … then typed `Swift, yes` | backend | **Done: "Wi-Fi off."** (finding 2) | `2f-wifi-typed-named` |
| 2g | … then typed `Swift, turn off Wi-Fi` | backend | not done ("Sorry, was that a yes or a no?") | `2g-wifi-typed-named` |
| 3a | B1 command card | injected | PASS: the agent's sentence ("What it says this does") comes first (text offset 69), then "What will run, first line: `gh repo create notes --private`" (offset 179), and the rest is folded ("2 more lines") | `3a-b1-command` |
| 3b | B2 step card | injected (real executor) | PASS: lists `git init`, `git add notes.md`, `git commit -m "First notes"`. The executor left `rm old-notes.md` off the step ("including 1 of the ones you listed") | `3b-b2-step` |
| 3c | A delete on its own card | injected (real executor) | PASS: `rm old-notes.md`, asked on its own card (`step: false`), after the step was approved | `3c-delete-own-card` |
| 3d | The backend's approval card (mock edit) | backend | Shown. A "yes" said with the hotkey approved it, as designed (`intake.approves`: voice through the hotkey may approve a card) | `3d-backend-confirm` |
| 4a | Email draft to a contact (fake Gmail) | backend | PASS: To "Dr Ada Lovelace &lt;ada.lovelace@example.edu&gt;", the demo contact. "approve" said with the hotkey started the 5-second send window (fake connector) | `4a-email-draft`, `4a-after-bare-approve` |
| 4b | "Which Sam?" with two matches | injected (with the run's `runs` row, as the backend sends it) | PASS: both full names as options, 20 s, Stop request | `4b-which-sam` |
| 5a | A timer coming due behind an approval card | backend | PASS: the card stays and the stack shows "1 thing needs you. Next: Your timer is up." After Reject, the timer's card shows once | `5a-timer-due-behind-card` |
| 5c–5f | Stack with a due timer: open, Skip, Done, End | backend, real clicks | PASS. Skip logs `stack action kind='due' action='skip'`. A due item's primary button is **Done** (`stack.ts:82`), which clears it, as designed. End: the stack empties and the timer doesn't come back after the card. | `5c-stack-open`, `5d-stack-park`, `5e-stack-reopen`, `5e-after-card`, `5f-stack-end`, `5f-after-card-nothing-back` |
| 5g–5j | Stack with Swift's question: park, reopen, end | backend, real clicks | PASS. "What time is it" said during "Turn off Wi-Fi?" parks the question. **Open** asks it again (new `ask` on the same thread). **End** empties the stack, and the question doesn't come back. | `5g-question-parked`, `5h-stack-open`, `5h-question-reopened`, `5j-question-ended` |
| 6 | Web address said; "open that site again"; "my university's website" without and with a memory | unit tests | PASS by unit tests: `tests/unit/test_recent_address.py`, 7/7 (pointing back, the 10-minute window, another conversation refused, a description asks without a memory, opens with a memory, never from the agent's answer or a tool result). Not run in the harness: the echo agent opens nothing, so report lines 255 and 330 FAIL there, as expected | none |
| 7 | The card moves out from under a higher-band window | Rust unit tests | PASS: `a_window_swift_cannot_come_in_front_of_moves_the_cards_to_the_nearest_uncovered_anchor`, `at_125_and_150_percent_the_cards_move_where_task_manager_covers_least`, `a_hotkey_while_still_covered_keeps_the_uncovered_anchor`, `nowhere_uncovered_stays_home`, `swift_goes_back_to_the_owners_spot_once_nothing_covers_it`, `the_owners_anchor_is_kept_when_nothing_covers_it`, `a_dropped_overlay_is_judged_where_it_was_dropped` | none |

**report.py against the harness run** (`--date 2026-11-14 --since 23:40`, with the harness's own interactions and log;
output in `qa-e2e-screens/report-harness.txt`). Every computed line passed except 255 and 330 ("that site again"), and
both of those are expected with the echo agent. Passed: 7, 8, 15, 16, 21, 27, 54, 60, 71, 77-78, 104, 108, 110, 123,
130, 146, 149, 204, 215, 256, 270, 280, 303, and 330 ("my university's website"). Line 110 confirms finding 1:
"10 old … deleted".

**Check 123's rule on the harness log.** `swift.log` holds none of the words said: "what time is it", "Wi-Fi",
"turn off", "usiu", "university", "Sam", "lecturer", "Lovelace", "research the history", "timer for", "notes.md",
"that site", "Missing Thursday" and the answers ("left it as it is", "Wi-Fi off", "Your timer") all count 0. "Rejected"
appears only as `status='rejected'`. Report line 123 PASS (0 lines with words), and line 280 PASS (run records hold no
words). The journal holds the recipient's domain only, as designed.

## Findings

### 1. The dev harness sweeps the owner's real recordings (medium; harness config, not product code)

`overlay/dev/harness-config.yaml` moves the logs to `%TEMP%` but not `stt.audio_dir` or `stt.test_set_dir`, which
default to `%LOCALAPPDATA%/Swift/audio` and `…/stt_testset`. The debug backend's start-up sweep and its weekly
improvement pass (`audio.improve_weekly`) work on the owner's clips.

Steps: start the `backend-harness` entry from `.claude/launch.json` and read its first lines. Mine at 23:43:00 said
`recordings swept | keep_days=7 deleted_old=10 deleted_unflagged=0 kept=318 test_set=19`. That's the owner's folder;
the same backend with redirected directories said `kept=0 test_set=0`.

The 10 clips were past the owner's own 7-day limit. His Swift deletes such clips on its daily sweep (it deleted 15 at
15:13 the same day), so nothing was lost that his own Swift would have kept. Still, a harness run deleted owner data,
and every session's harness run does the same.

Fix (for QA 1): in `harness-config.yaml`, set `stt.audio_dir` and `stt.test_set_dir` under `%TEMP%/swift-harness` and
`audio.improve_weekly: false`. My copy did that, and its sweep then saw an empty folder.

### 2. A typed "Swift, yes" answers Swift's own reversible question (product rule: decision needed)

`intake.approves` (`src/swift/intake.py:56-80`) allows a typed yes **with Swift's name** for Swift's reversible
question ("typed | never | only with name"). CLAUDE.md says "typing never approves", and its one exception names only
a plain **spoken** yes or a click.

Steps: in the harness, `debug.ask "turn off Wi-Fi"`, then the overlay's `text` frame `Swift, yes`. The result is
"Wi-Fi off." from the fake radio (`2f-wifi-typed-named`, `e2e-log-f2_typed_named_f4_sam_f5_stack.json`). A plain
typed `yes` is refused (2d), and so is typed `Swift, turn off Wi-Fi` (2g).

Either the rule or the table is wrong; the owner decides. Check 387 asks him on the real PC. I didn't change anything.

### 3. Lead: a question the overlay keeps but never draws (low; injected frames only, unproven)

`onAskMessage` (`overlay/src/main.ts:1490-1493`) draws a question only if the stage is "working" when it arrives;
otherwise it only stores it.

With injected frames for a run the overlay has no `runs` row for (sent while "Swift is ready" was on the card, or with
no notice at all), the working state isn't drawn, so the question isn't either. When the notice goes, the card is
empty and the capsule says "Waiting for your answer" for the question's whole 20 s (`4p-ask-over-ready-8s`;
variants in `e2e-log-f4_variants.json`). No console errors.

With the real backend, Swift's own question asked while the same notice was up **was drawn**
(`4r-own-question-over-ready`), because the backend sends the run's row first. So this is a fragility, not a
reproduced failure. It may bear on the open "a question shown as Working on it" (checks 206, 211, 218; cause
unproven), where the question also wasn't drawn. Worth a seam scenario: an `ask` whose `state: working` the presenter
refused.

### By design, not failures

- A "yes" or "approve" said with the hotkey approves an approval card (3d, 4a). `intake.approves`: "voice (hotkey) |
  yes". Hands-free needs the name; the harness has no wake path, so check 385 covers that.
- On a due timer in the stack, the primary button is **Done** and it clears the item (`stack.ts:82`; session
  `_stack_action`: `due` + anything but skip clears it).
- The echo agent's answer shows the whole prompt it was given (Swift's workflow list, earlier context): harness only.

### Harness notes for the next session

- Two pages connected to one backend kick each other off in a reconnect loop every second or so, and each reconnect
  resets what's drawn. An orphaned headless Chrome caused that here. Keep one overlay per backend.
- State lives in the backend across reloads (parked questions, rows, the stack). `e2e.mjs`'s `clean()` ends every
  stack item before a flow.
- An injected run needs its `runs` row before its `state`, or the overlay draws nothing (lead 3).

## What only the owner's PC can show: checks 380–389

Gmail in Chrome (380), several real contacts (381), Task Manager over a waiting card (382), 150% scaling with Read
more and the stack (383), the wake word (384), hands-free approval needing the name (385), the Wi-Fi question
hands-free (386), typing to it (387, finding 2), the stack with real pane windows (388), web addresses on `main` after
C3 (389). They're in `docs/testing/owner-checks.md` with report lines (`report.py` `_real_pc`) and ledger areas, plus a
focus entry. `plan.py --write` was run, so the next free number is now 390.

## Re-running

```bash
PYTHONPATH=src /c/Users/frchi/Documents/Swift/.venv/Scripts/python.exe docs/handoff/notes-2026-11-14/qa-e2e-screens/frames.py > frames.json
node docs/handoff/notes-2026-11-14/qa-e2e-screens/e2e.mjs <outDir> http://localhost:<vite> <backendPort> frames.json
```

`ONLY=f1_quick,f2_wifi,…` runs some flows. The backend must be the debug backend with redirected directories.
