"""Local speech-to-text (PLAN.md §6): Parakeet (default) or faster-whisper.

The model is loaded once, in a background thread started at backend startup,
from Swift's local model folder only (``HF_HUB_OFFLINE`` is forced in
``swift/__init__.py``). ``transcribe()`` waits for the load if needed and runs
inference in a worker thread so the event loop keeps serving the overlay.

Both engines share the same front end: near-silent recordings are skipped,
leading and trailing silence is trimmed, and word fixes are applied to the text.
"""

from __future__ import annotations

import asyncio
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from loguru import logger

from swift.stt.fixes import WordFixes

SAMPLE_RATE = 16_000
# Loudest 32 ms block below this is treated as silence and never reaches the model,
# which otherwise invents text ("Thank you.") for room noise. Room noise here is
# about -60 dBFS; quiet speech is around -40.
SILENCE_DB = -50.0
# Blocks below this at either end are trimmed, keeping TRIM_PAD_S around the speech.
TRIM_DB = -45.0
TRIM_PAD_S = 0.2
_GATE_BLOCK = 512

PARAKEET_DIR = "parakeet-tdt-0.6b-v2"
PARAKEET_REPO = "istupakov/parakeet-tdt-0.6b-v2-onnx"
PARAKEET_FILES = ["config.json", "vocab.txt", "encoder-model.int8.onnx", "decoder_joint-model.int8.onnx"]


class SttUnavailable(RuntimeError):
    def __init__(self, message: str, hint: str) -> None:
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True)
class Transcription:
    text: str
    stt_ms: int
    audio_s: float
    peak_db: float | None = None
    # What the model said before word fixes, when they changed anything.
    raw_text: str | None = None


@dataclass(frozen=True)
class ModelStats:
    model: str
    load_s: float
    private_mb_delta: float


class Transcriber(Protocol):
    async def transcribe(self, audio: np.ndarray) -> Transcription: ...


def _block_db(samples: np.ndarray) -> np.ndarray:
    n = len(samples) // _GATE_BLOCK
    if n == 0:
        return np.zeros(0)
    blocks = samples[: n * _GATE_BLOCK].reshape(n, _GATE_BLOCK)
    rms = np.sqrt(np.mean(blocks * blocks, axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-6))


def loudest_db(samples: np.ndarray) -> float:
    """RMS level of the loudest 32 ms block, in dBFS (float samples in -1..1)."""
    db = _block_db(samples)
    return float(db.max()) if len(db) and db.max() > -120.0 else -120.0


def trim_silence(samples: np.ndarray) -> np.ndarray:
    """Cut quiet blocks at both ends, keeping TRIM_PAD_S of margin around the speech.

    Long trailing silence makes some models return nothing; it also costs time.
    """
    db = _block_db(samples)
    loud = np.nonzero(db >= TRIM_DB)[0]
    if len(loud) == 0:
        return samples
    pad = int(TRIM_PAD_S * SAMPLE_RATE)
    start = max(0, int(loud[0]) * _GATE_BLOCK - pad)
    end = min(len(samples), (int(loud[-1]) + 1) * _GATE_BLOCK + pad)
    return samples[start:end]


def _private_mb() -> float:
    import psutil

    info = psutil.Process().memory_full_info()
    return getattr(info, "private", info.uss) / 2**20


