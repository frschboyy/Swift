"""Push-to-talk capture (PLAN.md §6).

By default the microphone is opened only while the hotkey is held, so Windows'
mic indicator is on only then. With ``preroll_s > 0`` a stream stays open and the
last ``preroll_s`` seconds are kept in a ring, so words spoken as the key goes
down are not lost (the indicator is then on whenever Swift runs). Blocks arrive
on PortAudio's thread; levels are handed to the asyncio loop at most ``LEVEL_HZ``
times a second.
"""

from __future__ import annotations

import asyncio
import math
import threading
import time
import wave
from collections import deque
from collections.abc import Callable
from pathlib import Path
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TypeVar
from typing import Protocol

import numpy as np
from loguru import logger

SAMPLE_RATE = 16_000
BLOCK = 512  # 32 ms
LEVEL_HZ = 30
MAX_SECONDS = 60.0

# Level mapping: -60 dBFS (room noise) -> 0, -12 dBFS (loud speech) -> 1.
FLOOR_DB = -60.0
CEIL_DB = -12.0


class MicError(RuntimeError):
    """The microphone could not be opened. ``hint`` says what the owner can do."""

    def __init__(self, message: str, hint: str) -> None:
        super().__init__(message)
        self.hint = hint


def level_from_block(block: np.ndarray) -> float:
    """Perceptual 0..1 level of an int16 block (RMS in dBFS, clamped)."""
    if block.size == 0:
        return 0.0
    x = block.astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(x * x)))
    if rms <= 0.0:
        return 0.0
    db = 20.0 * math.log10(rms)
    return max(0.0, min(1.0, (db - FLOOR_DB) / (CEIL_DB - FLOOR_DB)))


def save_wav(path: Path, audio: np.ndarray) -> None:
    """Write 16 kHz mono int16 audio as a WAV file (debug recordings)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(audio.astype(np.int16).tobytes())


def warm_up() -> None:
    """Load PortAudio and enumerate devices ahead of the first push-to-talk.

    The first stream opened in a process otherwise pays for this (~0.6 s here).
    Does not open the microphone. Call it on the thread that will open streams:
    with WASAPI, a stream opened on another thread fails with error -9999.
    """
    import sounddevice as sd

    sd.query_devices()


def _input_device() -> tuple[int | None, object | None]:
    """Prefer WASAPI's default input: fastest to start here (~0.35 s to first audio)."""
    import sounddevice as sd

    for api in sd.query_hostapis():
        if api["name"] == "Windows WASAPI" and api["default_input_device"] >= 0:
            return api["default_input_device"], sd.WasapiSettings(auto_convert=True)
    return None, None


class Recorder(Protocol):
    def start(self, on_level: Callable[[float], None]) -> None: ...

    def stop(self) -> np.ndarray: ...

    @property
    def capped(self) -> bool: ...


T = TypeVar("T")


