# Decisions log: every owner decision, by date, and where it's written

Swift's decisions are written in several places: the ADRs, the handoff's §5, the workstreams' decision sections, and
the studies the owner answered. This page is the **index**: one line per decision, newest first, pointing at the place
that holds the full text and reasoning. It doesn't restate them, so the source wins if they ever differ. Add a line
here whenever a decision is recorded somewhere else. Decisions still **open** are listed in the handoff
([`../handoff/README.md`](../handoff/README.md) §5), not here.

Built and verified are separate claims: a decision here may not be built yet, and a built one may not have passed its
owner check. The product rules in force are in [`CLAUDE.md`](../../CLAUDE.md) and
[`../product/action-authority.md`](../product/action-authority.md).

| Date | Decision | Where it's written |
|---|---|---|
| 2026-11-17 | Word fixes removed (rigid, context-free rewrites); closes W-01, W-02 | handoff §4 f, `findings.yaml` |
| 2026-11-15 | The 14 foundation decisions: one approval model (levels 0–3), typed words never approve, gestures, addresses asked about, recipients from the owner's words, Recycle Bin vs permanent delete, reason codes in `swift.log`, paying by gesture only, `intake.approves` the one decider, provisional check ids, `git bundle` between PCs | [`foundation-rules-review.md`](../explorations/foundation-rules-review.md) §7, [`action-authority.md`](../product/action-authority.md) |
| 2026-11-15 | `CLAUDE.md` slimmed, detail split into product, engineering, testing, security and architecture documents | [`claude-md-split.md`](../archive/adopted-proposals/claude-md-split.md) (archived) |
| 2026-11-15 | The correction offer is level 1 (a plain spoken "yes" while on screen) | [`workstreams.md`](../handoff/workstreams.md), decisions of 2026-11-14 (last items) |
| 2026-11-15 | An approved terminal card types the command and presses Enter; one line only; VS Code keeps its card and never gets Enter | [`workstreams.md`](../handoff/workstreams.md), decisions of 2026-11-14; check 397 |
| 2026-11-15 | VS Code writes keep the terminal's card until the UIA probe tells editor from terminal (OCT-01) | [`workstreams.md`](../handoff/workstreams.md); check 399 |
| 2026-11-15 | B4's open decisions: `show_result`, reuse of installed tools, outside tools as data or PNG, "Worker's pick", one shape at a time, shapes only on Done | [`b4-adaptive-results.md`](../design/b4-adaptive-results.md) §7 |
| 2026-11-15 | Cross-platform readiness saved for later, not studied (decision 29) | [`cross-platform-readiness.md`](../explorations/cross-platform-readiness.md) |
| 2026-11-14 | Modes study's seven decisions: learned trust (Wi-Fi off, Bluetooth off, airplane on), "ask me about everything", read-folder offers, plan card | [`modes-study.md`](../explorations/modes-study.md) |
| 2026-11-14 | B1 approval card wording; review item 9 carries on; B4 vetted tool set; Halo Step B go; B6 live view as a monitor window; memory store as plain files; B2 step grant; A10 move out from under higher-band windows; A7 the same request said again is the yes; C3 earlier addresses (later replaced by foundation decision 4) | [`workstreams.md`](../handoff/workstreams.md), "The owner's decisions of 2026-11-14" |
| 2026-11-13 | Three workstreams (orchestration and state, adaptive UI, agent autonomy) | [`workstreams.md`](../handoff/workstreams.md) |
| 2026-11-13 | A5 card lifetimes, B2 one grant per step, B4 results shaped to fit, B5 cards grow and expand, B6 study first, B7 slower transitions | [`workstreams.md`](../handoff/workstreams.md), "The owner's design decisions (2026-11-13)" |
| 2026-11-12 | The plan for the coming weeks | [`roadmap.md`](../handoff/roadmap.md) |
| 2026-11-11 | A second way in for "Hey Swift": an acoustic detector checked by Parakeet, behind `wake.acoustic` | [ADR-021](ADR-021-a-second-way-in-for-the-wake-phrase.md) |
| 2026-11-10 | One record per conversation; step 1 prototyped and dropped (added more than it removed) | [ADR-020](ADR-020-one-record-per-conversation.md) §6 |
| 2026-11-10 | A stop during "Sending…": an approved email waits 5 s, a stop keeps it (X-08) | handoff §5 "Answered" |
| 2026-11-07 | Halo is the design direction; deleting a file always asks | [ADR-019](ADR-019-halo-design-system.md) §7 |
| 2026-11-07 | The Deck's Step 1 built before the short checks; a request said beside a working card stays behind it | [ADR-018](ADR-018-the-deck.md) §4.1 |
| 2026-11-07 | "Say yes and I'll send a correction" follows the question rule | handoff §5 "Answered" |
| 2026-11-06 | The Deck: how requests share the screen | [ADR-018](ADR-018-the-deck.md) |
| 2026-11-06 | A recipient's domain stays out of `swift.log`, kept in the journal (X-19) | handoff §5 "Answered" |
| 2026-11-06 | The order of work after the seams audit and reliability review; seams decisions 1 (90 s no-progress end) and 9 (25 s lane window) | handoff §4, [`2026-11-seams-audit.md`](../audit/2026-11-seams-audit.md) §9 |
| 2026-11-05 | A plain "yes" counts only when the question is on screen | handoff §5 "Answered" |
| 2026-10-28 | Product direction adopted: Swift as the owner's own operator; parity only where daily use asks (decision 24) | [`product-direction.md`](../explorations/product-direction.md) |
| 2026-10-28 | The Capsule overlay | [ADR-017](ADR-017-capsule-overlay.md) |
| 2026-10-28 | Saved recordings kept 7 days, only if they serve a purpose (audit B-06) | handoff §5 "Answered", [`brief-recordings.md`](../archive/briefs/brief-recordings.md) (archived) |
| 2026-10-28 | ADR-016 Phases A–C approved; running defaults 10–15 (voice, when Swift speaks, power actions, music) | [ADR-016](ADR-016-assistant-parity.md) §11, handoff §5 "Running on a default" |
| 2026-10-28 | Running defaults 2–9 from the Capsule redesign (idle dot, countdowns, timer card, chime…) | handoff §5 "Running on a default", [`IMPLEMENTATION.md`](../design/swift-overlay/IMPLEMENTATION.md) |
| 2026-10-27 | Presence, idle time, interruptions, resuming | [ADR-014](ADR-014-presence-and-lifecycle.md) |
| 2026-10-27 | Overlay windows, card timing, the waiting stack, typing to Swift | [ADR-015](ADR-015-overlay-windows-and-card-timing.md) |
| 2026-10-26 | Attention, threads, requests side by side | [ADR-013](ADR-013-attention-threads-and-concurrent-requests.md) |
| 2026-10-26 | Workflow ecosystem questions (§12, §13.4), desktop interaction questions (§11) | [ADR-011](ADR-011-workflow-ecosystem.md), [ADR-012](ADR-012-desktop-interaction.md) |
| 2026-10-26 | Status labels never name the provider; only a result's byline does | [`architecture.md`](../architecture.md), ADR-008 |
| 2026-10-24 | Workflows, the trust boundary, "show me" | [ADR-010](ADR-010-workflows-and-show-me.md) |
| 2026-10-24 | Overlay UX: readable failures, movable placement, visible status | [ADR-009](ADR-009-overlay-ux.md) |
| 2026-10-23 | Swift's identity and the provider abstraction | [ADR-008](ADR-008-swift-identity-and-providers.md) |
| 2026-10-23 | A routing layer in front of Claude Code; Hermes spike later | [ADR-007](ADR-007-routing-layer.md) §9 |
| 2026-10-22 | The voice-overlay MVP replaces the v2.0 spec | [ADR-006](ADR-006-voice-overlay-mvp.md) |
| 2026-10-15 | Connector-ready integrations | [ADR-005](ADR-005-connector-ready-integrations.md) |
| 2026-10-15 | Phase 0 plan approved, personal use only | [ADR-000](ADR-000-phase0-plan-approval.md) |

B-01 reads (allowed without a card in the working folders, Documents and Downloads) and confirming a reversible change
(a Yes/No card) are in handoff §5 "Answered" without a date; both are now part of the approval levels in `CLAUDE.md`.
