# ADR-008: Swift's identity and the provider abstraction

- **Status:** Accepted
- **Date:** 2026-10-23
- **Builds on:** ADR-006 (Swift dispatches to Claude Code), ADR-007 (routing layer)

## 1. Context

The owner talks to Swift. Swift hands the work to an execution provider: Claude Code today, and maybe Codex or Hermes later (see `docs/spikes/hermes-agent.md`). Before this ADR, the overlay showed a generic "Working" card. Error hints were looked up by executor name inside `session.py`, and the demo executor said "Starting Claude Code…" even though no Claude Code was running. So nothing told the owner who was doing the work, and the one place that did name a provider was wrong.

## 2. Decision

**Two layers, and one direction of travel:** the user talks to Swift, Swift talks to providers, and Swift brings the results back.

| Layer | Owns | Code |
|---|---|---|
| Swift | the conversation, routing, approvals, follow-up context, presenting results, its own name | `session.py`, `routing/`, `identity.py` |
| Provider | executing one request | `executors/*` behind `Executor` |

### Provider interface (`executors/base.py`, `executors/providers.py`)

- Every executor declares `provider = ProviderInfo(id, name, capabilities, error_hint)`:
  - Claude Code: `CLAUDE_CODE`;
  - debug scenarios: `MOCK`, shown as "Demo agent", never as Claude Code;
  - echo stand-in: `SWIFT`, because no agent is involved.
- Progress is normalized. Each `ExecEvent` step carries an `activity` from a fixed vocabulary: `starting`, `reading`, `searching`, `editing`, `running`, `browsing`, `delegating`, `planning`, `thinking`, `waiting`, `switching`, `blocked`, `working`. It also carries `subagent` for work done by a helper the provider started.
  - Each provider maps its own events onto this vocabulary. For Claude Code that is `claude_mapping.TOOL_ACTIVITY`.
  - Anything a provider can't classify is `working`. Nothing is invented.
- `Providers` is the ordered set the session starts runs on. The first one is the default. A provider that raises `ExecutorUnavailable` is skipped, the next one is tried, and the skip is reported.
  - A failure *during* a run is not retried elsewhere, because the run may already have changed files.
  - The backend configures one provider today. Fallback is supported by the session (`fallbacks=`) and tested, but no config key exposes it until there is a second real provider.

### Protocol (additive; still v1)

| Message | New fields |
|---|---|
| `state` | `agent` |
| `step` | `activity`, `agent`, `subagent`; `kind: "handoff"` for Swift's own fallback step |
| `confirm.request` | `agent` |
| `result` | `agent`, `note` |
| `error` | `agent` |

- `agent` is `{id, name}`, or `null` when Swift did the work itself (time, date, open, identity).
- The overlay turns these into words in one file, `overlay/src/agents.ts`, which knows no provider by name:
  - working card: "Claude Code is reading", "Swift handed this to Claude Code". *Changed 2026-10-26 (owner): the working card no longer names the provider ("Reading", "Thinking", "Working on it"); the result's byline still does.*
  - confirm card: "Claude Code wants to:";
  - result card: "Swift · via Claude Code";
  - error card: "Claude Code ran into a problem".

### Identity

- The rules strip a leading "hey/hi/ok Claude|Codex|Hermes|ChatGPT" like the wake word and record `addressed_as`. The request then routes as usual.
- Said alone, or as "who are you?" or "are you Claude?", the greeting gets the local `identity` answer, for example "No, I'm Swift. Claude Code is one of the agents I work with."
- With a request, the request runs, and the clarification is a `note` on the result. It is said at most once an hour, so it never nags.
- `identity.py` only names providers that are configured: "hey Codex" with only Claude Code set up gets "The agent I work with right now is Claude Code".
- Claude Code's system prompt tells it that it works for Swift and that Swift presents its answer, so the answer doesn't introduce itself.

## 3. Adding a provider

1. Write an executor that implements `Executor`, with `provider = ProviderInfo(...)`, and map its events onto `Activity`.
2. Add its spoken name to `AGENT_NAMES` (and to `_AGENT` in `routing/rules.py`, if it's a new word).
3. Build it in `backend/__main__.py`, as the default or as a fallback.

Neither the session nor the overlay changes.

## 4. Not done / known limits

- *Done 2026-10-24:* the router's route is now `"agent"` (it was `"claude"`), including the eval labels. Learned examples and interaction logs written with `"claude"` are still read as `"agent"`.
- Model escalation stays provider-internal: Claude Code reports it as a `switching` step. A cross-provider hand-off mid-run would need a new event type and is not designed yet.
- Multi-agent runs are covered as far as one provider's own helpers go (`subagent`). Several providers on one request would need one `agent` per step, which the protocol already carries, plus a coordinator in the session.
