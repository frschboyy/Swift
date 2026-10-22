# Swift MVP — Plan (voice overlay that dispatches to Claude Code)

Status: **awaiting owner approval.** No code has been written for this MVP yet.

## 0. Decisions needed before Milestone 1

1. **This MVP replaces the direction in `SWIFT_BUILD_PROMPT.md` v2.0.** That spec calls for:
   - a tkinter overlay
   - a local LLM through Ollama
   - an `ActionGateway` permission engine
   - Gmail and Calendar tools
   - "cloud LLM off by default"

   The new brief rules all of those out and sends requests to Claude Code, a cloud service. Proposal:
   - Record the switch as `docs/decisions/ADR-006-voice-overlay-mvp.md`.
   - Add a banner at the top of `SWIFT_BUILD_PROMPT.md` saying it is paused, not deleted.
   - Treat the new brief as the authority for this MVP.
2. **System-wide installs.** I need your OK for:
   - **Rust (stable, MSVC target) through `rustup`.** This installs into `%USERPROFILE%\.cargo` and `%USERPROFILE%\.rustup` and edits your user PATH.
   - **`uv`.** It isn't on PATH, although `.venv` exists; the alternative is `.venv\Scripts\python -m pip`.

   Already present: Visual Studio 2022 C++ build tools, WebView2 155, Node 24 / npm 11, Claude Code 2.1.307, and Python 3.12 in `.venv`.
3. **Repository and branch.** Proposal: build on a new branch `mvp/overlay` cut from `phase0/scaffold`, in this repo. Reuse `src/swift/config` and the redacting logger. Leave `spikes/` untouched.
4. **Confirm-flow transport for Milestone 5** (see §7). I recommend option B.

## 1. Architecture

