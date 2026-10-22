"""Local speech-to-text with faster-whisper (PLAN.md §6).

The model is loaded once, in a background thread started at backend startup,
from Swift's local model cache only (``HF_HUB_OFFLINE`` is forced in
``swift/__init__.py``). ``transcribe()`` waits for the load if needed and runs
inference in a worker thread so the event loop keeps serving the overlay.
"""

from __future__ import annotations

import asyncio
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from loguru import logger

SAMPLE_RATE = 16_000
# Loudest 32 ms block below this is treated as silence and never reaches Whisper,
# which otherwise invents text ("Thank you.") for room noise. Room noise here is
# about -60 dBFS; quiet speech is around -40.
SILENCE_DB = -50.0
_GATE_BLOCK = 512


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


@dataclass(frozen=True)
class ModelStats:
    model: str
    load_s: float
    private_mb_delta: float


class Transcriber(Protocol):
    async def transcribe(self, audio: np.ndarray) -> Transcription: ...


def loudest_db(samples: np.ndarray) -> float:
    """RMS level of the loudest 32 ms block, in dBFS (float samples in -1..1)."""
    n = len(samples) // _GATE_BLOCK * _GATE_BLOCK
    if n == 0:
        return -120.0
    blocks = samples[:n].reshape(-1, _GATE_BLOCK)
    rms = float(np.sqrt(np.mean(blocks * blocks, axis=1)).max())
    return 20.0 * math.log10(rms) if rms > 1e-6 else -120.0


def _private_mb() -> float:
    import psutil

    info = psutil.Process().memory_full_info()
    return getattr(info, "private", info.uss) / 2**20


class WhisperTranscriber:
    def __init__(
        self, model: str, models_dir: Path, cpu_threads: int = 4, initial_prompt: str = "", beam_size: int = 5
    ) -> None:
        self.model_name = model
        self.models_dir = models_dir
        self.cpu_threads = cpu_threads
        self.beam_size = beam_size
        self.initial_prompt = initial_prompt or None
        self.stats: ModelStats | None = None
        self._model = None
        self._error: SttUnavailable | None = None
        self._loaded = threading.Event()
        # One inference at a time: CTranslate2 already uses every configured thread.
        self._busy = threading.Lock()

    def start_loading(self) -> None:
        threading.Thread(target=self._load, name="stt-load", daemon=True).start()

    def _load(self) -> None:
        from faster_whisper import WhisperModel

        before = _private_mb()
        t0 = time.perf_counter()
        try:
            self._model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type="int8",
                cpu_threads=self.cpu_threads,
                download_root=str(self.models_dir),
                local_files_only=True,
            )
        except Exception as exc:  # noqa: BLE001 - any failure means STT is unavailable
            logger.error("speech model failed to load", model=self.model_name, error=type(exc).__name__)
            self._error = SttUnavailable(
                f"The speech model '{self.model_name}' couldn't be loaded.",
                f"Make sure it's downloaded to {self.models_dir} (see README), then restart Swift.",
            )
        else:
            self.stats = ModelStats(self.model_name, round(time.perf_counter() - t0, 2), round(_private_mb() - before, 1))
            logger.info(
                "speech model loaded",
                model=self.model_name,
                load_s=self.stats.load_s,
                private_mb_delta=self.stats.private_mb_delta,
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
        with self._busy:
            t0 = time.perf_counter()
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
            text = " ".join(s.text.strip() for s in segments).strip()
            ms = int((time.perf_counter() - t0) * 1000)
        return Transcription(text, ms, audio_s, peak_db)
