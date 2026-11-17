"""The corrections report (eval/stt/corrections.py) over clips the owner corrected on the card."""

import importlib.util
import time
from pathlib import Path

import numpy as np

from swift.stt.recordings import Recordings, save_wav

REPORT = Path(__file__).resolve().parents[2] / "eval" / "stt" / "corrections.py"
spec = importlib.util.spec_from_file_location("stt_corrections", REPORT)
corrections = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(corrections)  # type: ignore[union-attr]


def corrected(r: Recordings, clip: str, heard: str, said: str, kind: str, noise_db: float, source: str = "wake") -> None:
    path = r.path_for(clip)
    assert path is not None
    save_wav(path, np.zeros(16_000, dtype=np.int16))
    r.note({"id": clip, "source": source, "transcript": heard, "status": "done", "stt_confidence": 0.7,
            "noise_db": noise_db, "audio_file": str(path), "audio_s": 1.0})
    assert r.correct(clip, heard, said, kind)


def test_the_report_finds_the_name_misheard_the_kinds_by_room_and_the_error_rate(tmp_path: Path) -> None:
    r = Recordings(tmp_path / "audio", tmp_path / "stt_testset", stt_model="parakeet-v2", clock=time.time)
    corrected(r, "a", "hey christy what time is it", "hey Swift what time is it", "name", -60.0)
    corrected(r, "b", "they swift open notepad", "hey Swift open notepad", "name", -40.0)
    corrected(r, "c", "turn of the lights", "turn off the lights", "wrong_word", -60.0, source="voice")
    out = corrections.report(corrections.load(tmp_path))
    assert out["corrections"] == 3 and out["by_kind"] == {"name": 2, "wrong_word": 1}
    assert out["by_source"] == {"wake": 2, "voice": 1}
    assert out["by_room"] == {"noisy": {"name": 1}, "quiet": {"name": 1, "wrong_word": 1}}
    assert out["name_heard_as"] == {"christy": 1}  # "they swift": the name was heard, "hey" wasn't
    assert ["hey", 1, {"they": 1}] in out["most_missed"]
    assert out["wer_by_model"] == {"parakeet-v2": round(3 / 14, 3)}
    text = corrections.show(out)
    assert '"Swift" heard as' in text and "christy" in text


def test_nothing_to_report_says_how_to_start(tmp_path: Path) -> None:
    out = corrections.report(corrections.load(tmp_path))
    assert out["corrections"] == 0 and "flag" in corrections.show(out)
