# Backlog

Ideas recorded here are out of scope for the current phase (§0.9). Each needs approval before work starts.

- **Plugin/MCP connector host** (ADR-005, Phase 7): run third-party connectors out of process, with a Swift-maintained capability mapping and an explicit allowlist.
- **Connector management UI:** enable or disable connectors and show their granted capabilities from the tray.
- **Candidate connectors:** Slack, and others to be decided.
- **Hermes Agent viability spike** (ADR-007 §7; the owner wants it tried, not now): run it headless on Windows, measure the time to its first step, check whether its tool calls can be intercepted for the overlay's confirm card, and compare it with Claude Code for scheduled and background jobs. *Partial outcome 2026-10-23 (docs review only; install failed on network errors, nothing measured): interception and an HTTP/SSE API with an approval endpoint exist; recommendation is not now. See `docs/spikes/hermes-agent.md`.*
