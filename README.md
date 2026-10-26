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

**Email workflow and "show me" (ADR-010), no microphone or Google account:** start the backend from the `backend-harness` entry in `.claude/launch.json` (or `--config overlay/dev/harness-config.yaml`: debug on, the fake email connector, logs in `%TEMP%\swift-harness`). The harness then shows buttons: **Email demo** runs find_contact → draft_email → send_email through Swift's real tools and gateway; **Say “show me”**, **“hide that”**, **“approve”** and **“stop”** send typed text as if spoken mid-run (`debug.say`). Nothing is ever sent: debug mode always uses the fake connector.

It tests rendering and the protocol only. Window behavior (focus, click-through, capture exclusion, dragging) needs the real Tauri build. Add `&anchor=top-right` (or any other anchor) to the URL to check a placement, or call `__shim.emit("placement", {anchor: "top-left"})`.

### Moving the overlay

Drag any card by its header: the overlay snaps to the nearest of six spots (top or bottom; left, centre or right) and remembers it. The tray menu's **Position** submenu offers the same choices. With **Move away from where I'm typing** on (the default), Swift opens at the opposite edge when its cards would cover the text caret of the app you're typing in. The choice is saved in `%LOCALAPPDATA%\Swift\overlay.json`. See [ADR-009](docs/decisions/ADR-009-overlay-ux.md).

## Push-to-talk (Milestone 2)

Hold **Ctrl+Shift+Space** (configurable: `hotkeys.push_to_talk`), speak, and release. The orb reacts to your voice. After release Swift transcribes on this PC and shows what it heard. Until Claude Code is wired in (Milestone 3), the default `executor.kind: "echo"` only displays the transcript; nothing leaves the machine.

- **Wait for the orb before speaking.** By default the microphone opens only while the key is held. On the development laptop, audio starts 0.35–0.6 s after the key goes down; anything said before that is lost.
- **Pre-roll (optional, off by default).** Set `audio.preroll_s: 0.5` in `config.yaml` and Swift keeps the microphone stream open, holds the last 0.5 s in memory, and prepends it when you press the key, so the first word is no longer clipped. **Privacy trade-off:** the microphone is then open whenever Swift runs, so Windows shows its mic-in-use indicator all the time. Nothing is recorded or stored while the key is up: the buffer is RAM only and is overwritten every half second; it leaves the process only if you press the key. Each interaction-log line records `preroll_ms` (audio prepended) and `first_audio_ms` (key-down to the first live block, about 10 ms with pre-roll). If the stream can't be opened, Swift opens the mic per request as before.

  Measured on the development laptop (`spikes/latency/preroll_probe.py`, 8 reps, WASAPI 16 kHz, Intel SST mic array):

  | Approach | Key-down to first audio | Idle cost |
  |---|---|---|
  | Open on key-down (default) | 335–430 ms median (290–885 ms range) | none |
  | Stream kept open but stopped, `start()` on key-down | 43–63 ms median (up to 260 ms) | 0.0% CPU, RSS unchanged (44-45 MB) |
  | Stream running (pre-roll) | next block, 4–35 ms; 0.5 s of audio already buffered | 1.4–4.4% of one core (varies between runs), RSS 45 MB, ring 16 KB |

  A stopped-but-open stream restarts quickly, but it still leaves ~45–60 ms unrecorded and holds the device, and I could not confirm from the development session whether Windows shows the mic indicator for a stopped stream, so it isn't implemented. Check by eye (open a stopped stream, look at the tray) before building on it.
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

### Routing and models (ADR-007)

Swift decides where each transcript goes before anything leaves the PC:

- **Commands to Swift** are handled at once, with no model. These are "stop", "cancel", "never mind", "repeat that", and "what can you do". Only the whole utterance counts: "stop reminding me…" is a request.
- **Time and date** are answered on this PC.
- **Opening things** ("open my downloads folder", "launch Chrome", "open the Swift project in VS Code") is done by Swift, with no model. Only names in the `local` section of `config.yaml` are opened: apps (default VS Code, Chrome, Notepad, Explorer), folders (Documents, Downloads, Desktop plus your own), and projects (`executor.working_dirs` by folder name plus `local.projects`). Unknown names ("open the thesis project") and compound requests ("open it and run the tests") go to Claude Code. The log records `route: local`, `action: open`, `target`.
- **Everything else goes to Claude Code**, on a model chosen by how demanding the request looks:
  - **light** (questions, lookups, short drafts, single commands) starts on **Haiku**
  - **standard** (changes, investigations, and anything unclear) starts on **Sonnet**
  - how demanding: keyword phrases first ("fix", "why does…", "what's in…"); where they can't tell, Sonnet, or a small local classifier (below) when `demand_classifier.enabled` is on
  - **"use opus …"** or **"use haiku …"** at the start picks the model, and **"think hard about …"** asks for Opus.
