"""Pydantic models for the four config files (§12).

Every model forbids unknown keys so typos surface as validation issues instead
of being silently ignored. Sections not consumed until later phases are present
with their spec defaults so the files are complete from first run.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONFIG_SCHEMA_VERSION = 1
PERMISSIONS_SCHEMA_VERSION = 1
PROFILES_SCHEMA_VERSION = 1
ALIASES_SCHEMA_VERSION = 1


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- config.toml -------------------------------------------------------------


class WakeSection(_Section):
    engine: Literal["openwakeword", "porcupine"] = "openwakeword"
    model_path: str = ""  # path to a custom model, or a pretrained name
    phrase: str = "Hey Swift"
    threshold: float = Field(0.5, ge=0.0, le=1.0)
    threshold_during_tts_delta: float = Field(0.2, ge=0.0, le=1.0)
    refractory_s: float = Field(1.5, ge=0.0)
    verify: Literal["off", "stt"] = "off"


class AudioSection(_Section):
    sample_rate: int = 16_000
    blocksize: int = 1280
    ring_seconds: float = Field(10.0, ge=10.0)
    preroll_ms: int = Field(300, ge=0)
    tail_guard_ms: int = Field(300, ge=0)
    device_poll_s: float = Field(2.0, gt=0.0)


class VadSection(_Section):
    start_timeout_s: float = Field(3.0, gt=0.0)
    end_silence_s: float = Field(0.8, gt=0.0)
    max_duration_s: float = Field(15.0, gt=0.0)
    dictation_end_silence_s: float = Field(1.5, gt=0.0)
    dictation_max_duration_s: float = Field(60.0, gt=0.0)


class SttSection(_Section):
    model: str = "base.en"
    compute_type: Literal["int8"] = "int8"


class TtsSection(_Section):
    engine: Literal["piper"] = "piper"
    voice: str = ""


class LlmSection(_Section):
    profile: Literal["auto", "low", "standard", "high"] = "auto"
    endpoint: str = "http://127.0.0.1:11434"
    num_ctx: int = Field(8192, ge=1024)
    keep_alive: str = "30m"


class InteractionSection(_Section):
    follow_up_s: float = Field(6.0, ge=0.0)  # 0 disables the follow-up window
    foreground_budget_s: float = Field(15.0, gt=0.0)
    working_set_ttl_s: float = Field(300.0, gt=0.0)


class PrivacySection(_Section):
    cloud_llm: Literal["off", "ask", "on"] = "off"
    cloud_data_classes: list[str] = Field(default_factory=list)
    log_content: bool = False
    debug_record_audio: bool = False

    @field_validator("cloud_llm")
    @classmethod
    def _only_off_in_mvp(cls, v: str) -> str:
        if v != "off":
            raise ValueError("only cloud_llm = 'off' is implemented in the MVP")
        return v

    @field_validator("cloud_data_classes")
    @classmethod
    def _no_data_classes_in_mvp(cls, v: list[str]) -> list[str]:
        if v:
            raise ValueError("cloud_data_classes is post-MVP and must be empty")
        return v


class LoggingSection(_Section):
    level: Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    rotation_mb: int = Field(10, ge=1)
    retention_files: int = Field(5, ge=1)


class SwiftConfig(_Section):
    schema_version: int = CONFIG_SCHEMA_VERSION
    wake: WakeSection = WakeSection()
    audio: AudioSection = AudioSection()
    vad: VadSection = VadSection()
    stt: SttSection = SttSection()
    tts: TtsSection = TtsSection()
    llm: LlmSection = LlmSection()
    interaction: InteractionSection = InteractionSection()
    privacy: PrivacySection = PrivacySection()
    logging: LoggingSection = LoggingSection()


# --- permissions.toml --------------------------------------------------------

DEFAULT_DENY_GLOBS: tuple[str, ...] = (
    "**/.ssh/**",
    "**/.env*",
    "**/*.kdbx",
    "**/*.pem",
    "**/*.key",
    "**/AppData/**",
    "**/.git/**/objects/**",
    "**/Mozilla/Firefox/Profiles/**",
    "**/Google/Chrome/User Data/**",
    "**/Microsoft/Edge/User Data/**",
    "**/credentials*",
)


class FilesPermissions(_Section):
    # Environment variables are expanded when the policy is built (Phase 3).
    allowed_roots: list[str] = Field(default_factory=lambda: ["%USERPROFILE%\\Documents"])
    deny_globs: list[str] = Field(default_factory=lambda: list(DEFAULT_DENY_GLOBS))
    max_file_mb: int = Field(20, ge=1)
    max_search_files: int = Field(2000, ge=1)
    max_extract_pages: int = Field(50, ge=1)
    max_extract_chars: int = Field(100_000, ge=1)


class ConfirmPermissions(_Section):
    high_risk_mode: Literal["challenge", "click_only", "voice_yes"] = "challenge"
    window_s: float = Field(8.0, gt=0.0)
    approval_ttl_s: float = Field(60.0, gt=0.0)


class PermissionsConfig(_Section):
    schema_version: int = PERMISSIONS_SCHEMA_VERSION
    files: FilesPermissions = FilesPermissions()
    confirm: ConfirmPermissions = ConfirmPermissions()

    # Set only by the loader, never read from the file (§8.3 fail-closed).
    # When True, the policy denies every non-read action.
    fail_closed: bool = Field(False, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _fail_closed_not_from_file(cls, data: object) -> object:
        if isinstance(data, dict) and "fail_closed" in data:
            raise ValueError("fail_closed cannot be set in permissions.toml")
        return data

    @classmethod
    def failed_closed(cls) -> PermissionsConfig:
        return cls.model_construct(
            schema_version=PERMISSIONS_SCHEMA_VERSION,
            files=FilesPermissions(),
            confirm=ConfirmPermissions(),
            fail_closed=True,
        )


# --- profiles.toml -----------------------------------------------------------


class ProjectTask(_Section):
    argv: list[str] = Field(min_length=1)
    timeout_s: float = Field(600.0, gt=0.0)
    summarize: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class ProjectProfile(_Section):
    path: str
    aliases: list[str] = Field(default_factory=list)
    ide: list[str] | None = None
    default: bool = False
    tasks: dict[str, ProjectTask] = Field(default_factory=dict)


class ProfilesConfig(_Section):
    schema_version: int = PROFILES_SCHEMA_VERSION
    projects: dict[str, ProjectProfile] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _single_default(self) -> ProfilesConfig:
        defaults = [name for name, p in self.projects.items() if p.default]
        if len(defaults) > 1:
            raise ValueError(f"only one project may be default; found {defaults}")
        return self


# --- aliases.toml ------------------------------------------------------------


class AliasesSeed(_Section):
    schema_version: int = ALIASES_SCHEMA_VERSION
    # Relational phrase -> contact email, e.g. "my dean" = "dean@uni.edu"
    aliases: dict[str, str] = Field(default_factory=dict)
