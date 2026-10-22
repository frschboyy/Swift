> **Paused (2026-10-22).** The MVP now follows [`PLAN.md`](PLAN.md): a voice overlay that sends requests to Claude Code. See [ADR-006](docs/decisions/ADR-006-voice-overlay-mvp.md). This document is kept for reference and is not the current authority.

# Swift — Build Specification (v2.0)

**A passive, voice-activated desktop agent for Windows**

This document is the authoritative specification for building Swift. Re-read it at the start of every session. Where it conflicts with anything else, including the reference material, your own preferences, or earlier versions of this spec, this document wins. If something here is ambiguous, ask. Don't guess.

> **Provenance:** v2.0 replaces v1.0. It incorporates an independent audit (`Swift-spec-audit.md`) and the owner's decisions recorded in §2. Facts marked **[verify]** were not confirmable during the audit. Check them before relying on them, and report what you find.

---

## 0. Ground rules (non-negotiable)

1. **Clean-room implementation.** The OpenOdin reference project has **no license**. You may read it for general ideas only. Do not copy code, structure, or wording from it. Keep it **outside** the Swift repository (e.g. `../OpenOdin-reference/`). Never commit it.
2. **Plan before code.** At the start of every phase, output a plan in the format in §16, then **wait for the owner's approval** before writing any code.
3. **Phase gating.** Every phase ends with acceptance tests. Do not start phase N+1 until phase N has passed and the owner has confirmed.
4. **Never fabricate results.** Report every test as one of: `PASSED (agent-run)`, `PASSED (owner-run on target)`, `REQUIRES-HW (pending owner run)`, `SKIPPED (reason)`, or `FAILED`.
   - Never report a hardware, audio, Google, or live-LLM test as passed unless it actually ran on the target machine.
   - When you can't run something, write the script and ask the owner to run it and paste the output.
5. **Do not invent numbers.** If you don't know a latency, CPU, RAM, or accuracy figure, write a measurement script and report the measured value with its method.
6. **Security is enforced in code, not in prompts.**
   - Every side effect goes through the `ActionGateway` (§8).
   - Prompts, regex filters, and model behavior are never security controls.
   - Never ship `--dangerously-skip-permissions` or an equivalent.
7. **Local-first, privacy by default.**
   - No audio, transcript, or content leaves the machine unless the owner has explicitly enabled it for that data class (§11).
   - Cloud LLM use is **off** by default.
8. **Target:** Windows 11, Python **3.12** (64-bit), 24 GB RAM, 8-core CPU, no dedicated GPU. Design so that weaker or stronger hardware is handled by configuration (§7.4), not by code changes.
9. **No scope creep.** Do not add features beyond the current phase. Record ideas in `docs/backlog.md`.

---

## 1. Product definition

### 1.1 What Swift is

Swift is a **persistent desktop agent** that the user controls by voice. It is not a voice chatbot.

Its defining requirement has three parts, and all three are required:

1. **Passive availability.** Swift starts at login and runs in the background, with a tray icon only and no main window.
2. **Activation by voice alone.** A user-configurable wake phrase starts an interaction. A global hotkey is a secondary path, never a replacement.
3. **Genuine task execution.** Swift completes real tasks through tools and integrations, verifies the outcome, and reports back by voice.

### 1.2 Interaction lifecycle (user's view)

1. **Standby.** Swift is listening locally for the wake phrase only. Nothing is recorded or transmitted.
2. **Wake.** The user says the wake phrase, often running straight into the command ("Hey Swift open my project"). Swift plays a short chime and shows a small overlay.
3. **Capture.** Swift records the command and stops when the user stops speaking. Longer dictation is supported.
4. **Understand.** Swift transcribes locally, then either matches a known command pattern (fast path) or reasons with the local LLM.
5. **Clarify** (if needed). Swift asks short questions, for example "Who is your dean?" The user answers without repeating the wake phrase.
6. **Propose and confirm** (for consequential actions). Swift states exactly what it will do, and the overlay shows the details. The user confirms (§8.5).
7. **Execute and verify.** Swift runs the steps, checks that the result really happened, and reports progress if the task takes a while.
8. **Respond.** Swift gives a concise spoken result and the overlay shows a summary.
9. **Follow-up window.** For a few seconds the user can continue ("make it shorter") without the wake phrase.
10. **Return to standby.**

At any point:
- Saying **"stop"** or **"cancel"**, or pressing the stop hotkey, halts speech and cancels pending work.
- Swift then reports anything that was already committed.

### 1.3 Advertised commands (MVP scope)

The MVP must complete all of these end to end, with verified outcomes.

| # | Command | Required capabilities |
|---|---|---|
| E1 | "Draft an email to my dean explaining this situation." | Contact/alias resolution; clarification ("What should I say about the situation?"); dictation mode; LLM drafting; Gmail draft create; read-back verification |
| E1b | "Make that email shorter." / "Send it." | Working set (`draft_id`); LLM rewrite; Gmail draft update; HIGH-risk confirmation for send; verify sent |
| E2 | "Find a free 30-minute slot with my supervisor next Tuesday and schedule a meeting." | Contact resolution; deterministic date/time-zone parsing; Calendar free/busy for both; if the attendee's calendar isn't visible, **say so** and offer to propose times from the user's calendar only; propose slot; HIGH-risk confirm (invites a third party); create event; verify |
| E3 | "Find the latest report in my project folder and summarize the outstanding issues." | Project profiles; file search; PDF/DOCX/text extraction; **quarantined** summarization of untrusted content; progress for long tasks |
| E4 | "Open my development environment and run the tests." | Project profiles (IDE launch + test task); deterministic launch; `run_project_task`; background task with completion report; summary of test results |
| E5 | "Remind me every Friday to send my supervisor a weekly update." | Local persistent scheduler; recurrence parsing; delivery by speech and toast; list and cancel reminders; survives reboot |

**Generic requests** that don't match a known command pattern go to the bounded LLM executor (§7.3), within the same tools and policies.

### 1.4 Explicitly out of MVP scope (deferred)

- Cloud LLM provider (architecture-ready, disabled).
- Generic UI automation (`windows-mcp` / UIA click/type).
- Arbitrary shell commands.
- File writes, moves, and deletes.
- Speaker verification.
- OS-level echo cancellation.
- Installer/MSIX/code signing.
- Multi-language support.
- Email search summarization: optional, behind a feature flag. It's allowed only after the provenance controls in §8.6 pass.

---

## 2. Owner decisions (recorded)

| Decision | Resolution |
|---|---|
| Audience | Personal use first, with distribution possible later. Every dependency's license is recorded in `docs/licenses.md`. Non-commercial or copyleft components must sit behind swappable interfaces. Before any distribution, a license review is mandatory (§15). |
| Wake phrase | **User-configurable.** "Hey Swift" is only an example. Phrase, engine, and model are config. Swift ships with documentation and scripts for training a custom openWakeWord model. Pretrained phrases may be used for personal use. |
| Confirmation | Voice-first. MEDIUM-risk actions use a voice "yes" bound to the exact action. HIGH-risk actions use a **visual challenge phrase spoken aloud**, or a click/hotkey (§8.5). A plain voice "yes" for HIGH risk is available only as a documented opt-in. |
| Other people's calendars | If the attendee's free/busy is visible, proceed. If not, tell the user ("I can't see Bob's calendar; it isn't shared with you") and offer to propose times from the user's calendar only. |
| Locked PC | Swift does **not** respond while the workstation is locked. The wake listener is paused while locked. |
| Cloud LLM | Undecided. Default **off**. The interface and privacy controls exist; a cloud provider is post-MVP and needs a separate approval. |
| Hardware | Owner's machine: 8-core CPU, 24 GB RAM, no GPU. For distribution, hardware varies, so model choice is selected by hardware profile (§7.4). |

---

## 3. Technology stack

Pin every dependency with hashes in a lockfile (`uv lock` or `pip-tools`) during Phase 0. The versions below are minimums known from the audit; confirm current versions when you lock.

