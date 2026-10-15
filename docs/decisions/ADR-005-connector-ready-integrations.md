# ADR-005: Connector-ready integrations

- **Status:** Accepted
- **Date:** 2026-10-15
- **Decided by:** Owner

## Context

The owner wants Swift to connect to services the way Slack, Claude, or Ollama do: through pluggable connectors that streamline workflows. The spec (§3, §18) keeps the `mcp` SDK and third-party tool servers out of the MVP, for two reasons. Third-party tool code and its self-declared permissions are untrusted (§8.6), and Phase 7 already schedules an MCP host with an explicit allowlist.

## Decision

1. The MVP keeps **built-in Google integrations** (Gmail, Calendar, People) as specified in §9.1.
2. Integrations sit behind a generic **Connector** boundary, so that a plugin or MCP-backed connector can be added later without touching templates or security code:
   - A connector declares a manifest: id, display name, auth method, and the tools it contributes.
   - **Swift assigns** each tool's `Capability`, `SideEffect`, and target extraction in its own code or config. A connector's self-description is never trusted.
   - Every connector tool is a `ToolSpec` registered in the `ToolRegistry`, so it executes only via the `ActionGateway`. All §8 rules apply unchanged.
   - All connector output is `UNTRUSTED_EXTERNAL` unless Swift's own code proves otherwise.
3. **Timing:** no connector code in Phase 0 (§0.9). The interface is defined when `tools/` and `integrations/` are built (Phase 3/5). A plugin/MCP host stays in Phase 7 and needs separate approval.

## Consequences

- The spec is not rewritten. `docs/architecture.md` will describe the connector boundary.
- `docs/backlog.md` records: an MCP/plugin connector host, a connector allowlist UI, and candidate connectors (Slack, etc.).
- The `test_architecture.py` layering rules extend to connectors: integrations must not import `tools/`, and only the gateway may execute.
