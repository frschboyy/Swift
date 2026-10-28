# Swift: handoff (2026-10-28)

Read this first when picking Swift up in a new Claude Code session or account. It holds everything still open: what's built, what's running, what the owner must run and decide, and in what order. The project's working rules are in [`CLAUDE.md`](../../CLAUDE.md).

## 1. Where things stand

**Local `main`** (not pushed anywhere) has all of this merged:

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
| Recordings | Saved recordings that improve hearing (7-day loop, audit B-06) | `recordings-status.md` |
| Dialogue | **ADR-016 Phase C**: Swift asks for what's missing, the question card, carry-over, end of speech, confirm cards read aloud | ADR-016 §16, `phase-c-status.md` |

Tests on `main` after the Phase C merge: 1272 Python, 78 overlay, 29 Rust (unchanged by C), plus `tsc`. Routing parity: 397/407, 0 harmful (the 10 misses are the web lane, §4 step 4).

## 2. Work in progress

None. Both sessions that were running when the credits ran out are finished and merged (2026-10-28):
- **Recordings loop** (`claude/busy-wiles-de06e3`): owner checks 110–116.
- **ADR-016 Phase C, dialogue** (`claude/phase-c-dialogue-b22c15`): owner checks 100–108. Checked in the dev harness; not yet on the real PC.

Their branches and the safety snapshots `backup/phase-c-wip` and `backup/recordings-wip` were deleted after the merge (§6).

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
   - **100–108:** Phase C, dialogue. **110–116:** saved recordings (remove `save_audio: true` first).
3. Paste the report:
   ```bash
   uv run python spikes/owner_checks/report.py --since HH:MM
   ```
   The next session diagnoses it against `%LOCALAPPDATA%\Swift\logs\swift.log` and fixes what failed.
4. Once the checks pass, **use Swift for real, every day, for two weeks**: the requests you would make anyway, not test phrases. Once a week, paste the usage report (counts only, nothing you said):
   ```bash
   uv run python spikes/usage/report.py --since 2026-10-29
   ```
   Add `--exclude YYYY-MM-DD` for a day spent testing; the report flags days with over 100 requests. Its numbers decide what comes after step 3, so long testing sessions shouldn't be mixed in; note the dates of any.

## 4. The agreed order of work

Adopted 2026-10-28 from [`docs/explorations/product-direction.md`](../explorations/product-direction.md), which explains each choice. In short: Swift should be the owner's own operator (recurring work, the owner's rules, any agent behind it, learning with consent), not a match for Copilot or Siri feature by feature. ADR-016's parity phases that aren't listed here are deferred.

**Now**

1. **Owner checks 50–116**, then fixes for what fails (§3).
2. ~~**A usage report**~~: built (2026-10-28), `spikes/usage/report.py`. Counts only, per ISO week: days used, requests per day, where requests went (Swift, light model, agent, not heard), share done cleanly (no card change, mid-run change or Try again), agent p50/p90, escalations, cost, workflows. Then two weeks of daily use (§3 step 4). Targets are in product-direction §9.
   - From a Claude Code session, the sandbox shows an old copy of `%LOCALAPPDATA%\Swift`; pass `--interactions //localhost/c$/Users/frchi/AppData/Local/Swift/interactions.jsonl` to read the real log.
   - Baseline before daily use (all testing, 2026-10-23 to 28): 332 requests, 25% answered by Swift, 78% done cleanly, agent p50 12.3 s, $2.43.
3. **Groundwork**, while the owner uses Swift. No behaviour change the owner should notice:
   - split `session.py` (4,400 lines): run launching, follow-ups, workflows and the local lanes into their own modules;
   - **run records**: one append-only event log per run (steps, tool calls, approvals, artifacts, which worker and why), generalizing the action journal; the interaction log becomes a view of it;
   - **a settings and memory store** owned by Swift, separate from `config.yaml` (which still wins), every record with its source (said, approved, inferred), plus "remember", "forget" and "what do you know about me";
   - **a `WorkerTask` contract**: executors take the request, a context pack Swift builds, the grant, a budget and a privacy class; a contract test runs the same tasks on the mock and on Claude Code;
   - **ADR-014 L3:** quiet modes and call detection.

**Next**, in this order unless the usage report says otherwise:

4. Notifications at rest, and one "while you were away" card on return (held cards, stack, unfinished, watcher results), sized to the gap.
5. **Watchers v1:** the owner's top two of ADR-011 §13 (likely boss emails, with the `gmail.metadata` scope already decided in ADR-011 §13.4, and a tech-news digest), with memory of what was already seen. Needs decision 22.
6. **Recipes from runs** (ADR-011 W3, redesigned): "do that again every Friday", "make that a workflow", built from run records rather than hand-written YAML.
7. **The Swift window v1** (a second Tauri window, from the tray): Activity with "Why?", What Swift knows, Workflows and automations, What Swift may do, Look and read. Then settings changed by voice ("speak less"), writing the same store.
8. **ADR-011 W2:** file tools with folder permissions.

**Later, each only when its trigger appears**

- The cheap web lane (ADR-016 Phase I): when daily use or watchers show the agent's 10–17 s is in the way.
- A second worker (decision 27): when a task needs one, e.g. a cheap or local model for the light lane, or an API research agent for watchers.
- Suggestions from patterns (ADR-011 L1): after a month of real data.
- A Chrome extension for Gmail web (ADR-012 D3): if daily use shows it.

**Deferred** (not started without the owner's OK): screen awareness and the vision fallback (ADR-016 F, ADR-012 D4/D5, decision 26), offline (G, decision 19), voice ID and the phone companion (H, decisions 20, 21), smart home and messaging connectors (decisions 16, 17), Apple Calendar.

**Small leftovers, only on request:**
- timers that pause and resume, a stopwatch, repeating reminders (ADR-016 §14.4);
- the redesign's timer card details (decision 5).

Audit B-05 (the first request after start is 8–25 s slower) is worth fixing during the groundwork: it shows in daily use.

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
| 22 | Which two watchers or nudges first (boss emails, tech news, opportunities, meeting soon, morning brief) | Step 5 |
| 23 | Personal index of mail, calendar and folders (local); which first | ADR-016 §6.1 |
| 24 | ~~Parity target~~: superseded by the product direction (2026-10-28): parity only where daily use asks for it | Answered |
| 25 | A plain privacy statement in settings (AI work in Claude's cloud; speech, system lane and index local) | Step 7 |
| 26 | Screenshots to a cloud model as a fallback (ADR-012 D5) | Deferred |
| 27 | Other AI providers (Codex, Hermes), and which tasks they'd take | A second worker (Later) |
| 28 | Learning by watching PC use (ADR-011 L3), a strong privacy decision | Never without a yes |

## 6. Leftover branches and folders

Cleaned up on 2026-10-28 with the owner's OK: every merged `claude/*` branch, its worktree under `.claude/worktrees/`, and the two `backup/*` snapshots are deleted. `main` is the only worktree.

Two early branches are kept on purpose: `mvp/overlay` and `phase0/scaffold`. Both are merged into `main`.

A new session that finishes and merges its work removes its own worktree and branch once the owner agrees:

```bash
git worktree remove <path>
```

```bash
git branch -d <branch>
```

One folder outside the repo is kept on purpose: `C:\Users\frchi\Documents\Swift-design-screens` holds the screenshots used for the redesign brief.
