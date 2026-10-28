"""Is a better local speech model worth it? (owner checks of 2026-10-27, docs/stt-models.md)

Runs each candidate over the owner's own recordings, on this machine only (nothing is uploaded):

- ``read``:   the 55 read prompts of ``%LOCALAPPDATA%\\Swift\\stt_corpus`` (quiet room);
- ``noisy``:  the 30 of ``stt_noisy`` (a TV, music, two metres away);
- ``checks``: 34 requests from the owner checks of 2026-10-27 17:00 (``checks_1027.jsonl``: the
  intended words come from the check script or the owner's own repeat; clips whose words are
  unknown are left out). ``failed`` marks the ones Swift got wrong or refused that day.
- ``kept``: Swift's own test set (``%LOCALAPPDATA%\\Swift\\stt_testset``, swift/stt/recordings.py):
  clips Swift kept because the owner said them again or corrected them, with the words meant.
  All of them count as ``failed``: each was misheard, refused or failed at the time.

Each clip goes through Swift's own front end first (silence gate, trim). Reported per model and
set: WER after light normalization (case, punctuation, "3"/"three", "p.m."/"pm", "TestMe"/"Test
Me", hesitations), the median and 90th-percentile time per clip, load time and memory, and for
Parakeet how many transcripts Swift would refuse as unclear (``assess``), right or wrong.

Usage (models not in Swift's folder go under --models-root, e.g. from Hugging Face):
    uv run python spikes/stt/model_compare.py --models-root <dir> --out <file.json> [--only a,b]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

SWIFT_DIR = Path(os.environ["LOCALAPPDATA"]) / "Swift"
HERE = Path(__file__).parent
THREADS = 4
NUMBERS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen".split()
FILLERS = {"um", "umm", "uh", "uhh", "er", "erm", "hmm", "mm", "ah"}

Recognize = Callable[[np.ndarray], tuple[str, Any]]


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as f:
        return np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def normalize(text: str) -> list[str]:
    text = text.lower().replace("p.m.", "pm").replace("a.m.", "am").replace("-", " ")
    text = re.sub(r"[^\w\s']", " ", text).replace("testme", "test me")
    words = [NUMBERS[int(w)] if w.isdigit() and int(w) < len(NUMBERS) else w for w in text.split()]
    return [w for w in words if w not in FILLERS]


def edits(ref: list[str], hyp: list[str]) -> int:
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[-1]


def clip_sets(only: set[str] | None) -> dict[str, list[tuple[Path, str, bool]]]:
    sets: dict[str, list[tuple[Path, str, bool]]] = {}
    for name, folder in (("read", SWIFT_DIR / "stt_corpus"), ("noisy", SWIFT_DIR / "stt_noisy")):
        refs = folder / "refs.jsonl"
        if refs.exists():
            rows = [json.loads(line) for line in refs.read_text(encoding="utf-8").splitlines() if line.strip()]
            sets[name] = [(folder / r["wav"], r["ref"], False) for r in rows if r.get("ref")]  # some aren't labelled
    rows = [json.loads(line) for line in (HERE / "checks_1027.jsonl").read_text(encoding="utf-8").splitlines() if line]
    checks = [(SWIFT_DIR / "audio" / r["wav"], r["ref"], bool(r.get("failed"))) for r in rows]
    sets["checks"] = [c for c in checks if c[0].exists()]
    kept = SWIFT_DIR / "stt_testset"
    if (kept / "index.json").exists():
        clips = json.loads((kept / "index.json").read_text(encoding="utf-8")).get("clips", [])
        sets["kept"] = [(kept / c["wav"], c["known"], True) for c in clips if c.get("known") and (kept / c["wav"]).exists()]
    return {k: v for k, v in sets.items() if only is None or k in only}


def parakeet(model: str, folder: Path, quantization: str | None) -> Callable[[], Recognize]:
    def load() -> Recognize:
        import onnx_asr
        import onnxruntime

        from swift.stt.transcriber import words_from_tokens

        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads = THREADS
        opts.inter_op_num_threads = 1
        asr = onnx_asr.load_model(model, folder, quantization=quantization, sess_options=opts).with_timestamps()

        def run(samples: np.ndarray) -> tuple[str, Any]:
            result = asr.recognize(samples, sample_rate=16_000)
            return result.text, words_from_tokens(result.tokens or [], result.logprobs or [])

        return run

    return load


def whisper(folder: Path, vad: bool, beam: int) -> Callable[[], Recognize]:
    def load() -> Recognize:
        from faster_whisper import WhisperModel

        model = WhisperModel(str(folder), device="cpu", compute_type="int8", cpu_threads=THREADS, local_files_only=True)

        def run(samples: np.ndarray) -> tuple[str, Any]:
            segments, _ = model.transcribe(
                samples, language="en", beam_size=beam, vad_filter=vad, temperature=0.0,
                condition_on_previous_text=False,
            )
            return " ".join(s.text.strip() for s in segments), None

        return run

    return load


def models(root: Path) -> dict[str, Callable[[], Recognize]]:
    return {
        "parakeet-v2-int8 (now)": parakeet("nemo-parakeet-tdt-0.6b-v2", SWIFT_DIR / "models" / "parakeet-tdt-0.6b-v2", "int8"),
        "parakeet-v2-fp32": parakeet("nemo-parakeet-tdt-0.6b-v2", root / "parakeet-tdt-0.6b-v2-onnx", None),
        "parakeet-v3-int8": parakeet("nemo-parakeet-tdt-0.6b-v3", root / "parakeet-tdt-0.6b-v3-onnx", "int8"),
        "whisper-large-v3-turbo+vad": whisper(root / "faster-whisper-large-v3-turbo", True, 5),
    }


def private_mb() -> float:
    import psutil

    info = psutil.Process().memory_full_info()
    return getattr(info, "private", info.uss) / 2**20


def run_model(name: str, load: Callable[[], Recognize], sets: dict[str, list[tuple[Path, str, bool]]]) -> dict[str, Any]:
    from swift.stt.transcriber import SILENCE_DB, Transcription, assess, loudest_db, trim_silence

    before, t0 = private_mb(), time.perf_counter()
    recognize = load()
    out: dict[str, Any] = {"load_s": round(time.perf_counter() - t0, 1), "private_mb": round(private_mb() - before)}
    recognize(np.zeros(16_000, dtype=np.float32))  # the first run pays for warming up
    for set_name, clips in sets.items():
        errors = words = refused_right = refused_wrong = 0
        times: list[float] = []
        failed_errors = failed_words = 0
        examples: list[dict[str, str]] = []
        for path, ref, failed in clips:
            samples = read_wav(path)
            text, heard = "", None
            if loudest_db(samples) >= SILENCE_DB:
                t1 = time.perf_counter()
                text, heard = recognize(trim_silence(samples))
                times.append((time.perf_counter() - t1) * 1000)
            r, h = normalize(ref), normalize(text)
            e = edits(r, h)
            errors, words = errors + e, words + len(r)
            if failed:
                failed_errors, failed_words = failed_errors + e, failed_words + len(r)
                examples.append({"ref": ref, "hyp": text.strip()})
            if heard is not None and assess(Transcription(text, 0, 0.0, words=heard)) == "unclear":
                refused_right, refused_wrong = refused_right + (e > 0), refused_wrong + (e == 0)
        out[set_name] = {
            "clips": len(clips), "wer": round(errors / max(words, 1), 3),
            "ms_median": round(statistics.median(times)) if times else None,
            "ms_p90": round(sorted(times)[int(0.9 * (len(times) - 1))]) if times else None,
            "refused_wrong_transcripts": refused_right if heard is not None or name.startswith("parakeet") else None,
            "refused_right_transcripts": refused_wrong if heard is not None or name.startswith("parakeet") else None,
        }
        if failed_words:
            out[set_name]["wer_on_failed"] = round(failed_errors / failed_words, 3)
            out[set_name]["failed"] = examples
        print(name, set_name, out[set_name]["wer"], out[set_name]["ms_median"], flush=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", default="", help="comma-separated model names (default: all)")
    parser.add_argument("--sets", default="", help="comma-separated: read,noisy,checks,kept (default: all)")
    args = parser.parse_args()
    sets = clip_sets(set(args.sets.split(",")) if args.sets else None)
    chosen = models(args.models_root)
    if args.only:
        chosen = {k: v for k, v in chosen.items() if any(o in k for o in args.only.split(","))}
    results = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    for name, load in chosen.items():
        try:
            results[name] = run_model(name, load, sets)
        except Exception as exc:  # noqa: BLE001 - a missing model mustn't stop the others
            print(name, "failed:", type(exc).__name__, str(exc)[:200], file=sys.stderr, flush=True)
            continue
        args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