```
┌──────────────── Tauri v2 process (Rust, overlay/src-tauri) ────────────────┐
│ • one overlay window: transparent, no decorations, always on top,           │
│   WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW, WDA_EXCLUDEFROMCAPTURE               │
│ • global shortcuts (push-to-talk, Esc while active, debug key)              │
│ • tray icon with "Quit"                                                     │
│ • click-through controller (cursor polling only while a card is up)         │
│ • starts and owns the Python backend inside a Job Object                    │
│     emits Tauri events ▼            ▲ invoke commands                       │
│ ┌──── WebView2 frontend (overlay/src: vanilla TypeScript + CSS) ──────────┐ │
│ │ renders the 7 states; forwards hotkey events to the backend             │ │
│ └──────────────────────────┬──────────────────────────────────────────────┘ │
└────────────────────────────┼────────────────────────────────────────────────┘
                             │ WebSocket ws://127.0.0.1:<port> + session token
┌────────────────────────────▼──── Python backend (src/swift, asyncio) ──────┐
│ Session state machine (authoritative) ── Recorder (sounddevice, 16 kHz)     │
│        │                                  └─ mic level ~30 Hz → UI          │
│        ├─ Transcriber (faster-whisper, int8, loaded once at startup)        │
│        ├─ Executor interface ── MockExecutor | ClaudeCodeExecutor           │
│        └─ InteractionLog (JSONL)                                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

Design choices, briefly:

- **The backend is a child process, not a Tauri "sidecar".**
  - Tauri sidecars must be a single frozen executable named with the target triple (for example `-x86_64-pc-windows-msvc.exe`). Freezing faster-whisper and CTranslate2 with PyInstaller is fragile and slow to iterate on.
  - Instead, Rust starts `<.venv>\Scripts\python.exe -m swift.backend` (path set in `config.yaml`) and assigns it to a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Quitting Tauri, or Tauri crashing, kills the backend and any `claude` processes under it.
  - For development the backend can also be started by hand, controlled by the `backend.spawn` setting.
- **Tauri owns the hotkeys and the window; Python owns state, audio and execution.** The frontend is a thin renderer: it sends user intents to the backend and draws the state the backend sends back.
- **The window is shown once and never hidden.** In idle it renders nothing and passes every click through. Moving it to another monitor uses `SetWindowPos(..., SWP_NOACTIVATE)`. This avoids the activation risk of Tauri's `show()`, which may call `ShowWindow(SW_SHOW)` and take focus **[verify in M1]**.

## 2. Folder layout (new and changed files)

```
overlay/                      Tauri v2 app
  package.json, tsconfig.json, vite.config.ts, index.html
  src/                        main.ts, ipc.ts, states/*.ts, orb.ts, styles.css
  src-tauri/
    Cargo.toml, tauri.conf.json, capabilities/default.json, icons/
    src/lib.rs                app setup, tray, shortcuts
    src/win.rs                Win32: ex-styles, display affinity, SetWindowPos
    src/hit_test.rs           click-through toggling
    src/backend.rs            spawn backend + Job Object, pass port/token
src/swift/
  backend/__main__.py         entry point: load config, load model, serve
  ipc/protocol.py             message dataclasses + validate/encode/decode
  ipc/server.py               websockets server, token check, single client
  session.py                  state machine (idle→listening→…)
  audio/recorder.py           sounddevice capture + RMS level
  stt/transcriber.py          faster-whisper wrapper
  executors/base.py           Executor protocol + event/result types
  executors/mock.py           scripted steps, optional confirm
  executors/claude_code.py    subprocess + stream-json reader
  executors/claude_mapping.py stream-json event → short step text (pure)
  runlog.py                   JSONL interaction log
  config/…                    extended with the new settings (existing package)
config.example.yaml           committed; config.yaml is gitignored
tests/                        test_protocol.py, test_claude_mapping.py,
                              test_executor_contract.py, test_session.py
```

## 3. IPC protocol (WebSocket, JSON text frames)

- **Transport:** the backend binds `127.0.0.1` only, on port `0` (the OS picks one).
  - Tauri generates a 32-byte random token and passes it to the backend through an environment variable. The backend prints the chosen port on stdout, and Rust reads it.
  - The frontend gets `{port, token}` through a Tauri command.
  - The first frame must be `hello` with the token, or the backend closes the socket. Only one client is accepted at a time.
- **Envelope:** `{"v":1, "type":"<kind>", "ts":<unix ms>, "data":{...}}`. Unknown `type` → `error{code:"bad_message"}`; nothing is ever executed from an unknown message.

| Direction | type | data |
|---|---|---|
| UI → BE | `hello` | `{token, client:"overlay", version}` |
| UI → BE | `ptt` | `{state:"down"\|"up"}` |
| UI → BE | `cancel` | `{}` (Esc) |
| UI → BE | `confirm.reply` | `{request_id, decision:"approve"\|"reject"}` |
| UI → BE | `debug.run` | `{scenario:"happy"\|"confirm"\|"error"\|"long"}` (MockExecutor; only when `debug: true`) |
| BE → UI | `state` | `{state:"idle"\|"listening"\|"transcribing"\|"working"\|"confirm"\|"result"\|"error", run_id?}` |
| BE → UI | `level` | `{rms: 0..1}` (~30 Hz, only while listening) |
| BE → UI | `transcript` | `{text, final:bool}` |
| BE → UI | `step` | `{run_id, text, kind:"tool"\|"text"\|"info", ts}` |
| BE → UI | `confirm.request` | `{request_id, run_id, title, detail, tool}` |
| BE → UI | `result` | `{run_id, status, summary, details?: {kind:"text"\|"list"\|"table", ...}}` |
| BE → UI | `error` | `{code, message, hint}` |

The UI keeps only the last 5 steps. Fade timers (6 s for results, 8 s for errors, paused while the cursor is over the card) live in the UI, which tells the backend nothing about them; the backend returns to `idle` after it sends a `result` or `error`.

## 4. Executor interface

```python
class Executor(Protocol):
    name: str
    async def start(self, request: str) -> str: ...                    # run_id
    def events(self, run_id: str) -> AsyncIterator[ExecEvent]: ...     # {type, text, ts}
    async def cancel(self, run_id: str) -> None: ...
    async def result(self, run_id: str) -> ExecResult: ...             # {status, summary, details}
```

- `ExecEvent.type` is one of `step | confirm | log`. A `confirm` event carries a `request_id` and is answered with `executor.reply(request_id, approve: bool)`. That is the one addition to the interface you described, and Milestone 5 needs it.
- `ExecResult.status` is one of `done | cancelled | error | rejected`.
- **MockExecutor** plays scripted scenarios with delays, including a confirm step and an error, so all 7 states can be driven without Claude.

### ClaudeCodeExecutor (Milestone 3)

Command line:
```
claude -p "<transcript>" --output-format stream-json --verbose
       --tools <config.allowed_tools>  --allowedTools <config.allowed_tools>
       --permission-mode dontAsk  --permission-prompts none
       --strict-mcp-config  --no-session-persistence  [--max-budget-usd N]
cwd = config.working_dir (one of the configured directories)
```
- **Default tools are `Read,Glob,Grep`.** `--tools` limits which tools exist, `--allowedTools` pre-approves them, and `dontAsk` with `--permission-prompts none` denies anything else instead of hanging.
- **The request goes to Claude through `subprocess` argument lists, never `shell=True`.** The transcript is passed as a single argv element.
- **Event mapping (pure function, unit-tested):**
  - `system/init` → "Starting Claude Code…"
  - `assistant` `tool_use` → short phrases such as "Reading `README.md`", "Searching for 'TODO'", or "Running `git status`" (paths shortened to the base name)
  - `assistant` text → the first sentence, truncated to 80 characters
  - `system/permission_denied` → "Blocked: <tool>"
  - `system/api_retry` → "Retrying (rate limit)…"
  - `result` → summary is the `result` text; status is `error` when `is_error` is set
  - Unrecognized event types are ignored, so a newer CLI doesn't break the mapping.
- **Cancel.** On Windows, SIGTERM and SIGINT don't work for a child the way they do on Unix.
  - Start `claude` with `CREATE_NEW_PROCESS_GROUP`.
  - On Esc, send `CTRL_BREAK_EVENT` and wait 2 s, then run `taskkill /T /F /PID`.
  - The Job Object (§1) is the backstop.
  - Whether `claude` handles `CTRL_BREAK` gracefully is **[verify in M3]**.

## 5. Overlay window mechanics (Windows)

| Requirement | Mechanism | Source |
|---|---|---|
| Transparent, no frame | `transparent: true`, `decorations: false`, `shadow: false` (true adds a 1px white border on undecorated windows), CSS `background: transparent` | Tauri config reference |
| Always on top, no taskbar entry | `alwaysOnTop`, `skipTaskbar`, plus `WS_EX_TOOLWINDOW` (also hides it from Alt+Tab) | Tauri; MS Learn |
| Never takes focus | `focus: false`, `focusable: false`, plus `WS_EX_NOACTIVATE` set with `SetWindowLongPtrW`. MS Learn: a window with this style "does not become the foreground window when the user clicks it." | MS Learn |
| Click-through | `set_ignore_cursor_events(true)` by default (see below) | docs.rs `WebviewWindow` |
| Excluded from capture | `SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE=0x11)`, called directly rather than relying on Tauri's `contentProtected`, whose Windows constant I couldn't confirm. Requires Windows 10 2004 or later. | MS Learn |
| Follows the cursor's monitor | When summoned: `cursor_position()` → `monitor_from_point()` → place the window over that monitor's work area, in physical pixels | docs.rs |
| DPI 100–200% | Tauri is per-monitor-DPI aware; layout uses CSS pixels and window placement uses physical pixels from the monitor | **[verify in M4]** |

**Click-through with clickable cards.** While a window ignores cursor events, the webview receives no `mousemove` events, so it can't detect hover by itself.
- The frontend reports the screen rectangles of its interactive elements (`set_hit_regions`), meaning confirm buttons and result cards.
- Only while that list is non-empty, Rust polls `GetCursorPos` every 33 ms. It turns `ignore_cursor_events` off when the cursor enters a rectangle and back on when it leaves.
- When idle, nothing polls.

**Hotkeys** (`tauri-plugin-global-shortcut`, which uses `RegisterHotKey` with `MOD_NOREPEAT`):
- **Push-to-talk (Ctrl+Shift+Space; Ctrl+Alt+Space until M2, see §10b).**
  - `Pressed` starts recording.
  - `Released` is detected by the plugin polling `GetAsyncKeyState` every 50 ms on the **non-modifier key** (Space). This adds up to about 50 ms of release latency.
  - Releasing Ctrl or Alt first does not end the recording; releasing Space does.
- **Esc** is registered **only while** Swift is listening, working or confirming, and unregistered as soon as it returns to idle. While registered, `RegisterHotKey` consumes Esc system-wide, so other apps won't see it during that time. This is a known tradeoff.
- **Debug key (Ctrl+Alt+F12)** cycles MockExecutor scenarios when `debug: true`.

## 6. Audio and STT

- **Capture:** `sounddevice.InputStream(samplerate=16000, channels=1, dtype="int16")` in callback mode, opened on PTT-down and closed on PTT-up.
  - The level is the RMS of each block, compressed with a square root for the orb and throttled to about 30 Hz.
  - Recordings are capped at 60 s, and anything under 0.3 s is discarded as an accidental tap.
- **STT:** `WhisperModel(cfg.model, device="cpu", compute_type="int8", cpu_threads=4)`, created once at startup.
  - `transcribe()` receives a float32 numpy array (its docstring, installed version 1.2.1, says it accepts "the audio waveform"), with `beam_size=1`, `language="en"`, `vad_filter=True`, and `initial_prompt` from config.
  - It runs in a worker thread so the event loop stays responsive.
- **Expected cost (from the earlier spike on this laptop, `spikes/latency/results/stt-20261015-231942.json`):**
  - base.en int8 loads in about 1.3 s.
  - Short clips take about 1.3–1.5 s wall time.
  - Private memory is about 1.0–1.2 GB after load and inference.

  The README will report a fresh measurement from the real backend.

## 7. Safety and the confirm flow (Milestone 5)

**What the installed CLI supports** (documented):
- `--permission-prompt-tool mcp__<server>__<tool>`: an MCP tool that answers permission prompts in `-p` mode.
- `--permission-prompts host|none`
- The Agent SDK `can_use_tool` callback, which returns allow (with `updated_input`) or deny (with `message`) and can stay pending indefinitely.

So real permission routing is possible. Nothing will be faked. The options are:

- **A. `--permission-prompt-tool` (keeps the raw CLI executor from M3).**
  - The backend provides a small stdio MCP server, which `claude` launches through `--mcp-config`. Its tool forwards each request to the backend over localhost and blocks until you approve or reject.
  - Cost: the `mcp` package plus a second local IPC hop.
  - The exact input and return JSON for the tool isn't spelled out on the pages I read **[verify with a probe]**.
- **B. Python `claude-agent-sdk` with `can_use_tool` (recommended).**
  - Documented, in-process, with an explicit allow or deny result. It runs the same `claude` CLI and produces the same message shapes, so the event mapping is reused.
  - Cost: in M5 the executor switches from a raw subprocess to the SDK, and the SDK is a new dependency.
  - The docs mention a "dummy PreToolUse hook" workaround that keeps the stream open.

Under both options:
- **Default policy:** read-only tools are pre-approved, and the allowlist from config is pre-approved.
- **Everything else** reaches the confirm card with the tool name and a one-line summary of what it will do.
- **No answer within `confirm_timeout_s` (default 120 s)** counts as reject.
- **Never used:** `bypassPermissions` or `--dangerously-skip-permissions`.

**Credentials.**
- Swift never reads or stores any; Claude Code uses its own login.
- `--bare` is **not** used, because it needs `ANTHROPIC_API_KEY` and ignores your subscription login.
- Logs and UI text pass through the existing redaction filter.

**Known exposure.** Without `--bare`, `claude -p` loads hooks, `.mcp.json` and CLAUDE.md from the working directory, without a trust prompt. Only add directories you trust to `working_dirs`. `--strict-mcp-config` stops project MCP servers from loading.

## 8. Config (`config.yaml`, gitignored; `config.example.yaml` committed)

```yaml
hotkeys: { push_to_talk: "Ctrl+Shift+Space", debug: "Ctrl+Alt+F12" }
stt: { model: "base.en", cpu_threads: 4, initial_prompt: "" }
executor: { kind: "claude_code", allowed_tools: ["Read", "Glob", "Grep"],
            working_dirs: ["C:/Users/frchi/Documents/Swift"], default_dir: 0,
            max_budget_usd: 1.0, confirm_timeout_s: 120 }
backend: { spawn: true, python: ".venv/Scripts/python.exe" }
logging: { interactions: "%LOCALAPPDATA%/Swift/interactions.jsonl",
           app_log: "%LOCALAPPDATA%/Swift/swift.log" }
debug: false
```

The file is validated with the existing pydantic config layer. Adds dependencies: `pyyaml`, `websockets`, `sounddevice`, `numpy`, `faster-whisper` (moved from the `spikes` group into runtime), and `claude-agent-sdk` in M5 if you pick option B.

## 9. Interaction log (JSONL, one line per interaction)

```json
{"ts":"…","id":"…","transcript":"…","audio_s":3.2,"stt_ms":1410,"stt_model":"base.en",
 "executor":"claude_code","working_dir":"…","run_ms":18230,
 "steps":[{"t_ms":120,"text":"Reading README.md"}],
 "status":"done|cancelled|error|rejected","confirmations":[{"tool":"Edit","decision":"approve","wait_ms":2100}],
 "error":null,"cost_usd":0.04,"swift_version":"0.2.0"}
```

The log is local only and append-only. Each record is written once, when the interaction ends.

## 10. Milestones and how each is tested

| # | Deliverable | Automated tests | You test |
|---|---|---|---|
| 1 | Overlay shell with MockExecutor driving all 7 states from the debug key | protocol encode/decode/validation, MockExecutor contract, session transitions | Type in Notepad while the overlay animates (no lost keys). Click through the overlay. Approve/Reject buttons work without taking focus. The overlay is invisible to Win+Shift+S and in an OBS or Teams screen share. No taskbar or Alt+Tab entry. |
| 2 | Push-to-talk, recorder, faster-whisper | recorder level math, too-short and cap handling (synthetic audio) | Hold the hotkey and speak: the orb reacts and the transcript appears |
| 3 | ClaudeCodeExecutor | event mapping against recorded stream-json fixtures; cancel path against a fake child process | A spoken read-only request shows live steps and a result card. Esc cancels mid-run. |
| 4 | Multi-monitor, DPI, tray, config, JSONL, startup timing | config validation, runlog schema | Use 2 monitors at 100% and 150–200%. Tray "Quit" leaves no `python` or `claude` processes. Startup is under 3 s (measured and logged). |
| 5 | Confirm flow wired to real permission requests | permission bridge with a fake SDK or MCP host | Ask for an edit: the card appears, and Reject leaves the file unchanged |

## 10a. Milestone 1 findings (2026-10-22, agent-run on the target laptop, debug build)

| Check | Result |
|---|---|
| Focus | PASSED (agent-run). The foreground window was sampled every 50 ms for 30 s while two scenarios ran: Swift was never foreground, and the foreground window never changed. |
| Extended styles | PASSED (agent-run). NOACTIVATE, TOOLWINDOW and TOPMOST are set and APPWINDOW is clear, before and after every click-through toggle. |
| Click-through | PASSED (agent-run). Click-through is on by default, off with the cursor over the Approve button, and back on after the cursor leaves. A synthetic click was not tested, to avoid clicking the owner's apps. |
| Capture exclusion | PASSED (agent-run). `WDA_EXCLUDEFROMCAPTURE` is set, and BitBlt captures of the overlay rect show only the windows underneath. |
| Rendering | PASSED (agent-run). With capture allowed (debug-only `SWIFT_DEV_ALLOW_CAPTURE`), the working, result, approval and cancelled cards render over other apps with a transparent background. |
| Placement | PASSED (agent-run). Bottom-centre of the cursor's monitor: 1080×840 physical at 150%. Multi-monitor is not tested (one monitor). |
| Backend lifetime | PASSED (agent-run). Killing the overlay process also ended the backend; the Job Object works on the crash path. Tray "Quit" is REQUIRES-HW (owner-run). |
| Idle memory | 179 MB private bytes for the whole tree (overlay, 6 WebView2 processes, backend, conhost), debug build, no Whisper model. The working-set sum (429 MB) double-counts shared pages. |

Defects found and fixed during these checks:
- **The window was hidden after the first click-through toggle.** tao re-hides any window it believes is hidden whenever it applies a style flag, and its `show()` activates the window after creation. The window is now created visible with `focus: false`, which tao shows with `SW_SHOWNOACTIVATE`.
- **The window got a taskbar and Alt+Tab entry.** tao rewrote the extended style asynchronously after `set_ignore_cursor_events`, restoring APPWINDOW and dropping TOOLWINDOW. The extended style is now enforced in the subclass's `WM_STYLECHANGING` handler, and click-through is toggled directly through Win32.
- **Vite crashed during rebuilds.** It watched `src-tauri/target` and crashed with EBUSY; Vite now ignores `src-tauri/`.

## 10b. Milestone 2 findings (2026-10-22, agent-run, debug build)

| Check | Result |
|---|---|
| Push-to-talk to transcript | PASSED (agent-run) with synthetic key holds and room audio. Real speech is owner-run. |
| Too-short tap, silence, Esc after release | PASSED (agent-run). A tap is ignored; silence gives "I didn't catch that"; Esc cancels transcription. |
| Mic start latency (key-down to first audio) | 0.35–0.6 s with WASAPI. A cold first open without warm-up was about 1.5 s. |
| Focus while recording | PASSED. Swift was never foreground. |
| Memory | The model adds about 1,012 MB. The rest of the tree is about 570 MB, so the 300 MB target is **not met** (README). Deferred to M4. |

Defects found and fixed:
- **WASAPI failed when PortAudio was set up on another thread** (error -9999, which was misreported as a privacy block). PortAudio is now warmed up on the event-loop thread, and the error message no longer claims a privacy block.
- **Transcription took 12.5 s on 2.7 s of noise.** faster-whisper's temperature fallback decoded the audio up to 6 times; it now does one greedy pass (`temperature=0`).
- **Ctrl+Alt+Space is owned by another app on this PC** (`RegisterHotKey` error 1409). The owner chose Ctrl+Shift+Space as the new default.

Open decision: keeping the mic stream open between presses would remove the 0.35–0.6 s start delay, but Windows would show the mic-in-use indicator all the time.

## 10c. Milestone 3 findings (2026-10-22, agent-run, Claude Code 2.1.307)

| Check | Result |
|---|---|
| Typed request (`debug.ask`) to result through the real backend and `claude` | PASSED (agent-run). Steps streamed; the result card arrived at 7.0 s (≈ $0.04). |
| Esc mid-run | PASSED (agent-run). "Cancelled" 0.4 s after cancel; no `claude.exe` left behind. |
| Tree kill on cancel | PASSED (unit test with a fake CLI): its grandchild process is gone after cancel. |
| Spoken request to Claude Code | REQUIRES-HW (owner-run): needs a real voice. |

Verified CLI behaviour (resolves the M3 assumptions in §11):
- **stream-json and `--verbose`:** the documented examples always pass `--verbose` with `-p --output-format stream-json`, and Swift always does too. Running without it was not tried.
- **No stdin:** with no stdin, `claude -p` waits 3 s for one. The request is now sent on stdin, which also avoids argv quoting and "-"-prefixed transcripts.
- **Ctrl+Break is ignored:** the run continued 55 s to completion. Cancel uses `taskkill /T /F`.
- **Undocumented events:** `rate_limit_event`, `system/task_summary`, `system/thinking_tokens` and `system/post_turn_summary` appear in the stream (one even after `result`). The mapper ignores unknown events.
- **Denials:** `dontAsk` denials arrive as `system/permission_denied` events and in `result.permission_denials`.

## 10d. Milestone 4 findings (2026-10-22, agent-run, release build)

| Check | Result |
|---|---|
| Startup to usable (overlay connected, hotkeys registered) | PASSED (agent-run): 2.16 / 2.32 / 2.32 s. Before moving PortAudio warm-up and model load after the ready line it was 2.5–3.7 s. |
| Idle memory excluding the model (< 300 MB) | PASSED (agent-run): 250–254 MB USS for the whole tree **including** the model (backend 170, WebView2 76, overlay 7). |
| Cleanup when the overlay is killed | PASSED (agent-run): 0 of 10 processes left, 3 times out of 3. |
| Multi-monitor and DPI placement | PASSED (unit tests: 100/125/150/200%, monitors left of / above / right of the primary, small work areas). On real hardware: REQUIRES-HW (owner-run; this laptop has one monitor). |
| JSONL interaction log | PASSED (unit tests: every field in the brief, ordering, a write failure never breaks an interaction). |
| Tray Open logs folder and Quit | REQUIRES-HW (owner-run). |

Corrections to earlier findings:
- **Memory (M2).** The M2 "570 MB excluding the model" was private bytes (commit), not RAM. CTranslate2 commits about 1 GB at model load and numpy's OpenBLAS 225 MB, almost none of it resident. The meaningful figure is USS.
- **OpenBLAS.** `OPENBLAS_NUM_THREADS=1` is now set in `swift/__init__.py`: −225 MB commit, no USS or speed change.
- **Audio thread.** PortAudio calls now run on one dedicated audio thread, so warm-up no longer blocks the event loop. First audio arrived at 244 ms in a check.

## 10e. Milestone 5 findings (2026-10-22/23, agent-run, claude-agent-sdk 0.2.172, Claude Code 2.1.307)

| Check (real backend + SDK + CLI in a scratch sandbox, driven over the overlay protocol) | Result |
|---|---|
| Write request, then Reject on the card | PASSED. Status `rejected`, the run stopped 0.2 s after the click, **no file created**. |
| Write request, then Approve on the card | PASSED. Status `done`, the file was created with the right content. |
| Esc while the card is up | PASSED. Status `cancelled`, no file, no `claude` process left, approval logged as `cancelled`. |
| Read-only question | PASSED. No card. |
| Interaction log | PASSED. Each approval is logged with tool, decision and timing, plus cost and `stopped_by`. |
| Clicking Approve or Reject on the real overlay | REQUIRES-HW (owner-run). |

Findings:
- **`can_use_tool` needs no workaround in this SDK version.** The documented dummy-hook workaround isn't needed: SDK 0.2.172 keeps stdin open while the callback is set.
- **Read-only shell commands bypass the card.** Claude Code auto-approves its built-in read-only commands (`ls -A` here) even with `Bash` in `confirm_tools`. Mutating commands still reach the card. This is documented in the README.
- **Reject stops the run.** Reject and no-answer use `interrupt=True`, so the run stops instead of trying another route.
- **Settings are not loaded.** `setting_sources=[]` means global allow rules can't bypass the card.
- **SDK warning silenced on purpose.** The SDK's `CanUseToolShadowedWarning` about the pre-approved read-only tools is expected and filtered.
- **SDK import cost.** Importing the SDK takes about 3 s cold, so it's now done in the background after the backend is ready.
- **Fixed during the live test:**
  - a cancelled approval had no decision in the log
  - absolute temp paths made the cards hard to read
  - the SDK warning was still printed

## 11. Assumptions I could not verify yet (each gets checked in the milestone named)

M1 status of the first four:
- **Activation and focus:** resolved (see §10a).
- **WebView2 clicks:** still owner-run. A real click on Approve should not activate the window.
- **Capture exclusion covering WebView2:** verified.
- **`hwnd()`:** exists on Windows.

- **M1:** Tauri's `show()` and `set_ignore_cursor_events` keep `WS_EX_NOACTIVATE` and don't activate the window.
- **M1:** Clicking a button inside WebView2 doesn't activate the window even with `WS_EX_NOACTIVATE`. WebView2 hosts its own child windows. If it does activate, the fix is to subclass the window and return `MA_NOACTIVATE` from `WM_MOUSEACTIVATE`.
- **M1:** `WDA_EXCLUDEFROMCAPTURE` on the top-level window also covers WebView2's child surfaces.
- **M1:** The Tauri `hwnd()` accessor exists on Windows. It isn't shown on docs.rs, which documents a Linux build. The fallback is `raw-window-handle`.
- **M2:** `faster-whisper` accepts a float32 waveform at 16 kHz with no resampling. The docstring implies this but doesn't state the sample rate.
- **M3:** `stream-json` with `-p` needs `--verbose`. Every documented example includes it.
- **M3:** `claude` responds to `CTRL_BREAK_EVENT`.
- **M4:** The idle memory target of under 300 MB without the model. WebView2 alone typically uses about 100 MB across its processes; this will be measured, not assumed.
- **M4:** Startup under 3 s. Model load is about 1.3 s; WebView2 cold start is unmeasured.
- **M5:** The exact JSON contract for `--permission-prompt-tool`, if you choose option A.
- **Plugin requirement:** the global-shortcut plugin page says the plugin "requires a Rust version of at least 1.90". The latest stable from rustup will satisfy this.
