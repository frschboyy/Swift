"""An acoustic "Hey Swift" detector: stage 1 of the second way in (ADR-021). Not wired in yet.

Every 80 ms of microphone audio gets a score in 0..1 for "Hey Swift just ended here". Three small models,
run here with onnxruntime (which onnx-asr already brings; nothing else is imported):

- openWakeWord's melspectrogram and embedding models (Apache-2.0): one 96-dim embedding per 80 ms,
  from the last 76 mel frames;
- the "Hey Swift" head from the wake trial (a TemporalCNN trained with ViolaWake's trainer): a score
  from the last 9 embeddings.

The computation follows ViolaWake 0.2.10's streaming backbone exactly. `spikes/wake/parity.py` checks the
scores against ViolaWake's on the trial's clips. Every session runs on one thread: at onnxruntime's default
thread count the same scoring took about 75% of a core instead of 7% (trial, round 3).
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from swift.wake import _TRIM, WakeMatch, match_wake_window

RATE = 16_000
CHUNK = 1280  # samples per score: 80 ms at 16 kHz
# Stage 2's windows: (seconds of audio, ending this long after the hit). All three count: without the long
# one, misses went from 28.1% to 29.5% (wake trial, round 3). Stage 2 runs once the utterance has ended, so
# the long one costs no waiting.
WINDOWS = ((1.2, 0.3), (1.6, 0.3), (2.0, 1.0))
# The request starts this long before the hit: the detector fires just after the name ends. On 84 of the
# owner's "Hey Swift <command>" takes: first word right 57 from -0.2 s, 47 from the hit, 40 from +0.1 s;
# from -0.3 s a piece of the name ("...wift") starts showing up (2026-11-11).
REQUEST_FROM = -0.2
_CONTEXT = 480  # samples before each chunk that the melspectrogram also sees
_MEL_FRAMES = 76  # mel frames per embedding
_EMBEDDINGS = 9  # embeddings per score


class HeySwiftScorer:
    """Streams int16 16 kHz audio in and gives one score per completed 80 ms (0.0 until 9 embeddings exist)."""

    def __init__(self, models_dir: Path, head: str = "hey_swift.onnx") -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1

        def load(name: str):  # noqa: ANN202
            return ort.InferenceSession(str(models_dir / name), options, providers=["CPUExecutionProvider"])

        self._mel, self._emb, self._head = load("melspectrogram.onnx"), load("embedding_model.onnx"), load(head)
        self._mel_in = self._mel.get_inputs()[0].name
        self._emb_in = self._emb.get_inputs()[0].name
        self._head_in = self._head.get_inputs()[0].name
        self.reset()

    def reset(self) -> None:
        """Forget everything heard (a reopened stream starts as a fresh one)."""
        self._pending = np.zeros(0, np.int16)
        self._context = np.zeros(0, np.int16)  # empty at the start, as ViolaWake's ring buffer is
        self._mels = np.ones((_MEL_FRAMES, 32), np.float32)
        self._embeddings: deque[np.ndarray] = deque(maxlen=_EMBEDDINGS)

    def push(self, block: np.ndarray) -> list[float]:
        """Add a block of any length; one score for each 80 ms it completes."""
        self._pending = np.concatenate([self._pending, np.asarray(block, np.int16).reshape(-1)])
        scores = []
        while len(self._pending) >= CHUNK:
            chunk, self._pending = self._pending[:CHUNK], self._pending[CHUNK:]
            scores.append(self._score(chunk))
        return scores

    def _score(self, chunk: np.ndarray) -> float:
        audio = np.concatenate([self._context, chunk]).astype(np.float32)[None, :]
        self._context = chunk[-_CONTEXT:]
        mel = np.squeeze(self._mel.run(None, {self._mel_in: audio})[0]).astype(np.float32) / 10.0 + 2.0
        self._mels = np.vstack([self._mels, mel])[-_MEL_FRAMES:]
        window = self._mels[None, :, :, None]
        self._embeddings.append(np.asarray(self._emb.run(None, {self._emb_in: window})[0], np.float32).reshape(96))
        if len(self._embeddings) < _EMBEDDINGS:
            return 0.0
        batch = np.stack(self._embeddings)[None, :, :]
        return float(np.asarray(self._head.run(None, {self._head_in: batch})[0]).reshape(-1)[0])

    @property
    def pending(self) -> int:
        """Samples pushed but not yet scored (less than one chunk)."""
        return len(self._pending)


class Scorer(Protocol):
    pending: int

    def push(self, block: np.ndarray) -> list[float]: ...

    def reset(self) -> None: ...


class AcousticWake:
    """Stage 1, always on: scores the microphone on its own thread and remembers when it heard "Hey Swift".

    ``push(block)`` is the recorder's tap: on the audio thread it only copies the block and its arrival
    time (``time.monotonic()``, the clock WakeListener's ``ended_at`` uses) into a bounded queue. A worker
    thread scores the blocks in order. A score at or over ``threshold`` is a hit at the time its 80 ms ended.
    After a hit, ``refractory_s`` passes before the next one. Hits from the last ``keep_s`` are kept, as times
    only: the detector keeps no audio. ``first_hit(t0, t1)`` is what the session asks once an utterance has
    ended.

    If the queue fills (the worker fell behind), its blocks are dropped and the scorer starts over, rather
    than scoring audio with a hole in it. ``reset()`` (a reopened stream) and ``pause()`` (locked, or
    listening paused) forget everything heard; while paused, pushed blocks are ignored.
    """

    def __init__(self, scorer: Scorer, threshold: float = 0.5, refractory_s: float = 1.5, keep_s: float = 15.0,
                 max_blocks: int = 200) -> None:
        self.threshold, self.refractory_s, self.keep_s = threshold, refractory_s, keep_s
        self._scorer = scorer
        self._queue: queue.Queue[tuple[np.ndarray, float, int] | None] = queue.Queue(max_blocks)
        self._lock = threading.Lock()
        self._hits: deque[float] = deque()
        self._paused = False
        # A reset bumps the generation: blocks pushed before it are skipped, and a block being scored when it
        # came adds no hit. The worker owns the scorer and resets it when it sees a new generation or _restart.
        self._gen = 0
        self._scored_gen = 0
        self._restart = False
        self.stats = {"hits": 0, "dropped": 0}  # content-free counters for the wake listening log line
        self._worker = threading.Thread(target=self._run, name="acoustic-wake", daemon=True)
        self._worker.start()

    def push(self, block: np.ndarray, at: float | None = None) -> None:
        """The audio thread: copy and enqueue, never block. ``at`` is when the block's last sample arrived."""
        if self._paused:
            return
        item = (np.asarray(block, np.int16).reshape(-1).copy(), time.monotonic() if at is None else at, self._gen)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self._drain()
            self.stats["dropped"] += 1
            self._restart = True
            self._queue.put_nowait(item)

    def first_hit(self, t0: float, t1: float) -> float | None:
        """The earliest hit between t0 and t1 (monotonic seconds), if any."""
        with self._lock:
            return next((t for t in self._hits if t0 <= t <= t1), None)

    def reset(self) -> None:
        """Forget what was heard (the stream reopened)."""
        with self._lock:
            self._gen += 1
            self._hits.clear()
        self._drain()

    def pause(self) -> None:
        """Locked or listening paused: hear nothing, and forget what was heard."""
        self._paused = True
        self.reset()

    def resume(self) -> None:
        self.reset()
        self._paused = False

    def wait_idle(self) -> None:
        """Until every pushed block is scored (for tests)."""
        self._queue.join()

    def close(self) -> None:
        self._drain()
        self._queue.put(None)
        self._worker.join(timeout=2)

    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
            self._queue.task_done()

    def _run(self) -> None:
        while (item := self._queue.get()) is not None:
            try:
                block, at, gen = item
                if gen != self._gen:
                    continue  # pushed before a reset
                if self._restart or gen != self._scored_gen:
                    self._restart, self._scored_gen = False, gen
                    self._scorer.reset()
                self._score(block, at, gen)
            except Exception:  # noqa: BLE001 - one bad block must not stop wake listening
                self._restart = True
            finally:
                self._queue.task_done()
        self._queue.task_done()

    def _score(self, block: np.ndarray, at: float, gen: int) -> None:
        before = self._scorer.pending
        for i, score in enumerate(self._scorer.push(block)):
            # The i-th completed chunk ends this many samples into the block; the block's last sample is `at`.
            end = (i + 1) * CHUNK - before
            t = at - (len(block) - end) / RATE
            if score < self.threshold:
                continue
            with self._lock:
                if gen != self._gen or (self._hits and t - self._hits[-1] < self.refractory_s):
                    continue
                self._hits.append(t)
                while self._hits and self._hits[0] < t - self.keep_s:
                    self._hits.popleft()
            self.stats["hits"] += 1


async def second_way_in(hit: float, audio: np.ndarray, started_at: float, transcriber: Any) -> WakeMatch | None:
    """Stage 2 (ADR-021): an utterance today's ``match_wake`` turned down, with an acoustic hit at ``hit``
    (monotonic seconds; the utterance's first sample is ``started_at``). Parakeet transcribes up to three
    windows around the hit, the shortest first. If one passes ``match_wake_window``, the words from just
    before the hit are the request. Transcription errors reach the caller, which handles them as for
    any utterance."""

    def at(t: float) -> int:
        return min(max(round((t - started_at) * RATE), 0), len(audio))

    for seconds, after in WINDOWS:
        window = audio[at(hit + after - seconds):at(hit + after)]
        if len(window) and match_wake_window((await transcriber.transcribe(window)).text):
            break
    else:
        return None
    rest = audio[at(hit + REQUEST_FROM):]
    text = (await transcriber.transcribe(rest)).text if len(rest) >= RATE // 10 else ""
    text = text.lstrip(_TRIM)
    first, _, tail = text.partition(" ")
    if "wift" in first.lower():  # a piece of the name, if the hit came early
        text = tail
    return WakeMatch("hey swift", text.lstrip(_TRIM).strip())
