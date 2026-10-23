# Hermes Agent viability trial (partial, 2026-10-23)

**Status: documentation review done; hands-on measurements NOT done.** `pip install hermes-agent==0.19.0` (PyPI, Python 3.13 venv) failed twice with network read timeouts and a connection reset (10054) while downloading. Nothing was installed system-wide, no installer EXE or `install.ps1` was run, and no account or key was created. Q2 (time to first step, idle memory) is unmeasured. The venv was deleted.

## Findings from the official docs (hermes-agent.nousresearch.com), not yet verified by running

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

- Revision: the "no documented embedding API" objection no longer holds. Hermes has an HTTP/SSE run API with a per-action approval endpoint, and a hook that can gate file changes. Interception is feasible, so the deciding criterion is plausibly satisfiable, but only by writing a plugin that routes `write_file`/`patch` to the gate. That is untested.
- Still against it as a front door: second runtime and permission system, latency unmeasured, Python 3.14/Node/Chromium footprint, an unsupported pip path.
- Possible later role: an executor for scheduled local jobs, once a resident daemon is acceptable.

## To finish the trial

1. Retry the install on a stable network (`pip install hermes-agent==0.19.0` in a venv, or the owner's OK for `install.ps1 -SkipBrowser -SkipComputerUse -NonInteractive`).
2. Owner decision: which provider key to use (no credentials were entered).
3. Measure launch to first step and idle RSS of the gateway; probe `/v1/runs` plus the approval event with a `write_file` call; write a minimal `pre_tool_call` plugin and confirm it blocks a file write.
