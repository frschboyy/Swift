"""AcousticWake (ADR-021 stage 1): hit times, refractory, reset, pause, a full queue, a scorer failing.

A fake scorer stands in for the models (not in git): it scores 1.0 on the chunks listed as hot, 0.0 elsewhere.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from swift.wake_acoustic import CHUNK, RATE, AcousticWake

BLOCK = 512  # the recorder's block (32 ms)
T0 = 1000.0  # monotonic time when the stream starts


class FakeScorer:
    def __init__(self, hot=(), gate: threading.Event | None = None, fail_on: int | None = None) -> None:
        self.hot, self.gate, self.fail_on = set(hot), gate, fail_on
        self.chunks = self._pending = self.resets = 0
        self.entered = threading.Event()

    @property
    def pending(self) -> int:
        return self._pending

    def push(self, block: np.ndarray) -> list[float]:
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(5)
        self._pending += len(block)
        out = []
        while self._pending >= CHUNK:
            self._pending -= CHUNK
            if self.chunks == self.fail_on:
                self.fail_on = None  # once
                raise RuntimeError("bad block")
            out.append(1.0 if self.chunks in self.hot else 0.0)
            self.chunks += 1
        return out

    def reset(self) -> None:
        self.chunks = self._pending = 0
        self.resets += 1


def stream(wake: AcousticWake, seconds: float, start: float = T0) -> float:
    """Push `seconds` of silence in recorder-sized blocks; returns when the last block arrived."""
    n = int(seconds * RATE / BLOCK)
    for k in range(n):
        wake.push(np.zeros(BLOCK, np.int16), at=start + (k + 1) * BLOCK / RATE)
        if k % 100 == 99:
            wake.wait_idle()  # the microphone comes in real time; never fill the queue here
    wake.wait_idle()
    return start + n * BLOCK / RATE


def chunk_end(k: int, start: float = T0) -> float:
    return start + (k + 1) * CHUNK / RATE


@pytest.fixture
def make():
    made = []

    def _make(scorer, **kw) -> AcousticWake:
        wake = AcousticWake(scorer, **kw)
        made.append(wake)
        return wake

    yield _make
    for wake in made:
        wake.close()


def test_a_hit_is_the_time_its_80_ms_ended(make):
    wake = make(FakeScorer(hot=[10]))
    stream(wake, 3.0)
    assert wake.first_hit(T0, T0 + 3) == pytest.approx(chunk_end(10), abs=1e-6)
    assert wake.stats["hits"] == 1


def test_first_hit_looks_only_between_the_times_asked(make):
    wake = make(FakeScorer(hot=[10, 40]))
    stream(wake, 5.0)
    assert wake.first_hit(T0, T0 + 5) == pytest.approx(chunk_end(10))
    assert wake.first_hit(chunk_end(10) + 0.01, T0 + 5) == pytest.approx(chunk_end(40))
    assert wake.first_hit(T0 + 4, T0 + 5) is None


def test_hits_closer_than_the_refractory_count_once(make):
    wake = make(FakeScorer(hot=[10, 11, 12, 20, 40]), refractory_s=1.5)  # 20 is 0.8 s after 10; 40 is 2.4 s
    stream(wake, 5.0)
    assert wake.stats["hits"] == 2
    assert wake.first_hit(chunk_end(10) + 0.01, T0 + 5) == pytest.approx(chunk_end(40))


def test_old_hits_are_forgotten(make):
    wake = make(FakeScorer(hot=[10, 300]), keep_s=15.0)  # 300 is 23.2 s after 10
    stream(wake, 26.0)
    assert wake.first_hit(T0, chunk_end(10) + 0.01) is None
    assert wake.first_hit(T0, T0 + 26) == pytest.approx(chunk_end(300))


def test_reset_forgets_hits_and_starts_the_scorer_over(make):
    scorer = FakeScorer(hot=[10])
    wake = make(scorer)
    end = stream(wake, 2.0)
    assert wake.first_hit(T0, end) is not None
    wake.reset()
    assert wake.first_hit(T0, end) is None
    stream(wake, 2.0, start=end)  # a fresh scorer: chunk 10 of the new stream is hot again
    assert scorer.resets == 1
    assert wake.first_hit(end, end + 2) == pytest.approx(chunk_end(10, start=end))


def test_while_paused_nothing_is_heard(make):
    scorer = FakeScorer(hot=[10])
    wake = make(scorer)
    wake.pause()
    end = stream(wake, 2.0)
    assert scorer.chunks == 0 and wake.first_hit(T0, end) is None
    wake.resume()
    stream(wake, 2.0, start=end)
    assert wake.first_hit(end, end + 2) == pytest.approx(chunk_end(10, start=end))


def test_a_block_being_scored_when_the_screen_locks_adds_no_hit(make):
    gate = threading.Event()
    scorer = FakeScorer(hot=[0], gate=gate)
    wake = make(scorer)
    wake.push(np.zeros(CHUNK, np.int16), at=T0 + CHUNK / RATE)
    assert scorer.entered.wait(5)  # the worker is inside push(), about to score a hit
    wake.pause()
    gate.set()
    wake.wait_idle()
    assert wake.first_hit(0, T0 + 10) is None and wake.stats["hits"] == 0


def test_a_full_queue_drops_its_blocks_and_starts_the_scorer_over(make):
    gate = threading.Event()
    scorer = FakeScorer(gate=gate)
    wake = make(scorer, max_blocks=5)
    wake.push(np.zeros(BLOCK, np.int16), at=T0)
    assert scorer.entered.wait(5)  # the worker is stuck on the first block
    for k in range(6):  # five fill the queue, the sixth overflows it
        wake.push(np.zeros(BLOCK, np.int16), at=T0 + k)
    assert wake.stats["dropped"] == 1
    gate.set()
    wake.wait_idle()
    assert scorer.resets == 1  # never scores across the hole


def test_a_failing_scorer_doesnt_stop_wake_listening(make):
    scorer = FakeScorer(hot=[20], fail_on=5)
    wake = make(scorer)
    stream(wake, 4.0)
    assert scorer.resets == 1  # started over after the bad block
    assert wake.stats["hits"] == 1  # and still heard the next "Hey Swift"


def test_push_copies_the_block():
    """The recorder's tap gets PortAudio's buffer, which is reused for the next block."""
    seen = []

    class Keep(FakeScorer):
        def push(self, block):
            seen.append(block)
            return super().push(block)

    wake = AcousticWake(Keep())
    try:
        buf = np.ones(BLOCK, np.int16)
        wake.push(buf, at=T0)
        wake.wait_idle()
        buf[:] = 7
        assert seen[0].max() == 1
    finally:
        wake.close()
