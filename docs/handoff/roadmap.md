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

- [ ] Restart Swift on today's `main` (Tray → Quit Swift, then `npm run tauri dev` in `overlay`), run the "Run these first" list in [`owner-checks.md`](../testing/owner-checks.md), and paste the report. <!-- report since 2026-11-12 -->
- [ ] Re-run what failed on 2026-11-05 and 2026-11-08, now that fixes landed. <!-- checks: 13, 191, 193-197 -->
- [ ] The safety fixes of 2026-11-10: stopping an approved email, names, Swift's own files. <!-- checks: 212-215 -->
- [ ] The fixes from your checks of 2026-11-09 (ADR-020 keeps them once these pass). <!-- checks: 201-211 -->
- [ ] The Deck: run these, then say whether to keep Step 1 (ADR-018 §4.1). <!-- checks: 168, 173, 179, 181 -->
- [ ] Requests in your own words, to show where Swift is rigid. <!-- checks: 233-239 -->
- [ ] Say whether to merge the branch with three fixes to follow-ups, calendar titles and workflow choice. <!-- branch: claude/harness-takeaways -->
- [ ] Say whether to merge the audit's fixes to reading rules, "open this" and contacts (owner checks 222–227). <!-- branch: claude/audit-fixes-google-calendar -->
- [ ] Say whether to merge the audit's recipient fixes ("Last, First" contacts, only the contact you picked). <!-- branch: claude/audit-fixes-recipients -->

## Next week, when you have 15 minutes each

- [ ] The second way in for "Hey Swift": set `wake.acoustic: true` in `config.yaml`, restart, and run these (ADR-021). <!-- checks: 228-232 -->
- [ ] The Halo look: start with `$env:VITE_SWIFT_LOOK = "halo"; npm run tauri dev`, and say what you think (ADR-019 §8). <!-- checks: 216-221 -->
- [ ] Listen to the two voices and choose one (decision 10): `uv run python spikes/tts/voice_test.py`.

## Weeks 1 to 3: use Swift for real, every day (handoff §4 d)

- [ ] Use Swift for the requests you'd make anyway, not test phrases. <!-- use: 14 since 2026-11-13 -->
- [ ] Once a week, paste the usage report: `uv run python spikes/usage/report.py --since 2026-11-13`.
- [ ] When something goes wrong, tell Claude the time and what you saw. It goes in as a failed check or a new one, and shows up in `ROADMAP.md`.

While you use it, Claude works on (handoff §4 f–h, nothing you need to run):

- [ ] Speech: the per-sentence check (W-03) before any more tuning, then safe word fixes (W-01, W-02).
- [ ] Prove the cause of wake misses after idle before another fix.
- [ ] Review item 9: one versioned screen snapshot, kept only if it removes more code than it adds.
- [ ] Review item 11: one table of lifetimes.

## After daily use: decide what comes next

- [ ] Decide on the light lane: retarget it or turn it off (seams decision 2, handoff §5).
- [ ] Go-ahead for Halo Step B, one card renderer (ADR-019).
- [ ] The interaction layer's nine decisions, before any ADR ([`interaction-layer.md`](../explorations/interaction-layer.md)).
- [ ] Choose the first two watchers (decision 22: boss emails, tech news, …).
- [ ] The rest of handoff §5, by the usage report's numbers.

## Then: groundwork, then the product steps (handoff §4)

- [ ] Groundwork, nothing you'd notice: split `session.py`, run records, a settings and memory store, the `WorkerTask` contract, quiet modes, B-05 (the slow first request).
- [ ] 4. Notifications at rest, and one "while you were away" card.
- [ ] 5. Watchers v1.
- [ ] 6. Recipes from runs ("do that again every Friday").
- [ ] 7. The Swift window v1.
- [ ] 8. File tools with folder permissions.

**The test for all of this** (product-direction §9): after six weeks of daily use, do you still reach for Copilot or a chat app for most things?
