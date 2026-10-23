"""Word fixes: correct terms the speech model keeps mishearing (PLAN.md §6).

A fix maps a phrase as heard ("tori") to what was meant ("Tauri"). Matching
is case-insensitive on whole words, hyphens and spaces between words are
interchangeable, and the longest phrase wins where two overlap. Replacements
are applied in one pass, so one fix's output is never fixed again.

Fixes come from two places, merged (config wins on conflicts):
- ``stt.word_fixes`` in config.yaml, written by hand;
- the learned file (``%LOCALAPPDATA%\\Swift\\word_fixes.json``), written by
  ``spikes/stt/learn_fixes.py`` after the owner approves each fix.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from loguru import logger

_WORD = re.compile(r"[\w']+")


def _key(phrase: str) -> str:
    return " ".join(_WORD.findall(phrase.lower()))


class WordFixes:
    def __init__(self, fixes: Mapping[str, str] | None = None) -> None:
        self.fixes = {_key(heard): meant for heard, meant in (fixes or {}).items() if _key(heard)}
        self._pattern: re.Pattern[str] | None = None
        if self.fixes:
            # Longest first, so "lack plot code" beats a shorter fix inside it.
            phrases = sorted(self.fixes, key=len, reverse=True)
            alternatives = (r"[\s\-]+".join(re.escape(w) for w in p.split()) for p in phrases)
            self._pattern = re.compile(r"(?<![\w'])(?:" + "|".join(alternatives) + r")(?![\w'])", re.IGNORECASE)

    def __len__(self) -> int:
        return len(self.fixes)

    def apply(self, text: str) -> str:
        if self._pattern is None or not text:
            return text
        return self._pattern.sub(lambda m: self.fixes.get(_key(m.group(0)), m.group(0)), text)

    @classmethod
    def load(cls, learned: Path | None, configured: Mapping[str, str] | None = None) -> WordFixes:
        """Learned fixes from ``learned`` (if it exists), overridden by ``configured``.

        A broken learned file is logged and ignored: it must not stop Swift.
        """
        fixes: dict[str, str] = {}
        if learned is not None and learned.exists():
            try:
                data = json.loads(learned.read_text(encoding="utf-8"))
                for item in data.get("fixes", []):
                    if item.get("enabled", True):
                        fixes[str(item["heard"])] = str(item["meant"])
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                logger.warning("ignoring unreadable word fixes file", path=str(learned), error=type(exc).__name__)
                fixes = {}
        fixes.update(configured or {})
        return cls(fixes)