| Layer | Choice | Notes and constraints |
|---|---|---|
| Runtime | CPython 3.12, 64-bit, venv managed by `uv` | Avoid 3.14-only packages in-process. |
| Audio I/O | `sounddevice` ≥ 0.5 (PortAudio) | Callback-mode input. No AEC available (§6.5). |
| Wake word | `openwakeword` 0.6.0, `inference_framework="onnx"` | Explicit ONNX on Windows. 1280-sample (80 ms) int16 frames at 16 kHz. Speex noise suppression is Linux-only, so don't use it. Pretrained models are **CC BY-NC-SA 4.0**: personal use only. |
| Wake (optional engine) | Porcupine (`pvporcupine`) | Optional, owner-supplied access key. Licensing terms **[verify]** before any distribution. |
| VAD | Silero VAD **ONNX model via onnxruntime** | **Do not** install the `silero-vad` pip package (it depends on PyTorch). Load the ONNX file bundled with `faster-whisper` (`faster_whisper/assets/silero_vad_v6.onnx`) or a pinned download. Mirror its input contract from `faster_whisper/vad.py` **[verify chunk size/state shape]**. |
| STT | `faster-whisper` ≥ 1.2, CPU, `compute_type="int8"` | Default `base.en`. `small.en` is selectable by hardware profile. Use `initial_prompt` seeded with contact, alias, and project names. |
| TTS | `piper-tts` (OHF-Voice/piper1-gpl), behind the `TTSEngine` interface | **GPL-3.0** and the Windows wheel exists. Choose a voice whose MODEL_CARD license is acceptable, and record it. (The `lessac` dataset is non-commercial **[verify]**.) An alternative engine must remain swappable for distribution. |
| LLM | Ollama (separate local service) via `ollama` Python client ≥ 0.6 | Set `num_ctx` explicitly (the default is 4096 on CPU-only machines) and `keep_alive` explicitly (the default is 5 min). Use **JSON-schema structured output** (`format=`), not native `tools=`. Don't combine the two. Models come from the hardware profile (§7.4). |
| Tray | `pystray` + `Pillow` | `run_detached()`. Always call `icon.stop()` on exit (it starts a non-daemon thread). |
| Overlay | `tkinter` (stdlib), on the **main thread** | All Tk calls happen on the Tk thread. Other threads communicate via `queue.Queue` + `root.after()` polling. |
| Windows platform | `pywin32` | Hidden message-only window: `WM_POWERBROADCAST`, `WTSRegisterSessionNotification` (lock/unlock), `RegisterHotKey`. Also a named mutex and a Job Object. |
| Audio sessions | `pycaw` + `comtypes` | Default capture endpoint identity (device-change detection). Best-effort conferencing detection **[verify capture-session enumeration]**. |
| Google | `google-api-python-client`, `google-auth`, `google-auth-oauthlib` | Gmail, Calendar, People APIs. |
| Secrets | `keyring` (Windows Credential Manager) | The blob limit is about 1280 UTF-16 characters. Store **only the refresh token**. If larger data is ever needed, use a DPAPI-encrypted file whose key is stored in the vault. |
| Config | `pydantic` v2 + `pydantic-settings`, TOML files | See §12. |
| Storage | `sqlite3` (stdlib) | Journal, scheduler, working-set persistence, aliases. |
| Text extraction | `pypdf`, `python-docx` | Size and page limits apply. |
| Dates | `python-dateutil` (rrule, parsing) + `zoneinfo` | Deterministic, never the LLM. A natural-language date helper library is the implementer's choice. |
| Logging | `loguru` with a mandatory redaction filter | Rotating 10 MB × 5. |
| Process/metrics | `psutil` | For measurement and the health watchdog. |
| Tests | `pytest`, `pytest-asyncio` (or the anyio plugin), `hypothesis` | Test markers per §14.2. |
| Licensing check | `pip-licenses` | Its output is committed to `docs/licenses.md`. |

**Not used in the MVP:**
- `windows-mcp`: requires Python ≥ 3.14, exposes PowerShell/Registry/FileSystem-delete tools, and has telemetry on by default.
- The `mcp` SDK.
- `promptwarden`: its published wheels contain no code.
- `openai`.

**Provider interfaces:**
- `WakeEngine`, `STTEngine`, and `TTSEngine` are swappable by config.
- `LLMProvider` is swappable by config **only after** the new provider/model passes the routing eval set (§14.4).

---

## 4. Architecture overview

```
 Main thread: Tk overlay mainloop ◄──── StatusEvent queue ────┐
 Tray thread (pystray)  ──── UserCommand queue ────────────┐  │
 Platform thread (hidden msg window: power, lock, hotkeys)─┤  │
                                                           ▼  │
 PortAudio callback ─► RingBuffer ─► WakeDetector ─► CORE asyncio loop (dedicated thread)
                           ▲                         │  SessionManager (state machine)
                           └── readers (capture/VAD) │  ├─ STT        (thread-pool executor)
                                                     │  ├─ Interpreter: FastPath → LLM
 Output stream ◄── DuplexCoordinator ◄── TTS ◄───────┤  ├─ Executor (templates + bounded LLM loop)
                                                     │  ├─ ActionGateway ─ Policy ─ Confirmation
                                                     │  │      └─ Tool adapters (files, apps, projects, Google)
                                                     │  ├─ WorkingSet / Provenance
                                                     │  ├─ Scheduler (SQLite)
                                                     │  └─ Journal + Audit (redacted)
                                                     └──────────────────────────────────────
 Ollama (separate local service, 127.0.0.1 only)
```

### 4.1 Concurrency model (fixed)

**Threads and what they do:**

| Thread | Responsibility |
|---|---|
| **Main thread** | Runs Tk (overlay). No business logic. |
| **Core thread** | Runs one `asyncio` event loop that owns the SessionManager, Executor, ActionGateway, integrations, scheduler, and storage. **All state mutation happens here.** |
| **PortAudio callback** | Only copies samples into the RingBuffer and records an overflow counter. Never blocks, allocates heavily, or logs per frame. |
| **Wake thread** | Reads 1280-sample frames from the RingBuffer, runs the wake engine, and posts `WakeDetected(ts)` to the core loop via `loop.call_soon_threadsafe`. |
| **Tray thread** | `pystray`. Sends `UserCommand`s to the core loop. |
| **Platform thread** | pywin32 message loop. Sends `PlatformEvent`s to the core loop. |
| **Bounded thread pool** (2–3 workers) | Blocking inference: STT, Piper synthesis, text extraction. Each job takes a cancellation token checked between chunks. |

**Messaging rules:**
- **Into the core:** threads talk to the core only through `call_soon_threadsafe` / `asyncio.Queue`.
- **Out of the core:** the core talks to UI threads only through immutable `StatusEvent` objects.

### 4.2 Process model

- One Swift process (`pythonw -m swift`), with single-instance enforcement through the named mutex `Local\Swift-<user SID>`. A second launch exits immediately with a log message.
- Child processes (project tasks, IDE launch helpers) are assigned to a Job Object with kill-on-close.
  - Exception: user-facing applications launched for the user (IDE, Notepad) are **not** in the kill-on-close job. They must outlive Swift.
- Ollama is an external service. Swift checks that its endpoint is loopback and refuses non-loopback endpoints unless cloud mode allows it.

---

## 5. Session state machine

Swift's state has two independent dimensions.

### 5.1 Availability (orthogonal)

`ACTIVE`, `MUTED` (user), `SUSPENDED_LOCKED`, `SUSPENDED_SLEEP`, `DND` (conferencing detected or user DND), `MIC_UNAVAILABLE` (no device, or signal blocked or flat).

- Wake detection runs only in `ACTIVE`.
- On entering any non-`ACTIVE` availability, the current interaction is cancelled and the working set is cleared on lock.

### 5.2 Interaction

```
STANDBY ─wake/hotkey─► LISTENING ─endpoint─► TRANSCRIBING ─► INTERPRETING
INTERPRETING ─► CLARIFYING ─(answer)─► INTERPRETING          (max 2 clarification turns)
INTERPRETING ─► PROPOSING ─► AWAITING_CONFIRMATION ─yes─► EXECUTING
                                       └─no/timeout/correction─► INTERPRETING | RESPONDING
INTERPRETING ─(no confirmation needed)─► EXECUTING ─► RESPONDING
EXECUTING ─(exceeds foreground budget)─► RESPONDING("I'll tell you when it's done") + background task
RESPONDING ─► FOLLOW_UP ─(speech)─► TRANSCRIBING
FOLLOW_UP ─(timeout)─► STANDBY
any ─stop/cancel/availability change─► CANCELLING ─► RESPONDING(report committed effects) ─► STANDBY
any ─unhandled error─► ERROR ─► RESPONDING(short apology) ─► STANDBY
```

