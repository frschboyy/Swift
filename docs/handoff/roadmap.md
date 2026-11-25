# Swift: the plan for the next few weeks (from 2026-11-12)

This is the plan. **Open `ROADMAP.md` at the top of the Swift folder for the live version**: the same steps, each with
where it stands now, what to do next, and the problems found in Swift's logs and your checks. Refresh it with:

```bash
uv run python spikes/owner_checks/roadmap.py
```

Claude refreshes it whenever you paste a report or say something went wrong. It comes from the handoff
([`README.md`](README.md) §3–§5), the ADRs and the open branches. When the plan itself changes, a session edits this file.

How a step's status is worked out: `checks:` passes once each check passed on today's code; `use:` counts days of real
use (days with more than 100 requests count as testing); `branch:` is done once the branch is merged; `report since:` is done
once a report from that day on is recorded. A step with none of these is ticked by hand (`- [x]`).

## Week of 2026-11-12: a clean baseline on the real PC

- [ ] Restart Swift on today's `main` (Tray → Quit Swift, then `npm run tauri dev` in `overlay`), run the "Run these first" list in [`owner-checks-status.md`](../testing/owner-checks-status.md), and paste the report. <!-- report since 2026-11-12 -->
- [ ] Re-run what failed on 2026-11-05 and 2026-11-08, now that fixes landed. <!-- checks: 13, 191, 193-197 -->
- [ ] The safety fixes of 2026-11-10: stopping an approved email, names, Swift's own files. <!-- checks: 212-215 -->
- [ ] The fixes from your checks of 2026-11-09 (ADR-020 keeps them once these pass). <!-- checks: 201-211 -->
- [ ] The Deck: run these, then say whether to keep Step 1 (ADR-018 §4.1). <!-- checks: 168, 173, 179, 181 -->
- [ ] Requests in your own words, to show where Swift is rigid. <!-- checks: 233-239 -->
- [x] Say whether to merge the branch with three fixes to follow-ups, calendar titles and workflow choice. Merged (`8082af7`).
- [x] The audit's fixes to reading rules, "open this" and contacts (owner checks 222–227): every fix is on `main` or replaced by a stricter one; branch deleted 2026-11-15 (handoff §6).
- [x] The audit's recipient fixes ("Last, First" contacts, only the contact you picked): replaced by X-02's stricter fix; branch deleted 2026-11-15 (handoff §6).

## The three workstreams (from your run of 2026-11-13)

Every item, with what's known, is in [`workstreams.md`](workstreams.md). A line passes when its checks pass on today's code.

**A. Task orchestration and state: what runs, what it waits for, and whether the screen says so**

- [ ] A1. A misheard "turn off the Wi-Fi" gets Swift's own question (fixed; run it). <!-- checks: 201, 243 -->
- [ ] A2. A question is shown as a question, never "Working on it". <!-- checks: 206, 211, 218 -->
- [ ] A4. Cards you haven't seen don't run out; a question out of sight keeps its time. <!-- checks: 208, 219 -->
- [ ] A5. Each card's lifetime fits its request (decided: a command's card goes soon after it's done; an answer stays until seen; a question stays while it waits and pauses out of sight). <!-- checks: 210 -->
- [ ] A6. A card opened from the stack carries on where it was, or says it ended.
- [ ] A7. One ask is one request, however it's worded. <!-- checks: 197, 204, 205 -->
- [ ] A8. Swift checks a thing happened before it says so ("Playing.", "Wi-Fi off"). <!-- checks: 235, 239 -->
- [ ] A9. An email is written wherever the cursor was. <!-- checks: 49, 215 -->
- [ ] A10. "Hey Swift" brings Swift in front of an always-on-top window. <!-- checks: 203 -->
- [ ] A12. A spoken Reject is heard as fast as a click. <!-- checks: 195 -->
- [ ] Structure: review item 9, one versioned screen snapshot acknowledged when drawn (the fix under A2–A6).

**B. Adaptive UI and UX, extending Halo**