- **Escalation:** a run moves up mid-request (Haiku → Sonnet → Opus, never down) and keeps its context. It moves when:
  - Claude calls `request_stronger_model`
  - Swift sees it struggling: more than `turn_limits` steps on one model, or tool calls failing twice in a row

  The overlay shows "Switching to Sonnet: …". `confirm_strong: true` asks before Opus.
- **Follow-ups:** each request is a fresh Claude Code process, so Swift itself passes on the last exchange. A request within `followup_context_s` (default 300 s, 0 = off) of the previous Claude answer is sent with that request, its answer and any approved actions, clipped. This makes "now commit it" or "how many functions are in it?" work. Only one exchange is kept. An error, a cancelled run, or saying "new topic" / "start over" clears it. The interaction log records `context: {previous, age_s}`.
- **Settings** (`config.yaml`): `routing`, `local`, `demand_classifier`, `executor.models`, `executor.escalation`, `executor.confirm_strong`, `executor.turn_limits`. The interaction log records `route`, `demand`, `start_model`, `models` and `escalations`.
- **Measured** (`spikes/routing/live_escalation.py`):
  - a light question on Haiku cost $0.0013, against about $0.03 on Sonnet
  - Haiku asked for Sonnet by itself 5.5 s into a refactoring request
  - on the 94 held-out requests in `eval/routes.jsonl`, the rules dropped none and never started standard work on Haiku

#### Demand classifier (ADR-007 §4)

A sentence-embedding model (`bge-small-en-v1.5`, int8 ONNX, 34 MB) compares the request with labeled examples and votes light or standard. It answers only where the keyword phrases can't place a request, and says light only when at least 70% of the nearest examples' weight agrees (`demand_classifier.threshold`). It loads in the background (about 5 s); until then, or without the model, the keywords answer alone.

```powershell
# bge-small -> %LOCALAPPDATA%\Swift\models\bge-small-en-v1.5 (about 35 MB; add 'onnx/model.onnx' for the 133 MB fp32 model)
.venv\Scripts\python.exe -c "import os; from huggingface_hub import snapshot_download; snapshot_download('Xenova/bge-small-en-v1.5', local_dir=os.path.expandvars(r'%LOCALAPPDATA%\Swift\models\bge-small-en-v1.5'), allow_patterns=['config.json', 'tokenizer.json', 'onnx/model_int8.onnx'])"
```

- **Measured** on the 94 held-out requests (`spikes/routing/eval_classifier.py`), against the keywords alone:
  - demand right 97.3% of the time (keywords: 94.5%)
  - Sonnet used for light work 1 time out of 55 light requests (keywords: 4)
  - Haiku given standard work 1 time out of 13 standard requests (keywords: 0). The miss: "tell me which strategy is most promising and why", a judgment call that reads like a lookup. Escalation (above) is the backstop.
  - no requests dropped, so route accuracy is unchanged
  - 14–18 ms per request (p95 35 ms, with other work running), about 97 MB more memory
- **Settings:** `demand_classifier.enabled` (default `false`: on the test split it started 1 of 13 standard requests on Haiku, where the keywords alone started none; turn it on to try it), `threshold`, `quantized` (`false` uses the fp32 model: same accuracy, about 20 ms, 183 MB), `model_dir`, `examples_file`.
- **Learning from use:** `spikes/routing/learn_demand.py` reads the interaction log and proposes examples. A light request that escalated becomes a standard example. A standard request that finished in one or two turns, with no escalation and no file edits, becomes a light candidate. You answer y/n for each. Kept examples go to `%LOCALAPPDATA%\Swift\demand_examples.jsonl` and load at startup, after the built-in ones (the train split of `eval/routes.jsonl`). Rerun it every week or so.

```powershell
uv run python spikes/routing/learn_demand.py          # review proposed examples
uv run python spikes/routing/learn_demand.py --list   # show the ones you kept
```

### Approving actions (Milestone 5)

When Claude Code wants to use one of the `confirm_tools`, the overlay shows a card saying exactly what will happen. For example, "Create or overwrite notes.md: 3 lines into docs\notes.md", "Edit a.py: replace … with …", or "Run a command: git commit -m …".