**Rules:**
- States are an `Enum`. Transitions are validated against an explicit transition table. Illegal transitions raise in tests and are logged and recovered in production.
- Every transition emits a `StatusEvent`.
- There is only one foreground interaction at a time.
  - A wake during `LISTENING`/`TRANSCRIBING` restarts capture.
  - A wake during `RESPONDING` acts as barge-in (§6.5).
  - A wake during `EXECUTING` asks "Should I cancel the current task?" unless the task is in the background.
- Background tasks: at most 2 concurrent. Their completion is announced at the next `STANDBY` moment (never interrupting an interaction) and also via toast.

---

## 6. Audio pipeline

### 6.1 AudioPump and RingBuffer

- Open one input stream on the **default capture endpoint**: 16 kHz mono int16, callback mode, blocksize 1280.
  - If 16 kHz isn't supported, open at the native rate and resample in the wake thread (implementer's choice of method, with a test).
- The RingBuffer holds ≥ 10 s of samples with a monotonically increasing sample index. Readers hold cursors.
  - When a reader falls behind by more than the buffer size, it's resynced and a counter is incremented.
- Health metrics: overflow count, reader resyncs, RMS level histogram (for mic-blocked detection).

### 6.2 Wake detection

`WakeEngine` interface:

```python
class WakeEngine(Protocol):
    sample_rate: int        # 16000
    frame_length: int       # samples per process() call
    phrase: str             # display text, also used by the optional verifier
    def process(self, frame: np.ndarray) -> float: ...   # score 0..1
    def reset(self) -> None: ...
    def close(self) -> None: ...
```

- The detection threshold, a refractory period after a fire (default 1.5 s), and `reset()` after a fire are all config.
- **Optional second-stage verifier** (`wake.verify = "off" | "stt"`):
  - On detection, transcribe the buffered window (wake ts − 2.0 s … wake ts + 0.3 s) with a small STT model.
  - Accept only if the transcript fuzzy-matches `phrase`.
  - Whether to enable it by default is decided by Phase 0 data (spike S1).
- **User-configurable wake phrase:** config sets `wake.engine`, `wake.model_path` (or a pretrained name), `wake.phrase`, and `wake.threshold`. The tray tooltip shows the active phrase.
  - `docs/wake_word.md` documents three options:
    - (a) Pretrained openWakeWord phrases (personal use only, CC BY-NC-SA).
    - (b) Training a custom openWakeWord model. Note: the training pipeline is Linux/GPU-oriented, so use WSL2 or Colab, and the Colab is reportedly broken on current runtimes **[verify]**. Provide `scripts/wakeword/` helpers and a tested procedure from spike S1.
    - (c) Porcupine with an owner key.
  - `swift wake evaluate --model X --corpus DIR` runs the evaluation protocol (§14.3) for any candidate model.

### 6.3 Command capture and endpointing

- Capture starts at **wake detection index − 300 ms** (pre-roll), so commands spoken without a pause aren't clipped. The wake phrase itself is trimmed by STT.
- Silero VAD runs on 512-sample chunks **[verify]**. All parameters are configurable:

  | Parameter | Default |
  |---|---|
  | `start_timeout` (no speech) | 3.0 s → "I didn't catch that", then STANDBY |
  | `end_silence` (command mode) | 0.8 s |
  | `max_duration` (command mode) | 15 s |
  | **Dictation mode** `end_silence` | 1.5 s |
  | **Dictation mode** `max_duration` | 60 s |

  Dictation mode is entered when the interpreter requests body text (e.g. the email content) or when the command starts with a drafting verb.
- The chime is played via the output stream, asynchronously. It never blocks capture. Capture ignores the chime's duration (the half-duplex rule below does not apply to the chime because pre-roll already started).

### 6.4 Device lifecycle

- Follow the **default capture endpoint**: poll its ID every 2 s via pycaw.
  - On change, re-open the stream.
  - Note: PortAudio caches the device list, so re-initialize PortAudio before re-opening **[verify the method]**.
- On open failure: retry with exponential backoff (1, 2, 4 … max 60 s) and set `MIC_UNAVAILABLE` with a tray state.
- **Blocked mic detection:** a perfectly flat or zero signal for 10 s means `MIC_UNAVAILABLE("microphone blocked — check Windows privacy settings")`.
- On resume from sleep or hibernate: close and re-open the stream, `reset()` the wake engine, and return to `ACTIVE` once the first frames arrive.
- **Conferencing (best-effort):**
  - Use the capture-session enumeration on the default capture endpoint plus a user-editable process list (`Teams.exe`, `ms-teams.exe`, `Zoom.exe`, browsers if the owner opts in) → `DND`.
  - A manual DND toggle (tray + hotkey) is always available.
  - DND is shown in the tray.

### 6.5 Half-duplex, barge-in, echo

There's no acoustic echo cancellation, so Swift has to avoid hearing itself.

- **While TTS is playing:**
  - Wake detection uses `wake.threshold_during_tts` (higher, default +0.2) and counts as **barge-in only**: it stops playback and starts capture.
  - Confirmation and follow-up capture are **closed**.
- Capture, confirmation, and follow-up windows open only after playback ends + **300 ms tail guard**.
- "Stop" or "cancel" during playback (via barge-in or hotkey) halts audio within 300 ms.
- Echo test (Phase 2): Swift's TTS speaking the wake phrase and "yes" must cause zero self-wakes and zero confirmations.

### 6.6 Privacy of audio

- Audio exists only in RAM (RingBuffer and capture buffers). It is never written to disk unless `privacy.debug_record_audio = true`, which is off by default and shown in the tray when on.
- Capture buffers are dropped after STT.

---

## 7. Understanding and execution

### 7.1 Interpreter (fast path first)

`Interpreter.parse(transcript, working_set) -> Intent | None`:

- A deterministic grammar plus slot parsers (dates/times/recurrence via dateutil + zoneinfo, app names, project names, contacts/aliases, file types). It covers at least:
  - The E1–E5 command forms and their common paraphrases.
  - Control words: stop, cancel, yes, no, mute, "forget that", "what can you do".
  - Simple info: time, date.
  - Reminders: list and cancel.
- If the fast path abstains, the **LLM interpreter** classifies the intent and extracts slots, using JSON schema output restricted to the registered intent names (an `enum`).
- If the LLM is unreachable, only argument-free, read-only, or app-launch intents from the fast path are allowed. Otherwise Swift says: "My reasoning engine is offline."

### 7.2 Plan templates (deterministic orchestration)

Each advertised command is a **plan template**: code that sequences typed tool calls, clarifications, and confirmations. The LLM is used only for slot extraction and for content generation (drafting, rewriting, summarizing).

Templates:
- `draft_email`, `revise_draft`, `send_draft`
- `schedule_meeting`
- `summarize_latest_document`
- `open_dev_env_and_test`
- `create_reminder`, `list_reminders`, `cancel_reminder`

Templates are preferred for anything known because they are deterministic, testable, and fast.

### 7.3 Bounded LLM executor (generic requests)

For intents that no template covers, `Executor.run(goal, working_set, budget)` runs a loop:

1. The LLM proposes **one step** as structured JSON:
   ```json
   {"kind": "call", "tool": "<enum of allowed tools>", "args": {...}}
   | {"kind": "ask", "question": "..."}
   | {"kind": "answer", "text": "..."}
   ```
2. The step is validated: tool name in the registry, `args` validated by the tool's Pydantic model.
   - On a validation failure, make **one** repair attempt with the error message, then fail safe ("I'm not sure how to do that").
3. The step goes through the `ActionGateway` (§8).
4. The `ToolResult` (labelled with provenance) is appended to the context.
5. The loop repeats.

**Budgets (config):**

| Budget | Default |
|---|---|
| Max steps | 6 |
| Max LLM calls | 8 |
| Max wall time | 90 s |
| Max context tokens | below `num_ctx` minus the answer reserve |

Budget exhaustion → report progress and stop. A cancellation token is checked before every step.

The tool catalog shown to the LLM is **filtered** to the tools relevant to the classified intent. The system prompt and catalog are kept byte-stable so Ollama can reuse the prompt-prefix cache.

### 7.4 LLM configuration and hardware profiles

**Provider interface:**

```python
class LLMProvider(Protocol):
    capabilities: LLMCapabilities   # json_schema_output, max_context, streaming, local: bool
    async def generate(self, messages: list[Msg], *, schema: dict | None,
                       max_tokens: int, temperature: float, cancel: CancelToken) -> LLMResult: ...
```

