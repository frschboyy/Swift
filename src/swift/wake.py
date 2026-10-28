"""Hands-free start: "hey Swift", "hello Swift", "good afternoon Swift".

There is no wake-word model. While wake listening is on, the microphone stream
feeds ``WakeListener``, which cuts the audio into short utterances by level. Each
one goes through the speech model Swift already has, and ``match_wake`` decides
whether it opens with a greeting and Swift's name. Nothing is kept or sent anywhere:
an utterance that is not a wake phrase is dropped after it is transcribed.

The match is by closeness, not by exact words: any greeting near "hey / hi /
hello / ok", "good morning / afternoon / evening", or one the owner adds, followed by
a word that sounds like "Swift" ("swiff", "swifty"). A greeting alone never wakes
Swift, and neither does "Swift" alone: speech about the Swift language would.
"""

from __future__ import annotations

import re
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

import numpy as np

from swift.audio.recorder import BLOCK, CEIL_DB, FLOOR_DB, SAMPLE_RATE, level_from_block

NAME = "swift"
# What a brisk control phrase is compared with (``close_control``).
CONTROL_SOUNDS = ("show me", "stop", "hide", "pause", "go on", "reject", "cancel")
GREETINGS = ("hey", "hay", "hi", "hello", "hallo", "hullo", "hiya", "heya", "howdy", "yo", "ok", "okay")
# "good <time of day>"; "good day" too.
TIMES_OF_DAY = ("morning", "afternoon", "evening", "day")
# Sounds-like threshold (difflib ratio): "swiff" 0.80, "swifty" 0.91, "sift" 0.89.
CLOSE = 0.8
# The phrase may follow a filler ("um, hey Swift") but not a sentence.
MAX_LEAD_WORDS = 2

_WORD = re.compile(r"[a-z']+")
_TRIM = " \t\r\n,.:;!?-–—"


@dataclass(frozen=True)
class WakeMatch:
    # What was recognized as the wake phrase, e.g. "hey swift".
    phrase: str
    # What was said after it ("what time is it"), empty if nothing.
    remainder: str


def _close(word: str, target: str, close: float = CLOSE) -> bool:
    if word == target:
        return True
    return len(word) >= 3 and SequenceMatcher(None, word, target).ratio() >= close


def _greeting_len(words: list[str], i: int, extra: tuple[tuple[str, ...], ...]) -> int:
    """Words in the greeting that starts at ``words[i]``, or 0."""
    for phrase in extra:
        if tuple(words[i : i + len(phrase)]) == phrase:
            return len(phrase)
    word = words[i]
    if word == "good" and i + 1 < len(words) and any(_close(words[i + 1], t) for t in TIMES_OF_DAY):
        return 2
    if word in GREETINGS or (len(word) >= 4 and any(_close(word, g) for g in GREETINGS)):
        return 1
    return 0


def match_wake(text: str, extra_greetings: Iterable[str] = (), *, close: float = CLOSE) -> WakeMatch | None:
    """The wake phrase at the start of ``text`` (case, punctuation and mishearings forgiven).

    ``close`` is how near the name must sound. Lower only where the phrase can't start anything
    by itself: said into the hotkey, "hey Crift" and "hey thrift" were the name (2026-10-27).
    """
    found = [(m.group(), m.end()) for m in _WORD.finditer(text.lower().replace("’", "'"))]
    words = [w.strip("'") for w, _ in found]
    extra = tuple(tuple(_WORD.findall(g.lower())) for g in extra_greetings if g.strip())
    for i in range(min(len(words), MAX_LEAD_WORDS + 1)):
        n = _greeting_len(words, i, extra)
        if n and i + n < len(words) and _close(words[i + n].removesuffix("'s"), NAME, close):
            end = found[i + n][1]
            return WakeMatch(" ".join(words[i : i + n + 1]), text[end:].lstrip(_TRIM).strip())
    return None


def match_address(text: str, extra_greetings: Iterable[str] = ()) -> WakeMatch | None:
    """Swift addressed by name: a wake phrase, or the name alone first ("Swift, approve").

    Only for answers during a run, where the name alone is deliberate enough; it never
    starts an interaction (speech about the Swift language would).
    """
    if (m := match_wake(text, extra_greetings)) is not None:
        return m
    found = [(w.group(), w.end()) for w in _WORD.finditer(text.lower().replace("’", "'"))]
    if found and _close(found[0][0].strip("'").removesuffix("'s"), NAME):
        return WakeMatch(NAME, text[found[0][1]:].lstrip(_TRIM).strip())
    return None


