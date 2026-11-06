"""Interaction log: one JSON line per interaction (research data, local only).

Fields (absent when they don't apply):

- ``ts`` (start, local time with offset) and ``id``
- ``source``: "voice", "debug.run" or "debug.ask"
- ``transcript``, ``audio_s``, ``first_audio_ms`` (key-down to first audio), ``preroll_ms`` (audio from before the key-down), ``stt_ms`` and ``stt_model``
- ``peak_db`` (loudest 32 ms of the recording, dBFS) and ``audio_file`` (when ``stt.save_audio`` is on)
- ``transcript_raw``: what the model heard, when word fixes changed it
- ``route`` (control, local, claude), ``action`` (control/local), ``demand`` and ``override`` (claude)
- ``start_model``, ``models`` (every model that ran) and ``escalations``: ``[{to, by, reason, t_ms}]`` (Claude Code)
- ``executor``, ``run_ms`` (the executor's run), ``interaction_ms`` (key-down to result)
- ``steps``: ``[{t_ms, text}]``
- ``status``: done, cancelled, error or rejected, with ``error`` (a code) and ``reason``
- ``approvals``: ``[{tool, decision, asked_ms, answered_ms, source, heard}]`` (``source``: voice or click)
- ``context``: ``{previous, age_s}`` when the previous exchange was sent along (follow-ups)
- ``cost_usd``, ``turns``, ``denied``, ``exit_code`` (Claude Code runs)

The transcript is written in full: this file is the owner's own data and never
leaves the machine. The app log (``swift.log``) stays redacted.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from loguru import logger

from swift import __version__

FIELD_ORDER = (
    "ts", "id", "source", "transcript", "transcript_raw", "audio_s", "first_audio_ms", "preroll_ms", "stt_ms", "stt_model",
    "peak_db", "audio_file",
    "route", "action", "demand", "override", "start_model", "models", "escalations",
    "executor", "run_ms", "interaction_ms", "steps", "status", "error", "reason", "approvals",
    "cost_usd", "turns", "denied", "exit_code", "scenario",
)

# The one line each interaction leaves in swift.log. An allow-list: a field that isn't here stays in
# the local interaction log only, so a new field can't reach swift.log until someone decides it may.
SUMMARY_FIELDS: frozenset[str] = frozenset({
    "action", "answered_later", "artifacts", "asked", "asks", "audio_s", "back", "carried", "clip_flags",
    "confirmed", "context", "cost_usd", "demand", "denied", "desktop", "dialogue",
    "duration_ms", "ended", "endpoint_waits", "error", "executor", "first_audio_ms", "fix",
    "follows_local", "fragment", "heard_back_ms", "improve", "intents", "interaction_ms", "live", "midrun",
    "models", "moved_on", "noise_db", "offer", "offered", "offered_resume", "override", "parked", "paused",
    "peak_db", "preroll_ms", "provider", "queued", "queued_behind", "reason", "redirected", "redirects",
    "resumed", "retries", "retry_of", "route", "run_ms", "scenario", "since_back_ms", "skipped",
    "source", "spoken_chars", "start_model", "status", "stopped_by", "stt_confidence", "stt_ms",
    "thread", "turns", "undo", "views", "workflow",
})
# Fields that stay out on purpose: words, or the name or path of something of the owner's.
LOCAL_ONLY_FIELDS: frozenset[str] = frozenset({
    "addressed_as", "approvals", "asked_unanswered", "audio_file", "id", "steps", "target", "transcript",
    "transcript_heard", "transcript_raw", "ts", "unclear",
})
_ESCALATION_FIELDS = ("to", "by", "t_ms")  # not ``reason``: the model writes it, and it can restate the request


def unclassified(fields: Iterable[str]) -> set[str]:
    """Fields nobody has decided on: safe (they stay out of swift.log), but the tests refuse them."""
    return set(fields) - SUMMARY_FIELDS - LOCAL_ONLY_FIELDS - {"escalations"}


def summary(record: dict[str, Any]) -> dict[str, Any]:
    """What ``swift.log`` may say about an interaction: its shape, never the owner's words."""
    line = {key: value for key, value in record.items() if key in SUMMARY_FIELDS}
    line["steps"] = len(record.get("steps", []))
    if "transcript" in record:
        line["transcript_chars"] = len(str(record["transcript"]))
    if "escalations" in record:
        line["escalations"] = [{k: e[k] for k in _ESCALATION_FIELDS if k in e} for e in record["escalations"]]
    return line


class InteractionLog:
    def __init__(self, path: Path, stt_model: str | None = None) -> None:
        self.path = path
        self.stt_model = stt_model
        self._lock = threading.Lock()

    def append(self, record: dict[str, Any]) -> None:
        """Never raises: losing a log line must not break the interaction."""
        row = dict(record)
        if "transcript" in row and self.stt_model and row.get("source") == "voice":
            row.setdefault("stt_model", self.stt_model)
        row["swift_version"] = __version__
        ordered = {k: row[k] for k in FIELD_ORDER if k in row}
        ordered |= {k: v for k, v in row.items() if k not in ordered}
        line = json.dumps(ordered, ensure_ascii=False, default=str) + "\n"
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line)
        except OSError as exc:
            logger.error("could not write the interaction log", path=str(self.path), error=str(exc))