- Ollama options are set explicitly: `num_ctx` (default 8192), `keep_alive` (policy-driven; default 30m after last use, then unload), `think=False` for routing, `temperature=0` for routing/extraction, and 0.3–0.7 for drafting.
- Swift counts tokens (approximately) per call and fails loudly when a prompt exceeds its budget. **No silent truncation.**

**Hardware profiles** (`llm.profile = auto | low | standard | high`) select the models:

| Role | Default `standard` (owner's machine) | Notes |
|---|---|---|
| Intent and slot extraction | small model (e.g. a 1.7B–4B instruct model) | Final choice from spike S3. |
| Drafting, summarizing, generic executor | `qwen3:8b` (Q4_K_M) | Kept only if spike S2/S3 data supports it. |

`auto` picks the profile from core count, RAM, and a 10-second micro-benchmark run on first start, and records the result.

### 7.5 Working set, context and follow-ups

`WorkingSet` is a typed object on the core loop with these slots:

- `last_draft` (draft_id, recipient, subject)
- `last_files`
- `last_event_proposal`
- `last_search_results`
- `pending_proposal`
- `conversation_turns` (last 6, provenance-labelled)

**Lifetime rules:**
- Idle TTL: 5 minutes.
- Cleared on lock, on "forget that", and on Swift restart.
- **Exception:** `last_draft.draft_id` is persisted in SQLite for 24 h, so "send that email" works after a restart. Swift always re-fetches the draft from Gmail before acting on it.

**Behavior:**
- Referents ("it", "that email", "the second one") resolve **only** against the working set. If resolution is ambiguous, Swift asks.
- **Follow-up window:** 6 s after a response, with no wake phrase needed. The overlay shows a countdown ring. Configurable; 0 disables it.
- **Corrections** during `AWAITING_CONFIRMATION` ("no, Wednesday") revise the pending proposal and re-confirm.

### 7.6 Long-running tasks

- Any task expected to exceed the 15 s foreground budget, or actually exceeding it (project tests, long summarization), moves to the background. Swift says: "Running the tests now. I'll tell you when they're done."
- Background tasks report progress events to the overlay and tray tooltip, and can be cancelled ("cancel the tests").
- On completion, Swift gives a spoken summary at the next idle moment, plus a toast.

### 7.7 Verification

- Every tool declares `verify()`.
- A task is reported as done **only** if verification returns `VERIFIED`.
  - `UNKNOWN` → "I did X but couldn't confirm it worked."
  - `FAILED` → report the failure.
- Examples:
  - Draft: re-fetch by id.
  - Send: message id present in the sent label.
  - Event: get by id, attendees match.
  - App launch: a window for the process appears within 10 s.
  - Project task: exit code captured.
  - Reminder: row persisted and next fire time computed.

---

## 8. Trust boundary

### 8.1 Tool contract

```python
class Capability(StrEnum):
    READ_LOCAL = "read_local"            # files in allowed roots
    READ_ACCOUNT = "read_account"        # email, calendar, contacts
    WRITE_PRIVATE = "write_private"      # drafts, reminders, own-calendar events without attendees
    COMMUNICATE = "communicate"          # anything that reaches another person: send email, invites
    EXECUTE = "execute"                  # launch app, run project task
    DESTRUCTIVE = "destructive"          # deletes/overwrites — no MVP tools have this

class SideEffect(StrEnum): NONE, REVERSIBLE, IRREVERSIBLE

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    capability: Capability
    side_effect: SideEffect
    timeout_s: float
    def targets(self, args) -> list[Target]: ...        # paths, recipients, apps, projects
    def idempotency_key(self, args) -> str | None: ...
    async def execute(self, args, ctx) -> ToolResult: ...
    async def verify(self, args, result, ctx) -> Verification: ...
```

**`ToolResult` fields:**
- `ok` and a short `message`.
- `data` (typed).
- `provenance`: `TRUSTED_USER`, `TRUSTED_LOCAL_CONFIG`, or `UNTRUSTED_EXTERNAL`.
  - File contents, email bodies/subjects/senders, calendar event text from others, and web content are **always** `UNTRUSTED_EXTERNAL`.
- `external_ids`.

**Tools never call other tools.** Only templates and the executor sequence tools.

### 8.2 ActionGateway (the only path to side effects)

- The `ToolRegistry` exposes `ToolSpec` metadata. **Only the gateway holds references to `execute`.**
- This also covers scheduler-fired jobs and retries.
- **Gateway sequence:**
  1. Validate args (Pydantic).
  2. Resolve targets.
  3. Evaluate policy (capability, targets, provenance taint, availability state, cloud mode).
  4. Confirm if required.
  5. Write the journal entry `PENDING`.
  6. Execute with timeout and cancellation.
  7. Verify.
  8. Write the journal entry `DONE` or `FAILED`.
  9. Write the audit record.
- An architecture test asserts that no module other than `gateway.py` calls `ToolSpec.execute`. Use static analysis (AST scan) in `tests/test_architecture.py`.

### 8.3 Policy

`permissions.toml` (in `%APPDATA%\Swift\`) is validated by Pydantic. **On a parse or validation error, Swift fails closed:** all non-read actions are denied, and the tray shows an error.

Defaults:

| Capability | Default decision | Escalations |
|---|---|---|
| READ_LOCAL | ALLOW (inside allowed roots, not deny-globbed) | — |
| READ_ACCOUNT | ALLOW | — |
| WRITE_PRIVATE | ALLOW, with a spoken announcement ("Draft saved") | Tainted context → MEDIUM |
| EXECUTE (known app or project task from config) | ALLOW for apps, MEDIUM for project tasks | Target not in config → DENY |
| COMMUNICATE | HIGH | Recipient not in contacts/aliases and not spoken by the user → DENY in tainted context, HIGH otherwise |
| DESTRUCTIVE | DENY | — |

Decisions are `ALLOW`, `CONFIRM(MEDIUM)`, `CONFIRM(HIGH)`, or `DENY(reason)`.

**Hard rules (not overridable in config):**
- No action executes while the availability is not `ACTIVE`.
- No tool not explicitly registered in code can be called.
- DESTRUCTIVE requires a code change to enable.

### 8.4 Execution safety for EXECUTE

- `launch_app(app_id)`: app IDs come only from `profiles.toml` or a resolved Start-menu shortcut index (built at startup, user-scoped). Launch via `ShellExecuteW`/`os.startfile` on the resolved path. Never use a shell string.
- `run_project_task(project_id, task_id)`:
  - The argv list comes from `profiles.toml`. The executable is resolved to an absolute path at config load (not via the runtime PATH) and logged.
  - `shell=False`, the cwd is the project root, and the environment is the minimal inherited set plus the profile's `env` entries.
  - Timeout from the profile (default 600 s). Process-tree kill via the Job Object on timeout or cancel.
  - Output is captured to a temp file with a size cap. Output is `UNTRUSTED_EXTERNAL` when summarized.
- There is **no general shell tool.** A transcript can never become a command line.

### 8.5 Confirmation

Every confirmation is bound to an `ActionDigest`:

```python
@dataclass(frozen=True)
class ActionDigest:
    tool: str
    normalized_args: dict
    resolved_targets: list[Target]
    consequence: str        # e.g. "Send email 'Weekly update' to dean.smith@uni.edu"
    risk: Literal["MEDIUM", "HIGH"]
    def hash(self) -> str: ...
```

- The overlay shows `consequence` and the full targets. TTS speaks a short form.
- Approval is recorded against `digest.hash()`, is **single use**, and expires after 60 s. The gateway recomputes the digest immediately before execution. If it differs, the approval is void and Swift re-confirms.
- **Capture window:** opens after TTS ends + 300 ms and lasts 8 s.
  - Responses go through a **closed-vocabulary matcher**:
    - Affirmatives: yes, yeah, confirm, do it, send it, go ahead.
    - Negatives: no, cancel, stop, wait.
    - Anything else is treated as a correction or new instruction.
  - Silence or an unrecognized response means **not approved**.
- **MEDIUM:** a voice affirmative within the window, or a click on the overlay, or the confirm hotkey (default `Ctrl+Alt+Enter`).
- **HIGH** (default `confirm.high_risk_mode = "challenge"`):
  - The overlay displays a random two-word challenge (from a curated list of easily pronounced, phonetically distinct words, e.g. "orange river").
  - Swift says: "To confirm, read the two words on screen, or press Ctrl+Alt+Enter."
  - The words are **never spoken by Swift**. Approval requires both words matched (fuzzy) in the transcript, or the click/hotkey.
  - Rationale: a spoken "yes" can come from Swift's own speaker, a meeting, a TV, or a bystander, and can be induced by injected content. The challenge proves the user is looking at the exact action. It keeps voice-only operation while defeating these failure modes.
  - Alternatives:
    - `"click_only"`.
    - `"voice_yes"`: opt-in. `docs/permissions.md` documents the risk, and the tray shows a warning icon.

### 8.6 Provenance and prompt-injection controls

Every message in LLM context carries a provenance label. Rules enforced in code:

1. **Quarantined processing.** Summarizing, extracting from, or rewriting untrusted content (files, emails, test output) happens in a **tool-less LLM call**: no tool catalog, output schema limited to text/fields. Its output is itself `UNTRUSTED_EXTERNAL` and may be spoken or displayed but can't introduce new tool calls.
2. **Taint.** Once any `UNTRUSTED_EXTERNAL` content is in the executor's context, the context is **tainted** for the rest of the task. Policy escalations apply (§8.3).
3. **Target origin.** In a tainted context, the targets of COMMUNICATE/EXECUTE actions (recipients, paths, projects, apps) must originate from `TRUSTED_USER` (the user's utterance, resolved via contacts/aliases) or `TRUSTED_LOCAL_CONFIG`. Targets that appear only in untrusted content → DENY.
4. **Prompt structure.** Untrusted content goes inside clearly delimited data blocks. This is a helpful measure, but **not** a control.
5. An injection-pattern detector may exist as **telemetry only**. It logs and never gates.

### 8.7 Filesystem scope

- `files.allowed_roots` (default `%USERPROFILE%\Documents` plus project roots from `profiles.toml`).
- Path handling, in order:
  1. Reject UNC, device (`\\?\`, `\\.\`), and ADS (`:` after the drive) paths.
  2. `Path.resolve(strict=True)`.
  3. Require that the result is inside a resolved root.
  4. Reject reparse points (symlinks/junctions) unless the resolved target is itself inside a root.
- **Deny-globs** (configurable, defaults include): `**/.ssh/**`, `**/.env*`, `**/*.kdbx`, `**/*.pem`, `**/*.key`, `**/AppData/**`, `**/.git/**/objects/**`, browser profile directories, `**/credentials*`.
- Limits: 20 MB per file read, 2000 files per search, extraction capped at 50 pages / 100k characters.

### 8.8 Audit and journal

- **Journal** (SQLite `journal`): id, ts, task_id, tool, digest_hash, state (`PENDING|EXECUTING|DONE|FAILED|UNKNOWN`), idempotency_key, external_ids, and error class.
- On startup, entries in `PENDING`/`EXECUTING` are **never resumed**. Swift tells the user: "Before I restarted, I may not have finished: {consequence}."
- **Idempotency:**
  - Calendar events use a client-supplied event `id` derived from the idempotency key **[verify id format rules]**.
  - Sending uses `drafts.send` on a specific draft id, executed at most once per approval.
- **Audit log** (`%LOCALAPPDATA%\Swift\audit.jsonl`): ts, tool, capability, decision, risk, digest_hash, `consequence` (redacted), targets (email addresses kept, since they're needed for accountability), result, and verification.
  - **No** bodies, file contents, transcripts, or tokens.

---

## 9. Integrations

### 9.1 Google (Gmail, Calendar, People)

- **OAuth:** installed-app flow via `google-auth-oauthlib`, using the owner's own Google Cloud project. `docs/google_setup.md` walks through:
  - Creating the project and enabling the APIs.
  - The OAuth consent screen.
  - **Publishing status:** "Testing" refresh tokens expire after 7 days. The owner chooses between publishing "In production" (an unverified-app warning for restricted scopes, acceptable for personal use) and weekly re-authentication. Spike S4 records the choice.
- **Scopes** (minimal):
  - `gmail.compose` (drafts + send)
  - `calendar.events`
  - `calendar.freebusy` **[verify the scope name; else `calendar.readonly`]**
  - `contacts.readonly`
  - `gmail.readonly` **only** if email search is enabled (feature flag, default off).
- **Tokens:** only the refresh token is stored, in Credential Manager (`service="Swift/Google"`). Access tokens live in memory. `swift auth status|login|revoke` CLI.
- **Gmail tools:**

  | Tool | Capability |
  |---|---|
  | `gmail_create_draft(to, subject, body)` | WRITE_PRIVATE |
  | `gmail_update_draft(draft_id, …)` | WRITE_PRIVATE |
  | `gmail_get_draft(draft_id)` | READ_ACCOUNT |
  | `gmail_send_draft(draft_id)` | COMMUNICATE, HIGH |

- **Calendar tools:**

  | Tool | Capability |
  |---|---|
  | `calendar_freebusy(emails, window)` | READ_ACCOUNT |
  | `calendar_create_event(…, attendees)` | COMMUNICATE (if attendees, otherwise WRITE_PRIVATE) |
  | `calendar_get_event(id)` | READ_ACCOUNT |

  - Free/busy: if an attendee's entry contains `errors` (e.g. `notFound`) or the calendar isn't visible, the template tells the user and offers to propose from the user's calendar only (owner decision §2).
  - Working hours: config, default 09:00–17:00 Mon–Fri. Time zone: system zone via `zoneinfo`, stated explicitly in proposals ("Tuesday 21 October, 2:00 PM your time").
- **Contacts:** `contacts_search(name)` via the People API, plus the local alias table.

### 9.2 Contact resolution and aliases

- Relational phrases ("my dean", "my supervisor") resolve via the alias table first (SQLite or `aliases.toml`).
- If an alias is unknown, Swift asks: "Who is your supervisor?" It then searches contacts for the answer, confirms the match ("Bob Lee, bob@uni.edu?"), and saves the alias after confirmation.
- Multiple matches → Swift reads out the top two or three for disambiguation.
- A newly created alias is a WRITE_PRIVATE action (ALLOW, announced).

### 9.3 Project profiles (`profiles.toml`)

```toml
[projects.thesis]
path = "C:/Users/me/Projects/thesis"
aliases = ["my project", "thesis"]
ide = ["C:/Users/me/AppData/Local/Programs/Microsoft VS Code/Code.exe", "."]
default = true

[projects.thesis.tasks.tests]
argv = ["C:/Users/me/Projects/thesis/.venv/Scripts/python.exe", "-m", "pytest", "-q"]
timeout_s = 600
summarize = "pytest"   # parser hint for result summary
```

"My development environment" means the default project's `ide`. "Run the tests" means its `tests` task.

### 9.4 Reminders and scheduler

- `scheduler/` is backed by SQLite: id, text, rrule (RFC 5545 via dateutil), tz, next_fire, created_at, last_fired, and missed policy.
- Parsing ("every Friday", "at 9", "tomorrow at 3pm") is deterministic. If the time is missing, Swift asks: "What time on Fridays?"
- **Delivery:**
  - Toast, plus TTS when availability is `ACTIVE` and the interaction state is `STANDBY`.
  - When locked: a generic toast ("Swift reminder"), with the content spoken or shown after unlock.
  - In DND: toast only.
- Missed fires (machine asleep or off) are delivered once on resume/start with "missed at …". They are never delivered multiple times.
- Tools:

  | Tool | Capability |
  |---|---|
  | `reminder_create` | WRITE_PRIVATE |
  | `reminder_list` | READ_LOCAL |
  | `reminder_cancel` | WRITE_PRIVATE, with spoken confirmation of which reminder — MEDIUM |

- Reminders work fully offline.

### 9.5 Documents

- `find_files(root_alias, pattern|type, sort=mtime, limit)`.
- `read_document(path)` extracts text from txt/md/pdf/docx within the limits in §8.7.
- "Latest report" heuristic: files in the project root (recursive, depth ≤ 4) with extensions pdf/docx/md and name tokens (report, status, summary, issues) or, failing that, the most recent of those types. Swift states which file it chose.
- Summarization is quarantined (§8.6) and chunked map-reduce when the document is over budget. Progress is spoken ("This is a long document; give me a moment").

---

## 10. User interface

### 10.1 Tray

- **Icon states:** active, listening/working, muted, DND, suspended (locked/sleep), mic unavailable, error, cloud-active (post-MVP), and an insecure-confirmation-mode warning.
- **Menu:**
  - Pause/Resume listening
  - Do not disturb
  - Wake phrase: "…" (info)
  - Reminders… (lists them in the overlay)
  - Open logs folder
  - Open config folder
  - Google account: status / sign in / sign out
  - Quit
- The tooltip shows the state and the active background task.

### 10.2 Overlay

- A small top-centre island, click-through except when showing a confirmation.
- It shows: state (Listening / Thinking / Working / Waiting for you / Done / Error), the live or final transcript (one line, truncated), the proposal `consequence` with targets during confirmation, the HIGH-risk challenge words, the follow-up countdown, and background task progress.
- Hidden during fullscreen or presentation apps, except for confirmations.
- Animation timers run **only while visible**. No idle redraw loop.
- Accessibility: text is always present (not colour-only). Font size is configurable.

### 10.3 Hotkeys (RegisterHotKey, configurable)

| Hotkey | Action |
|---|---|
| `Ctrl+Alt+Space` | Start listening (no wake phrase) |
| `Ctrl+Alt+Enter` | Confirm |
| `Ctrl+Alt+Backspace` | Stop/cancel |
| `Ctrl+Alt+M` | Mute toggle |

If a hotkey registration fails (conflict), log it and show it in the tray.

### 10.4 Speech style

- Responses are concise (≤ 2 sentences by default) and front-loaded with the outcome.
- Errors are categorized: "I couldn't reach Gmail", "I don't have access to Bob's calendar", "That's outside the folders I'm allowed to read".
- Swift never reads out email or document content longer than the summary unless asked.

---

## 11. Privacy and data handling

| Data | Where | Retention |
|---|---|---|
| Raw audio | RAM ring buffer and capture buffers | Overwritten continuously; capture buffers dropped after STT. Never on disk (unless debug recording is on, which shows a tray indicator) |
| Transcripts | RAM (WorkingSet) | Session TTL (5 min), cleared on lock. Not logged at INFO. At DEBUG only if `privacy.log_content=true` |
| Tool results/content | RAM (WorkingSet) | Same as transcripts |
| Draft id, reminder data, aliases | SQLite `%LOCALAPPDATA%\Swift\swift.db` | Draft id 24 h; reminders until deleted; aliases until deleted |
| Audit log | `%LOCALAPPDATA%\Swift\audit.jsonl` | 90 days rotation (config), metadata only |
| App log | `%LOCALAPPDATA%\Swift\logs\` | 10 MB × 5, redacted |
| Models | `%LOCALAPPDATA%\Swift\models\` with a manifest (name, source, SHA-256, license) | Until removed |
| Google refresh token | Credential Manager | Until `swift auth revoke` |

**Controls (`config.toml` `[privacy]`):**
- `cloud_llm = "off" | "ask" | "on"` (default `off`; only `off` is implemented in the MVP).
- `cloud_data_classes = []` (post-MVP).
- `log_content = false`.
- `debug_record_audio = false`.

**Network policy:**
- In standby, the Swift process opens **no non-loopback connections**.
- Network use occurs only for Google API calls during tasks, and for explicit `swift models fetch`.
- Set `HF_HUB_OFFLINE=1` (and equivalent switches) at runtime so model libraries never fetch implicitly.
- Inventory and disable any third-party telemetry.

**Redaction filter** (applied to all log sinks and the audit log), with unit tests: OAuth tokens/bearer strings, refresh tokens, email bodies, and anything matching key/secret patterns.

**Offline behavior:**
- Wake, STT, local LLM, files, apps, project tasks, and reminders all work offline.
- Google tools return `OFFLINE` and Swift says so. Nothing is queued for later sending.

---

## 12. Configuration

**Precedence:** built-in defaults → `%APPDATA%\Swift\config.toml` → environment variables (`SWIFT_*`, development only).

**Files in `%APPDATA%\Swift\`:**
- `config.toml`
- `permissions.toml`
- `profiles.toml`
- `aliases.toml` (optional seed; runtime aliases live in SQLite)

**Handling rules:**
- Every file has a `schema_version` and a Pydantic model.
- On first run, defaults are written with comments.
- Validation errors are shown in the tray and logged.
- Behavior on error:
  - `permissions.toml` errors → fail closed.
  - Other files → fall back to defaults for the invalid section.
- A `.env` file is used only for development overrides. No secrets anywhere in files. `docs/configuration.md` documents every key.

---

## 13. Project structure

```
swift/
├── pyproject.toml            uv.lock
├── README.md                 SWIFT_BUILD_PROMPT.md (this file)
├── docs/
│   ├── architecture.md       threat_model.md      permissions.md
│   ├── configuration.md      wake_word.md         google_setup.md
│   ├── licenses.md           backlog.md           decisions/ (ADR-NNN-*.md)
├── scripts/
│   ├── install_autostart.ps1 uninstall_autostart.ps1
│   ├── measure_idle.py       measure_latency.py   soak.py
│   └── wakeword/             (training + evaluation helpers)
├── spikes/                   (Phase 0 throwaway code; never imported by src)
├── eval/
│   ├── utterances.jsonl      (gold intents/slots for routing eval)
│   ├── tasks.yaml            (task suite with end-state oracles)
│   ├── injection/            (adversarial payload corpus)
│   └── README.md             (wake audio corpora live outside git; paths via config)
├── src/swift/
│   ├── __main__.py           app.py (composition root, startup/shutdown order)
│   ├── config/               (models.py, loader.py, paths.py)
│   ├── logging_setup.py
│   ├── events.py             (StatusEvent, UserCommand, PlatformEvent, WakeDetected)
│   ├── audio/                (pump.py, ringbuffer.py, vad.py, capture.py, duplex.py, devices.py, chime.py)
│   ├── wake/                 (base.py, openwakeword_engine.py, porcupine_engine.py, verifier.py, factory.py)
│   ├── stt/                  (base.py, faster_whisper_engine.py)
│   ├── tts/                  (base.py, piper_engine.py)
│   ├── llm/                  (base.py, ollama_provider.py, prompts.py, tokens.py)
│   ├── session/              (state.py, manager.py, context.py)
│   ├── agent/                (interpreter.py, grammar.py, slots.py, templates/, executor.py)
│   ├── tools/                (spec.py, registry.py, files.py, documents.py, apps.py, projects.py,
│   │                          gmail.py, calendar.py, contacts.py, reminders.py)
│   ├── security/             (gateway.py, policy.py, confirm.py, digest.py, provenance.py,
│   │                          paths.py, redact.py, audit.py)
│   ├── integrations/google/  (auth.py, gmail_client.py, calendar_client.py, people_client.py)
│   ├── scheduler/            (store.py, scheduler.py, recurrence.py)
│   ├── store/                (db.py, journal.py, aliases.py, migrations/)
│   ├── platform/             (windows.py: mutex, message window, hotkeys, job objects, lock/power)
│   └── ui/                   (tray.py, overlay.py)
└── tests/
    ├── unit/  integration/  windows/  replay/  eval/
    └── test_architecture.py  (gateway-only execution, import-layering rules)
```

**Layering rules** (enforced by `test_architecture.py`):
- `tools/` must not import `session/`, `agent/`, or `ui/`.
- `ui/` imports only `events.py`.
- Only `security/gateway.py` calls `execute`.
- `integrations/` must not import `tools/`.

---

## 14. Testing, evaluation and acceptance

### 14.1 Principles

- Success means a **verified end state**, not a tool returning `ok`.
- Every claim comes with its method, sample size, and a confidence interval where relevant.
- Hardware, Google, and live-LLM results come from owner-run scripts on the target machine. The agent records them verbatim.

### 14.2 Test layers and markers

| Layer | Marker | Runs where |
|---|---|---|
| Unit (pure logic, policy, digest, grammar, recurrence, paths, redaction) | none | Anywhere, CI |
| Property/adversarial (Hypothesis policy suite, path suite, command suite, LLM-output fuzz) | none | Anywhere, CI |
| Replay (WAV corpora through pump → wake → VAD → STT) | `replay` | Anywhere with models |
| LLM fixture (recorded LLM responses for determinism) | none | CI |
| Live LLM eval | `live_llm` | Owner machine with Ollama |
| Windows integration (mutex, hotkeys, message window, launch, Job Object) | `windows` | Windows |
| Hardware (live mic/speaker) | `hw` | Owner, on target |
| Google (test account) | `google` | Owner, with credentials |

### 14.3 Measurement protocols

- **Wake accuracy:**
  - Positives: ≥ 300 utterances of the configured phrase covering 3 distances (0.5 m, 1.5 m, 3 m), 3 noise conditions (quiet, music/TV, office babble), with the phrase both followed by a command without a pause and alone. As many speakers as available; report per condition.
  - Negatives: ≥ 24 h of representative audio, including TV/podcasts, the owner's environment, and recordings of the owner's own speech without the phrase.
  - Report the FRR/FA-per-hour curve against threshold, the chosen threshold, Wilson 95 % CI for TPR, and the rule-of-three upper bound for FA when zero events occur.
- **Detection latency:** from the annotated end of the wake phrase in recordings to the `WakeDetected` event. Report p50 and p90.
- **Command-onset capture:** the % of no-pause commands whose first word is present in the transcript.
- **End-to-end latency:** measured from the **VAD-annotated true end of speech** (not the endpoint decision) to first audio sample out. Reported per class (fast path, LLM-routed, generative), and as cold vs warm. ≥ 30 runs per class.
- **Idle resources:** `measure_idle.py` samples the **Swift process tree** (CPU % of one core, private bytes) every 5 s for 60 min. It separately records Ollama's process. Report median and p95 under AC and battery.
- **Task success:** `eval/tasks.yaml` has ≥ 100 tasks across E1–E5, generic requests, clarification paths, and failure paths (offline, calendar not shared, no matching file). Each task has an end-state oracle. Report:
  - success rate with CI
  - **safe-failure** rate (asked, declined, or reported correctly)
  - **unsafe outcome count** (wrong recipient/target, unconfirmed side effect), which must be **0**.
- **Routing eval:** `eval/utterances.jsonl` has ≥ 150 utterances (typed transcripts plus STT outputs of recorded audio) with gold intent and slots. Report exact-match intent accuracy, slot accuracy, and valid-JSON rate per model.
- **Soak:** `soak.py` runs 8 h with a replayed wake + command every 10 min plus idle periods.
  - Pass: no crash, no stuck state, RSS slope ≤ 5 MB/h after warm-up, p90 latency drift ≤ 20 %.

### 14.4 MVP acceptance targets

These are initial targets. They will be rebaselined with Phase 0 data and require owner approval to change.

| Criterion | Target |
|---|---|
| Wake TPR (configured phrase) | Wilson 95 % lower bound ≥ 93 % on ≥ 300 positives |
| False activations | ≤ 1 per 8 h, demonstrated over ≥ 24 h of negatives (≤ 1 per 4 h acceptable if the verifier is off and the owner approves) |
| Wake detection latency | p90 ≤ 400 ms |
| Command-onset capture | ≥ 95 % |
| E2E latency, fast path | p90 ≤ 2.0 s warm |
| E2E latency, LLM-routed single action | p90 ≤ 5.0 s warm (cold reported, no target) |
| Generative/multi-step | acknowledgement ≤ 2.0 s; result reported; no hard cap |
| Idle CPU (standby core) | median < 3 % of one core |
| Idle memory (standby core, models unloaded) | ≤ 200 MB private bytes (tighten after measurement); warm-resident figure reported |
| Task success | ≥ 90 % on ≥ 100 tasks (CI reported); unsafe outcomes = 0 |
| Routing eval | ≥ 95 % intent accuracy, ≥ 99 % valid JSON after repair |
| Policy/adversarial suites | 0 violations (≥ 1000 generated cases + all fixtures) |
| Injection corpus | 0 unconfirmed side effects; 0 side effects to attacker-supplied targets |
| Echo safety | 0 self-wakes / 0 self-confirmations in 20 trials |
| Sleep/resume | wake works ≤ 10 s after resume, 10/10 cycles (sleep and hibernate) |
| Mic replug / default-device switch | recovers ≤ 10 s, 10/10 |
| Lock | 0 responses while locked, 10/10 |
| Reboot | tray ≤ 60 s after login; wake-ready ≤ 90 s |
| Standby network | 0 non-loopback connections in 60 min |
| Soak | per §14.3 |

---

## 15. Licensing and distribution readiness

- `docs/licenses.md` lists every dependency, model, and voice with its license, and is generated by `pip-licenses` plus a manual model table.
- **Known constraints:**
  - openWakeWord pretrained models: CC BY-NC-SA 4.0 (non-commercial).
  - Piper: GPL-3.0.
  - Some Piper voices: non-commercial datasets.
  - Porcupine: commercial terms **[verify]**.
  - Custom wake models trained with openWakeWord's negative feature sets: data-license implications **[verify before distribution]**.
- Before any distribution, a license review gate must pass:
  - Replace or isolate non-commercial and GPL components as required.
  - Signing and packaging are post-MVP.

---

## 16. Development workflow

For every phase:

1. **Plan** (no code). The plan contains:
   - Objective; files to create or change; interfaces (signatures); tests with IDs mapped to acceptance criteria.
   - **Decisions requiring owner approval** (architectural, irreversible, security- or privacy-relevant, dependency additions).
   - **Implementation choices I will make unless you object** (reversible, local).
   - Risks, and what the owner will need to run.
2. **Wait for approval.**
3. **Implement.** Small commits. Type hints everywhere (`from __future__ import annotations`). Every new security-relevant path gets tests in the same commit.
4. **Test.** Run all agent-runnable tests. Produce scripts plus exact instructions for owner-run tests.
5. **Report:**
   - Each acceptance test with its status from the taxonomy in §0.4.
   - Measured numbers with method.
   - Deviations from the plan.
   - New risks.
   - Backlog additions.
6. **Stop.** Wait for the owner to confirm the phase has passed, including owner-run results.

**Other rules:**
- Record every approved decision as an ADR in `docs/decisions/`.
- Ask clarifying questions whenever a requirement is ambiguous. Prefer asking over guessing.

---

## 17. Phase plan

No time estimates. Each phase lists its major uncertainties instead.

### Phase 0 — Scaffold and risk spikes

**Objective:** Validate the assumptions that could invalidate the design before building on them.

**Deliverables:**
- **Scaffold:**
  - `pyproject.toml` and lockfile.
  - Config models and loader with `%APPDATA%` paths.
  - Logging with the redaction filter (tests).
  - `python -m swift --version` → `Swift 0.1.0`.
  - `docs/architecture.md` (concurrency model, process model).
  - `docs/threat_model.md`.
  - `docs/licenses.md` (initial).
- **Spike S1, wake word** (`spikes/wake/`):
  - Establish a working training procedure (WSL2 or Colab) for a custom openWakeWord model for the owner's chosen phrase, plus 1–2 alternates.
  - Build the evaluation script (§14.3) and collect the owner's initial corpus.
  - Report FRR/FA curves.
  - Evaluate the STT second-stage verifier's effect on FA and latency.
- **Spike S2, latency/resources** (owner machine):
  - STT `base.en`/`small.en` int8 on 2/5/10 s clips.
  - Candidate LLMs (qwen3:8b plus two smaller models): prefill tok/s and decode tok/s at 500/1500/3000-token prompts, cold vs warm (prefix cached).
  - Piper time-to-first-audio.
  - RAM per loaded component.
- **Spike S3, interpretation reliability:**
  - Draft `eval/utterances.jsonl` (≥ 150).
  - Measure intent and slot accuracy and the valid-JSON rate per candidate model, with and without the fast-path grammar prototype.
- **Spike S4, Google:**
  - The owner sets up the project.
  - Decide the publishing status.
  - Verify scopes, refresh-token storage size, and supervisor free/busy visibility, and record the actual error format when it isn't shared.
- `docs/decisions/ADR-001…`: wake phrase/engine/verifier, model tiering, rebaselined §14.4 targets, OAuth approach.

**Acceptance:**
- P0-1: venv install from the lockfile succeeds on the owner's machine.
- P0-2: `--version` works.
- P0-3: redaction tests pass.
- P0-4: spike reports contain real measured numbers.
- P0-5: the owner approves the ADRs.

**Exit:** go/no-go recorded for each spike. If S1 fails the targets, the owner chooses: different phrase, verifier on, Porcupine, or relaxed target.

**Uncertainty:** the wake training pipeline's current state, and local LLM quality.

### Phase 1 — Audio core and standby

**Deliverables:**
- `platform/windows.py`: mutex, message window, lock/power events, hotkeys, Job Object.
- `audio/pump.py`, `ringbuffer.py`, `devices.py`.
- `wake/` (configured engine, threshold, refractory, optional verifier).
- `events.py`, `session/state.py` (availability dimension and the transition table), the core loop skeleton, `app.py` startup/shutdown order.
- `ui/tray.py` (availability states, pause/DND/quit).
- `scripts/measure_idle.py`.
- The replay harness.
- `install_autostart.ps1`/`uninstall_autostart.ps1`: Scheduled Task, at logon, current user, limited privileges, `pythonw.exe` from the Swift venv, restart-on-failure ×3.

**Acceptance:**
- P1-1 (replay): the corpus reproduces S1 metrics within ±2 % TPR.
- P1-2 (hw): 20 live wakes at 3 distances, logged with scores.
- P1-3 (windows): a second instance exits.
- P1-4 (hw): lock → `SUSPENDED_LOCKED` and no wakes. Unlock → `ACTIVE`, 5/5.
- P1-5 (hw): sleep/resume 5 cycles → wake within 10 s.
- P1-6 (hw): default-device switch and replug → recovers.
- P1-7: idle CPU and memory measured and reported.
- P1-8: standby network test → 0 connections.
- P1-9: clean shutdown leaves no threads or processes (test).

### Phase 2 — Voice I/O and interaction lifecycle

**Deliverables:**
- VAD (ONNX), capture with pre-roll, command and dictation modes, endpointing config.
- STT engine (thread pool, warm/unload policy, `initial_prompt`).
- Piper TTS with streaming playback.
- `duplex.py` (half-duplex, barge-in, tail guard), chime.
- Overlay (main thread, states, transcript), interaction state machine through `RESPONDING`/`FOLLOW_UP` with an echo-back stub ("You said …").
- Stop/cancel handling.
- `measure_latency.py`.

**Acceptance:**
- P2-1 (replay): WER reported on the corpus.
- P2-2 (hw): no-pause commands captured fully, ≥ 18/20.
- P2-3 (hw): echo safety, 0/20 self-wakes while TTS speaks the wake phrase.
- P2-4 (hw): "stop" during TTS halts ≤ 300 ms, 10/10.
- P2-5: re-wake during capture restarts capture.
- P2-6: follow-up window accepts speech without the wake word and closes on timeout.
- P2-7: a 40 s dictation is captured fully in dictation mode.
- P2-8: STT latency reported.

### Phase 3 — Trust boundary and deterministic tools

**Deliverables:**
- `tools/spec.py`, `registry.py`.
- `security/` (gateway, policy, digest, confirm with MEDIUM/HIGH modes, provenance, paths, audit).
- `store/journal.py`.
- `agent/grammar.py` + `interpreter.py` (fast path only), template runner.
- Tools: `find_files`, `read_document`, `launch_app`, `focus_app`, `run_project_task`.
- `profiles.toml`.
- Overlay confirmation UI with challenge words.
- `test_architecture.py`.

**Acceptance:**
- P3-1: policy property suite, 0 violations.
- P3-2: path adversarial suite (`..`, junctions, symlinks, ADS, UNC, `\\?\`, 8.3 names, deny-globs) all denied.
- P3-3: command suite (≥ 200 crafted strings) → no process other than configured argv.
- P3-4: digest mutation after approval → re-confirm.
- P3-5 (hw): confirmation spoofing — "yes" played from the speaker during/after the prompt → not approved. HIGH risk with only "yes" → not approved. Silence → not approved.
- P3-6 (hw): "open my development environment and run the tests" → IDE window verified, tests run in the background, completion spoken with pass/fail counts.
- P3-7 (hw): "find the latest PDF in my Documents" → correct file stated.
- P3-8: crash between `PENDING` and `DONE` → no re-execution, user informed.
- P3-9: architecture test passes.

### Phase 4 — LLM interpretation and bounded executor

**Deliverables:**
- `llm/` (provider, capabilities, token budgeting, explicit `num_ctx`/`keep_alive`), LLM interpreter (intent + slots), executor loop with budgets and validation/repair.
- `session/context.py` (WorkingSet, TTL, referents, corrections, clarifications).
- Quarantined summarizer.
- Taint propagation.
- The `summarize_latest_document` template.
- Routing eval runner.
- Hardware profile selection.

**Acceptance:**
- P4-1 (live_llm): routing eval meets §14.4.
- P4-2: LLM-output fuzz (malformed JSON, unknown tool, wrong types, extra fields) → no execution, graceful speech.
- P4-3: injection corpus (≥ 50 payloads, including paraphrased, multilingual, encoded, and instructions in filenames) through E3 and the generic executor → 0 unconfirmed side effects, 0 attacker-target actions.
- P4-4 (hw): E3 end to end, with the summary naming the correct file and the issues verified against a seeded test document.
- P4-5: budget exhaustion and cancellation mid-loop → correct reporting.
- P4-6: latency per class reported.
- P4-7: the Ollama-down path → fast-path-only behavior and correct spoken message.

**Uncertainty:** local model planning quality. Mitigation: templates first, narrow catalogs.

### Phase 5 — Google, contacts, reminders

**Deliverables:**
- `integrations/google/` (auth with refresh token only, clients).
- Tools: gmail, calendar, contacts.
- Aliases with first-use clarification.
- Templates: `draft_email`, `revise_draft`, `send_draft`, `schedule_meeting`, `create_reminder`/`list_reminders`/`cancel_reminder`.
- `scheduler/`.
- Reminder delivery rules.
- `swift auth` CLI.
- `docs/google_setup.md`.

**Acceptance (google + hw, using a test account and a test "supervisor" account):**
- P5-1: E1 with an unknown alias → clarification → alias saved → draft created and verified by re-fetch.
- P5-2: E1b "make it shorter" → draft updated (verified shorter). "Send it" → HIGH challenge → sent (verified in sent mail).
- P5-3: E2 with a shared calendar → slot proposed in the correct time zone → HIGH confirm → event created with attendee (verified).
- P5-4: E2 with an unshared calendar → Swift states it can't see the calendar and offers own-calendar proposal.
- P5-5: E5 → reminder persisted. Fires on a simulated Friday (clock injection). Survives restart. Missed-fire delivered once after simulated sleep.
- P5-6: offline → Google tools report offline; reminders still fire.
- P5-7: token larger than the vault limit is handled. Revoke works.
- P5-8: duplicate-send test (kill after approval) → at most one email.

### Phase 6 — Reliability, privacy, MVP gate

**Deliverables:**
- Conferencing DND (best-effort) + manual DND.
- Mic-blocked detection.
- Overlay polish (fullscreen suppression).
- Retention jobs.
- Privacy config surface.
- `soak.py`.
- Full eval runs.
- README with measured results and methodology.

**Acceptance:** every row of §14.4 has a measured result recorded with method. Any target missed is either fixed, or the owner explicitly approves a documented exception.

**Exit:** the MVP is declared by the owner.

### Phase 7 — Post-MVP (each item needs separate approval)

- Cloud LLM provider (privacy gate, data-class controls, eval-gated).
- `windows-mcp` via `uvx`, as a separate process, with an explicit tool allowlist (no PowerShell/Registry/FileSystem/Type/Click by default), telemetry off, and capability mapping maintained by Swift (MCP tool annotations are untrusted).
- Email search and summarization.
- Packaging (PyInstaller/MSIX), code signing, and installer/uninstaller with config migration.
- Windows AEC capture mode.
- Speaker verification.
- License review for distribution.

---

## 18. What NOT to do

- Do not copy or vendor OpenOdin code. Do not keep it in the repo.
- Do not add a general shell tool, or let any transcript or LLM output become a command line.
- Do not call `ToolSpec.execute` outside `security/gateway.py`.
- Do not treat regex scanners, prompt wording, or MCP tool annotations as security controls.
- Do not accept a confirmation captured while TTS is playing, or one not bound to the current digest.
- Do not respond to commands while the PC is locked.
- Do not send audio, transcripts, or content off the machine (cloud is off). Do not enable library telemetry.
- Do not install the `silero-vad` pip package (PyTorch), `windows-mcp`, `mcp`, or `promptwarden` in the MVP.
- Do not rely on Ollama defaults for `num_ctx` or `keep_alive`.
- Do not log transcripts, email or file content, or tokens at default log levels.
- Do not report hardware or live tests as passed unless they were run on the target. Do not invent numbers.
- Do not start a phase without an approved plan, or the next phase before the owner confirms the current one.
- Do not add a foreground main window.

---

## 19. Your first action

1. Read this entire document. If the OpenOdin reference is available outside the repo, skim it for general ideas only.
2. Output the **Phase 0 plan** in the §16 format, covering the scaffold and spikes S1–S4. Include the exact list of owner-run steps and what data the owner needs to collect (wake corpus, Google setup).
3. List any questions where this spec is ambiguous for Phase 0.
4. **Wait for approval.** Do not write code until the owner approves.
