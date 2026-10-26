# ADR-010: Workflows, the trust boundary, and "show me"

- **Status:** Accepted (owner, 2026-10-24: approved as proposed, with the proposed answers in §10)
- **Decided by:** Owner
- **Date:** 2026-10-24
- **Builds on:** ADR-005 (connectors), ADR-007 (routing), ADR-008 (Swift and its providers), ADR-009 (overlay UX)

## 1. Context

The owner wants Swift to do real work ("send an email to my lecturer") and to be able to say "show me" at any moment to see what Swift is doing.

The code today can't support that:

- **Providers report only text.** A run is a stream of `step` strings and one `result` card. Swift can't tell a draft from a log line, so it has nothing to "show".
- **No trust boundary in code.** `docs/architecture.md` describes `security/gateway.py` (validate → resolve → policy → confirm → journal → execute → verify → audit) and ADR-005 connectors, but neither exists in `src/`. The only confirm cards are Claude Code's own permission prompts (`can_use_tool`).
- **No voice during a run.** Push-to-talk while working is ignored ("ptt ignored: busy"). The only exception is answering a confirm card.
- **One provider-specific hook.** Swift already runs an in-process MCP server named `swift` for Claude Code (`request_stronger_model`), but nothing generalises it.

The executor and provider split (ADR-008) is sound and stays. This ADR adds what sits around it.

## 2. Decision in one picture

```
 owner ──voice/click──► Swift session ──start──► provider (Claude Code; later Codex, Hermes)
                          │   ▲                         │
                          │   │ artifacts, confirm      │ MCP tool calls
                          ▼   │                         ▼
                       overlay        Swift tool host ("swift" MCP server)
                                         │  find_contact, draft_email, present  (no side effects)
                                         │  send_email                          (side effect)
                                         ▼
                                   ActionGateway ──► connector (Gmail; fake in tests)
                                   validate → resolve → policy → confirm card →
                                   journal PENDING → execute → verify → journal DONE/FAILED → audit
```

- The **provider decides what to do**: it writes the email and chooses when to send.
- **Swift does it**: Swift's tools hold the state, the gateway enforces the rules, and the connector talks to Google.
- Swift **sees structured state**, because the provider can only change the draft or send it through Swift's tools. Swift publishes that state to the overlay as **artifacts**.

## 3. Swift-owned workflow tools (item 1)

### 3.1 One registry, served over MCP

- `swift/workflows/tools.py` defines each tool as a `ToolSpec`:
  - `name`, description, JSON input schema;
  - **`side_effect`**: `none` | `external`, assigned by Swift and never by a connector (ADR-005);
  - an async handler.
- The registry is provider-neutral. A tool's handler receives a `RunScope`: the current run's artifacts, the recipients it has resolved, and its gateway. It never receives provider objects.
- Tools with `side_effect="external"` can only reach a connector through `ActionGateway.execute`. A unit test enforces this (§4.4).

### 3.2 First tools

| Tool | Side effect | Does |
|---|---|---|
| `find_contact(query)` | none | Resolves "my lecturer" or "Dr Smith" to candidates, first from `contacts` in `config.yaml` (name, email, aliases such as "lecturer"), then from the connector's directory (People API, `contacts.readonly`). Publishes a `recipient` artifact. Every address it returns is remembered as **resolved** for this run. |
| `draft_email(to, subject, body, draft_id?)` | none | Creates or revises a draft **held by Swift**: nothing reaches Google yet. Returns `draft_id` and `version`. Publishes an `email_draft` artifact; each revision is a new version. |
| `send_email(draft_id)` | external | Sends the exact draft version, through the gateway (§4). Returns `sent` with the message id, `rejected`, or `failed` with a reason. |
| `present(kind, title, data)` | none | Shows a `text`, `list` or `table` artifact, so a provider can put any structured result in front of the owner. |

Later workflows (calendar invite, reminders) add tools here. Neither the session nor the overlay changes for them.

### 3.3 In-process now, loopback HTTP for providers out of process

Considered:

- **In-process SDK server only** (`create_sdk_mcp_server`, as `request_stronger_model` is today). Zero setup and no port, but only Claude Code's SDK can reach it.
- **stdio MCP server** that the provider launches. Codex and Hermes would each start a fresh Swift process. That child process can't see the session's state or show a confirm card without a second channel back to Swift, so it would need the HTTP server anyway.
- **Loopback streamable-HTTP MCP server** inside the Swift backend (`127.0.0.1`, random port, bearer token). Codex (`[mcp_servers.swift] url = …`, `bearer_token_env_var`) and Hermes (`mcp_servers.swift.url` plus `headers`) both support this.

