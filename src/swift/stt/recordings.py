"""Saved recordings that earn their keep (audit 2026-10, B-06).

A recording is kept only when it can improve transcription, and only on this PC:

- **Flagged** when it is saved, for any of these reasons (``FLAGS``):
  ``unsure`` (the model was unsure of a word), ``say_again`` (Swift asked to say it again),
  ``repeated`` (the owner said it again, or corrected it, within a few seconds), ``missed_wake``
  (speech just before a wake phrase or the hotkey, which Swift didn't take as addressed to it),
  ``failed`` (the request failed).
- **Known words:** a repeat or correction heard surely gives the words the owner meant for the
  clip before it. They are the only words written down, in the index next to the clips.
- **Kept** at most ``keep_days`` (0: nothing is saved). A clip with no flag goes once the time for
  a repeat has passed (``HOLD_S``), unless ``keep_all``.
- **Test set:** a flagged clip with known words is copied to ``test_dir``, kept after
  ``keep_days``, at most ``test_max`` clips, the oldest dropped first.
- ``clear()`` deletes the clips, the index and the test set ("Clear saved recordings").

The index (``index.json``) holds content-free metadata: id, time, length, source, flags, how sure
the model was, the outcome, and the known words where the owner gave them. Never the transcript.
Nothing here opens a network connection; logs carry counts only. Audio and words are never used
to train a model: the improvement pass (``swift.stt.improve``) proposes word fixes for the owner
to approve and checks accuracy.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

SAMPLE_RATE = 16_000
FLAGS = ("unsure", "say_again", "repeated", "missed_wake", "failed")
INDEX = "index.json"
# A request started this soon after the last one ended may be the owner saying it again.
REPEAT_S = 10.0
# ...or this soon after Swift asked to say it again (the owner reads the card first).
SAY_AGAIN_S = 20.0
# Speech the open microphone heard this soon before a wake phrase or the hotkey: perhaps a missed wake.
MISSED_WAKE_S = 6.0
# A clip with no flag waits this long for a repeat before it is deleted (keep_all off).
HOLD_S = 30.0
# A repeat gives known words only if the model was at least this sure of each word.
SURE_P = 0.6
# Two transcripts sharing this much of their words are the same request said again.
SAME_WORDS = 0.5
SAY_AGAIN_ERRORS = frozenset({"unclear_speech", "no_speech"})
# Sources whose clips come from the owner speaking a request.
VOICE_SOURCES = frozenset({"voice", "wake", "followup", "correction", "retry", "beside"})
_WORD = re.compile(r"[\w']+")
# "No, I said ...", "I meant ...": the rest is the request as meant.
_CORRECTION = re.compile(r"^\s*(?:(?:no|nope|sorry|actually)\b[\s,.!]*)?(?:i\s+(?:said|meant|mean)\b[\s,:.]*)", re.I)
_ID = re.compile(r"^[\w-]{1,64}$")


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def correction(text: str) -> str | None:
    """The meant words of "no, I said <words>", or None if ``text`` isn't a correction."""
    match = _CORRECTION.match(text)
    if match is None:
        return None
    rest = text[match.end():].strip()
    return rest or None


def same_request(a: str, b: str) -> bool:
    """Whether ``b`` reads as ``a`` said again (a mishearing changes a few words, not most)."""
    wa, wb = set(words(a)), set(words(b))
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= SAME_WORDS


def save_wav(path: Path, audio: np.ndarray) -> None:
    """16 kHz mono int16, as the recorder delivers it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(np.asarray(audio).astype(np.int16).tobytes())


def read_wav(path: Path) -> np.ndarray:
    """int16-scaled float32 samples, as the transcriber takes them."""
    with wave.open(str(path)) as f:
        return np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32)


@dataclass
class _Last:
    """The last spoken request, in memory only: to tell whether the next one repeats it."""

    id: str
    ended: float  # time.monotonic()
    text: str
    said_again: bool
    went_wrong: bool


@dataclass
class _Unaddressed:
    """Speech the open microphone heard and didn't take as addressed to Swift: in memory only."""

    audio: np.ndarray
    ended: float  # time.monotonic()