- **Approve** lets that one call run.
- **Reject**, or no answer within `confirm_timeout_s`, denies it, and Claude Code **stops** (status `rejected`).
- **Esc** cancels the whole run.
- **By voice:** while the card is open, hold the hotkey and say "approve" (or "yes", "go ahead") or "reject" (or "no"). "Stop" or "cancel" cancels the run like Esc. Anything else shows a hint on the card and leaves it open. Push-to-talk is only accepted on an open card; at other times during a run it is still ignored. If you click while a spoken answer is being transcribed, the click wins.

Every decision is recorded in the interaction log's `approvals`, with `source` (`voice` or `click`) and `heard` (what was said on the card). Paths inside the working folder are shown relative to it; a path **outside** it is shown in full, so it stands out.

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
- **Claude Code is started ahead of time** (`executor.prewarm: true`, the default). Starting `claude` takes 5–13 s on this laptop before the model is even called. So Swift keeps one started and waiting (about 96 MB), sends your request to it, and starts a fresh one after every request, so requests stay independent. With it, Claude Code's first step shows 0.2–0.4 s after the transcript, and a one-word answer arrives in 2–2.6 s instead of about 9 s. A request made within about 5 s of the previous answer waits for the next one to finish starting. Measure it with `spikes/latency/claude_startup.py`.
- **Measured on the development laptop (before pre-warming):**
  - a read-only question took 7–8 s
  - a file write with approval took 5–7 s
  - Reject stopped the run 0.2 s after the click, and Esc 0.4–0.5 s after
  - each request cost $0.005–0.05

### Speech model

Two engines, picked with `stt.engine` in `config.yaml`:

| Engine | Model | Accuracy on the owner's voice | Typical request | Memory |
|---|---|---|---|---|
| `parakeet` (default) | NVIDIA Parakeet-TDT 0.6B v2, int8, via `onnx-asr` | 5.2% character errors | 0.6–1.2 s | about 780 MB |
| `whisper` | faster-whisper `small.en`, beam 5 | 4.9% character errors | 4.3–4.8 s | about 340 MB |

Accuracy and speed are from `spikes/stt` on 40 read requests, plugged in. Memory is weights plus inference buffers (USS). Whisper's `model: "base.en"` with `beam_size: 1` uses less memory but makes about twice as many errors.

- **Offline only:** the backend never downloads a model. Fetch the one you use once:

```powershell
# Parakeet -> %LOCALAPPDATA%\Swift\models\parakeet-tdt-0.6b-v2 (about 630 MB)
.venv\Scripts\python.exe -c "import os; from huggingface_hub import snapshot_download; snapshot_download('istupakov/parakeet-tdt-0.6b-v2-onnx', local_dir=os.path.expandvars(r'%LOCALAPPDATA%\Swift\models\parakeet-tdt-0.6b-v2'), allow_patterns=['config.json', 'vocab.txt', '*.int8.onnx'])"
# Whisper -> %LOCALAPPDATA%\Swift\models\whisper
.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; import os; WhisperModel('small.en', device='cpu', compute_type='int8', download_root=os.path.expandvars(r'%LOCALAPPDATA%\Swift\models\whisper'))"
```

- **Silence:** both engines skip near-silent recordings and trim silence at the start and end before transcribing.
- **Word fixes (both engines):** a phrase the model keeps mishearing can be corrected after transcription, for example `word_fixes: {"tori": "Tauri"}` in `config.yaml`. Matching ignores case, only whole words match, and spaces and hyphens are treated alike. When a fix changes a transcript, the interaction log keeps the original as `transcript_raw`.
- **Learned word fixes:** `spikes/stt/learn_fixes.py` transcribes your test set (below), finds the phrases the engine got wrong, and asks you about each one. The ones you keep go to `%LOCALAPPDATA%\Swift\word_fixes.json` (`stt.word_fixes_file`), loaded at startup. Fixes in `config.yaml` win over learned ones. Reject fixes that would change a real word, such as "deadlock" → "git log". Rerun it as you label more recordings.
- **Vocabulary (Whisper only):** put names and jargon you say often in `initial_prompt`. Whisper follows its spelling. Parakeet has no prompt, so use word fixes instead.
- **Hearing what the model heard:** set `save_audio: true` and each push-to-talk is saved as `<interaction id>.wav` in `audio_dir` (default `%LOCALAPPDATA%\Swift\audio`). The interaction log's `audio_file` names it. The files stay on this PC; delete them whenever you like, and turn this off when you're done.

