"""Commented default files written on first run (§12).

``tests/unit/test_config.py`` asserts each template parses to exactly the
model defaults, so these cannot drift from ``models.py`` unnoticed.
"""

from __future__ import annotations

CONFIG_TOML = """\
# Swift configuration. Every key is documented in docs/configuration.md.
# Invalid sections fall back to their defaults and are reported in the tray.
schema_version = 1

[wake]
engine = "openwakeword"           # "openwakeword" | "porcupine"
model_path = ""                   # custom model file, or a pretrained name
phrase = "Hey Swift"              # display text; also used by the verifier
threshold = 0.5
threshold_during_tts_delta = 0.2  # added to threshold while Swift is speaking
refractory_s = 1.5
verify = "off"                    # "off" | "stt" (second-stage verifier)

[audio]
sample_rate = 16000
blocksize = 1280
ring_seconds = 10.0
preroll_ms = 300
tail_guard_ms = 300
device_poll_s = 2.0

[vad]
start_timeout_s = 3.0
end_silence_s = 0.8
max_duration_s = 15.0
dictation_end_silence_s = 1.5
dictation_max_duration_s = 60.0

[stt]
model = "base.en"                 # "small.en" on stronger hardware profiles
compute_type = "int8"

[tts]
engine = "piper"
voice = ""                        # set after the voice license is recorded

[llm]
profile = "auto"                  # "auto" | "low" | "standard" | "high"
endpoint = "http://127.0.0.1:11434"
num_ctx = 8192
keep_alive = "30m"

[interaction]
follow_up_s = 6.0                 # 0 disables the follow-up window
foreground_budget_s = 15.0
working_set_ttl_s = 300.0

[privacy]
cloud_llm = "off"                 # only "off" is implemented in the MVP
cloud_data_classes = []
log_content = false               # transcripts/content in DEBUG logs only if true
debug_record_audio = false        # writes audio to disk; shown in the tray when on

[logging]
level = "INFO"
rotation_mb = 10
retention_files = 5
"""

PERMISSIONS_TOML = """\
# Swift permissions. If this file fails to parse or validate, Swift FAILS
# CLOSED: every non-read action is denied until it is fixed.
# See docs/permissions.md.
schema_version = 1

[files]
allowed_roots = ["%USERPROFILE%\\\\Documents"]  # project roots from profiles.toml are added
deny_globs = [
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
]
max_file_mb = 20
max_search_files = 2000
max_extract_pages = 50
max_extract_chars = 100000

[confirm]
# "challenge": read two on-screen words aloud, or press the confirm hotkey.
# "click_only": click or hotkey only.
# "voice_yes": a plain spoken "yes" (opt-in, weaker; see docs/permissions.md).
high_risk_mode = "challenge"
window_s = 8.0
approval_ttl_s = 60.0
"""

PROFILES_TOML = """\
# Swift project profiles. Example:
#
# [projects.thesis]
# path = "C:/Users/me/Projects/thesis"
# aliases = ["my project", "thesis"]
# ide = ["C:/Users/me/AppData/Local/Programs/Microsoft VS Code/Code.exe", "."]
# default = true
#
# [projects.thesis.tasks.tests]
# argv = ["C:/Users/me/Projects/thesis/.venv/Scripts/python.exe", "-m", "pytest", "-q"]
# timeout_s = 600
# summarize = "pytest"
schema_version = 1
"""

ALIASES_TOML = """\
# Optional alias seed. Runtime aliases live in Swift's database.
# Example:
# [aliases]
# "my dean" = "dean@example.edu"
schema_version = 1
"""
