"""Local speech-to-text (PLAN.md §6): Parakeet (default) or faster-whisper.

The model is loaded once, in a background thread started at backend startup,
from Swift's local model folder only (``HF_HUB_OFFLINE`` is forced in
``swift/__init__.py``). ``transcribe()`` waits for the load if needed and runs
inference in a worker thread so the event loop keeps serving the overlay.

Both engines share the same front end: near-silent recordings are skipped,
leading and trailing silence is trimmed, and word fixes are applied to the text.
Both also say how sure they were of each word (``Transcription.words``), so the
session can refuse to act on speech that noise made unclear (``assess``).
"""

from __future__ import annotations

import asyncio
import math
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

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
# Blocks at or below this are digital silence (the stream starting up), not the room.
_DEAD_DB = -85.0
# Fewer live blocks than this and the room level isn't measured.
_MIN_FLOOR_BLOCKS = 8

PARAKEET_DIR = "parakeet-tdt-0.6b-v2"
PARAKEET_REPO = "istupakov/parakeet-tdt-0.6b-v2-onnx"
PARAKEET_FILES = ["config.json", "vocab.txt", "encoder-model.int8.onnx", "decoder_joint-model.int8.onnx"]


# Calibrated on the owner's 40 clips mixed with noise (spikes/stt/noise_bench.py,
# docs/stt-noise.md). A word less likely than UNCLEAR_P counts as unclear: on clean
# speech those were mostly real mistakes ("Kick the failing test").
UNCLEAR_P = 0.4
# A transcript whose words average below REJECT_P is not acted on. Text invented from
# background voices averaged about 0.5; correct transcripts about 0.95. At 0.7 this
# caught 90% of invented text and 78% of badly wrong transcripts, and 3% of right ones.
REJECT_P = 0.7
_PUNCT = re.compile(r"^[\W_]*$")


class SttUnavailable(RuntimeError):
    def __init__(self, message: str, hint: str) -> None:
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True)
class Word:
    text: str
    p: float  # the model's probability for its least likely token


@dataclass(frozen=True)
class Heard:
    """What an engine recognized; ``words`` is None when it can't say how sure it is."""

    text: str
    words: tuple[Word, ...] | None = None


@dataclass(frozen=True)
class Transcription:
    text: str
    stt_ms: int
    audio_s: float
    peak_db: float | None = None
    # What the model said before word fixes, when they changed anything.
    raw_text: str | None = None
    # Words as the model heard them (before fixes), with their probabilities.
    words: tuple[Word, ...] | None = None
    # How loud the room was between words (dBFS), or None if the clip was too short to say.
    noise_db: float | None = None

    @property
    def confidence(self) -> float | None:
        """Probability of the least likely word, or None if the engine didn't say."""
        if not self.words:
            return None
        return min(w.p for w in self.words)

    def unclear(self, unclear_p: float = UNCLEAR_P) -> list[str]:
        """Words heard with less than ``unclear_p`` probability."""
        return [w.text for w in self.words or () if w.p < unclear_p]


@dataclass(frozen=True)
class ModelStats:
    model: str
    load_s: float
    private_mb_delta: float


def words_from_tokens(tokens: list[str], logprobs: list[float]) -> tuple[Word, ...]:
    """Group sub-word tokens into words (a leading space starts one).

    A word's probability is that of its least likely token; punctuation tokens
    join the word before them without counting, since "?" vs "." is not a
    misheard word.
    """
    words: list[list[Any]] = []
    for tok, lp in zip(tokens, logprobs, strict=False):
        punct = bool(_PUNCT.match(tok.strip()))
        if tok.startswith((" ", "▁")) and not punct or not words:
            words.append([tok.strip(" ▁"), None if punct else lp])
        else:
            words[-1][0] += tok
            if not punct:
                words[-1][1] = lp if words[-1][1] is None else min(words[-1][1], lp)
    return tuple(Word(t, round(math.exp(lp), 3)) for t, lp in words if lp is not None)


Clarity = Literal["clear", "partly", "unclear"]


