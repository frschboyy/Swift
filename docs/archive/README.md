# Archive: kept for history, not current

Nothing in this folder describes Swift as it is now or tells a session what to do. Each document was finished,
replaced or adopted, and is kept for its reasoning and as a record. Where it still matters, the current home is named.
Moved here on 2026-11-18 (docs consolidation, `docs/audit/2026-11-18-docs-audit.md`).

| Folder / file | What it was | Why it's here | Current home |
|---|---|---|---|
| `2026-10-mvp-plan/SWIFT_BUILD_PROMPT.md` | The v2.0 build spec (tkinter overlay, Ollama, cloud off) | Paused 2026-10-22, replaced by the voice-overlay MVP (ADR-006) | `CLAUDE.md`, ADR-006 onward |
| `2026-10-mvp-plan/PLAN.md` | The MVP plan, "awaiting owner approval" | Approved and built; its milestones are long past | `docs/handoff/README.md`, `docs/handoff/roadmap.md` |
| `2026-10-mvp-plan/backlog.md` | Phase-0 ideas: an MCP connector host, a connector UI, Slack, the Hermes spike | The Hermes spike ran (`docs/spikes/hermes-agent.md`); the rest is in the handoff's Deferred list | `docs/handoff/README.md` §4 |
| `briefs/brief-phase-c.md`, `briefs/phase-c-status.md` | Task and status for ADR-016 Phase C (dialogue) | Built and merged | ADR-016 §16 |
| `briefs/brief-recordings.md`, `briefs/recordings-status.md` | Task and status for the 7-day recordings loop (audit B-06) | Built and merged; word fixes it mentions were removed 2026-11-17 | `src/swift/stt/recordings.py`, `docs/security/privacy.md` |
| `briefs/brief-halo.md` | Task for Halo steps A and B | Both built and on `main` (2026-11-10, 2026-11-14) | ADR-019, `docs/design/halo-system/` |
| `2026-11-14-sessions/status-review-2026-11-14.md` | Every decision checked against the code at `a8f12ce` | A dated snapshot; the code has moved since | `docs/handoff/README.md` |
| `2026-11-14-sessions/notes/` | QA parts 1–3, the C3 review notes, verdicts on three old branches, harness screenshots | QA cleanup merged (phase 2 results inside); the branches are gone | `docs/audit/findings.yaml` for any open item |
| `adopted-proposals/claude-md-proposed.md`, `adopted-proposals/claude-md-split.md` | Proposals to rewrite and split `CLAUDE.md` | Adopted 2026-11-15 | `CLAUDE.md`, `docs/product/`, `docs/engineering/`, `docs/testing/strategy.md`, `docs/security/privacy.md`, `docs/architecture/ownership.md` |
| `design/pen-dev-handoff/` | The brief and screenshots given to pen.dev at `6cdc25f` (2026-11-07) | It produced Halo; the current pen.dev prompt is B8's | `docs/design/halo-system/` (`b8-pen-prompt.md`) |

The audit documents in `docs/audit/` are not archived: `findings.yaml` and several tests point at their sections, so
they stay where they are as the reasoning behind each finding. ADRs are never archived; a superseded one says so in
its status line.
