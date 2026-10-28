"""Swift speaks (ADR-016 §4, Phase B): the answer said aloud, short, and never heard by Swift itself.

- **``Speaker``**: ``speak(text)`` starts saying it and returns at once; ``stop()`` cuts it off
  (the hotkey, Esc, a new request); ``speaking`` and ``quiet_since`` tell the microphone side
  when Swift's own voice may be in the room. ``WindowsSpeaker`` uses the Windows voices through
  SAPI (``pywin32``, already a dependency): no download, about 50 ms to start. One worker thread
  owns the voice, so COM stays on one thread and nothing on the core loop waits for audio.
  ``FakeSpeaker`` records what would be said (tests, debug mode).
- **``spoken(text)``**: the spoken form of a card. The card keeps everything; the voice says the
  first sentence or two (at most ``MAX_SPOKEN`` characters, cut at a sentence end), with markdown,
  links, code and emoji taken out. A long agent answer is never read out whole.

Piper (ADR-016 §11 decision 1) can replace ``WindowsSpeaker`` behind the same three methods
once its voice license is recorded.
"""

from __future__ import annotations

import asyncio
import contextlib
import queue
import re
import threading
import time
from collections.abc import Callable

from loguru import logger

# The longest thing said for one answer; the card shows the rest.
MAX_SPOKEN = 220
MAX_SENTENCES = 2
# After Swift stops talking, the room may still ring with it this long: the microphone side ignores it.
TAIL_S = 0.6

_FENCE = re.compile(r"```.*?```", re.S)
_CODE = re.compile(r"`([^`]*)`")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+.*$", re.M)  # "## Result": a label for the eye, not worth saying
_MARK = re.compile(r"^\s{0,3}(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)", re.M)
_EMPH = re.compile(r"(\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1")
_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿️]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"'(])")


def spoken(text: str, limit: int = MAX_SPOKEN) -> str:
    """What to say for ``text``: plain words, the first sentence or two, never more than ``limit``."""
    t = _HEADING.sub("", _FENCE.sub(" ", text))
    t = _LINK.sub(r"\1", t)
    t = _URL.sub("a link", t)
    t = _CODE.sub(r"\1", t)
    t = _MARK.sub("", t)
    t = _EMPH.sub(r"\2", t)
    t = _EMOJI.sub("", t)
    t = " ".join(t.replace("\n", " ").split())
    sentences = _SENTENCE.split(t)
    if len(t) <= limit and len(sentences) <= MAX_SENTENCES:
        return t
    said = ""
    for sentence in sentences[:MAX_SENTENCES]:
        if len(said) + len(sentence) + 1 > limit:
            break
        said = f"{said} {sentence}".strip()
    if said:
        return said
    cut = t[:limit].rsplit(" ", 1)[0].rstrip(",;:")  # one very long sentence: up to a word
    return cut + "…"


class Speaker:
    """Says things. The base class says nothing (speech off)."""

    def __init__(self) -> None:
        self._speaking = False
        self._quiet_at = 0.0  # time.monotonic() when the last speech ended
        self.on_done: Callable[[], None] | None = None

    @property
    def speaking(self) -> bool:
        return self._speaking

    def recently(self, at: float, tail_s: float = TAIL_S) -> bool:
        """Whether Swift was talking at ``at`` (time.monotonic()), or had only just stopped."""
        return self._speaking or at <= self._quiet_at + tail_s

    def speak(self, text: str) -> None:  # noqa: ARG002
        return

    def stop(self) -> None:
        return

    def close(self) -> None:
        return

    def _ended(self) -> None:
        self._speaking = False
        self._quiet_at = time.monotonic()
        if self.on_done is not None:
            self.on_done()


class FakeSpeaker(Speaker):
    """Records what would be said; ``finish()`` ends the current speech (tests)."""

    def __init__(self) -> None:
        super().__init__()
        self.said: list[str] = []
        self.stopped = 0

    def speak(self, text: str) -> None:
        self.said.append(text)
        self._speaking = True

    def stop(self) -> None:
        if self._speaking:
            self.stopped += 1
            self._ended()

    def finish(self) -> None:
        if self._speaking:
            self._ended()


_ASYNC, _PURGE = 1, 2  # SVSFlagsAsync, SVSFPurgeBeforeSpeak
_DONE = 1  # SpeechRunState.SRSEDone


class WindowsSpeaker(Speaker):
    """The Windows voices through SAPI, on one worker thread that owns the voice."""

    def __init__(self, voice: str = "", rate: int = 0, volume: int = 100,
                 loop: asyncio.AbstractEventLoop | None = None) -> None:
        super().__init__()
        self._loop = loop or asyncio.get_event_loop()
        self._commands: queue.Queue[tuple[str, str]] = queue.Queue()
        self._thread = threading.Thread(target=self._run, args=(voice, rate, volume), name="speech", daemon=True)
        self.ready = threading.Event()
        self.error: str | None = None
        self._thread.start()

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        self._speaking = True
        self._commands.put(("speak", text))

    def stop(self) -> None:
        if self._speaking:
            self._commands.put(("stop", ""))

    def close(self) -> None:
        self._commands.put(("close", ""))

    def _done(self) -> None:
        with contextlib.suppress(RuntimeError):  # the loop has closed: Swift is quitting
            self._loop.call_soon_threadsafe(self._ended)

    def _run(self, voice_name: str, rate: int, volume: int) -> None:
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            if voice_name:
                _choose(voice, voice_name)
            voice.Rate = max(-10, min(10, rate))
            voice.Volume = max(0, min(100, volume))
        except Exception as exc:  # noqa: BLE001 - no SAPI here: Swift stays silent and says why in the log
            self.error = str(exc)
            logger.warning("speech unavailable", error=self.error)
            self.ready.set()
            return
        self.ready.set()
        talking = False
        while True:
            try:
                cmd, text = self._commands.get(timeout=0.05)
            except queue.Empty:
                cmd, text = "", ""
            try:
                if cmd == "speak":
                    voice.Speak(text, _ASYNC | _PURGE)
                    talking = True
                elif cmd == "stop" and talking:
                    voice.Speak("", _ASYNC | _PURGE)
                elif cmd == "close":
                    voice.Speak("", _ASYNC | _PURGE)
                    break
                if talking and voice.Status.RunningState == _DONE and self._commands.empty():
                    talking = False
                    self._done()
            except Exception as exc:  # noqa: BLE001 - a bad voice or a COM hiccup ends this speech, not Swift
                logger.warning("speech failed", error=str(exc))
                talking = False
                self._done()
        pythoncom.CoUninitialize()


def _choose(voice: object, name: str) -> None:
    """Pick the voice whose name contains ``name`` ("Mark", "Zira"), from the desktop and OneCore lists."""
    import win32com.client

    want = name.lower()
    for token in voice.GetVoices():  # type: ignore[attr-defined]
        if want in token.GetDescription().lower():
            voice.Voice = token  # type: ignore[attr-defined]
            return
    category = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
    category.SetId(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices", False)
    for token in category.EnumerateTokens():
        if want in token.GetDescription().lower():
            voice.Voice = token  # type: ignore[attr-defined]
            return
    logger.warning("voice not found; using the default", voice=name)


def voices() -> list[str]:
    """The Windows voices this PC has (desktop and OneCore), for settings and the log."""
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        found = [t.GetDescription() for t in win32com.client.Dispatch("SAPI.SpVoice").GetVoices()]
        category = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
        category.SetId(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices", False)
        found += [t.GetDescription() for t in category.EnumerateTokens()]
        return found
    except Exception:  # noqa: BLE001
        return []