def assess(t: Transcription, unclear_p: float = UNCLEAR_P, reject_p: float = REJECT_P) -> Clarity:
    """How far to trust a transcript.

    unclear: too much of it was a guess to act on (background voices heard as
    words, speech buried in noise). partly: some words were guessed. A single word
    is never unclear: "stop" must work, and a lone misheard word does little harm.
    A threshold of 0 turns its check off; engines that report no probabilities
    are always trusted.
    """
    if not t.words:
        return "clear"
    mean_p = sum(w.p for w in t.words) / len(t.words)
    if len(t.words) > 1 and mean_p < reject_p:
        return "unclear"
    return "partly" if t.unclear(unclear_p) else "clear"


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


def noise_floor_db(samples: np.ndarray) -> float | None:
    """The room's level between words: the 10th percentile of the 32 ms blocks, in dBFS.

    On the owner's recordings (docs/stt-noise.md) a quiet room measured -72 to -45 and a
    room with a TV talking -49 to -31. Digital silence at the start of a stream is skipped.
    """
    db = _block_db(samples)
    live = db[db > _DEAD_DB]
    if len(live) < _MIN_FLOOR_BLOCKS:
        return None
    return round(float(np.percentile(live, 10)), 1)


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
        self._loading = False
        # One inference at a time: each engine already uses every configured thread.
        self._busy = threading.Lock()

    def _load_model(self) -> Any:
        raise NotImplementedError

    def _recognize(self, samples: np.ndarray) -> Heard:
        raise NotImplementedError

    def _missing_hint(self) -> str:
        return f"Make sure it's downloaded to {self.models_dir} (see README), then restart Swift."

    def start_loading(self) -> None:
        if self._loading or (self._loaded.is_set() and self._model is not None):
            return
        self._loading = True
        threading.Thread(target=self._load, name="stt-load", daemon=True).start()

    @property
    def loaded(self) -> bool:
        return self._loaded.is_set() and self._model is not None

    def release(self) -> None:
        """Free the model's memory (away for a while, ADR-014 §6). The next use loads it again."""
        with self._busy:
            if self._model is None:
                return
            self._model = None
            self._loaded.clear()
            self._error = None
        logger.info("speech model released")

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
            self._loading = False
            self._loaded.set()

    @property
    def busy(self) -> bool:
        """A transcription is running now."""
        return self._busy.locked()

    def prime(self) -> None:
        """Run the model once on a moment of near-silence (blocking), so the first real utterance
        after a lock or sleep doesn't pay for paging the model back in (ADR-014 §6)."""
        if not self.loaded:
            return
        noise = np.random.default_rng(0).normal(0, 0.003, SAMPLE_RATE).astype(np.float32)
        with self._busy:
            if self._model is None:
                return
            t0 = time.perf_counter()
            try:
                self._recognize(noise)
            except Exception as exc:  # noqa: BLE001 - priming only costs speed
                logger.warning("speech model warm-up run failed", error=type(exc).__name__)
                return
        logger.info("speech model primed", ms=int((time.perf_counter() - t0) * 1000))

    async def wait_loaded(self) -> None:
        if not self._loaded.is_set():
            self.start_loading()  # released while away: load again on first use
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
        noise_db = noise_floor_db(samples)  # before trimming: the gaps are what it measures
        samples = trim_silence(samples)
        with self._busy:
            t0 = time.perf_counter()
            heard = self._recognize(samples)
            ms = int((time.perf_counter() - t0) * 1000)
        raw = heard.text.strip()
        text = self.fixes.apply(raw)
        return Transcription(
            text, ms, audio_s, peak_db, raw if text != raw else None, heard.words if raw else None, noise_db
        )


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

    def _recognize(self, samples: np.ndarray) -> Heard:
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
        # No word probabilities: the noise thresholds were calibrated on Parakeet only,
        # so Whisper transcripts are trusted as before.
        return Heard(" ".join(s.text.strip() for s in segments))


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
        ).with_timestamps()  # adds tokens and their log-probabilities to the text

    def _recognize(self, samples: np.ndarray) -> Heard:
        result = self._model.recognize(samples, sample_rate=SAMPLE_RATE)
        return Heard(result.text, words_from_tokens(result.tokens or [], result.logprobs or []))
