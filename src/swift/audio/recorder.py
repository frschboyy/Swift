"""Push-to-talk capture (PLAN.md §6).

By default the microphone is opened only while the hotkey is held, so Windows'
mic indicator is on only then. With ``preroll_s > 0`` a stream stays open and the
last ``preroll_s`` seconds are kept in a ring, so words spoken as the key goes
down are not lost (the indicator is then on whenever Swift runs). Wake listening keeps the stream open
too and gets every block through ``tap``. Blocks arrive
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


def _device_name(device: int | None) -> str:
    try:
        import sounddevice as sd

        info = sd.query_devices(device if device is not None else sd.default.device[0])
        return str(info["name"]) if isinstance(info, dict) else ""
    except Exception:  # noqa: BLE001 - only for the log
        return ""


def _refresh_devices() -> None:
    """Make PortAudio list the devices as they are now (its list is fixed at initialization)."""
    try:
        import sounddevice as sd

        sd._terminate()  # noqa: SLF001 - sounddevice's own way to re-enumerate devices
        sd._initialize()  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001 - keep the old list rather than fail the reopen
        logger.warning("couldn't refresh the device list", error=str(exc))


class Recorder(Protocol):
    def start(self, on_level: Callable[[float], None], lead_s: float | None = None) -> None: ...

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

    ``keep_open`` does the same without a pre-roll, for wake listening: ``tap`` then
    receives every block (on the audio thread; keep it quick), and ``start(lead_s=...)``
    prepends that much of the audio just before it, at most ``lookback_s``.

    A stream kept open for hours can stop delivering audio without an error (sleep and
    resume, a headset connecting, the default device changing). ``check_stream`` reopens
    it when no block has arrived for a while; the backend calls it every few seconds, so
    hands-free listening recovers without waiting for the next hotkey press.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        max_seconds: float = MAX_SECONDS,
        preroll_s: float = 0.0,
        *,
        keep_open: bool = False,
        lookback_s: float = 0.0,
    ) -> None:
        self._audio = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio")
        self._loop = loop
        self._max_blocks = int(max_seconds * SAMPLE_RATE / BLOCK)
        self._preroll_blocks = math.ceil(preroll_s * SAMPLE_RATE / BLOCK) if preroll_s > 0 else 0
        self._blocks: list[np.ndarray] = []
        self._keep_open = keep_open or self._preroll_blocks > 0
        self._lookback_blocks = math.ceil(lookback_s * SAMPLE_RATE / BLOCK) if lookback_s > 0 else 0
        self._ring: deque[np.ndarray] = deque(maxlen=max(self._preroll_blocks, self._lookback_blocks, 1))
        self.tap: Callable[[np.ndarray], None] | None = None
        # Called (on the audio thread) after the kept-open stream was reopened.
        self.on_reopen: Callable[[], None] | None = None
        # The input device of the open stream, for the log.
        self.device_name = ""
        # Paused (screen locked, asleep: ADR-014): the kept-open stream is closed and stays closed.
        self.paused = False
        # pause() / resume() calls in the order they were made: only the newest is carried out, so a
        # pause still queued behind a busy audio thread never closes the microphone after the owner
        # came back (owner checks, 2026-10-27: "microphone paused" logged after the unlock).
        self._wanted = 0
        self._wanted_lock = threading.Lock()
        # time.monotonic() when the kept-open stream was last opened (unlock-to-listening, in the log).
        self.opened_at = 0.0
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
        # time.monotonic() of the last block from the stream: how ``check_stream`` sees a stall.
        self._last_block = 0.0

    def prepare(self) -> Future[None]:
        """Warm PortAudio up in the background, and open the pre-roll stream if enabled.

        A start() queues behind it.
        """
        return self._audio.submit(self._prepare)

    def _prepare(self) -> None:
        warm_up()
        if self._keep_open:
            try:
                self._open_stream()
            except MicError as exc:
                logger.warning("pre-roll stream not opened; opening the mic per request", error=str(exc))

    def _on_audio_thread(self, fn: Callable[[], T]) -> T:
        return self._audio.submit(fn).result()

    def start(self, on_level: Callable[[float], None], lead_s: float | None = None) -> None:
        self._on_audio_thread(lambda: self._start(on_level, lead_s))

    def stop(self) -> np.ndarray:
        return self._on_audio_thread(self._stop)

    def snapshot(self) -> np.ndarray:
        """What has been recorded so far, while it goes on (the end-of-turn check, swift/endpoint.py)."""
        with self._lock:
            blocks = list(self._blocks)
        return np.concatenate(blocks).reshape(-1) if blocks else np.zeros(0, dtype=np.int16)

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
            self._last_block = self.opened_at = time.monotonic()
            self.device_name = _device_name(device)
            logger.info("microphone opened", device=self.device_name, kept_open=self._keep_open)
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

    def _start(self, on_level: Callable[[float], None], lead_s: float | None = None) -> None:
        self.capped = False
        self.first_audio_ms = None
        self.preroll_ms = 0
        self._on_level = on_level
        self._t_start = time.perf_counter()
        if self._keep_open and self._stream is not None and not self._stream.active:
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
            lead = self._preroll_blocks if lead_s is None else min(math.ceil(lead_s * SAMPLE_RATE / BLOCK), self._lookback_blocks)
            self._blocks = list(self._ring)[-lead:] if lead else []
            self._ring.clear()
            self.preroll_ms = int(sum(len(b) for b in self._blocks) * 1000 / SAMPLE_RATE)
            self._recording = True

    def _stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False
        if not self._keep_open or self.paused:
            self._close_stream()
        with self._lock:
            blocks, self._blocks = self._blocks, []
        if not blocks:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(blocks).reshape(-1)

    def check_stream(self, stall_s: float = 3.0) -> bool:
        """Reopen the kept-open stream if it died or went quiet. True if it was reopened.

        Blocks until the audio thread has done it; call from a worker thread, not the loop.
        """
        return self._on_audio_thread(lambda: self._check_stream(stall_s))

    def pause(self) -> None:
        """Close the kept-open stream until ``resume`` (Windows' microphone indicator goes off)."""
        wanted = self._want()
        self._on_audio_thread(lambda: self._pause(wanted))

    def resume(self) -> None:
        """Reopen it with a fresh device list (the owner is back; devices may have changed)."""
        wanted = self._want()
        self._on_audio_thread(lambda: self._resume(wanted))

    def _want(self) -> int:
        with self._wanted_lock:
            self._wanted += 1
            return self._wanted

    def _superseded(self, wanted: int | None) -> bool:
        return wanted is not None and wanted != self._wanted

    def _pause(self, wanted: int | None = None) -> None:
        if self._superseded(wanted):
            logger.info("microphone pause skipped: resumed since")
            return
        self.paused = True
        if self._keep_open and not self._recording:
            self._close_stream()
            logger.info("microphone paused")

    def _resume(self, wanted: int | None = None) -> None:
        if self._superseded(wanted):
            return  # paused again since
        was_paused, self.paused = self.paused, False
        if not self._keep_open or self._recording:
            return
        stream = self._stream
        if not was_paused and stream is not None and stream.active and time.monotonic() - self._last_block < 1.0:
            return  # its pause was overtaken and it is still delivering audio: no need to reopen
        self._close_stream()
        # The device list as it was first: refreshing it re-enumerates every audio API and was
        # the slow part of coming back (owner checks, 2026-10-27: 4.7 s from unlock to listening,
        # the speech model ready after 1.4 s). Refreshed only if that fails; a device that went
        # away while locked is caught by ``check_stream`` (no audio for 3 s: refresh, reopen).
        t0 = time.monotonic()
        refreshed = False
        try:
            try:
                self._open_stream()
            except MicError:
                refreshed = True
                _refresh_devices()
                self._open_stream()
        except MicError as exc:
            logger.warning("microphone not reopened on return; the watchdog will retry", error=str(exc))
            return
        logger.info("microphone reopened", ms=int((time.monotonic() - t0) * 1000), refreshed=refreshed)
        if self.on_reopen is not None:
            try:
                self.on_reopen()
            except Exception as exc:  # noqa: BLE001
                logger.warning("after-reopen hook failed", error=str(exc))

    def _check_stream(self, stall_s: float) -> bool:
        if not self._keep_open or self._recording or self.paused:
            return False  # a recording reopens a dead stream itself (``_start``)
        stream = self._stream
        quiet_s = time.monotonic() - self._last_block
        if stream is not None and stream.active and quiet_s < stall_s:
            return False
        logger.warning(
            "microphone stream stopped delivering audio; reopening",
            opened=stream is not None, active=bool(stream is not None and stream.active), quiet_s=round(quiet_s, 1),
        )
        self._close_stream()
        _refresh_devices()  # after sleep or a headset change PortAudio's device list is stale
        try:
            self._open_stream()
        except MicError as exc:
            logger.warning("microphone stream not reopened; trying again shortly", error=str(exc))
            return False
        if self.on_reopen is not None:
            try:
                self.on_reopen()
            except Exception as exc:  # noqa: BLE001 - a listener bug must not stop the stream
                logger.warning("after-reopen hook failed", error=str(exc))
        return True

    def _callback(self, indata: np.ndarray, frames: int, _time: object, _status: object) -> None:
        self._last_block = time.monotonic()
        tap = self.tap
        if tap is not None:
            try:
                tap(indata)
            except Exception as exc:  # a listener bug must not stop the recording
                logger.warning("audio tap failed", error=str(exc))
        with self._lock:
            if not self._recording:
                if self._keep_open:
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