### Comparing speech models on your voice

`spikes/stt/` measures how accurate and how fast each candidate model is on **your** recordings. It's a separate dependency group: Swift itself doesn't use it.

```powershell
uv sync --group sttbench
uv run --group sttbench python spikes/stt/corpus.py read        # read ~40 sentences aloud (about 10 min)
uv run --group sttbench python spikes/stt/corpus.py label       # correct transcripts of Swift's saved recordings
uv run --group sttbench python spikes/stt/bench.py --download   # fetch every model once (~1.5 GB)
uv run --group sttbench python spikes/stt/bench.py              # WER and speed per model
uv run --group sttbench python spikes/stt/learn_fixes.py        # review word fixes for Swift's engine
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

**Since the switch to Parakeet (2026-10-23, i7-10610U, plugged in):** the speech model takes about 780 MB once loaded and used (685 MB of weights plus about 90 MB of inference buffers). Whisper `small.en` took about 340 MB. With Parakeet the whole tree is therefore around 880 MB. Loading takes about 6.7 s for either model, in the background; the backend's ready line still comes in about 1 s.

Task Manager's "Commit size" (private bytes) is much larger, about 1.3 GB for the backend. That's memory the libraries reserve but don't touch; CTranslate2 alone commits about 1 GB when the model loads. Swift sets `OPENBLAS_NUM_THREADS=1`, which removes another 225 MB that numpy would reserve. Earlier milestones reported private bytes, which overstated the real footprint.

**Speed.**

| | |
|---|---|
| Launch to usable (overlay connected, hotkeys registered) | 2.2–2.3 s (logged as `overlay ready startup_ms=` in `swift.log`) |
| Model ready | about 1.3 s after that, in the background; a push-to-talk before then waits |
| Key-down to first audio | 0.24–0.6 s |
| Transcription of a 2 s push-to-talk | 0.4–2.8 s, depending on CPU load |
| Small read-only Claude Code request | about 7 s (2–5 s with `prewarm`, since 2026-10-23) |

## Tray menu

Only one copy of Swift runs at a time. Launching it again while it's running shows "Swift is already running" on the overlay, and the new copy exits.

- **Open logs folder:** opens `%LOCALAPPDATA%\Swift`, where the interaction log and the app log live.
- **Quit Swift:** closes the overlay and the backend, and any Claude Code run with them.

## Milestone 1: what to try

With `debug: true` in `config.yaml`, press **Ctrl+Alt+F12**. Each press plays the next scenario: `happy` → `confirm` → `error` → `long` → `email`. Each one shows the listening orb with a fake mic level, then the transcript and the working steps, and ends on a result or error card.

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

## Wake phrase (hands-free)

Set `wake.enabled: true` in `config.yaml` and say "hey Swift", "hello Swift" or "good afternoon Swift" (also "hi", "ok", "good morning/evening", and sound-alikes such as "hey swiff"). Say the request in the same breath ("hey Swift, what time is it") or wait for the listening card and say it after; it ends when you stop talking. The hotkey keeps working.

There is no wake-word model: the open microphone is cut into short utterances, each is transcribed locally by the speech model Swift already uses, and anything that doesn't start with a greeting plus "Swift" is dropped unlogged (`src/swift/wake.py`). Costs: Windows' mic-in-use indicator stays on while Swift runs, and the speech model runs on every short utterance in earshot. Add greetings with `wake.greetings`.

With wake listening on, you don't need the hotkey or the wake phrase to answer Swift:
- **During a run:** say "show me", "hide that" or "stop".
- **On a confirm card:** say "reject", "no" or "stop". **Approving needs Swift's name**, "Swift, approve" (or a click or the hotkey), so a TV or someone nearby saying "yes" can't approve anything.
- **After an answer:** for 8 seconds (`wake.followup_s`; 0 turns it off), just reply. The card shows "Listening for a reply… N s".

- **To change what a card shows**, whatever it is (an email, an event, a file edit) and whichever agent asked, say what to change: "no, make it Friday at three". Hands-free, start with its name: "Swift, make it Friday". The agent revises it and you get a new card. If an agent can't revise in place, Swift says no to that card and asks again with your change. A question ("is that the notes file?") leaves the card open.

Other speech near the microphone is ignored.

Swift does not yet pause wake listening when the PC is locked ([threat model](docs/threat_model.md) T7); edits and commands still need your approval on the overlay.
