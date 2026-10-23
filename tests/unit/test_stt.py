"""Speech front end (gate, trim, word fixes) and engine selection. No real models."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from swift.settings import SttSettings
from swift.stt.fixes import WordFixes
from swift.stt.transcriber import (
    SAMPLE_RATE,
    LocalTranscriber,
    ParakeetTranscriber,
    trim_silence,
)


class EchoModel(LocalTranscriber):
    """Returns fixed text and remembers what audio reached the model."""

    name = "echo"

    def __init__(self, text: str, fixes: WordFixes | None = None) -> None:
        super().__init__(Path("."), fixes=fixes)
        self.text = text
        self.heard: list[np.ndarray] = []

    def _load_model(self) -> object:
        return object()

    def _recognize(self, samples: np.ndarray) -> str:
        self.heard.append(samples)
        return self.text


def speech(seconds: float, lead_s: float = 0.0, tail_s: float = 0.0) -> np.ndarray:
    """int16 audio: silence, a loud tone, silence."""
    tone = (8000 * np.sin(2 * np.pi * 220 * np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE)).astype(np.int16)
    return np.concatenate([
        np.zeros(int(lead_s * SAMPLE_RATE), np.int16), tone, np.zeros(int(tail_s * SAMPLE_RATE), np.int16)
    ])


async def test_fixes_apply_and_raw_text_is_kept() -> None:
    stt = EchoModel("What does the Tori config set?", WordFixes({"tori": "Tauri"}))
    stt._load()
    result = await stt.transcribe(speech(1.0))
    assert result.text == "What does the Tauri config set?"
    assert result.raw_text == "What does the Tori config set?"


async def test_raw_text_absent_when_nothing_changed() -> None:
    stt = EchoModel("Run the tests.", WordFixes({"tori": "Tauri"}))
    stt._load()
    assert (await stt.transcribe(speech(1.0))).raw_text is None


async def test_silence_is_trimmed_before_the_model() -> None:
    stt = EchoModel("hi")
    stt._load()
    await stt.transcribe(speech(1.0, lead_s=1.0, tail_s=2.0))
    kept = len(stt.heard[0]) / SAMPLE_RATE
    assert 1.0 <= kept <= 1.0 + 2 * 0.2 + 0.07  # the speech plus the padding on each side


def test_trim_leaves_all_silence_alone() -> None:
    silent = np.zeros(SAMPLE_RATE, dtype=np.float32)
    assert len(trim_silence(silent)) == SAMPLE_RATE


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("open the tori config", "open the Tauri config"),
        ("Open the Tori-config", "Open the Tauri-config"),  # only the phrase changes
        ("how long did the lack plot code request take", "how long did the last Claude Code request take"),
        ("lack plot  code", "last Claude Code"),  # any spacing
        ("lack-plot code", "last Claude Code"),  # hyphens count as spaces
        ("a story about tories", "a story about tories"),  # whole words only
        ("plot the data", "plot the data"),
    ],
)
def test_word_fix_matching(text: str, expected: str) -> None:
    fixes = WordFixes({"tori": "Tauri", "lack plot code": "last Claude Code"})
    assert fixes.apply(text) == expected


def test_fixes_apply_in_one_pass() -> None:
    # The output of one fix is never fixed again by another.
    fixes = WordFixes({"a": "b", "b": "c"})
    assert fixes.apply("a b") == "b c"


def test_load_merges_learned_and_config_with_config_winning(tmp_path: Path) -> None:
    learned = tmp_path / "word_fixes.json"
    learned.write_text(json.dumps({"fixes": [
        {"heard": "tori", "meant": "Tory"},
        {"heard": "deadlock", "meant": "git log", "enabled": False},
        {"heard": "bean size", "meant": "beam size"},
    ]}), encoding="utf-8")
    fixes = WordFixes.load(learned, {"Tori": "Tauri"})
    assert fixes.apply("tori deadlock bean size") == "Tauri deadlock beam size"


def test_unreadable_learned_file_is_ignored(tmp_path: Path) -> None:
    learned = tmp_path / "word_fixes.json"
    learned.write_text("{not json", encoding="utf-8")
    assert len(WordFixes.load(learned, {"x": "y"})) == 1
    assert len(WordFixes.load(tmp_path / "missing.json")) == 0


async def test_parakeet_missing_files_gives_download_hint(tmp_path: Path) -> None:
    from swift.stt.transcriber import SttUnavailable

    stt = ParakeetTranscriber(tmp_path)
    stt._load()
    with pytest.raises(SttUnavailable) as err:
        await stt.wait_loaded()
    assert "parakeet-tdt-0.6b-v2" in err.value.hint


def test_stt_settings_default_to_parakeet() -> None:
    s = SttSettings()
    assert s.engine == "parakeet" and s.model_label == "parakeet-tdt-0.6b-v2-int8"
    assert SttSettings(engine="whisper").model_label == "small.en"