@dataclass
class Recordings:
    audio_dir: Path
    test_dir: Path
    keep_days: int = 7
    keep_all: bool = False
    test_max: int = 200
    # A clip whose least sure word is below this is flagged "unsure" (stt.unclear_p).
    unsure_p: float = 0.4
    clock: Callable[[], float] = time.time
    mono: Callable[[], float] = time.monotonic
    _held: dict[str, float] = field(default_factory=dict)  # unflagged clip id -> when it may go (mono)
    _last: _Last | None = None
    _unaddressed: _Unaddressed | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def enabled(self) -> bool:
        return self.keep_days > 0

    # ---- saving and flagging --------------------------------------------------------------

    def path_for(self, clip_id: str) -> Path | None:
        """Where to save the clip of interaction ``clip_id``; None when recordings are off."""
        if not self.enabled or not _ID.match(clip_id):
            return None
        return self.audio_dir / f"{clip_id}.wav"

    def heard_unaddressed(self, audio: np.ndarray) -> None:
        """Speech wake listening didn't take as addressed to Swift. Kept in memory for
        ``MISSED_WAKE_S`` only: saved only if the owner addresses Swift right after it."""
        if self.enabled:
            self._unaddressed = _Unaddressed(np.asarray(audio).copy(), self.mono())

    def note(self, record: dict[str, Any]) -> list[str]:
        """An interaction finished: flag its clip, perhaps the clip before it, and a missed wake
        phrase just before it. Returns its flags. Never raises."""
        try:
            return self._note(record)
        except Exception:  # noqa: BLE001 - the log line of an interaction must not break it
            logger.exception("recordings: could not flag a clip")
            return []

    def _note(self, record: dict[str, Any]) -> list[str]:
        if not self.enabled:
            return []
        now = self.mono()
        self._expire_held(now)
        source = record.get("source")
        if source not in VOICE_SOURCES:
            return []
        clip_id = str(record.get("id", ""))
        text = str(record.get("transcript") or record.get("transcript_heard") or "")
        started = now - (record.get("interaction_ms") or 0) / 1000
        error, status = record.get("error"), record.get("status")
        confidence = record.get("stt_confidence")
        has_clip = bool(record.get("audio_file")) and _ID.match(clip_id) is not None

        flags: list[str] = []
        if isinstance(confidence, (int, float)) and confidence < self.unsure_p:
            flags.append("unsure")
        if error in SAY_AGAIN_ERRORS:
            flags.append("say_again")
        elif status == "error":
            flags.append("failed")

        self._missed_wake(clip_id, started, source)
        self._repeat_of_last(text, started, confidence, error, status, source)

        if has_clip:
            entry = {
                "id": clip_id, "ts": round(self.clock(), 1), "audio_s": record.get("audio_s"), "source": source,
                "flags": flags, "confidence": confidence, "status": status, "error": error,
            }
            self._write_entry(entry)
            if not flags and not self.keep_all:
                self._held[clip_id] = now + HOLD_S
        self._last = _Last(
            clip_id if has_clip else "", now, text, error in SAY_AGAIN_ERRORS,
            status in ("error", "cancelled", "rejected"),
        )
        return flags

    def _missed_wake(self, clip_id: str, started: float, source: str) -> None:
        heard, self._unaddressed = self._unaddressed, None
        if heard is None or source not in ("wake", "voice") or not 0 <= started - heard.ended <= MISSED_WAKE_S:
            return
        miss_id = f"{clip_id}-miss" if clip_id else f"miss-{int(self.clock())}"
        path = self.path_for(miss_id)
        if path is None:
            return
        try:
            save_wav(path, heard.audio)
        except OSError as exc:
            logger.warning("recordings: could not save a clip", error=type(exc).__name__)
            return
        self._write_entry({
            "id": miss_id, "ts": round(self.clock(), 1), "audio_s": round(len(heard.audio) / SAMPLE_RATE, 2),
            "source": "wake_miss", "flags": ["missed_wake"],
        })
        logger.info("recordings: missed wake phrase kept", before_s=round(started - heard.ended, 1))

    def _repeat_of_last(
        self, text: str, started: float, confidence: Any, error: Any, status: Any, source: str
    ) -> None:
        last = self._last
        if last is None or not last.id or not text:
            return
        window = SAY_AGAIN_S if last.said_again else REPEAT_S
        if not 0 <= started - last.ended <= window:
            return
        meant = correction(text)
        if meant is None and not (last.said_again or source == "correction" or same_request(last.text, text)):
            return
        if meant is None and not last.said_again and not last.went_wrong and source != "correction" \
                and words(last.text) == words(text):
            return  # heard the same twice: the owner asked again, it wasn't misheard
        known = meant or text
        sure = isinstance(confidence, (int, float)) and confidence >= SURE_P and error is None and status != "error"
        self._update_entry(last.id, "repeated", known if sure else None)

    def _expire_held(self, now: float) -> None:
        for clip_id, until in list(self._held.items()):
            if now >= until:
                del self._held[clip_id]
                self._delete_clip(clip_id)

    def tick(self) -> None:
        """Drop the unflagged clips whose time for a repeat has passed (every minute or so)."""
        self._expire_held(self.mono())

    # ---- the index ----------------------------------------------------------------------

    def _index_path(self, folder: Path) -> Path:
        return folder / INDEX

    def _load(self, folder: Path) -> dict[str, dict[str, Any]]:
        path = self._index_path(folder)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            logger.warning("recordings: unreadable index, starting a new one", folder=folder.name)
            return {}
        return {str(e["id"]): e for e in data.get("clips", []) if isinstance(e, dict) and "id" in e}

    def _save(self, folder: Path, entries: dict[str, dict[str, Any]]) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        path = self._index_path(folder)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"clips": list(entries.values())}, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._load(self.audio_dir).values())

    def test_set(self) -> list[dict[str, Any]]:
        """The test set's clips: ``{id, wav, known, flags, added}``, oldest first."""
        with self._lock:
            return sorted(self._load(self.test_dir).values(), key=lambda e: e.get("added", 0))

    def _write_entry(self, entry: dict[str, Any]) -> None:
        with self._lock:
            entries = self._load(self.audio_dir)
            entries[entry["id"]] = {k: v for k, v in entry.items() if v is not None}
            self._save(self.audio_dir, entries)

    def _update_entry(self, clip_id: str, flag: str, known: str | None) -> None:
        with self._lock:
            entries = self._load(self.audio_dir)
            entry = entries.get(clip_id)
            if entry is None:
                return
            if flag not in entry.setdefault("flags", []):
                entry["flags"].append(flag)
            if known:
                entry["known"] = known
            self._save(self.audio_dir, entries)
        self._held.pop(clip_id, None)
        if known:
            self._to_test_set(entry)

    def _to_test_set(self, entry: dict[str, Any]) -> None:
        src = self.audio_dir / f"{entry['id']}.wav"
        if self.test_max <= 0 or not src.exists():
            return
        with self._lock:
            tests = self._load(self.test_dir)
            try:
                self.test_dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, self.test_dir / src.name)
            except OSError as exc:
                logger.warning("recordings: could not add to the test set", error=type(exc).__name__)
                return
            tests[entry["id"]] = {
                "id": entry["id"], "wav": src.name, "known": entry["known"], "flags": entry.get("flags", []),
                "audio_s": entry.get("audio_s"), "added": round(self.clock(), 1),
            }
            dropped = 0
            for old in sorted(tests.values(), key=lambda e: e.get("added", 0))[: max(0, len(tests) - self.test_max)]:
                tests.pop(old["id"])
                (self.test_dir / old["wav"]).unlink(missing_ok=True)
                dropped += 1
            self._save(self.test_dir, tests)
        logger.info("recordings: added to the test set", size=len(tests), dropped=dropped)

    def _delete_clip(self, clip_id: str) -> None:
        with self._lock:
            (self.audio_dir / f"{clip_id}.wav").unlink(missing_ok=True)
            entries = self._load(self.audio_dir)
            if entries.pop(clip_id, None) is not None:
                self._save(self.audio_dir, entries)

    # ---- retention and clearing ---------------------------------------------------------

    def sweep(self) -> dict[str, int]:
        """Delete clips older than ``keep_days`` (all of them when 0), and clips the index doesn't
        know (from before this, or a crash) unless ``keep_all``. At start-up and once a day."""
        cutoff = self.clock() - self.keep_days * 86400
        deleted = unknown = kept = 0
        with self._lock:
            entries = self._load(self.audio_dir)
            if self.audio_dir.is_dir():
                for wav in self.audio_dir.glob("*.wav"):
                    try:
                        old = wav.stat().st_mtime < cutoff
                        stray = wav.stem not in entries and not self.keep_all and wav.stem not in self._held
                        if old or stray:
                            wav.unlink()
                            deleted += old
                            unknown += stray and not old
                        else:
                            kept += 1
                    except OSError:
                        continue
            gone = [i for i in entries if not (self.audio_dir / f"{i}.wav").exists()]
            for clip_id in gone:
                entries.pop(clip_id)
            if gone:
                self._save(self.audio_dir, entries)
        counts = {"deleted_old": deleted, "deleted_unflagged": unknown, "kept": kept,
                  "test_set": len(self.test_set())}
        logger.info("recordings swept", keep_days=self.keep_days, **counts)
        return counts

    def clear(self) -> dict[str, int]:
        """Delete every saved clip, the index and the test set ("Clear saved recordings")."""
        clips = tests = 0
        with self._lock:
            self._held.clear()
            self._last = None
            self._unaddressed = None
            for folder in (self.audio_dir, self.test_dir):
                if not folder.is_dir():
                    continue
                for wav in folder.glob("*.wav"):
                    try:
                        wav.unlink()
                    except OSError:
                        continue
                    if folder == self.audio_dir:
                        clips += 1
                    else:
                        tests += 1
                for name in (INDEX, "improve.json", "endpoint_feed.json"):
                    (folder / name).unlink(missing_ok=True)
        logger.info("recordings cleared", clips=clips, test_set=tests)
        return {"clips": clips, "test_set": tests}


__all__ = ["FLAGS", "Recordings", "correction", "read_wav", "same_request", "save_wav"]
