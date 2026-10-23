"""Interaction log: one JSON line per interaction (research data, local only).

Fields (absent when they don't apply):

- ``ts`` (start, local time with offset) and ``id``
- ``source``: "voice", "debug.run" or "debug.ask"
- ``transcript``, ``audio_s``, ``first_audio_ms`` (key-down to first audio), ``stt_ms`` and ``stt_model``
- ``peak_db`` (loudest 32 ms of the recording, dBFS) and ``audio_file`` (when ``stt.save_audio`` is on)
- ``transcript_raw``: what the model heard, when word fixes changed it
- ``executor``, ``run_ms`` (the executor's run), ``interaction_ms`` (key-down to result)
- ``steps``: ``[{t_ms, text}]``
- ``status``: done, cancelled, error or rejected, with ``error`` (a code) and ``reason``
- ``approvals``: ``[{tool, decision, asked_ms, answered_ms}]``
- ``cost_usd``, ``turns``, ``denied``, ``exit_code`` (Claude Code runs)

The transcript is written in full: this file is the owner's own data and never
leaves the machine. The app log (``swift.log``) stays redacted.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from loguru import logger

from swift import __version__

FIELD_ORDER = (
    "ts", "id", "source", "transcript", "transcript_raw", "audio_s", "first_audio_ms", "stt_ms", "stt_model",
    "peak_db", "audio_file",
    "executor", "run_ms", "interaction_ms", "steps", "status", "error", "reason", "approvals",
    "cost_usd", "turns", "denied", "exit_code", "scenario",
)


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