**Chosen:**

- The same registry is served two ways:
  - **in-process** to Claude Code, extending the existing `swift` server; and
  - over a **loopback HTTP MCP server** for out-of-process providers, using the `mcp` package, which `claude-agent-sdk` already depends on.
- The HTTP server is built with the first out-of-process adapter (phase B, §8), not now. It gets:
  - a fresh bearer token per run, valid only while that run's scope is open;
  - a `127.0.0.1` bind only;
  - Swift's existing rule of no non-loopback endpoints.

### 3.4 One run at a time

- Swift runs one interaction at a time (ADR-006), so the tool host has **one open `RunScope`**.
- The session opens the scope before the provider starts and closes it when the run ends.
- A tool call with no open scope, or from a stale run, fails with "no active run" and never reaches a connector.

### 3.5 Claude Code specifics

- The Swift tools join `allowed_tools`, so Claude Code's own permission prompt doesn't ask about them. The gateway's confirm card is the one approval.
- Claude Code's other tools keep today's rules: read-only tools are allowed, and Edit/Write/Bash go to the confirm card.
- The system prompt gains one sentence: email goes only through Swift's tools; never send mail any other way.

## 4. The trust boundary: a minimum `ActionGateway` (item 2)

`swift/security/gateway.py`. Every `side_effect="external"` tool call goes through `ActionGateway.execute(action)`. An `Action` is the tool name, its resolved target(s), a payload digest, and a human summary.

| Step | For `send_email` |
|---|---|
| 1. validate | The draft exists in this run. `to`, `subject` and `body` are non-empty. The address is syntactically valid. Size limits apply. |
| 2. resolve | **Every recipient must be resolved:** returned by `find_contact` in this run, or listed in `contacts` in config. An address that only came from the model is denied. Untrusted content can't choose the recipient (T1). |
| 3. policy | `email.send` is **always confirm**. No setting turns it off; the gateway has no "auto" for external side effects. Policy failures **deny** (fail closed). |
| 4. confirm | The overlay's confirm card **shows the draft itself**: recipient name and address, subject, and body. It also carries the artifact reference. The approval is bound to the draft's `(draft_id, version, digest)`, is single use, and expires with the card (`confirm_timeout_s`). Voice "approve" keeps the noisy-room double-check (ADR-007 §8). |
| 5. journal | Before execute: `PENDING` with action id, tool, digest, recipient domain, and time. **Metadata only, never the body** (T8). The journal is an append-only JSONL file in `%LOCALAPPDATA%\Swift\journal.jsonl`. |
| 6. execute | The digest is **recomputed immediately before execute**. A mismatch voids the approval (T3). Then the connector sends. |
| 7. verify | The connector must return a message id. Gmail's `drafts.send` returns the sent `Message`. With no id, the result is `FAILED`, never "sent". |
| 8. journal | `DONE` with the message id, or `FAILED` with the reason. A `PENDING` entry found at startup is reported in the log and **never resumed** (T10: at most one send per approval). |
| 9. audit | One structured log line per action, through the redaction patcher. |

### 4.1 How the gateway shows a confirm card

- Today confirm cards come only from executor events. The gateway asks the **session** through a `Confirmer` callback instead.
- The session sends `confirm.request` with a Swift request id (`swift:<n>`), `agent: null` (Swift is asking, not the provider), and `artifact_id`.
- The session handles `confirm.reply` for these ids itself, instead of forwarding them to the executor.
- Click, voice, timeout and Esc behave exactly as they do for provider cards.

### 4.2 What a reject does

The tool returns `rejected` to the provider, with "The owner rejected sending this email. Don't retry; stop and say so." The run ends with a "Not approved" result, as it does for Claude Code permission rejections today.

### 4.3 Not in this minimum

These come with the workflows that need them:

- path rules (T5);
- challenge words for HIGH risk;
- `permissions.toml` policy beyond the fixed "external = confirm";
- taint tracking beyond the resolved-recipient rule.

### 4.4 Enforced by tests

- No module other than `security/gateway.py` calls a connector's side-effecting methods. This is an AST scan, a first slice of the planned `test_architecture.py`.
- The fake connector counts sends; tests assert zero sends on reject, timeout, a digest change and an unresolved recipient.

## 5. Run artifacts (item 3)

### 5.1 New outbound message (additive; protocol stays v1)

