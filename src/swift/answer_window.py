"""A question's window for its answer: one deadline, on one clock (seams audit 2026-11, S3).

Each question Swift asks gets its own ``AnswerWindow``; before, every question shared one timer
slot and one window slot in the session, so a second question cancelled the first one's timer
(T-01), a re-ask kept the old window (T-03), and the two clocks disagreed (T-11).

A window is in one of four states:

- ``idle``: not on screen yet (waiting behind another question), or set aside: no timer;
- ``asking``: Swift is saying the question (or saying it again). No countdown yet; a guard timer
  closes it if the voice never ends;
- ``listening``: the microphone is open for the answer until ``deadline``, counted from the end of
  Swift's speech (owner decision 9: 25 s from the end of speech);
- ``closed``: answered, put off or ended; it never opens again.

At the deadline, if the owner is still saying something (or it is still being transcribed), the
window waits a little longer, up to ``CAP_S`` past the deadline (T-02). An utterance belongs to the
window if it *started* before the deadline, whenever it was transcribed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Literal

from swift import clock

State = Literal["idle", "asking", "listening", "closed"]

# How long past its deadline a window waits for an answer still being said, and how often it looks.
CAP_S = 6.0
STEP_S = 0.5
# An utterance from the open microphone starts with this much room noise before the words (wake.py's pad):
# one that "starts" up to this long before Swift asked can still be the answer.
ANSWER_LEAD_S = 0.3


class AnswerWindow:
    def __init__(self, on_close: Callable[[], None], busy: Callable[[], bool] = lambda: False) -> None:
        """``on_close``: called once when the time runs out (never when ``close()`` is called).
        ``busy``: whether the owner is saying something right now (the window then waits for it)."""
        self._on_close = on_close
        self._busy = busy
        self.state: State = "idle"
        self.deadline: float | None = None
        self._timer: asyncio.TimerHandle | None = None

    # ---- changes -----------------------------------------------------------------------------

    def asking(self, guard_s: float) -> None:
        """Swift is saying the question: no countdown until it has; closes after ``guard_s`` regardless."""
        if self.state == "closed":
            return
        self.state, self.deadline = "asking", None
        self._arm(guard_s)

    def listen(self, seconds: float) -> float:
        """The microphone opens for the answer now, for ``seconds``: the deadline (clock time)."""
        if self.state == "closed":
            return self.deadline or clock.now()
        self.state = "listening"
        self.deadline = clock.now() + seconds
        self._arm(seconds)
        return self.deadline

    def pause(self) -> None:
        """Off the screen for now (another question in front): no timer until it comes back."""
        if self.state != "closed":
            self._cancel()
            self.state, self.deadline = "idle", None

    def close(self) -> None:
        """Answered, put off or ended: the timer stops, and ``on_close`` isn't called."""
        self._cancel()
        self.state = "closed"

    # ---- questions -----------------------------------------------------------------------------

    @property
    def open(self) -> bool:
        return self.state in ("asking", "listening")

    def takes(self, started_at: float | None = None, asked_at: float | None = None) -> bool:
        """Whether something said belongs to this window: it is listening, and the utterance started
        before the deadline (``started_at``), or, with no time given, the window hasn't closed. One begun
        before the question was asked (``asked_at``) is the owner saying the request again, not answering
        (A7, owner's run 2026-11-13 14:21: "How are you? Can you turn off the", cut short as the question
        appeared, became a second request beside the first)."""
        if self.state != "listening" or self.deadline is None:
            return False
        if started_at is None:
            return True
        return started_at <= self.deadline and (asked_at is None or started_at >= asked_at - ANSWER_LEAD_S)

    def left(self) -> float | None:
        """Seconds until the deadline while listening (0 while it waits past it), else None."""
        if self.state != "listening" or self.deadline is None:
            return None
        return max(0.0, self.deadline - clock.now())

    @property
    def timer(self) -> asyncio.TimerHandle | None:
        return self._timer

    # ---- the clock ------------------------------------------------------------------------------

    def _arm(self, seconds: float) -> None:
        self._cancel()
        try:
            self._timer = asyncio.get_running_loop().call_later(max(0.0, seconds), self._fire)
        except RuntimeError:
            self._timer = None  # no loop (a unit test of the state alone)

    def _cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _fire(self) -> None:
        self._timer = None
        if self.state == "listening" and self.deadline is not None and self._busy() \
                and clock.now() < self.deadline + CAP_S:
            self._arm(STEP_S)  # still being said, or transcribed: wait for it (T-02)
            return
        if self.state in ("asking", "listening"):
            self.state = "closed"
            self._on_close()
