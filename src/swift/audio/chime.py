"""A short, soft chime the moment Swift hears its name or the hotkey (``audio.chime``).

Two quiet notes rising (about 0.2 s), made here rather than shipped as a file, and played
through Windows' own sound player on a worker thread so nothing waits for it. Elsewhere
(tests, other systems) it does nothing.
"""

from __future__ import annotations

import io
import sys
import threading
import wave

import numpy as np
from loguru import logger

RATE = 22_050
# Two notes (Hz) and how long each lasts (s): soft and rising, "I'm listening".
NOTES = ((660.0, 0.07), (990.0, 0.12))
# Peak level, about -22 dBFS: heard at the desk, too quiet to drown the owner's first word.
VOLUME = 0.08


def chime_wav(notes: tuple[tuple[float, float], ...] = NOTES, volume: float = VOLUME) -> bytes:
    """The chime as a WAV file in memory (16-bit mono), each note faded in and out so it doesn't click."""
    parts = []
    for hz, seconds in notes:
        t = np.arange(int(RATE * seconds)) / RATE
        tone = np.sin(2 * np.pi * hz * t)
        fade = min(len(t) // 4, int(RATE * 0.02))
        envelope = np.ones(len(t))
        envelope[:fade] = np.linspace(0.0, 1.0, fade)
        envelope[-fade:] = np.linspace(1.0, 0.0, fade)
        parts.append(tone * envelope)
    samples = (np.concatenate(parts) * volume * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(samples.tobytes())
    return buf.getvalue()


class Chime:
    """Plays the chime without waiting for it; a chime still playing isn't started again."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and sys.platform == "win32"
        self._wav = chime_wav() if self.enabled else b""
        self._playing = threading.Lock()

    def __call__(self, _source: str = "") -> None:
        if not self.enabled or self._playing.locked():
            return
        threading.Thread(target=self._play, name="chime", daemon=True).start()

    def _play(self) -> None:
        if not self._playing.acquire(blocking=False):
            return
        try:
            import winsound

            # SND_MEMORY can't be combined with SND_ASYNC, hence the thread.
            winsound.PlaySound(self._wav, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        except Exception as exc:  # noqa: BLE001 - no sound device: the overlay still shows it
            logger.warning("chime not played", error=type(exc).__name__)
        finally:
            self._playing.release()
