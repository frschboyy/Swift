# Swift

A voice overlay for Windows 11. Hold a hotkey, speak, and Swift sends the request to an existing agent (Claude Code, headless), showing progress and results in a transparent overlay that never takes keyboard focus.

**Status:** MVP Milestone 1 (overlay shell driven by a mock executor). The plan is [`PLAN.md`](PLAN.md); the change of direction is recorded in [ADR-006](docs/decisions/ADR-006-voice-overlay-mvp.md). The original v2.0 spec, [`SWIFT_BUILD_PROMPT.md`](SWIFT_BUILD_PROMPT.md), is paused.

## Requirements (Windows 11)

| Tool | Notes |
|---|---|
| Python 3.12 (64-bit) + [`uv`](https://docs.astral.sh/uv/) | The backend runs from the repo's `.venv`. |
| Rust stable, MSVC target (`rustup`) | Builds the Tauri shell. |
| Visual Studio 2022 Build Tools, "Desktop development with C++" | Needed by Rust's MSVC target. |
| Node.js 20+ and npm | Frontend tooling; installed locally in `overlay/`. |
| WebView2 runtime | Ships with Windows 11. |

## Setup

From the repository root, in PowerShell:

```powershell
uv sync --frozen                  # backend dependencies into .venv
Copy-Item config.example.yaml config.yaml
cd overlay
npm ci                            # frontend + Tauri CLI, local to overlay/
```

If `uv` isn't on your PATH, it may be in `%APPDATA%\Python\Python313\Scripts`.

## Run (development)

```powershell
cd overlay
npm run tauri dev
```

The first build compiles the Rust side and takes several minutes; later runs are incremental. Build from PowerShell or cmd, not Git Bash: Git Bash's `/usr/bin/link` shadows the MSVC linker `link.exe` and the build fails with `link: extra operand`. Tauri starts the Python backend itself (`.venv\Scripts\python.exe -m swift.backend --config config.yaml`) inside a Job Object, so quitting Swift also stops the backend.

Overrides (environment variables, development only):

- `SWIFT_PYTHON`: a different Python interpreter for the backend.
- `SWIFT_ROOT`: the repository root, if the overlay was built elsewhere.
- `SWIFT_BACKEND_PORT` + `SWIFT_SESSION_TOKEN`: connect to a backend you started yourself, for example with `python -m swift.backend --token <32+ chars> --console`.
- `SWIFT_DEV_ALLOW_CAPTURE=1`: debug builds only. Leaves the overlay visible to screenshots so its rendering can be checked. Release builds always exclude it from capture.

The overlay's console prints `[overlay] …` diagnostics (placement, hotkeys, click-through changes).

### UI-only harness (no Rust needed)

`overlay/dev/harness.html` runs the overlay UI in an ordinary browser, with a stand-in for Tauri, against a backend you start yourself:

```powershell
.venv\Scripts\python.exe -m swift.backend --config config.yaml --port 8765 --token devharness-token-0123456789abcdef --console
npm --prefix overlay run dev
# open http://localhost:1420/dev/harness.html?port=8765&token=devharness-token-0123456789abcdef
# in the browser console: __shim.emit("hotkey", {name: "debug", state: "down"})
```

It tests rendering and the protocol only. Window behavior (focus, click-through, capture exclusion) needs the real Tauri build.

## Push-to-talk (Milestone 2)

Hold **Ctrl+Shift+Space** (configurable: `hotkeys.push_to_talk`), speak, and release. The orb reacts to your voice. After release Swift transcribes on this PC and shows what it heard. Until Claude Code is wired in (Milestone 3), the default `executor.kind: "echo"` only displays the transcript; nothing leaves the machine.

- **Wait for the orb before speaking.** The microphone opens only while the key is held. On the development laptop, audio starts 0.35–0.6 s after the key goes down; anything said before that is lost.
- **Hotkey conflicts.** If another app already owns the hotkey, Swift shows an error card naming it. Pick another key in `config.yaml`. The default used to be Ctrl+Alt+Space, but another app owned it on the development laptop.
- **Esc** after releasing cancels the transcription. A tap shorter than 0.3 s is ignored.

### Sending requests to Claude Code (Milestone 3)

Set this in `config.yaml`:

```yaml
executor:
  kind: "claude_code"
  working_dirs: ["C:/Users/me/Projects/thesis"]   # Claude Code runs here; trusted folders only
  allowed_tools: ["Read", "Glob", "Grep"]         # read-only by default
  max_budget_usd: 1.0                             # per request
```

Then hold the hotkey and ask, for example, "What's in the executors folder?". Steps stream into the overlay as Claude Code works, and the result card shows its answer. **Esc** stops the run.

**How Swift runs it:**
- `claude -p --output-format stream-json`, with the request on stdin, never on the command line.
- Only `allowed_tools` exist, and in `dontAsk` mode anything else is denied (shown as "Blocked: …"). Approving other actions from the overlay arrives in Milestone 5.
- MCP servers from the project are not loaded (`--strict-mcp-config`), and sessions are not saved (`--no-session-persistence`).
- Uses your normal Claude Code login. Swift never sees credentials.

**Things to know:**
- **This sends your transcript to Anthropic,** as any Claude Code request does. Transcription itself stays on this PC.
- **Only add folders you trust.** Without `--bare`, `claude -p` still runs the project's hooks and reads its `CLAUDE.md`, with no trust prompt.
- **Esc kills the run** and everything it started. `claude` ignores Ctrl+Break on Windows, so there is no gentler stop.
- **Measured on the development laptop:** a small read-only question took about 7 s and $0.04; Esc stopped a run within 0.4 s.

### Speech model

- **Where it lives:** `%LOCALAPPDATA%\Swift\models\whisper` (faster-whisper format: `base.en` by default, `small.en` optional).
- **Offline only:** the backend never downloads it. To fetch it once:

```powershell
.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; import os; WhisperModel('base.en', device='cpu', compute_type='int8', download_root=os.path.expandvars(r'%LOCALAPPDATA%\Swift\models\whisper'))"
```

**Measured on the development laptop** (i5, 4 cores / 8 threads, 16 GB, CPU only, debug build):

| | base.en, int8 |
|---|---|
| Model load (background, after the backend is ready) | 2.4–7.5 s; slower when the overlay is starting at the same moment |
| Model memory (private bytes added by loading) | 1,012–1,019 MB |
| Backend total with model loaded, after transcribing | 1,422 MB private |
| Overlay + WebView2 | about 160 MB private |
| Transcription, 5 s recorded clip | 1.15 s once warm |
| Transcription, 2 s push-to-talk | 0.4–2.8 s (depends on CPU load) |

The 300 MB idle target is **not met yet**. Excluding the model's own 1,012 MB, the whole tree uses about 570 MB: 160 MB for the overlay, and about 410 MB in the backend for faster-whisper's libraries (CTranslate2, onnxruntime for its voice filter, PyAV) and inference buffers. Reducing this is Milestone 4 work.

## Milestone 1: what to try

With `debug: true` in `config.yaml`, press **Ctrl+Alt+F12**. Each press plays the next scenario: `happy` → `confirm` → `error` → `long`. Each one shows the listening orb with a fake mic level, then the transcript and the working steps, and ends on a result or error card.

- **Esc** cancels while Swift is listening, working or waiting for approval. Swift only claims Esc during those states.
- On the confirm card, **Approve** and **Reject** are clickable. Everywhere else, clicks pass through to the window below.
- Result cards fade after 6 s and error cards after 8 s. Hovering pauses the timer, and clicking a card dismisses it.
- **Quit:** tray icon → *Quit Swift*.

## Tests

```powershell
uv run pytest                     # Python: protocol, executors (incl. a fake claude CLI), session, server, settings, push-to-talk
cd overlay; npm run typecheck     # TypeScript
cd overlay/src-tauri; cargo test  # Rust: hit-testing geometry
```

## Logs and data

Everything stays on this machine:

- **App log:** `%LOCALAPPDATA%\Swift\logs\swift.log`, with secrets and transcripts redacted.
- **Interaction log (JSONL, from Milestone 4):** `%LOCALAPPDATA%\Swift\interactions.jsonl`.

## Layout

```
overlay/             Tauri v2 shell (Rust in src-tauri/, TypeScript in src/)
src/swift/           Python backend: ipc/, executors/, session.py, settings.py
tests/unit/          Python unit tests
spikes/              Phase 0 measurements (reference only)
docs/decisions/      Architecture decision records
```
