"""The action journal (ADR-010 §4; threat model T10).

One JSON line per state change: ``PENDING`` before a side effect runs, then
``DONE`` or ``FAILED``. Metadata only: never an email body, subject or full
address (T8). An action still ``PENDING`` when Swift starts is reported and
never resumed, so a crash can't send an email twice.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from loguru import logger

State = Literal["PENDING", "DONE", "FAILED"]


class Journal:
    def __init__(self, path: Path | None) -> None:
        # None keeps the entries in memory only (tests).
        self.path = path
        self.entries: list[dict[str, Any]] = []

    def write(self, action_id: str, state: State, **fields: Any) -> None:
        entry = {"ts": datetime.now().astimezone().isoformat(timespec="milliseconds"), "action": action_id,
                 "state": state, **fields}
        self.entries.append(entry)
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("could not write the action journal", error=str(exc))

    def unfinished(self) -> list[dict[str, Any]]:
        """Actions whose last entry is ``PENDING``: interrupted mid-execute. Never resumed."""
        last: dict[str, dict[str, Any]] = {}
        if self.path is not None and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and "action" in entry:
                    last[entry["action"]] = entry
        for entry in self.entries:
            last[entry["action"]] = entry
        return [e for e in last.values() if e.get("state") == "PENDING"]

    def report_unfinished(self) -> None:
        for entry in self.unfinished():
            logger.warning("an action was interrupted before it finished; it will not be retried",
                           action=entry["action"], tool=entry.get("tool"))
