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
- **The mic stays open 0.3 s after you release,** so the last word isn't cut off.
- **Silence is skipped.** If the loudest 32 ms of a recording is below -50 dBFS, Swift says "I didn't catch that" without running Whisper. The interaction log records each recording's `peak_db`, so you can check your mic level.
- **Esc** after releasing cancels the transcription. A tap shorter than 0.3 s is ignored.

### Sending requests to Claude Code

Set this in `config.yaml`:

```yaml
executor:
  kind: "claude_code"
  working_dirs: ["C:/Users/me/Projects/thesis"]   # Claude Code runs here; trusted folders only
  allowed_tools: ["Read", "Glob", "Grep"]         # run without asking (keep these read-only)
  confirm_tools: ["Edit", "Write", "Bash"]        # each call asks on the overlay first
  max_budget_usd: 1.0                             # per request
  confirm_timeout_s: 120                          # no answer = rejected
```

Then hold the hotkey and ask, for example, "What's in the executors folder?". Steps stream into the overlay as Claude Code works, and the result card shows its answer. **Esc** stops the run.

### Approving actions (Milestone 5)

When Claude Code wants to use one of the `confirm_tools`, the overlay shows a card saying exactly what will happen. For example, "Create or overwrite notes.md: 3 lines into docs\notes.md", "Edit a.py: replace … with …", or "Run a command: git commit -m …".

- **Approve** lets that one call run.
- **Reject**, or no answer within `confirm_timeout_s`, denies it, and Claude Code **stops** (status `rejected`).
- **Esc** cancels the whole run.

Every decision is recorded in the interaction log's `approvals`. Paths inside the working folder are shown relative to it; a path **outside** it is shown in full, so it stands out.

**How Swift runs it.** Swift uses the Python Agent SDK (`claude-agent-sdk`), with your installed `claude` CLI:
- `allowed_tools` are pre-approved. `confirm_tools` exist, but each call goes to the overlay first. No other tool exists.
- **Settings files are not loaded** (`setting_sources=[]`), so an "allow" rule in your Claude settings can't skip the card.
- MCP servers from the project are not loaded (`--strict-mcp-config`), and sessions are not saved.
- Claude Code's `AskUserQuestion` is answered automatically with "make an assumption and say so". There is no way to answer it by voice yet.
- It uses your normal Claude Code login. Swift never sees credentials.

**Things to know:**
- **Read-only shell commands skip the card.** Claude Code auto-approves its built-in set of read-only commands (such as `ls` or `git status`) even when `Bash` needs confirmation. Anything that changes files or state still asks.
- **This sends your transcript to Anthropic,** as any Claude Code request does. Transcription itself stays on this PC.
- **Only add folders you trust.** Claude Code reads and may act on what's there.
- **Esc kills the run** and everything it started. `claude` ignores Ctrl+Break on Windows, so there is no gentler stop.
- **Measured on the development laptop:**
  - a read-only question took 7–8 s
  - a file write with approval took 5–7 s
  - Reject stopped the run 0.2 s after the click, and Esc 0.4–0.5 s after
  - each request cost $0.005–0.05

### Speech model

- **Where it lives:** `%LOCALAPPDATA%\Swift\models\whisper` (faster-whisper format: `small.en` by default, `base.en` optional).
- **Offline only:** the backend never downloads it. To fetch it once:

```powershell
.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; import os; WhisperModel('small.en', device='cpu', compute_type='int8', download_root=os.path.expandvars(r'%LOCALAPPDATA%\Swift\models\whisper'))"
```

- **Accuracy vs. speed** (`stt` in `config.yaml`): `small.en` with `beam_size: 5` is the default. `base.en` with `beam_size: 1` is about 2.5× faster but much less accurate.
- **Vocabulary:** put names and jargon you say often in `initial_prompt`. Whisper follows its spelling.
- **Hearing what Whisper heard:** set `save_audio: true` and each push-to-talk is saved as `<interaction id>.wav` in `audio_dir` (default `%LOCALAPPDATA%\Swift\audio`). The interaction log's `audio_file` names it. The files stay on this PC; delete them whenever you like, and turn this off when you're done.

### Comparing speech models on your voice

`spikes/stt/` measures how accurate and how fast each candidate model is on **your** recordings. It's a separate dependency group: Swift itself doesn't use it.

```powershell
uv sync --group sttbench
uv run --group sttbench python spikes/stt/corpus.py read        # read ~40 sentences aloud (about 10 min)
uv run --group sttbench python spikes/stt/corpus.py label       # correct transcripts of Swift's saved recordings
uv run --group sttbench python spikes/stt/bench.py --download   # fetch every model once (~1.5 GB)
uv run --group sttbench python spikes/stt/bench.py              # WER and speed per model
```