- [ ] B1. An approval card says in a plain sentence what it does and why; the command folds underneath. <!-- checks: 199 -->
- [ ] B2. Fewer approvals: one grant for a coherent step of a task (decided: one approval per step, its commands listed; anything irreversible keeps its own card; after the grant).
- [ ] B3. Working, waiting for you, waiting for an OK, doing and failed each look different (Halo B8; verified in grayscale in the harness). <!-- checks: 206, 218, 417 -->
- [ ] B4. Results laid out to fit them: tables, comparisons, diagrams, previews, charts, project cards (built; the worker's pick on charts). <!-- checks: 404-407, 433 -->
- [ ] B5. Cards grow when the content needs it, and expand by hand: built, then changed on 2026-11-24 to a scrolling card with Expand into a workspace and Minimize (ADR-019 §11). <!-- checks: 419, 464, 465 -->
- [ ] B6. The watch has its own look: a monitor with its steps and a console line (built; no "of 6 · about 1 min left"). Watch is offered only once a request has taken two steps. <!-- checks: 458 -->
- [ ] B7. Motion you can see: cards grow from the orb, fold, drain; the tail settles last (built). <!-- checks: 221, 420 -->
- [x] B8. Your pen.dev prompt that extends Halo: written (`docs/design/halo-system/b8-pen-prompt.md`), and the B8 build from it merged 2026-11-18.
- [ ] B9. The watch docked on the orb's edge, or mini in a corner; the Dock button cycles them (built). <!-- checks: 440 -->
- [ ] B10. The watch stays connected to its request: the card holds while it's open, one clock (built, partial: no tether). <!-- checks: 305 -->
- [ ] B11. Progress in the watch: its steps, "Step N" (built with B6). <!-- checks: 305 -->
- [ ] B12. "Open answer" leads back to the answer (blocked after a restart: needs the answer from the run record). <!-- checks: 305 -->
- [ ] B13. File lists shown as a tree, with Open, Show in folder and arrow keys (built). <!-- checks: 436 -->
- [ ] B14. A running timer on the orb and in the stack, "+5 min", "done" / "5 more" said (built). <!-- checks: 421, 432 -->

**C. Agent autonomy: working out how to reach a goal, inside the product rules**

- [ ] C1. Never answer with a fact Swift doesn't have (your location): it asks.
- [ ] C2. Booking (a ride, a flight): find the way, sign-in by you, confirm before paying.
- [ ] C3. Opening a website works.
- [ ] C4. Find a tool it lacks, say why, and ask before installing it.
- [ ] C5. Reminders, schedules and repeating automations. <!-- checks: 237, 239 -->
- [ ] C6. "Play some music" finds out how you play music.
- [ ] C7. "Remember that…" (the memory store).
- [ ] C9. "What's on my screen?" sees more than the front window (screen awareness, deferred). <!-- checks: 237 -->
- [ ] Decide on a credentials vault for C2 and C4 (sign-in is yours today).

## Next week, when you have 15 minutes each

- [ ] The second way in for "Hey Swift": set `wake.acoustic: true` in `config.yaml`, restart, and run these (ADR-021). <!-- checks: 228-232 -->
- [ ] The Halo look, now the only look: start Swift as usual and say what you think (ADR-019 §8, §10). <!-- checks: 216-221 -->
- [ ] Listen to the two voices and choose one (decision 10): `uv run python spikes/tts/voice_test.py`.

## Weeks 1 to 3: use Swift for real, every day (handoff §4 d)

- [ ] Use Swift for the requests you'd make anyway, not test phrases. <!-- use: 14 since 2026-11-13 -->
- [ ] Once a week, paste the usage report: `uv run python spikes/usage/report.py --since 2026-11-13`.
- [ ] When something goes wrong, tell Claude the time and what you saw. It goes in as a failed check or a new one, and shows up in `ROADMAP.md`.

While you use it, Claude works on (handoff §4 f–h, nothing you need to run):

- [x] Speech: the per-sentence check (W-03), merged 2026-11-13; any more tuning is scored on your saved clips. (Word fixes were removed on 2026-11-17.)
- [ ] Prove the cause of wake misses after idle before another fix.
- [ ] Context-aware speech ([`context-aware-speech.md`](../explorations/context-aware-speech.md)): step 1 is done; you said yes to the weekly labelling card (seams decision 7, 2026-11-18), so step 2, the monitor, can start; the card isn't built yet.
- [ ] Review item 9: one versioned screen snapshot, kept only if it removes more code than it adds.
- [ ] Review item 11: one table of lifetimes.

## After daily use: decide what comes next

- [x] Decide on the light lane: retarget it or turn it off (seams decision 2, handoff §5). Decided 2026-11-18: off until retargeted at thread questions, "try again" and small talk; no warm CLI while off.
- [x] Go-ahead for Halo Step B, one card renderer (ADR-019). Given and merged 2026-11-14; owner checks 305–306.
- [ ] The interaction layer's nine decisions, before any ADR ([`interaction-layer.md`](../explorations/interaction-layer.md)).
- [ ] Choose the first two watchers (decision 22: boss emails, tech news, …).
- [ ] The rest of handoff §5, by the usage report's numbers.

## Then: groundwork, then the product steps (handoff §4)

- [x] Groundwork, built: run records (`runs.py`), the memory store (`memory.py`), the `WorkerTask` contract and the step grant (2026-11-14).
- [ ] Groundwork, still open: split `session.py`, settings in Swift's own store (product-direction §6.1, §6.3), quiet modes, B-05 (the slow first request).
- [ ] 4. Notifications at rest, and one "while you were away" card.
- [ ] 5. Watchers v1.
- [ ] 6. Recipes from runs ("do that again every Friday").
- [ ] 7. The Swift window v1.
- [ ] 8. File tools with folder permissions.

**The test for all of this** (product-direction §9): after six weeks of daily use, do you still reach for Copilot or a chat app for most things?
