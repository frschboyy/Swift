"""Push-to-talk capture (PLAN.md §6).

The microphone is opened only while the hotkey is held, so Windows' mic
indicator is on only then. Blocks arrive on PortAudio's thread; levels are
handed to the asyncio loop at most ``LEVEL_HZ`` times a second.
"""

from __future__ import annotations

import asyncio
import math
import threading
import time
from collections.abc import Callable
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


class MicRecorder:
    """Records 16 kHz mono int16 from the default input device."""

    def __init__(self, loop: asyncio.AbstractEventLoop, max_seconds: float = MAX_SECONDS) -> None:
        self._loop = loop
        self._max_blocks = int(max_seconds * SAMPLE_RATE / BLOCK)
        self._blocks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream = None
        self._last_level = 0.0
        self._on_level: Callable[[float], None] | None = None
        self.capped = False
        # Key-down to first audio block: speech before this is lost.
        self.first_audio_ms: int | None = None
        self._t_start = 0.0

    def start(self, on_level: Callable[[float], None]) -> None:
        import sounddevice as sd

        self._blocks = []
        self.capped = False
        self.first_audio_ms = None
        self._on_level = on_level
        self._t_start = time.perf_counter()
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

    def stop(self) -> np.ndarray:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        with self._lock:
            blocks, self._blocks = self._blocks, []
        if not blocks:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(blocks).reshape(-1)

    def _callback(self, indata: np.ndarray, frames: int, _time: object, _status: object) -> None:
        if self.first_audio_ms is None:
            self.first_audio_ms = int((time.perf_counter() - self._t_start) * 1000)
        with self._lock:
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
