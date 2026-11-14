"""Run records (groundwork, handoff §4): one append-only event log per run.

A run is one request, from the moment Swift starts on it to its end: the interaction record's ``id``.
Each run is a file, ``runs/<id>.jsonl``, one JSON line per event, written as it happens:

- ``started``: ``origin`` (ADR-019 N2), ``source``, ``thread``
- ``worker``: ``provider``, ``ui`` (the provider's run id) and ``skipped`` (who couldn't take it), each time one starts
- ``step``: ``t_ms``, ``activity``, ``by`` ("swift": Swift's own step)
- ``asked``: ``t_ms``, ``tool`` (an approval card)
- ``artifact``: ``kind``, ``version``, ``phase``
- ``ended``: the interaction's ``swift.log`` line (``runlog.summary``: why it went where it went, the
  worker, the outcome) and each approval's decision

Content-free: what happened, never the owner's words, a worker's text or a draft. The owner's
words are in the local interaction log, the view of this record with them: its ``steps``,
``approvals`` and ``artifacts`` are written here only (``step``, ``asked``, ``artifact``), and the
session writes its line, then the ``ended`` event, as the request ends. Side effects are the
journal's (``security/journal.py``), each action naming its run.
"""

from __future__ import annotations

import contextvars
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from swift.ipc.protocol import ORIGINS
from swift.runlog import summary
# An approval's fields that say what happened; ``heard`` (the owner's words) and ids stay out.
_APPROVAL_FIELDS = ("tool", "decision", "source", "asked_ms", "answered_ms", "by", "explained")

# The request the running task works for: a journal entry written in it names its run.
current: contextvars.ContextVar[str | None] = contextvars.ContextVar("swift_run_record", default=None)

Status = Literal["running", "ended", "interrupted"]


class RunRecords:
    def __init__(self, folder: Path | None) -> None:
        # None keeps the events in memory only (tests).
        self.folder = folder
        self._memory: dict[str, list[dict[str, Any]]] = {}
        self._live: set[str] = set()  # started in this process and not ended

    def event(self, run: str, name: str, /, **fields: Any) -> None:
        """Append one event. Never raises: losing a record line must not break the request."""
        if not run:
            return
        row = {"ts": datetime.now().astimezone().isoformat(timespec="milliseconds"), "event": name}
        row |= {k: v for k, v in fields.items() if v is not None}
        if name == "started":
            self._live.add(run)
        elif name == "ended":
            self._live.discard(run)
        if self.folder is None:
            self._memory.setdefault(run, []).append(row)
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            with (self.folder / f"{run}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:
            logger.warning("could not write a run record", error=type(exc).__name__)

    def events(self, run: str) -> list[dict[str, Any]]:
        if self.folder is None:
            return list(self._memory.get(run, []))
        path = self.folder / f"{run}.jsonl"
        if not run or not path.is_file():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a line cut short by a crash
        return out

    def status(self, run: str) -> Status | None:
        """Whether ``run`` is still going, ended, or was cut off by Swift stopping; None: no such run."""
        if run in self._live:
            return "running"
        events = self.events(run)
        if not events:
            return None
        return "ended" if events[-1].get("event") == "ended" else "interrupted"

    # The interaction record's lists are filled here only, so the record and the log can't disagree.

    def begin(self, record: dict[str, Any], origin: str = "asked") -> None:
        assert origin in ORIGINS, origin
        record["steps"], record["approvals"] = [], []
        current.set(record["id"])
        self.event(record["id"], "started", origin=origin, source=record.get("source"), thread=record.get("thread"))

    def worker(self, record: dict[str, Any], provider: str, ui: str, skipped: list[str]) -> None:
        record["provider"] = provider
        if skipped:
            record["skipped"] = skipped
        self.event(record["id"], "worker", provider=provider, ui=ui, skipped=skipped or None)

    def step(self, record: dict[str, Any], t_ms: int, text: str, activity: str | None, by: str | None = None) -> None:
        record["steps"].append({"t_ms": t_ms, "text": text, "activity": activity} | ({"by": by} if by else {}))
        self.event(record["id"], "step", t_ms=t_ms, activity=activity, by=by)

    def asked(self, record: dict[str, Any], tool: str | None, request_id: str, t_ms: int, by: str | None = None,
              explained: bool | None = None) -> None:
        extra = ({"by": by} if by else {}) | ({"explained": explained} if explained is not None else {})
        record["approvals"].append({"tool": tool, "request_id": request_id, "asked_ms": t_ms} | extra)
        self.event(record["id"], "asked", t_ms=t_ms, tool=tool, **extra)

    def artifact(self, record: dict[str, Any], artifact_id: str, kind: str, version: int, phase: str) -> None:
        record.setdefault("artifacts", []).append({"id": artifact_id, "kind": kind, "version": version, "phase": phase})
        self.event(record["id"], "artifact", kind=kind, version=version, phase=phase)

    def end(self, record: dict[str, Any]) -> None:
        approvals = [{k: a[k] for k in _APPROVAL_FIELDS if k in a} for a in record.get("approvals", [])]
        self.event(record.get("id", ""), "ended", **summary(record), approvals=approvals or None)