```jsonc
{ "type": "artifact", "data": {
    "run_id": "cc-3",
    "id": "draft-1",                  // stable within the run
    "kind": "email_draft",            // email_draft | recipient | send_status | text | list | table
    "phase": "drafting",              // resolving | drafting | confirming | sending | done | failed
    "version": 2,                     // increases on every update; the overlay drops older versions
    "title": "Email to Dr Smith",
    "data": { /* depends on kind, below */ },
    "agent": null                     // who produced it (null: Swift's own tools)
} }
```

| `kind` | `data` |
|---|---|
| `recipient` | `{query, candidates: [{name, email, source}], chosen: index or null}` |
| `email_draft` | `{to: [{name, email}], subject, body}`. Bodies are clipped to 16 KB, and the frame stays under `MAX_FRAME_BYTES`. |
| `send_status` | `{state: "waiting_approval" or "sending" or "sent" or "failed" or "rejected", message_id?, reason?}` |
| `text` / `list` / `table` | The same shapes as `ResultDetails` today. |

### 5.2 Other protocol additions

- **`confirm.request` gains `artifact_id`** (optional). When it's set, the card renders that artifact: for `send_email`, the draft.
- **`view`** (outbound): `{run_id, artifact_id or null, open: bool}`. Swift tells the overlay to open or close the detail view. This is how a voice "show me" reaches the overlay.
- **`view`** (inbound): `{action: "show" | "hide"}`. The same request from a click on the card's **Show** button. Swift answers with an outbound `view`, so voice and click take one path, and the backend still owns state.
- **`run.voice`** (outbound): `{run_id, phase: listening | transcribing | idle | hint, text}`. Push-to-talk feedback on the working card, like `confirm.voice` on the confirm card.
- **`debug.say`** (inbound, debug mode only): `{text}`. Typed text treated as if spoken **during a run**. Used by the dev harness and tests to run "show me" without a microphone.

Old overlays ignore the unknown types and fields: `decode()` passes unknown types through and `onMessage` drops them.

### 5.3 The session keeps snapshots

- For the current run, the session keeps the latest version of each artifact, keyed by `id`, and the run's **phase** (the phase of the newest update).
- Snapshots are dropped when the run ends. The final `result` may include the `send_status` artifact's id, so "show me" right after a send still has something to open while the result card is up.
- The interaction log records artifact kinds, versions and phases, never their content (T8).

## 6. Voice during a run (item 4)

- Push-to-talk while **working** now records and transcribes, as on a confirm card. It reports through `run.voice` instead of the nudge. The transcript goes to a **mid-run grammar**, a new Tier-1 function `rules.route_midrun(text)`:

  | Said | Action |
  |---|---|
  | "show me", "show me that", "let me see", "what are you doing" | `show`: the most relevant artifact (§7) |
  | "show (me) the draft / email / recipient / progress / steps" | `show` with a kind |
  | "hide that", "hide it", "close that", "go back" | `hide` |
  | "stop", "cancel", "never mind" (existing control rules) | cancel the run, like Esc |

- Matching is on the whole utterance, as for control rules. It never starts a run and never reaches a model. It is handled in milliseconds after STT.
- Anything else gets a hint on the card: "I'm still on the last request. Say “show me” or “stop”." The words are not queued as a new request, because a request heard mid-run is easy to mishear and its moment may have passed.
- On a **confirm card**, the existing approve/reject/stop grammar gains `show` and `hide`. `show` opens the full draft when the card shows a shortened one.
- The wake phrase stays off during runs, unchanged.

## 7. The "show me" view (item 5)

### 7.1 Which artifact is shown

The most relevant artifact for the run's current phase:

| Phase | Shown first |
|---|---|
| resolving | `recipient` |
| drafting / confirming | `email_draft` |
| sending / done / failed | `send_status` (with the draft below it) |
| a phase with no artifact, or no artifacts at all | the newest artifact; failing that, the step list, expanded even in compact mode |

"Show the draft" names the kind and overrides the phase. The overlay picks the artifact from Swift's `view` message, so the choice lives in Python and is tested there.

### 7.2 Layout within the fixed 720 × 560 window

- **The detail view replaces the working card's body. It is not a second window or panel.**
  - The card stays at its anchor and never moves mid-run (ADR-009).
  - It grows within the existing card zone (`CARD_ZONE_H` = 340 px), so smart placement's caret check stays correct.
  - A long body scrolls inside the view, which is a hit region (`data-hit`) while open.
- The header keeps the spinner, the activity ("Claude Code is drafting") and Stop. A **Back to steps** button and voice "hide that" return to the steps.
- A **Show** button appears on the working card once the run has an artifact. "Show me" is never voice-only.
- New artifact versions update the open view in place: "Draft · v2", without a flash.
- **Accessibility:**
  - The view is a `region` with a heading. Updates are announced politely and only on phase changes, not every version.
  - Text keeps ADR-009's contrast. Forced colors and reduced motion are respected.