def close_control(text: str) -> str | None:
    """A brisk control phrase as the speech model misheard it ("so me", "show be", "stops"): the
    phrase meant, or None. Only for clips of a few words; the model guesses most on short ones.
    """
    words = [w.strip("'") for w in _WORD.findall(text.lower().replace("’", "'"))]
    if not words or len(words) > 3:
        return None
    said = "".join(words)
    best = max(CONTROL_SOUNDS, key=lambda c: SequenceMatcher(None, said, c.replace(" ", "")).ratio())
    return best if SequenceMatcher(None, said, best.replace(" ", "")).ratio() >= CLOSE else None


class NoiseGate:
    """Tells speech from the room by level (0..1, ``level_from_block``), following the room.

    Speech is a level some way above the room's own level, so a quiet room lets a normal voice
    through and a fan or a TV raises the bar; the absolute minimum only keeps near-silence out.
    (Until 2026-10-27 the minimum was 0.3, about -46 dBFS, whatever the room: in a quiet room
    the owner had to raise their voice.) The room's level follows the input quickly through
    pauses and slowly through speech, so a steady noise that starts out looking like speech
    stops being taken for it after some seconds.
    """

    def __init__(self, min_level: float = 0.12, margin: float = 0.2) -> None:
        self.min_level = min_level
        self.margin = margin
        self.floor = 0.0

    def speech(self, level: float) -> bool:
        is_speech = level > max(self.min_level, self.floor + self.margin)
        self.floor += (level - self.floor) * (0.002 if is_speech else 0.02)
        return is_speech

    @property
    def room_db(self) -> float:
        """The room's level now, in dBFS (``level_from_block``'s scale undone)."""
        return round(FLOOR_DB + self.floor * (CEIL_DB - FLOOR_DB), 1)


