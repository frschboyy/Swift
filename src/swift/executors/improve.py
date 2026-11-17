"""The improvement pass as one of Swift's own runs (audit B-06; ``swift.stt.improve``).

Started by the tray's "Improve speech recognition", or once a week while the owner is idle. It
shows a step while it checks the test set, then a result card with the accuracy check. Everything
runs on this PC: no network, no model training.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from loguru import logger

from swift.executors.base import SWIFT, ExecEvent, ExecResult, LocalRuns, WorkerTask
from swift.stt.improve import Report, run_pass
from swift.stt.recordings import Recordings
from swift.stt.transcriber import LocalTranscriber, SttUnavailable

# The words a run of this executor is started with (the card's title and the log's request).
REQUEST = "Improve speech recognition"


class ImproveExecutor(LocalRuns):
    name = "improve"
    provider = SWIFT

    def __init__(self, recordings: Recordings, transcriber: LocalTranscriber) -> None:
        self.recordings = recordings
        self.transcriber = transcriber
        super().__init__()
        self.last: Report | None = None

    async def start(self, task: WorkerTask) -> str:
        run_id = f"improve-{next(self._ids)}"
        self._results[run_id] = None
        return run_id

    def _recognize(self, audio):  # type: ignore[no-untyped-def]  # stt thread
        return self.transcriber._transcribe_sync(audio).text

    async def events(self, run_id: str) -> AsyncIterator[ExecEvent]:
        self._get(run_id)
        yield ExecEvent("step", "Checking your saved recordings", activity="reading")
        try:
            await self.transcriber.wait_loaded()
            report = await asyncio.to_thread(run_pass, self._recognize, self.recordings)
        except SttUnavailable as exc:
            self._results[run_id] = ExecResult("error", f"{exc} {exc.hint}")
            return
        self.last = report
        self._results[run_id] = ExecResult("done", report.summary(), meta={"improve": report.counts()})

    async def result(self, run_id: str) -> ExecResult:
        result = self._get(run_id)
        if result is None:
            logger.warning("improvement pass ended without a result")
            return ExecResult("cancelled", "Stopped.")
        return result