- The confirm card for `send_email` uses the same draft renderer, with the body clipped to about 8 lines and a "Show full draft" button or voice "show me".

## 8. More providers (item 7)

Both fit the existing `Executor` / `ProviderInfo` interface and use the same Swift tools through the loopback MCP server (§3.3). Interfaces were checked against official docs on 2026-10-24.

### 8.1 Codex: use `codex app-server`, not `codex exec --json`

- **Why not `exec`:** `codex exec --json` streams events (`thread.started`, `turn.started`, `item.started`/`item.completed`, `turn.completed`/`turn.failed`), but it can't ask a client for approval. It only runs inside a sandbox (`--sandbox read-only|workspace-write`) or with automatic review. Swift's confirm card could not stand in front of a write.
- **Transport:** `codex app-server` speaks JSON-RPC over stdio (newline-delimited). Start-up is `initialize` and `initialized`, then `thread/start` and `turn/start {threadId, input}`.
- **Events:**
  - `item/started` and `item/completed` become steps. Item types such as `commandExecution` (running), `fileChange` (editing) and `mcpToolCall` map to `Activity`.
  - `item/agentMessage/delta` streams the answer.
  - `turn/completed` gives the result.
- **Approvals:** the server requests `item/commandExecution/requestApproval` and `item/fileChange/requestApproval` become `ExecEvent("confirm")`. Swift answers `accept` or `decline`, never `acceptForSession`.
- **Cancel:** `turn/interrupt`.
- **Swift's tools:**
  - Config: `[mcp_servers.swift] url = "http://127.0.0.1:<port>/mcp"`, `bearer_token_env_var = "SWIFT_MCP_TOKEN"`.
  - Approval mode: `tools.<tool>.approval_mode = "auto"` for Swift's tools only, because Swift's gateway already confirms.
  - Config isolation: run with `--ignore-user-config` semantics so the owner's own Codex config can't widen permissions. *To verify in phase B:* passing this per process (`-c` overrides or a private `CODEX_HOME`).
- **ProviderInfo:** `CODEX = ProviderInfo("codex", "Codex", {"files", "commands", "confirm"})`.

### 8.2 Hermes: use the API server's runs API

- **Transport:** the run is started with `POST /v1/runs {input, instructions}` on `127.0.0.1:8642`. Every call carries `Authorization: Bearer <API_SERVER_KEY>`, which is required even on loopback.
- **Events** come from `GET /v1/runs/{id}/events` (SSE):
  - `tool.started` / `tool.completed` become steps;
  - `subagent.start` sets `subagent=True`;
  - `approval.request` becomes a confirm card;
  - `run.completed`, `run.failed`, `run.cancelled` and `run.interrupted` end the run.
- **Approvals:** `POST /v1/runs/{id}/approval {request_id, execution_generation, choice: "once" | "deny"}`. A 409 for a stale generation is treated as "no longer pending".
- **Cancel:** `POST /v1/runs/{id}/stop`.
- **Swift's tools:** `mcp_servers.swift: {url, headers: {Authorization: "Bearer …"}}`, so Hermes names them `mcp_swift_send_email`, and so on. Set `trust: full` on that server, because the gateway confirms; don't add a second prompt.
- **Coverage gap:** Hermes' own gate covers dangerous terminal commands, not file writes. The `pre_tool_call` plugin from the spike stays needed for write/patch (`docs/spikes/hermes-agent.md`).

### 8.3 Order of work

| Phase | Scope |
|---|---|
| **A (this branch)** | Registry, gateway, journal, artifacts, mid-run voice, "show me" view, fake and Gmail connectors, in-process tools for Claude Code, scripted demo |
| **B** | Loopback HTTP MCP server and the Codex adapter |
| **C** | Hermes adapter, after the spike's open items (provider key, live approval round trip) |

B and C each need the owner's go-ahead.

## 9. First connector: Gmail (item 6)

- `swift/connectors/base.py` defines the `EmailConnector` protocol:
  - `directory(query) -> [Contact]`;
  - `send(draft) -> SentMessage` (gateway-only).
  - Connectors have a manifest (id, name, auth) per ADR-005; Swift, not the manifest, assigns side effects.
