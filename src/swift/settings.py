"""MVP configuration from ``config.yaml`` (PLAN.md §8, ADR-006).

A missing file gives the defaults. An invalid file is an error: Swift
refuses to start rather than run with settings the owner didn't intend.
``%VAR%`` references in paths are expanded from the environment, defaults
included. An unset ``%LOCALAPPDATA%`` or ``%APPDATA%`` falls back to its usual
place under the user profile; any other unset variable is a settings error, so
Swift never writes to a folder literally named ``%VAR%``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_ENV_REF = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")
# Where Windows puts these when the variable is missing (a process started with a bare environment).
_PROFILE_DIRS = {"LOCALAPPDATA": ("AppData", "Local"), "APPDATA": ("AppData", "Roaming")}


def _env_value(name: str) -> str:
    if value := os.environ.get(name):
        return value
    if name in _PROFILE_DIRS:
        return str(Path.home().joinpath(*_PROFILE_DIRS[name]))
    raise ValueError(f"%{name}% is not set in the environment")


def expand(value: str) -> str:
    """Replace ``%VAR%`` references; ValueError names an unset variable."""
    return _ENV_REF.sub(lambda m: _env_value(m.group(1)), value)


class _Section(BaseModel):
    # validate_default: the default paths hold %LOCALAPPDATA% too and must be expanded.
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class Hotkeys(_Section):
    push_to_talk: str = "Ctrl+Shift+Space"
    debug: str = "Ctrl+Alt+F12"
    # Opens the overlay's text box: type a request instead of saying it (ADR-015 §10). "" turns it off.
    type: str = "Ctrl+Alt+Space"


class SttSettings(_Section):
    # parakeet: Parakeet-TDT 0.6B v2 int8 (fast, accurate). whisper: faster-whisper `model`.
    engine: Literal["parakeet", "whisper"] = "parakeet"
    cpu_threads: int = Field(4, ge=1, le=32)
    # Whisper only.
    model: Literal["base.en", "small.en"] = "small.en"
    beam_size: int = Field(5, ge=1, le=10)
    initial_prompt: str = ""
    # Heard phrase -> meant phrase, e.g. {"tori": "Tauri"}. Both engines. Merged
    # over the learned fixes in word_fixes_file (these win).
    word_fixes: dict[str, str] = Field(default_factory=dict)
    word_fixes_file: str = "%LOCALAPPDATA%/Swift/word_fixes.json"
    # Noise checks (docs/stt-noise.md). The agent is told which words the model was
    # less sure of than unclear_p, so it asks instead of guessing. A transcript whose
    # words average below reject_p isn't acted on ("I couldn't make that out").
    # 0 turns either check off.
    unclear_p: float = Field(0.4, ge=0.0, le=1.0)
    reject_p: float = Field(0.7, ge=0.0, le=1.0)
    # Approving an action by voice in a noisy room (the room between words louder than
    # noisy_db dBFS) takes a second "approve" or a click: with a TV on, "stop" was once
    # heard as "sure". Rejecting is never held up.
    noisy_db: float = Field(-50.0, le=0.0)
    # Debug: keep every recording for audio.keep_days, not only the useful ones (audio.keep_all).
    save_audio: bool = False
    audio_dir: str = "%LOCALAPPDATA%/Swift/audio"
    # Clips with words the owner gave (a repeat, a correction), kept after audio.keep_days to check
    # transcription against (swift/stt/recordings.py). At most audio.test_set_max, oldest dropped first.
    test_set_dir: str = "%LOCALAPPDATA%/Swift/stt_testset"

    @field_validator("audio_dir", "word_fixes_file", "test_set_dir")
    @classmethod
    def _expand(cls, v: str) -> str:
        return expand(v)

    @property
    def model_label(self) -> str:
        return "parakeet-tdt-0.6b-v2-int8" if self.engine == "parakeet" else self.model


class AudioSettings(_Section):
    # Seconds of audio kept from before the key goes down (0 = off). Above 0 the microphone
    # stays open while Swift runs, so Windows' mic-in-use indicator is on all the time.
    preroll_s: float = Field(0.0, ge=0.0, le=2.0)
    # A short soft chime the moment Swift hears "hey Swift" or the hotkey (false: the overlay's
    # "Listening…" only).
    chime: bool = True
    # Recordings (audit B-06, swift/stt/recordings.py): a clip is kept only when it can improve
    # transcription (heard unsurely, "say it again", repeated or corrected, a missed wake phrase, a
    # failed request), and for this many days at most. 0: no recording is saved. Never leaves the PC.
    keep_days: int = Field(7, ge=0, le=90)
    # Keep every recording for keep_days, useful or not (debugging; stt.save_audio means the same).
    keep_all: bool = False
    # Useful clips with known words, kept as a test set after keep_days (oldest dropped first).
    test_set_max: int = Field(200, ge=0, le=2000)
    # The improvement pass (word fixes to approve, an accuracy check): once a week, while idle.
    improve_weekly: bool = True


class WakeSettings(_Section):
    """Say "hey / hello / good afternoon Swift" instead of holding the hotkey (swift/wake.py).

    Off by default: it keeps the microphone open, so Windows' mic-in-use indicator is on
    whenever Swift runs, and it runs the speech model on every short utterance it hears
    (on this machine, never sent anywhere).
    """

    enabled: bool = False
    # Greetings to accept besides hey / hi / hello / ok / good morning|afternoon|evening.
    greetings: list[str] = Field(default_factory=list)
    # Speech whose words averaged below this probability is ignored (0 = off)...
    min_p: float = Field(0.5, ge=0.0, le=1.0)
    # ...except a wake phrase heard while nothing runs: it needs only this much (0 = no bar).
    # The model is often unsure of the name itself; approving still needs it (T2).
    phrase_min_p: float = Field(0.2, ge=0.0, le=1.0)
    # After a bare "hey Swift", the request ends this long after you stop talking...
    end_silence_s: float = Field(0.9, gt=0)
    # ...and Swift stops listening if you say nothing for this long.
    start_timeout_s: float = Field(5.0, gt=0)
    # After an answer, reply without the wake phrase for this long (the card shows it; 0 = off).
    # During a run, "show me", "stop" and "reject" work without it too; approving needs
    # "Swift, approve" (or a click or the hotkey), so overheard speech can't approve anything.
    followup_s: float = Field(8.0, ge=0, le=60)
    # ...or this long when the answer asks something ("Which Tuesday?"). Unanswered by then, the
    # conversation is kept as unfinished: "continue", or just answering, picks it up.
    question_s: float = Field(25.0, ge=0, le=120)
    # A reply in that window (no wake phrase) must be at least this sure of its words, and sound
    # like you rather than the room (0 = only wake.min_p). Said less surely: "Try saying it again".
    followup_min_p: float = Field(0.7, ge=0.0, le=1.0)


class ExecutorSettings(_Section):
    kind: Literal["echo", "mock", "claude_code"] = "echo"
    # Run without asking. Keep these read-only.
    allowed_tools: list[str] = Field(default_factory=lambda: ["Read", "Glob", "Grep"])
    # Available, but every call shows the overlay's confirm card first.
    confirm_tools: list[str] = Field(default_factory=lambda: ["Edit", "Write", "Bash"])
    working_dirs: list[str] = Field(default_factory=list)
    default_dir: int = Field(0, ge=0)
    # Read, Glob and Grep run without a card only in the working folders and these; anywhere else a
    # card first (owner, 2026-10-28; audit B-01). %VAR% references are expanded.
    read_dirs: list[str] = Field(default_factory=lambda: ["%USERPROFILE%/Documents", "%USERPROFILE%/Downloads"])
    # Never read, even with a card, on top of Swift's own list (sign-ins, keys, browser profiles).
    never_read: list[str] = Field(default_factory=list)
    max_budget_usd: float | None = Field(1.0, gt=0)
    # ADR-017: when it runs out the card waits in the stack, so it can be short.
    confirm_timeout_s: float = Field(45.0, gt=0)
    # Keep one Claude Code process started and waiting, so a request skips its 5-13 s startup.
    prewarm: bool = True
    # Model per demand (ADR-007): light requests start on Haiku, the rest on Sonnet; strong is
    # reached only by escalation or "use opus".
    models: dict[Literal["light", "standard", "strong"], str] = Field(
        default_factory=lambda: {"light": "claude-haiku-5-5", "standard": "claude-sonnet-5-5", "strong": "claude-opus-5-5"}
    )
    # Move a run to a stronger model mid-request when Claude asks or keeps struggling.
    escalation: bool = True
    # Ask on the overlay before switching a run to the strong model.
    confirm_strong: bool = False
    # Web search and fetch for ordinary requests ("research the history of tea"). They only read,
    # so there's no card; a workflow gets them only if its manifest declares them.
    web: bool = True
    # Tool-using steps on one model before Swift moves the run up.
    turn_limits: dict[Literal["light", "standard"], int] = Field(default_factory=lambda: {"light": 8, "standard": 25})
    # Quick facts and everyday language: one tool-free call to the light model, no agent run (ADR-007 §10).
    quick_answers: bool = True


class LocalSettings(_Section):
    """What "open ..." may open (ADR-007). Spoken names only; nothing else is ever started."""

    enabled: bool = True
    # Spoken name -> command or registered app name. Chrome and Notepad resolve through Windows.
    apps: dict[str, str] = Field(
        default_factory=lambda: {
            "vs code": "code",
            "vscode": "code",
            "visual studio code": "code",
            "code": "code",
            "chrome": "chrome",
            "google chrome": "chrome",
            "notepad": "notepad",
            "explorer": "explorer",
            "file explorer": "explorer",
        }
    )
    # Spoken name -> folder, added to Documents, Downloads and Desktop (these names win).
    folders: dict[str, str] = Field(default_factory=dict)
    # Spoken name -> project folder, added to executor.working_dirs (named by folder name).
    projects: dict[str, str] = Field(default_factory=dict)
    # The app a project opens in unless the request names one (a key of apps).
    editor: str = "vs code"

    @field_validator("folders", "projects")
    @classmethod
    def _expand(cls, v: dict[str, str]) -> dict[str, str]:
        return {k: expand(p) for k, p in v.items()}


class DemandClassifierSettings(_Section):
    # Local demand classifier (ADR-007 §4). Off, or with the model missing, the keyword estimate answers alone.
    # Off by default (owner decision 2026-10-23): on the test split it under-estimated 1 of 13 standard
    # requests, where the keywords had 0. Turn on once that is back to 0 (more examples, learn_demand.py).
    enabled: bool = False
    model_dir: str = "%LOCALAPPDATA%/Swift/models/bge-small-en-v1.5"
    # int8 model (34 MB, ~14 ms); false uses the fp32 one (133 MB, ~20 ms), same accuracy on the eval set.
    quantized: bool = True
    # Share of the nearest examples' weight that must say light; below it the request starts on Sonnet.
    threshold: float = Field(0.7, gt=0, le=1)
    # Examples you approved with spikes/routing/learn_demand.py, added to the built-in ones.
    examples_file: str = "%LOCALAPPDATA%/Swift/demand_examples.jsonl"

    @field_validator("model_dir", "examples_file")
    @classmethod
    def _expand(cls, v: str) -> str:
        return expand(v)


class ContactSettings(_Section):
    """Someone Swift may email (ADR-010): "my lecturer" finds them through ``aliases``."""

    name: str = Field(min_length=1)
    email: str = Field(pattern=r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")
    aliases: list[str] = Field(default_factory=list)


class ConnectorSettings(_Section):
    # Which email service Swift's tools use (ADR-010 §9). gmail needs signing in first:
    # uv run --group spikes python -m swift.connectors.gmail signin. Debug mode always uses fake.
    email: Literal["none", "fake", "gmail"] = "none"
    # Where calendar-event adds events (ADR-011 W1). google shares the Gmail sign-in, which needs
    # signing in again once to grant calendar.events. Debug mode always uses fake.
    calendar: Literal["none", "fake", "google"] = "none"


class WorkflowSettings(_Section):
    """Workflows (ADR-011 W1): the built-in ones ship with Swift; yours live in ``dir``."""

    enabled: bool = True
    dir: str = "%APPDATA%/Swift/workflows"

    @field_validator("dir")
    @classmethod
    def _expand(cls, v: str) -> str:
        return expand(v)


class DesktopSettings(_Section):
    """Desktop awareness (ADR-012 D1-D2): where you are, "this" and "here", writing where you are.

    Read only when you speak, never stored, sent only when a request needs it. Never read:
    password managers, banking sites and private browser windows, plus what you add here.
    """

    enabled: bool = True
    # More apps never to look at, by executable name ("Signal.exe").
    never_read_apps: list[str] = Field(default_factory=list)
    # More window-title words never to look at ("payroll", "mybank.com").
    never_read_titles: list[str] = Field(default_factory=list)


class SystemSettings(_Section):
    """The system lane (ADR-016 §3): timers, reminders, volume, theme and other device controls
    Swift does itself, in milliseconds, without a model. Nothing here sleeps, restarts or shuts down."""

    enabled: bool = True
    # Timers, alarms and reminders, kept across restarts.
    schedule_file: str = "%LOCALAPPDATA%/Swift/schedule.json"
    # A short sound when one is due.
    chime: bool = True

    @field_validator("schedule_file")
    @classmethod
    def _expand(cls, v: str) -> str:
        return expand(v)


class SpeechSettings(_Section):
    """Swift's voice (ADR-016 §4): answers said aloud, in short. The card always shows everything.

    replies: "auto" speaks the answer to a spoken request and stays quiet for a typed one;
    "always" speaks every answer; "never" keeps Swift silent. Never while you are away, locked
    or asleep. Timers and alarms are said when they go off unless replies are "never".
    """

    enabled: bool = True
    replies: Literal["auto", "always", "never"] = "auto"
    # A Windows voice by name ("Mark", "Zira", "David"); empty: the Windows default.
    voice: str = ""
    rate: int = Field(0, ge=-10, le=10)
    volume: int = Field(100, ge=0, le=100)


class LoggingSettings(_Section):
    interactions: str = "%LOCALAPPDATA%/Swift/interactions.jsonl"
    app_log_dir: str = "%LOCALAPPDATA%/Swift/logs"
    # Every side effect (a sent email), before and after; metadata only (ADR-010 §4).
    journal: str = "%LOCALAPPDATA%/Swift/journal.jsonl"
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("interactions", "app_log_dir", "journal")
    @classmethod
    def _expand(cls, v: str) -> str:
        return expand(v)


class Settings(_Section):
    hotkeys: Hotkeys = Field(default_factory=Hotkeys)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    wake: WakeSettings = Field(default_factory=WakeSettings)
    stt: SttSettings = Field(default_factory=SttSettings)
    executor: ExecutorSettings = Field(default_factory=ExecutorSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    local: LocalSettings = Field(default_factory=LocalSettings)
    # Route transcripts (ADR-007): commands and time/date handled by Swift, the rest to the
    # executor with a demand estimate. False sends every transcript to the executor as before.
    routing: bool = True
    # A request within this many seconds of the previous Claude answer is sent with that
    # exchange as context, so "now commit it" works (ADR-007 §9). 0 turns it off.
    followup_context_s: float = Field(300.0, ge=0)
    demand_classifier: DemandClassifierSettings = Field(default_factory=DemandClassifierSettings)
    connectors: ConnectorSettings = Field(default_factory=ConnectorSettings)
    workflows: WorkflowSettings = Field(default_factory=WorkflowSettings)
    desktop: DesktopSettings = Field(default_factory=DesktopSettings)
    system: SystemSettings = Field(default_factory=SystemSettings)
    speech: SpeechSettings = Field(default_factory=SpeechSettings)
    # The only people Swift resolves besides your Google contacts (ADR-010 §4: addresses never
    # come from the model or from speech alone).
    contacts: list[ContactSettings] = Field(default_factory=list)
    # Your name as it ends the emails Swift drafts ("Regards, Francis Chianu"). Empty: the name on
    # your Google account.
    owner_name: str = ""
    debug: bool = False


class SettingsError(ValueError):
    pass


def load_settings(path: Path | None) -> Settings:
    if path is None or not path.exists():
        return Settings()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SettingsError(f"{path.name}: cannot read: {exc}") from None
    if not isinstance(data, dict):
        raise SettingsError(f"{path.name}: top level must be a mapping")
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()
        )
        raise SettingsError(f"{path.name}: {problems}") from None
