# ADR-006: Voice overlay MVP that dispatches to Claude Code

- **Status:** Accepted
- **Date:** 2026-10-22
- **Decided by:** Owner

## Context

`SWIFT_BUILD_PROMPT.md` v2.0 describes a self-contained agent: a tkinter overlay, a local LLM through Ollama, a Swift-owned `ActionGateway` permission engine, Gmail/Calendar integrations, and cloud LLM use off by default. Phase 0 spikes were run against that spec.

The owner has replaced that direction for the MVP with a "mostly face, very little brain" design: Swift captures voice, transcribes locally, hands the request to an existing agent (Claude Code, headless), and shows progress and results in a transparent overlay.

## Decision

1. `PLAN.md` (approved 2026-10-22) is the authority for the MVP. `SWIFT_BUILD_PROMPT.md` is **paused, not deleted**; it carries a banner saying so.
2. Overlay shell: Tauri v2 with a vanilla TypeScript frontend (replaces tkinter).
3. Backend: Python, under `src/swift`, talking to the overlay over a token-protected WebSocket on 127.0.0.1. Tauri starts it as a child process in a kill-on-close Job Object (not a frozen sidecar).
4. Execution goes to Claude Code. **This sends transcripts to a cloud service**, which reverses the v2.0 "cloud LLM off by default" rule for this executor. Transcription stays local.
5. Swift does not build its own permission engine. Claude Code's permission system is the control. Its defaults are read-only tools plus a config allowlist. In Milestone 5, its permission requests reach the overlay's confirm card through the Python `claude-agent-sdk` `can_use_tool` callback (PLAN.md §7, option B).
6. Out of scope for the MVP: wake word, Ollama, Gmail/Calendar, memory, multiple agents, installers.
7. MVP config is `config.yaml` (PLAN.md §8), loaded by `swift.settings`. The v2.0 TOML config package (`swift.config`) and the redacting logger stay; the TOML files are not used by the MVP.

## Consequences

- Phase 0 results that still apply: STT latency and memory for `base.en` on this machine, and the redacting logger.
- Results that no longer apply: the Ollama routing evaluation, Google OAuth probes, and wake-word corpus tooling. They stay in `spikes/` for reference.
- The Rust toolchain (rustup, MSVC target) is now a development dependency.