- `connectors/fake.py`: an in-memory `FakeMailConnector` for tests and debug mode. It records sends and can be told to fail.
- `connectors/gmail.py`:
  - Uses Gmail REST through `google-api-python-client`, imported lazily. The libraries stay in the `spikes` dependency group for now; a separate `google` group needs `uv lock` on the owner's machine (follow-up).
  - Sends with `drafts.create` then `drafts.send` under `gmail.compose`, the scope S4 verified. No `gmail.readonly` and no mail search, unchanged.
  - Uses `people.searchContacts` / `otherContacts` under `contacts.readonly` for the directory.
- **Sign-in is the owner's.**
  - `uv run --group spikes python -m swift.connectors.gmail signin` opens the browser through `InstalledAppFlow`, as `spikes/google/oauth_probe.py` does, and stores **only the refresh token** in Credential Manager (`Swift/Google`) (T9).
  - Claude never enters credentials. Swift starts without it and says "Gmail isn't connected" with that command as the hint.
- **Config** (`config.yaml`): `connectors.email: none | fake | gmail` (default `none`) and `contacts: [{name, email, aliases}]`.

## 10. Owner's decisions (2026-10-24: the proposed answers, approved)

1. **Approve the design as a whole?** In particular: the confirm card is the only approval for Swift tools (no Claude Code prompt in front of it), and `email.send` can never be set to auto.
2. **Recipient rule:** is "only addresses from your contacts, config, or `find_contact`" right? It means "email jane@example.com" spoken aloud is **denied** unless Jane is in your contacts or config, because a spoken address can't be trusted from STT. The alternative is to also allow an address that appears literally in the transcript.
3. **Mid-run speech that isn't a command:** a hint only (proposed), or remember it as the next request once the run ends?
4. **Debug mode:** use the fake connector automatically, so the demo never touches Google (proposed)?

## 11. Owner-run checks (REQUIRES-HW / REQUIRES-GOOGLE)

These can't be verified in tests or the dev harness:

- **REQUIRES-GOOGLE:** `signin` against your Google project; a real send to your own second address via voice; the "unverified app" screen; refresh after restart; People search for "lecturer".
- **REQUIRES-HW:**
  - "show me" by voice mid-run in a quiet and a noisy room;
  - push-to-talk on the working card in the real Tauri window;
  - scrolling the draft in the detail view, which needs the hit region on real DPI;
  - the card staying in place across anchors while it grows.
- **Claude Code end to end:** with `connectors.email: fake`, a real Claude Code run calls `find_contact` → `draft_email` → `send_email`. This needs a signed-in `claude`.

## 12. Consequences

- **New packages:** `swift/workflows/`, `swift/security/`, `swift/connectors/`.
- **Protocol additions are backward compatible:**
  - new outbound types `artifact`, `view`, `run.voice`;
  - new inbound types `view`, `debug.say`;
  - one new optional field, `artifact_id` on `confirm.request`.
- **`docs/architecture.md`** is updated so the trust-boundary section describes what exists, not only the plan.
- **`ExecResult` doesn't change.** Artifacts travel beside the run, not inside the result.

## 13. Implementation status (phase A, 2026-10-24, branch `claude/workflow-foundations-eaf9e4`)

Built as decided. Verified by unit tests with the fake connector and by the dev harness (§11 still applies).

| Part | Where | Tests |
|---|---|---|
| Protocol additions | `ipc/protocol.py`, `overlay/src/protocol.ts` | `test_protocol.py` |
| Connectors | `connectors/base.py`, `fake.py`, `gmail.py` | Gmail only by the owner (REQUIRES-GOOGLE) |
| Gateway and journal | `security/gateway.py`, `security/journal.py` | `test_workflows.py`, `test_architecture.py` |
| Tools and artifacts | `workflows/tools.py`, `scope.py`, `artifacts.py` | `test_workflows.py` |
| Session: scope, Swift confirm cards, show me, mid-run voice | `session.py`, `routing/rules.py` (`route_midrun`) | `test_show_me.py`, `test_voice_confirm.py` |
| Claude Code gets the tools | `executors/claude_code.py` | `test_claude_executor.py` |
| Demo and harness | `executors/mock.py` (`email` scenario, `Call` items), `overlay/dev/` | `test_show_me.py`; harness run in a browser |
| Settings | `contacts`, `connectors.email`, `logging.journal` | `test_settings.py` |

Differences from the text above:

- The Google libraries stay in the `spikes` dependency group (§9). A separate `google` group needs `uv lock`, which wasn't available where this was built.
- Push-to-talk while working replaces ADR-009's "Swift is still busy" nudge: the working card now shows Listening / Transcribing and the hint instead.
- On Swift's send card, "show me" expands the clipped draft in place, rather than opening a separate view.