- **The test set** lives in `%LOCALAPPDATA%\Swift\stt_corpus`, never in git. `read` records you reading `spikes/stt/prompts.txt`. Recording starts before you speak, so nothing is clipped. `label` works through push-to-talk clips Swift saved (`stt.save_audio: true`), which are closer to real use.
- **Models compared:**
  - faster-whisper `small.en` (beam 5 and beam 1), `base.en` and `distil-small.en`
  - Moonshine base and tiny
  - NVIDIA Parakeet-TDT 0.6B v2, int8 via `onnx-asr`
- **For fair timings,** run plugged in, with Windows power mode on "Best performance". This laptop's CPU slows down on battery and when hot.
- **Results** are written to `spikes/stt/results/`, which is gitignored because it contains your transcripts.
- **Note:** `uv sync --group sttbench` removes the Phase 0 `spikes` group packages from `.venv`. `uv sync` restores the normal setup.

## Performance

Measured on the development laptop (i5, 4 cores / 8 threads, 16 GB RAM, CPU only), release build, `base.en` int8.

**Memory.** These figures are USS: memory only this process holds, which is what is freed if it exits.

| Process | USS |
|---|---|
| Backend (Python) before the model loads | 38 MB |
| Speech model, loaded and used (weights plus inference buffers) | about 143 MB |
| Backend total, model loaded | 168–170 MB |
| WebView2 (6 processes) | 75–76 MB |
| Overlay (`swift-overlay.exe`) | 6.6 MB |
| **Whole tree, idle, model loaded** | **250–254 MB** |

Excluding the model, the tree uses about 110 MB, inside the 300 MB target.

Task Manager's "Commit size" (private bytes) is much larger, about 1.3 GB for the backend. That's memory the libraries reserve but don't touch; CTranslate2 alone commits about 1 GB when the model loads. Swift sets `OPENBLAS_NUM_THREADS=1`, which removes another 225 MB that numpy would reserve. Earlier milestones reported private bytes, which overstated the real footprint.

**Speed.**

| | |
|---|---|
| Launch to usable (overlay connected, hotkeys registered) | 2.2–2.3 s (logged as `overlay ready startup_ms=` in `swift.log`) |
| Model ready | about 1.3 s after that, in the background; a push-to-talk before then waits |
| Key-down to first audio | 0.24–0.6 s |
| Transcription of a 2 s push-to-talk | 0.4–2.8 s, depending on CPU load |
| Small read-only Claude Code request | about 7 s |

## Tray menu

Only one copy of Swift runs at a time. Launching it again while it's running shows "Swift is already running" on the overlay, and the new copy exits.

- **Open logs folder:** opens `%LOCALAPPDATA%\Swift`, where the interaction log and the app log live.
- **Quit Swift:** closes the overlay and the backend, and any Claude Code run with them.

## Milestone 1: what to try

With `debug: true` in `config.yaml`, press **Ctrl+Alt+F12**. Each press plays the next scenario: `happy` → `confirm` → `error` → `long`. Each one shows the listening orb with a fake mic level, then the transcript and the working steps, and ends on a result or error card.

- **Esc** cancels while Swift is listening, working or waiting for approval. Swift only claims Esc during those states.
- On the confirm card, **Approve** and **Reject** are clickable. Everywhere else, clicks pass through to the window below.
- Result cards fade after 6 s and error cards after 8 s. Hovering pauses the timer, and clicking a card dismisses it.
- **Quit:** tray icon → *Quit Swift*.

## Tests

```powershell
uv run pytest                     # Python: protocol, executors and the approval bridge, session, server, settings, push-to-talk, log
cd overlay; npm run typecheck     # TypeScript
cd overlay/src-tauri; cargo test  # Rust: hit-testing and multi-monitor/DPI placement
```

## Logs and data

Everything stays on this machine:

- **App log:** `%LOCALAPPDATA%\Swift\logs\swift.log`, with secrets and transcripts redacted.
- **Interaction log:** `%LOCALAPPDATA%\Swift\interactions.jsonl` (path: `logging.interactions`). One JSON line per interaction:
  - `ts` and `id`; `source` is `voice`, `debug.run` or `debug.ask`
  - `transcript` (in full), `audio_s`, `first_audio_ms`, `stt_ms`, `stt_model`
  - `peak_db` (loudest 32 ms, dBFS) and `audio_file` (only with `stt.save_audio: true`)
  - `executor`, `run_ms` (the agent's run) and `interaction_ms` (key-down to result)
  - `steps`: `[{t_ms, text}]`
  - `status`: `done`, `cancelled`, `error` or `rejected`, with `error` (a code) and `reason`
  - `approvals`: `[{tool, decision, asked_ms, answered_ms}]`
  - `cost_usd`, `turns`, `denied` and `exit_code` for Claude Code runs

  It is never uploaded. Delete it whenever you like.

## Layout

```
overlay/             Tauri v2 shell (Rust in src-tauri/, TypeScript in src/)
src/swift/           Python backend: ipc/, audio/, stt/, executors/, session.py, runlog.py, settings.py
tests/unit/          Python unit tests
spikes/              Phase 0 measurements (reference only)
docs/decisions/      Architecture decision records
```