class LocalTranscriber:
    """Loading, threading and the shared front end. Subclasses supply the model."""

    name = "?"

    def __init__(self, models_dir: Path, cpu_threads: int = 4, fixes: WordFixes | None = None) -> None:
        self.models_dir = models_dir
        self.cpu_threads = cpu_threads
        self.fixes = fixes or WordFixes()
        self.stats: ModelStats | None = None
        self._model: Any = None
        self._error: SttUnavailable | None = None
        self._loaded = threading.Event()
        # One inference at a time: each engine already uses every configured thread.
        self._busy = threading.Lock()

    def _load_model(self) -> Any:
        raise NotImplementedError

    def _recognize(self, samples: np.ndarray) -> str:
        raise NotImplementedError

    def _missing_hint(self) -> str:
        return f"Make sure it's downloaded to {self.models_dir} (see README), then restart Swift."

    def start_loading(self) -> None:
        threading.Thread(target=self._load, name="stt-load", daemon=True).start()

    def _load(self) -> None:
        before = _private_mb()
        t0 = time.perf_counter()
        try:
            self._model = self._load_model()
        except Exception as exc:  # noqa: BLE001 - any failure means STT is unavailable
            logger.error("speech model failed to load", model=self.name, error=type(exc).__name__, detail=str(exc)[:200])
            self._error = SttUnavailable(f"The speech model '{self.name}' couldn't be loaded.", self._missing_hint())
        else:
            self.stats = ModelStats(self.name, round(time.perf_counter() - t0, 2), round(_private_mb() - before, 1))
            logger.info(
                "speech model loaded",
                model=self.name,
                load_s=self.stats.load_s,
                private_mb_delta=self.stats.private_mb_delta,
                word_fixes=len(self.fixes),
            )
        finally:
            self._loaded.set()

    async def wait_loaded(self) -> None:
        if not self._loaded.is_set():
            await asyncio.to_thread(self._loaded.wait)
        if self._error is not None:
            raise self._error

    async def transcribe(self, audio: np.ndarray) -> Transcription:
        await self.wait_loaded()
        return await asyncio.to_thread(self._transcribe_sync, audio)

    def _transcribe_sync(self, audio: np.ndarray) -> Transcription:
        assert self._model is not None
        samples = audio.astype(np.float32).reshape(-1) / 32768.0
        audio_s = round(len(samples) / SAMPLE_RATE, 2)
        peak_db = round(loudest_db(samples), 1)
        if peak_db < SILENCE_DB:
            return Transcription("", 0, audio_s, peak_db)
        samples = trim_silence(samples)
        with self._busy:
            t0 = time.perf_counter()
            raw = self._recognize(samples).strip()
            ms = int((time.perf_counter() - t0) * 1000)
        text = self.fixes.apply(raw)
        return Transcription(text, ms, audio_s, peak_db, raw if text != raw else None)


class WhisperTranscriber(LocalTranscriber):
    def __init__(
        self,
        model: str,
        models_dir: Path,
        cpu_threads: int = 4,
        initial_prompt: str = "",
        beam_size: int = 5,
        fixes: WordFixes | None = None,
    ) -> None:
        super().__init__(models_dir, cpu_threads, fixes)
        self.name = model
        self.beam_size = beam_size
        self.initial_prompt = initial_prompt or None

    def _load_model(self) -> Any:
        from faster_whisper import WhisperModel

        return WhisperModel(
            self.name,
            device="cpu",
            compute_type="int8",
            cpu_threads=self.cpu_threads,
            download_root=str(self.models_dir),
            local_files_only=True,
        )

    def _recognize(self, samples: np.ndarray) -> str:
        segments, _info = self._model.transcribe(
            samples,
            language="en",
            beam_size=self.beam_size,
            # No VAD: push-to-talk already bounds the speech, and Silero VAD
            # dropped short or quiet requests whole. Silence is gated above.
            vad_filter=False,
            # One greedy pass. The default temperature fallback re-decodes up to 6 times
            # on unclear audio (12.5 s for 2.7 s of room noise on this laptop).
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=self.initial_prompt,
        )
        return " ".join(s.text.strip() for s in segments)


class ParakeetTranscriber(LocalTranscriber):
    """NVIDIA Parakeet-TDT 0.6B v2 (English), int8 ONNX, via onnx-asr.

    On the development laptop it was as accurate as Whisper small.en with beam 5
    and about 8x faster (spikes/stt). It takes no vocabulary prompt; word fixes
    cover jargon instead.
    """

    name = "parakeet-tdt-0.6b-v2-int8"

    def _model_dir(self) -> Path:
        return self.models_dir / PARAKEET_DIR

    def _missing_hint(self) -> str:
        return f"Make sure it's downloaded to {self._model_dir()} (see README), then restart Swift."

    def _load_model(self) -> Any:
        import onnx_asr
        import onnxruntime

        missing = [f for f in PARAKEET_FILES if not (self._model_dir() / f).exists()]
        if missing:
            raise FileNotFoundError(f"missing {', '.join(missing)}")
        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads = self.cpu_threads
        opts.inter_op_num_threads = 1
        return onnx_asr.load_model(
            "nemo-parakeet-tdt-0.6b-v2", self._model_dir(), quantization="int8", sess_options=opts
        )

    def _recognize(self, samples: np.ndarray) -> str:
        return str(self._model.recognize(samples, sample_rate=SAMPLE_RATE))