class MicRecorder:
    """Records 16 kHz mono int16 from the default input device.

    Every PortAudio call (warm-up, open, close) runs on one dedicated thread:
    WASAPI fails with -9999 on a stream opened from a thread other than the one
    that initialized PortAudio, and warming up there keeps the event loop free.

    With ``preroll_s > 0`` the stream is opened by ``prepare()`` and stays open;
    until ``start()`` its blocks only feed a ring of the last ``preroll_s`` seconds,
    which ``start()`` prepends to the recording. If that stream cannot be opened
    (or dies), ``start()`` falls back to opening the mic on demand.
    """

    def __init__(
        self, loop: asyncio.AbstractEventLoop, max_seconds: float = MAX_SECONDS, preroll_s: float = 0.0
    ) -> None:
        self._audio = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio")
        self._loop = loop
        self._max_blocks = int(max_seconds * SAMPLE_RATE / BLOCK)
        self._preroll_blocks = math.ceil(preroll_s * SAMPLE_RATE / BLOCK) if preroll_s > 0 else 0
        self._blocks: list[np.ndarray] = []
        self._ring: deque[np.ndarray] = deque(maxlen=max(self._preroll_blocks, 1))
        self._recording = False
        self._lock = threading.Lock()
        self._stream = None
        self._last_level = 0.0
        self._on_level: Callable[[float], None] | None = None
        self.capped = False
        # Key-down to first audio block: speech before this is lost. With pre-roll the stream
        # is already running, so this is just the wait for the next block (under one block).
        self.first_audio_ms: int | None = None
        # Audio from before the key-down that was prepended (0 without pre-roll).
        self.preroll_ms = 0
        self._t_start = 0.0

    def prepare(self) -> Future[None]:
        """Warm PortAudio up in the background, and open the pre-roll stream if enabled.

        A start() queues behind it.
        """
        return self._audio.submit(self._prepare)

    def _prepare(self) -> None:
        warm_up()
        if self._preroll_blocks:
            try:
                self._open_stream()
            except MicError as exc:
                logger.warning("pre-roll stream not opened; opening the mic per request", error=str(exc))

    def _on_audio_thread(self, fn: Callable[[], T]) -> T:
        return self._audio.submit(fn).result()

    def start(self, on_level: Callable[[float], None]) -> None:
        self._on_audio_thread(lambda: self._start(on_level))

    def stop(self) -> np.ndarray:
        return self._on_audio_thread(self._stop)

    def _open_stream(self) -> None:
        """Open and start the input stream. Audio thread only."""
        import sounddevice as sd

        device, extra = _input_device()
        try:
            try:
                self._stream = sd.InputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=BLOCK,
                    device=device, extra_settings=extra, callback=self._callback,
                )
            except sd.PortAudioError:
                if device is None:
                    raise
                # WASAPI refused (e.g. exclusive mode elsewhere): fall back to the default device.
                self._stream = sd.InputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=BLOCK, callback=self._callback
                )
            self._stream.start()
        except sd.PortAudioError as exc:
            self._stream = None
            raise _mic_error(exc) from None
        except ValueError as exc:  # no input device at all
            self._stream = None
            raise MicError(f"No microphone found ({exc}).", "Connect a microphone or enable one in Windows Sound settings.") from None

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:  # a dead device must not break the next request
                logger.warning("closing the microphone stream failed", error=str(exc))

    def _start(self, on_level: Callable[[float], None]) -> None:
        self.capped = False
        self.first_audio_ms = None
        self.preroll_ms = 0
        self._on_level = on_level
        self._t_start = time.perf_counter()
        if self._preroll_blocks and self._stream is not None and not self._stream.active:
            self._close_stream()  # the pre-roll stream died (device removed, ...): reopen below
        if self._stream is None:
            with self._lock:
                self._blocks = []
                self._ring.clear()
                self._recording = True
            try:
                self._open_stream()
            except MicError:
                with self._lock:
                    self._recording = False
                raise
            return
        with self._lock:
            self._blocks = list(self._ring)
            self._ring.clear()
            self.preroll_ms = int(sum(len(b) for b in self._blocks) * 1000 / SAMPLE_RATE)
            self._recording = True

    def _stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False
        if not self._preroll_blocks:
            self._close_stream()
        with self._lock:
            blocks, self._blocks = self._blocks, []
        if not blocks:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(blocks).reshape(-1)

    def _callback(self, indata: np.ndarray, frames: int, _time: object, _status: object) -> None:
        with self._lock:
            if not self._recording:
                if self._preroll_blocks:
                    self._ring.append(indata.copy())
                return
            if self.first_audio_ms is None:
                self.first_audio_ms = int((time.perf_counter() - self._t_start) * 1000)
            if len(self._blocks) >= self._max_blocks:
                self.capped = True
                return
            self._blocks.append(indata.copy())
        now = time.monotonic()
        if self._on_level is not None and now - self._last_level >= 1 / LEVEL_HZ:
            self._last_level = now
            level = level_from_block(indata)
            self._loop.call_soon_threadsafe(self._on_level, level)


def _mic_error(exc: Exception) -> MicError:
    text = str(exc)
    logger.warning("microphone open failed", error=text)
    if "-9999" in text or "Unanticipated host error" in text or "access" in text.lower():
        # -9999 covers privacy blocks and other host failures alike.
        return MicError(
            "Windows wouldn't open the microphone.",
            "Check Settings > Privacy & security > Microphone (allow desktop apps), and that no app is using it exclusively.",
        )
    if "-9996" in text or "Invalid device" in text or "-9985" in text:
        return MicError("The microphone isn't available.", "Check that it's plugged in and not in use exclusively by another app.")
    return MicError(f"The microphone couldn't be opened ({text}).", "Check Windows Sound settings, then try again.")
