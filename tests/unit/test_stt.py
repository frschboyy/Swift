"""Speech front end (gate, trim) and engine selection. No real models."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from swift.settings import SttSettings
from swift.stt.transcriber import (
    SAMPLE_RATE,
    Heard,
    Transcription,
    LocalTranscriber,
    ParakeetTranscriber,
    Word,
    assess,
    trim_silence,
    words_from_tokens,
)


class EchoModel(LocalTranscriber):
    """Returns fixed text and remembers what audio reached the model."""

    name = "echo"

    def __init__(self, text: str) -> None:
        super().__init__(Path("."))
        self.text = text
        self.heard: list[np.ndarray] = []

    def _load_model(self) -> object:
        return object()

    def _recognize(self, samples: np.ndarray) -> Heard:
        self.heard.append(samples)
        return Heard(self.text, tuple(Word(w, 0.9) for w in self.text.split()))


def speech(seconds: float, lead_s: float = 0.0, tail_s: float = 0.0) -> np.ndarray:
    """int16 audio: silence, a loud tone, silence."""
    tone = (8000 * np.sin(2 * np.pi * 220 * np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE)).astype(np.int16)
    return np.concatenate([
        np.zeros(int(lead_s * SAMPLE_RATE), np.int16), tone, np.zeros(int(tail_s * SAMPLE_RATE), np.int16)
    ])


async def test_silence_is_trimmed_before_the_model() -> None:
    stt = EchoModel("hi")
    stt._load()
    await stt.transcribe(speech(1.0, lead_s=1.0, tail_s=2.0))
    kept = len(stt.heard[0]) / SAMPLE_RATE
    assert 1.0 <= kept <= 1.0 + 2 * 0.2 + 0.07  # the speech plus the padding on each side


def test_trim_leaves_all_silence_alone() -> None:
    silent = np.zeros(SAMPLE_RATE, dtype=np.float32)
    assert len(trim_silence(silent)) == SAMPLE_RATE


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


def test_tokens_group_into_words_ignoring_punctuation() -> None:
    tokens = [" What", "'", "s", " in", " the", " ex", "ec", "utors", " fold", "er", "?"]
    logprobs = [-0.07, -0.16, 0.0, 0.0, -0.03, -0.32, 0.0, -0.63, 0.0, 0.0, -3.0]
    words = words_from_tokens(tokens, logprobs)
    assert [w.text for w in words] == ["What's", "in", "the", "executors", "folder?"]
    assert words[3].p == round(math.exp(-0.63), 3)  # the least likely token
    assert words[4].p == 1.0  # an unsure "?" is not a misheard word


@pytest.mark.parametrize(
    ("probs", "expected"),
    [
        ([0.99, 0.95, 0.9], "clear"),
        ([0.99, 0.2, 0.9, 0.97], "partly"),  # one guessed word: name it, still act
        ([0.5, 0.6, 0.45, 0.55], "unclear"),  # invented from background voices: all middling
        ([0.9, 0.1], "unclear"),
        ([0.3], "partly"),  # a single word ("stop") is never refused
    ],
)
def test_assess(probs: list[float], expected: str) -> None:
    t = Transcription("x", 1, 1.0, words=tuple(Word(f"w{i}", p) for i, p in enumerate(probs)))
    assert assess(t) == expected
    assert assess(t, unclear_p=0.0, reject_p=0.0) == "clear"


def test_assess_trusts_engines_without_probabilities() -> None:
    assert assess(Transcription("hello", 1, 1.0)) == "clear"


async def test_word_probabilities_reach_the_transcription() -> None:
    stt = EchoModel("run the tests")
    stt._load()
    result = await stt.transcribe(speech(1.0))
    assert [w.text for w in result.words] == ["run", "the", "tests"] and result.confidence == 0.9


def test_noise_floor_tells_a_quiet_room_from_a_noisy_one() -> None:
    import numpy as np

    from swift.stt.transcriber import noise_floor_db

    rng = np.random.default_rng(0)
    speech = 0.2 * np.sin(np.arange(16_000) * 0.05)

    def clip(room: float) -> np.ndarray:
        gap = room * rng.standard_normal(8_000)
        return np.concatenate([np.zeros(8_000), gap, speech + room * rng.standard_normal(16_000), gap])

    quiet, noisy = noise_floor_db(clip(10 ** (-65 / 20))), noise_floor_db(clip(10 ** (-35 / 20)))
    assert quiet is not None and noisy is not None
    assert quiet < -55 and noisy > -45  # digital silence at the start is not the room
    assert noise_floor_db(np.full(2_000, 0.1)) is None  # too short to say
