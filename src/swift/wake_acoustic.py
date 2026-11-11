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

from collections import deque
from pathlib import Path

import numpy as np

CHUNK = 1280  # samples per score: 80 ms at 16 kHz
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
