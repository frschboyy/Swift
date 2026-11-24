"""Finished requests are kept for reopening past the session's last three (owner, 2026-11-24; recent.py ``Gone``)."""

import asyncio
import time
from types import SimpleNamespace

from swift import recent
from swift.session import MAX_RUNS


def _run(n: int) -> SimpleNamespace:
    answer = SimpleNamespace(type="result", data={"status": "done", "summary": f"answer {n}"})
    return SimpleNamespace(answer=answer, alive=False, ui_id=f"r{n}", started_ms=int(time.time() * 1000) + n,
                           title=f"request {n}", summary="", words="", thread=f"t{n}")


def _session() -> SimpleNamespace:
    return SimpleNamespace(_runs=[], _gone=recent.Gone(MAX_RUNS), _focus=None)


def test_the_gone_list_stays_short_and_the_kept_one_reopens_older_answers():
    session = _session()
    runs = [_run(n) for n in range(10)]
    for run in runs:
        session._gone.append(run)
    assert list(session._gone) == runs[-MAX_RUNS:]  # "stop the research one" still sees only the last few
    assert len(session._gone.kept) == 10
    brought: list[SimpleNamespace] = []

    async def bring(run: SimpleNamespace) -> bool:
        brought.append(run)
        return True

    session._bring = bring
    asyncio.run(recent.open_(session, "r1", "open"))  # long out of the session's last three
    assert brought == [runs[1]]


def test_kept_holds_each_run_once_and_at_most_max_kept():
    session = _session()
    run = _run(0)
    session._gone.append(run)
    session._gone.append(run)
    assert list(session._gone.kept) == [run]
    for n in range(1, recent.MAX_KEPT + 5):
        session._gone.append(_run(n))
    assert len(session._gone.kept) == recent.MAX_KEPT
    assert run not in session._gone.kept