class WakeListener:
    """Cuts the microphone stream into utterances and hands each to ``on_utterance``.

    ``feed`` is called from the audio thread for every block, so it only measures levels
    and copies blocks. ``on_utterance(audio, ended_at)`` is called there too, with the
    utterance (int16, 16 kHz, a little room noise around it) and the ``time.monotonic()``
    its last block arrived. Utterances shorter than ``min_s`` (a cough, a click) or
    longer than ``max_s`` (a conversation, not a wake phrase and a short request) are dropped.

    Utterances are cut at a pause of ``end_silence_s``: 0.6 s split requests said deliberately,
    word by word, so the end was lost (owner checks, 2026-10-27). And up to ``max_s``: at 6 s,
    a slow "hey Swift, write me a fifteen page paper on ..." was dropped as too long.

    ``on_peek(audio)`` (if given, and ``accept_peek()`` allows it) gets the first ``peek_s`` of an
    utterance that is still going, once: enough for "hey Swift", so Swift can show it heard the
    name while the owner is still saying the request.

    ``end_silence`` (if given) is asked for the pause that ends an utterance as it ends, so the
    session can make it longer while Swift waits for a free-text answer (ADR-016 §5.1). ``speaking``
    says whether an utterance is being collected right now.

    Except when ``accept_short()`` says so (a run is going, or a reply window is open): then
    one of at least ``short_s`` is handed on as ``on_utterance(audio, ended_at, True)``, because
    "stop" or "show me" said briskly is often under ``min_s`` of speech (owner checks,
    2026-10-27: 19 too short during a research run, every "show me" lost). The session keeps it
    only if it is one of the control phrases.
    """

    def __init__(
        self,
        on_utterance: Callable[..., None],
        *,
        end_silence_s: float = 0.8,
        min_s: float = 0.4,
        short_s: float = 0.15,
        max_s: float = 10.0,
        pad_s: float = 0.3,
        peek_s: float = 1.3,
        gate: NoiseGate | None = None,
        accept_short: Callable[[], bool] | None = None,
        on_peek: Callable[[np.ndarray], None] | None = None,
        accept_peek: Callable[[], bool] | None = None,
        end_silence: Callable[[], float] | None = None,
    ) -> None:
        self._on_utterance = on_utterance
        self.end_silence = end_silence
        self.accept_short = accept_short
        self._on_peek = on_peek
        self.accept_peek = accept_peek
        self._peeked = False
        self._gate = gate or NoiseGate()
        per_s = SAMPLE_RATE / BLOCK
        self._end_blocks = max(1, round(end_silence_s * per_s))
        self._min_blocks = max(1, round(min_s * per_s))
        self._short_blocks = max(1, round(short_s * per_s))
        self._max_blocks = max(1, round(max_s * per_s))
        self._peek_blocks = max(1, round(peek_s * per_s))
        self._pad: deque[np.ndarray] = deque(maxlen=max(1, round(pad_s * per_s)))
        self._blocks: list[np.ndarray] = []
        self._lead = 0  # room-noise blocks at the start of the utterance
        self._quiet = 0  # silent blocks at the end of the utterance so far
        self._too_long = False
        self._too_long_blocks = 0
        self._max_too_long = max(1, round(30 * per_s))  # never deaf for more than 30 s at a stretch
        # Content-free counters for the periodic "wake listening" log line (``take_stats``).
        self.stats = {
            "blocks": 0, "speech_blocks": 0, "utterances": 0, "too_short": 0, "short": 0, "too_long": 0,
            "forced_resets": 0, "peeks": 0,
        }
        self.loudest = 0.0

    @property
    def speaking(self) -> bool:
        """An utterance is being collected now (read from the event loop: a snapshot is enough)."""
        return bool(self._blocks) and not self._too_long

    def _end_now(self) -> int:
        if self.end_silence is None:
            return self._end_blocks
        try:
            return max(1, round(self.end_silence() * SAMPLE_RATE / BLOCK))
        except Exception:  # noqa: BLE001 - a session bug must not stop the stream
            return self._end_blocks

    def reset(self) -> None:
        """Forget the current utterance and the room's level (e.g. after the stream was reopened)."""
        self._blocks, self._pad = [], type(self._pad)(maxlen=self._pad.maxlen)
        self._lead = self._quiet = self._too_long_blocks = 0
        self._too_long = self._peeked = False
        self._gate = NoiseGate(self._gate.min_level, self._gate.margin)

    def take_stats(self) -> dict[str, float]:
        """The counters since the last call (and the room's level now), then start again."""
        out: dict[str, float] = {
            **self.stats, "loudest": round(self.loudest, 2), "room": round(self._gate.floor, 2),
            "room_db": self._gate.room_db,
        }
        self.stats = dict.fromkeys(self.stats, 0)
        self.loudest = 0.0
        return out

    def feed(self, block: np.ndarray) -> None:
        block = block.reshape(-1).copy()  # PortAudio reuses its buffer
        level = level_from_block(block)
        speech = self._gate.speech(level)
        self.stats["blocks"] += 1
        self.stats["speech_blocks"] += speech
        self.loudest = max(self.loudest, level)
        if self._too_long:
            # A conversation, music or a TV can keep "speech" going without a pause; don't stay
            # deaf until it stops: start over after 30 s.
            self._too_long_blocks += 1
            if self._too_long_blocks >= self._max_too_long:
                self.stats["forced_resets"] += 1
                self._too_long, self._too_long_blocks, self._blocks, self._quiet = False, 0, [], 0
        if not self._blocks and not self._too_long:
            if speech:
                self._blocks = [*self._pad, block]
                self._lead = len(self._pad)
                self._pad.clear()
                self._quiet = 0
                self._peeked = False
            else:
                self._pad.append(block)
            return
        self._quiet = 0 if speech else self._quiet + 1
        if not self._too_long:
            self._blocks.append(block)
            if len(self._blocks) - self._lead - self._quiet > self._max_blocks:
                self._blocks, self._too_long = [], True
                self.stats["too_long"] += 1
            elif (
                not self._peeked and self._on_peek is not None and self._quiet == 0
                and len(self._blocks) - self._lead >= self._peek_blocks
                and (self.accept_peek is None or self.accept_peek())
            ):
                self._peeked = True
                self.stats["peeks"] += 1
                self._on_peek(np.concatenate(self._blocks))
        if self._quiet >= self._end_blocks and self._quiet >= self._end_now():
            blocks, self._blocks = self._blocks, []
            self._too_long = False
            spoken = len(blocks) - self._lead - self._quiet
            if blocks and spoken >= self._min_blocks:
                self.stats["utterances"] += 1
                self._on_utterance(np.concatenate(blocks), time.monotonic())
            elif blocks and spoken >= self._short_blocks and self.accept_short is not None and self.accept_short():
                self.stats["short"] += 1
                self._on_utterance(np.concatenate(blocks), time.monotonic(), True)
            elif blocks:
                self.stats["too_short"] += 1
