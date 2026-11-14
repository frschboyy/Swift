"""The improvement pass as one of Swift's own runs (audit B-06; ``swift.stt.improve``).

Started by the tray's "Improve speech recognition", or once a week while the owner is idle. It
shows a step while it checks the test set, then one confirm card with the word fixes it would add
("'tori' -> 'Tauri'"), and a result card with the accuracy check. Nothing is applied unless the
card is approved; a card left unanswered is asked again on the next pass. Everything runs on this
PC: no network, no model training.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

from loguru import logger

from swift.executors.base import SWIFT, ExecEvent, ExecResult, LocalRuns, WorkerTask
from swift.stt.fixes import WordFixes
from swift.stt.improve import Proposal, Report, decide, run_pass
from swift.stt.recordings import Recordings
from swift.stt.transcriber import LocalTranscriber, SttUnavailable

# The words a run of this executor is started with (the card's title and the log's request).
REQUEST = "Improve speech recognition"
# How long the word-fix card waits before it is left for next time.
ANSWER_S = 300.0
SHOWN_FIXES = 8


def describe(proposals: list[Proposal]) -> str:
    lines = [f"“{p.heard}” → “{p.meant}”" + (f" (heard {p.count} times)" if p.count > 1 else "")
             for p in proposals[:SHOWN_FIXES]]
    if len(proposals) > SHOWN_FIXES:
        lines.append(f"and {len(proposals) - SHOWN_FIXES} more")
    return "\n".join(lines) + "\n\nLearned from clips you said again. Reject: never suggested again."


class ImproveExecutor(LocalRuns):
    name = "improve"
    provider = SWIFT

    def __init__(
        self,
        recordings: Recordings,
        transcriber: LocalTranscriber,
        fixes_file: Path,
        configured_fixes: Mapping[str, str] | None = None,
        answer_s: float = ANSWER_S,
    ) -> None:
        self.recordings = recordings
        self.transcriber = transcriber
        self.fixes_file = fixes_file
        self.configured_fixes = dict(configured_fixes or {})
        self.answer_s = answer_s
        super().__init__()
        self.last: Report | None = None

    async def start(self, task: WorkerTask) -> str:
        run_id = f"improve-{next(self._ids)}"
        self._results[run_id] = None
        return run_id

    def _recognize(self, audio):  # type: ignore[no-untyped-def]  # stt thread
        heard = self.transcriber._transcribe_sync(audio)
        return heard.text, heard.raw_text if heard.raw_text is not None else heard.text

    async def events(self, run_id: str) -> AsyncIterator[ExecEvent]:
        self._get(run_id)
        yield ExecEvent("step", "Checking your saved recordings", activity="reading")
        try:
            await self.transcriber.wait_loaded()
            report = await asyncio.to_thread(run_pass, self._recognize, self.recordings, self.fixes_file)
        except SttUnavailable as exc:
            self._results[run_id] = ExecResult("error", f"{exc} {exc.hint}")
            return
        self.last = report
        text = report.summary()
        if report.proposals:
            request_id = f"{run_id}:fixes"
            future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            self._answers[request_id] = future
            n = len(report.proposals)
            yield ExecEvent(
                "confirm", f"Use {n} new word fix{'es' if n > 1 else ''}?", request_id=request_id,
                detail=describe(report.proposals), tool="word_fixes",
            )
            try:
                approve = await asyncio.wait_for(future, self.answer_s)
            except TimeoutError:
                text += " The word fixes weren't answered: I'll ask again next time."
            else:
                await asyncio.to_thread(decide, self.fixes_file, report.proposals, approve)
                if approve:
                    self.transcriber.fixes = WordFixes.load(self.fixes_file, self.configured_fixes)
                    text += f" Added {n} word fix{'es' if n > 1 else ''}: in use now."
                else:
                    text += " Word fixes left out; they won't be suggested again."
            finally:
                self._answers.pop(request_id, None)
        self._results[run_id] = ExecResult("done", text, meta={"improve": report.counts()})

    async def result(self, run_id: str) -> ExecResult:
        result = self._get(run_id)
        if result is None:
            logger.warning("improvement pass ended without a result")
            return ExecResult("cancelled", "Stopped.")
        return result
