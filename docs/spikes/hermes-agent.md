# Hermes Agent viability trial (2026-10-23)

**Status: installed and probed headless; no model call made.** The second install attempt (`pip install --default-timeout 120 --retries 10 hermes-agent==0.19.0` into `spikes/hermes/.venv`, Python 3.13) worked; the first two failed on network resets. Isolated `HERMES_HOME`; no system-wide install, no installer EXE, no account, no owner credentials. A model-backed first step is unmeasured because no provider key is configured: `hermes chat -q "say hi"` stops with "No inference provider configured" (needs `hermes model` or an `OPENROUTER_API_KEY`/`OPENAI_API_KEY`). The owner must choose a provider before that can be done.

## Measurements (i7-10610U, 16 GB, Windows 11, no model call)

| Measure | Result |
|---|---|
| Install | pip install works though the docs call it unsupported; `hermes --version` reports "Install method: pip". About 60 packages; `aiohttp` must be added by hand or the API server won't start. |
| `hermes --version` | 3.3 s cold, 1.7 s warm. |
| `hermes chat -q` to the "no provider" error | one run took 91 s (first run, with `HERMES_HOME` empty; likely first-run setup or gateway attach; not re-run). Treat as unexplained, not representative. |
| `hermes gateway` with the API server enabled: `/health` answers | 10.8 s after launch. |
| Idle memory of that gateway (no chat platforms) | about 116 MB (a 101 MB Python process plus launcher stubs). |

## Interception check (run: `probe_hook.py`, no model needed)

A plugin in `HERMES_HOME/plugins/swift_gate/` (`plugin.yaml` plus `register(ctx)`; `ctx.register_hook("pre_tool_call", fn)`; enabled via `plugins.enabled` in `config.yaml`) returned `{"action": "block", "message": ...}` for `write_file`/`patch`. Hermes' own dispatcher `model_tools.handle_function_call("write_file", ...)` then returned the block message and the file was **not written**; the same call without the plugin wrote the file. So a hook can stop every file-changing tool call before it runs. An `approve` action escalates to Hermes' human gate (not exercised: it needs a live run). The API server's `/v1/capabilities` confirms `run_approval_response` and `approval_events`. Not tested end to end: a real run emitting `approval.request` to a client, and subagent calls through the hook (dispatch passes `task_id`, but not verified).

## Findings from the official docs (hermes-agent.nousresearch.com); interception and the API server were confirmed by running

| Question | Finding |
|---|---|
| Native Windows | Yes. Tier 1 support on Windows 10/11 via `install.ps1` (`iex (irm ...)`, installs under `%LOCALAPPDATA%\hermes`; it provisions Python 3.14, Node, ripgrep, FFmpeg, Chromium and `cua-driver` unless skipped) or an MSIX Desktop package. The docs say not to install into your own venv with pip/uv ("PM" manages environments). `hermes-agent` 0.19.0 is on PyPI (`pyproject` range `>=3.11,<3.15`), which is an undocumented path. |
| Provider key | Needs a configured provider (`hermes model`, an OpenRouter/OpenAI key, or Nous Portal OAuth). Not tried; owner decision needed. |
| Headless | `hermes chat -q "..."` or `--query-file`. In that mode a dangerous command is denied by default (`approvals.single_query_mode: deny`). |
| Intercepting tool calls (deciding criterion) | **Yes, several ways.** (a) `pre_tool_call` plugin or shell hooks can return `block`, `approve` (escalate to the human gate) or `modify`; shell-hook examples match `write_file|patch`, so file changes are coverable. (b) The API server's `/v1/runs` emits `approval.request`, parks the run in `waiting_for_approval`, and takes `POST /v1/runs/{id}/approval` with `once`/`deny`. (c) ACP over stdio sends approval prompts to the client (allow once/session/always/deny). Caveat: the built-in approval gate covers *dangerous terminal commands*, not every file write, so a Swift confirm card needs a `pre_tool_call` hook to cover write/patch. Timeouts fail closed. Whether subagent calls pass the same gate is undocumented. |
| Programmatic interface | **Yes, contrary to the ADR-007 §7 write-ups.** OpenAI-compatible HTTP server (`hermes gateway` with `API_SERVER_ENABLED`, default `127.0.0.1:8642`, bearer key required): `/v1/chat/completions`, `/v1/responses`, `/v1/runs` plus SSE events (`tool.started`, `subagent.start`, `run.completed`), stop and approval endpoints. Also ACP over stdio. |
| Subagents | `delegate_task`; the ADR says separate processes, but the docs say **threads** (`ThreadPoolExecutor`). One `delegation.model` applies to all children; per-task models need `model_map`/`profile_routes`. Parent can list/steer/stop children. |
| Skills, memory | Confirmed: agentskills.io-format skills the agent creates; FTS5 session recall; agent-curated memory. |
| Cron | Built in: `hermes cron create/list/run/...`, schedules like `every monday 9am`, cron expressions, one-shot `in 2h`; per-job model pin and reasoning effort; delivery to local files or Telegram/Slack/Discord. **Needs the gateway daemon running** (ticks every 60 s). Cron runs deny dangerous commands by default. |

## Comparison for scheduled jobs (docs-level only; Claude Code routines and Managed Agents not re-researched here)

- Hermes cron runs on this PC against local files, but needs a resident gateway daemon, a second runtime and a provider key, and its approval model is separate from Swift's.
- Claude Code routines and Claude Managed Agents scheduled deployments keep the Claude permission model; Managed Agents run in Anthropic's sandbox, not on local files. Not compared further.

## Recommendation: **not now**, with one revision to ADR-007

- Revision: the "no documented embedding API" objection no longer holds. Hermes has an HTTP/SSE run API with a per-action approval endpoint, and a hook that can gate file changes. Interception is feasible: the deciding criterion is met for file writes through a `pre_tool_call` plugin (proved by `probe_hook.py`); the live approval round trip to the overlay is still untested.
- Still against it as a front door: second runtime and permission system, about 116 MB idle for a resident gateway, startup 2–3 s for the CLI and about 11 s for the API server, model-call latency unmeasured, Python 3.14/Node/Chromium footprint, an unsupported pip path.
- Possible later role: an executor for scheduled local jobs, once a resident daemon is acceptable.

## Still open

1. Owner chooses a provider and supplies a key (nothing was entered). Then measure launch to first step with a model, and run `/v1/runs` with a `write_file` call to watch `approval.request` and `POST /v1/runs/{id}/approval`.
2. Confirm subagent (`delegate_task`) calls go through the same hook.
3. Compare cron against Claude Code routines and Managed Agents with real runs.
