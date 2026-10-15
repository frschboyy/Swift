"""S2: faster-whisper latency on CPU (int8) for 2/5/10 s clips.

Usage:  uv run --group spikes python spikes/latency/stt_bench.py [--reps 10]
Run piper_bench.py first (it writes the clips).

For each model (base.en, small.en) and beam size (1, 5):
  - load time from disk (model downloaded beforehand, not timed)
  - transcription wall time per clip, warm, n=--reps
  - real-time factor
Audio is decoded and resampled to 16 kHz once, outside the timed region.
Clips are Piper speech, so accuracy here is not meaningful (WER comes from
the real corpus in Phase 2); only latency is.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _util import SPIKES_DIR, Timer, models_dir, private_mb, summarize, write_result  # noqa: E402

MODELS = ["base.en", "small.en"]
BEAMS = [1, 5]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--threads", type=int, default=4, help="cpu_threads (physical cores)")
    args = ap.parse_args()

    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio

    clip_dir = SPIKES_DIR / "latency" / "results" / "clips"
    clips = {p.stem: decode_audio(str(p), sampling_rate=16000) for p in sorted(clip_dir.glob("clip_*s.wav"))}
    if not clips:
        sys.exit("no clips found; run piper_bench.py first")

    root = models_dir() / "whisper"
    out: dict[str, dict] = {}
    for name in MODELS:
        WhisperModel(name, device="cpu", compute_type="int8", download_root=str(root))  # download only
        before = private_mb()
        with Timer() as load:
            model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=args.threads, download_root=str(root))
        loaded = private_mb()
        list(model.transcribe(next(iter(clips.values())), language="en", beam_size=1)[0])  # warm-up

        per: dict[str, dict] = {}
        for beam in BEAMS:
            for clip, audio in clips.items():
                dur = len(audio) / 16000
                times = []
                text = ""
                for _ in range(args.reps):
                    with Timer() as t:
                        segments, _info = model.transcribe(
                            audio, language="en", beam_size=beam, vad_filter=False, condition_on_previous_text=False
                        )
                        text = " ".join(s.text.strip() for s in segments)
                    times.append(t.elapsed)
                per[f"beam{beam}/{clip}"] = {
                    "audio_s": round(dur, 2),
                    "wall_s": summarize(times),
                    "rtf_p50": round(summarize(times)["p50"] / dur, 3),
                    "text": text,
                }
                print(name, f"beam{beam}", clip, per[f"beam{beam}/{clip}"]["wall_s"])
        out[name] = {
            "load_s": round(load.elapsed, 3),
            "private_mb_delta_after_load": round(loaded - before, 1),
            "private_mb_after_inference": private_mb(),
            "runs": per,
        }
        del model

    write_result(
        "latency",
        "stt",
        {
            "compute_type": "int8",
            "cpu_threads": args.threads,
            "reps": args.reps,
            "models": out,
            "method": "warm, sequential; segments fully consumed inside timer; vad_filter off",
        },
    )


if __name__ == "__main__":
    main()
