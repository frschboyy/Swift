"""One question's window for its answer (swift/answer_window.py; seams audit S3), on a virtual clock."""

from __future__ import annotations

import asyncio
from typing import Any

from virtual_clock import VirtualLoop

from swift import clock
from swift.answer_window import CAP_S, AnswerWindow


def _run(coro: Any) -> Any:
    loop = VirtualLoop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_it_listens_until_its_deadline_then_closes_once() -> None:
    async def go() -> tuple[list[float], str, float | None]:
        closed: list[float] = []
        w = AnswerWindow(lambda: closed.append(clock.now()))
        start = clock.now()
        assert w.listen(25) == start + 25 and w.left() == 25 and w.takes()
        await asyncio.sleep(30)
        return [t - start for t in closed], w.state, w.left()

    assert _run(go()) == ([25.0], "closed", None)


def test_asking_has_no_countdown_and_the_window_starts_when_swift_has_said_it() -> None:
    async def go() -> tuple[bool, float | None, float]:
        w = AnswerWindow(lambda: None)
        w.asking(55)
        listening_while_asking = w.takes()
        await asyncio.sleep(8)  # Swift says the question for 8 s
        start = clock.now()
        deadline = w.listen(25)
        return listening_while_asking, w.left(), deadline - start

    assert _run(go()) == (False, 25.0, 25.0)


def test_a_reask_starts_a_whole_window_again() -> None:
    async def go() -> tuple[float | None, list[float]]:
        closed: list[float] = []
        w = AnswerWindow(lambda: closed.append(clock.now()))
        start = clock.now()
        w.listen(25)
        await asyncio.sleep(20)
        w.asking(55)  # "Sorry, was that a yes or a no?", said for 5 s
        await asyncio.sleep(5)
        w.listen(25)
        left = w.left()
        await asyncio.sleep(30)
        return left, [t - start for t in closed]

    assert _run(go()) == (25.0, [50.0])


def test_it_waits_for_an_answer_still_being_said_up_to_the_cap() -> None:
    async def go(speaking_for: float) -> float:
        closed: list[float] = []
        start = clock.now()
        w = AnswerWindow(lambda: closed.append(clock.now()), busy=lambda: clock.now() < start + speaking_for)
        w.listen(1)
        await asyncio.sleep(20)
        return closed[0] - start

    assert _run(go(2.2)) == 2.5  # waited until the owner had finished (looked every 0.5 s)
    assert _run(go(100)) == 1 + CAP_S  # never longer than the cap


def test_an_utterance_counts_if_it_started_before_the_deadline() -> None:
    async def go() -> tuple[bool, bool, bool]:
        w = AnswerWindow(lambda: None)
        start = clock.now()
        w.listen(1)
        return w.takes(start + 0.9), w.takes(start + 1.1), AnswerWindow(lambda: None).takes(start)

    assert _run(go()) == (True, False, False)


def test_paused_and_closed_windows_have_no_timer_and_close_runs_nothing() -> None:
    async def go() -> tuple[str, Any, list[int], str]:
        closed: list[int] = []
        w = AnswerWindow(lambda: closed.append(1))
        w.listen(1)
        w.pause()
        paused = (w.state, w.timer)
        await asyncio.sleep(5)
        w.listen(1)
        w.close()
        await asyncio.sleep(5)
        w.listen(1)  # closed for good
        return paused[0], paused[1], closed, w.state

    assert _run(go()) == ("idle", None, [], "closed")
