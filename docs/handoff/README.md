# Swift: handoff (2026-10-28)

Read this first when picking Swift up in a new Claude Code session or account. It holds everything still open: what's built, what's running, what the owner must run and decide, and in what order. The project's working rules are in [`CLAUDE.md`](../../CLAUDE.md).

## 1. Where things stand

**Local `main`** (not pushed anywhere) is at `50f8e0f` or later, and has all of this merged:

| Area | What | Where it's described |
|---|---|---|
| Lanes | Fast local answers, the system lane (timers, volume, display, radios, windows…), the light model lane, workflows, the agent | ADR-007 §10, ADR-016 §13–14 |
| Speech | Local speech-to-text (parakeet), wake listening, the room-relative noise gate, Swift speaks (Windows voices) | `docs/stt-*.md`, ADR-016 §15 |
| Actions | Gateway with confirm cards and undo; calendar (look, change, cancel, Meet links); Gmail drafts written as the owner; Google Contacts | ADR-010, ADR-011 |
| Attention | Up to 3 requests at once, presence, held cards, the waiting stack, typing to Swift | ADR-013, ADR-014, ADR-015 |
| Overlay | **Capsule redesign** (dark and light, tray panel, pause listening, speaking state) | ADR-017, `docs/design/swift-overlay/` |
| Live view | Watching research or Word writing while it runs | ADR-017 §7 |
| Audit | 13 fixes from the October audit; the full report | `docs/audit/2026-10-audit.md` |
| Hardening | B-02 (writes only when asked), B-03 (due items kept until shown), B-04 (Restart Swift) | audit doc §4–5 |

Tests on `main` at `50f8e0f`: 1131 Python, 73 overlay, 29 Rust, plus `tsc`. Routing parity: 365/375, 0 harmful.

## 2. Work that was running when the credits ran out

Two sessions were mid-task. Their branches had **no commits yet** when this was written; they were asked to commit their progress as `WIP …` commits and write a status file in `docs/handoff/`.

| Task | Branch | Folder (worktree) | Brief to restart it |
|---|---|---|---|
| **ADR-016 Phase C: dialogue** | `claude/phase-c-dialogue-b22c15` | `.claude/worktrees/phase-c-dialogue-b22c15` | [`brief-phase-c.md`](brief-phase-c.md) |
| **Recordings that improve hearing** (7-day loop) | `claude/busy-wiles-de06e3` | `.claude/worktrees/busy-wiles-de06e3` | [`brief-recordings.md`](brief-recordings.md) |

**To pick one up:**
1. Look at what it left:
   ```bash
   git -C .claude/worktrees/phase-c-dialogue-b22c15 status --short
   git log --oneline main..refs/heads/claude/phase-c-dialogue-b22c15
   ```
2. If there are uncommitted changes, commit them on that branch as `WIP …`. Never discard them.
3. Read `docs/handoff/phase-c-status.md` (or `recordings-status.md`) on that branch, if it exists.
4. Start a new session **in that worktree folder**, give it the brief file, and tell it to continue from the WIP state.

If a branch has nothing (no commits, no changes), start the brief from scratch on a new branch cut from `main`.

## 3. What the owner runs next (in order)

The owner tests on the real PC with [`docs/testing/owner-checks.md`](../testing/owner-checks.md), then pastes the report.

1. Restart Swift: Tray → Quit Swift, then in `overlay`:
   ```bash
   npm run tauri dev
   ```
   The first start after Rust changes takes about a minute.
2. Note the time. Run these checks; **none has been run on the real PC yet**:
   - **50–62:** audit fixes. Skip 60 unless "it may have been added / sent" shows.
   - **63–75:** Capsule redesign. 68 includes a 10-minute wait away from the mouse.
   - **76–80:** hardening (Notepad, timers with a card open, Restart Swift, Task Manager).
   - **90–96:** live view.
   - **ADR-016 A2** (not in the checks file):
     - "turn off Bluetooth" → yes → "undo that";
     - "turn on airplane mode" → no;
     - "turn on do not disturb";
     - "turn the volume down and write a haiku about tea".
   - When those branches are merged: **100+** (Phase C) and **110+** (recordings).
3. Paste the report:
   ```bash
   uv run python spikes/owner_checks/report.py --since HH:MM
   ```
   The next session diagnoses it against `%LOCALAPPDATA%\Swift\logs\swift.log` and fixes what failed.

## 4. The agreed order of work

1. Owner checks 50–96, then fixes for what fails.
2. **ADR-016 Phase C** (dialogue), in progress, and **the recordings loop**, in progress (§2).
3. **ADR-014 L3:** quiet modes and call detection. Small; it must come before Swift speaks up unprompted.
4. **The web lane** (ADR-016 Phase I, cheap part): fast weather, news and "is it open now". These are the 10 parity misses, 10–17 s on the agent today.
5. **ADR-011 W2 + W3:** file tools with permissions, and recipes (fixed-step workflows; faster, cheaper email and calendar).
6. **Proactive Swift:** ADR-016 D together with ADR-011 watchers and digests. Swift's clock (ADR-016 A) is the scheduler. Needs owner decision 22.
7. **ADR-012 D3:** Word, Explorer, and Chrome/Gmail adapters. Then ADR-016 F (screen awareness).
8. **Later, only with the owner's OK:**
   - ADR-012 D4/D5 (decision 26);
   - ADR-010 B/C, other providers (decision 27);
   - ADR-016 G, offline (decision 19);
   - ADR-016 H, voice ID and phone (decisions 20, 21).

Small leftovers, to slot in anywhere:
- timers that pause and resume, a stopwatch, repeating reminders (ADR-016 §14.4);
- audit B-05 (the first request after start is 8–25 s slower);
- the redesign's timer card details (decision 5).

## 5. Decisions waiting on the owner

**Answered:**
- Saved recordings: keep **7 days**, and only if they serve a purpose. That's the recordings loop task.
- B-01 reads: allowed without a card in the working folders, Documents and Downloads.

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
| 10 | Voice: Windows voices or Piper? | Windows voices; Piper after a listening test |
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
| 22 | Which proactive nudges first (meeting soon, reminders, low battery, morning brief) | Step 6 |
| 23 | Personal index of mail, calendar and folders (local); which first | ADR-016 §6.1 |
| 24 | Parity target: everyday feel, with calls, SMS, camera and wallet out until a phone companion | Planning |
| 25 | A plain privacy statement in settings (AI work in Claude's cloud; speech, system lane and index local) | Settings work |
| 26 | Screenshots to a cloud model as a fallback (ADR-012 D5) | Step 8 |
| 27 | Other AI providers (Codex, Hermes) | Step 8 |
| 28 | Learning by watching PC use (ADR-011 L3), a strong privacy decision | Never without a yes |

## 6. Leftover branches and folders

Every `claude/*` branch listed by `git worktree list` other than the two in §2 is already merged into `main`. Their worktrees under `.claude/worktrees/` can be removed after the owner agrees:

```bash
git worktree remove <path>
```

One file is untracked in the owner's checkout and is kept on purpose: `C:\Users\frchi\Documents\Swift-design-screens` (outside the repo) holds the screenshots used for the redesign brief.
