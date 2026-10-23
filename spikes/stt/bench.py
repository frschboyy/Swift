"""Compare speech models on your own recordings: accuracy (WER) and speed.

Usage (from the repo root, plugged in, Windows power mode "Best performance"):
  uv run --group sttbench python spikes/stt/bench.py --download     # fetch all models once
  uv run --group sttbench python spikes/stt/bench.py                # run every model
  uv run --group sttbench python spikes/stt/bench.py --models parakeet-v2,fw-small.en-b5

The test set comes from corpus.py (%LOCALAPPDATA%\\Swift\\stt_corpus). Each model
is loaded once, warmed up on one clip, then times every clip once. Whisper runs
with Swift's settings (no VAD, temperature 0, initial_prompt from config.yaml
unless --no-prompt). All models use 4 CPU threads, one per physical core.
Leading and trailing silence is trimmed from every clip first (--no-trim to skip).

WER is computed after light normalization (lowercase, no punctuation), so
"README." and "readme" match but "3" and "three" don't.
Results go to spikes/stt/results/ (gitignored: they contain your transcripts).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _util import machine_info, models_dir, summarize, write_result  # noqa: E402
from corpus import CORPUS_DIR, SAMPLE_RATE, load_refs, read_wav  # noqa: E402

THREADS = 4
REPO = Path(__file__).resolve().parents[2]
# Hugging Face downloads (Moonshine, Parakeet) go to Swift's model store, next to Whisper.
os.environ.setdefault("HF_HUB_CACHE", str(models_dir() / "hf"))

Transcribe = Callable[[np.ndarray], str]


def whisper(name: str, beam: int) -> Callable[[bool, str], Transcribe]:
    def load(download: bool, prompt: str) -> Transcribe:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            name, device="cpu", compute_type="int8", cpu_threads=THREADS,
            download_root=str(models_dir() / "whisper"), local_files_only=not download,
        )

        def run(audio: np.ndarray) -> str:
            segments, _ = model.transcribe(
                audio, language="en", beam_size=beam, vad_filter=False, temperature=0.0,
                condition_on_previous_text=False, initial_prompt=prompt or None,
            )
            return " ".join(s.text.strip() for s in segments).strip()

        return run

    return load


def moonshine(name: str) -> Callable[[bool, str], Transcribe]:
    def load(download: bool, _prompt: str) -> Transcribe:
        if not download:
            os.environ["HF_HUB_OFFLINE"] = "1"
        from moonshine_onnx import MoonshineOnnxModel, load_tokenizer

        model = MoonshineOnnxModel(model_name=name)
        tokenizer = load_tokenizer()

        def run(audio: np.ndarray) -> str:
            # About 6 tokens per second of speech is plenty; the default cap is 192.
            tokens = model.generate(audio[None, :], max_len=int(len(audio) / SAMPLE_RATE * 6) + 10)
            return tokenizer.decode_batch(tokens)[0].strip()

        return run

    return load


def onnx_asr_model(name: str, quantization: str | None) -> Callable[[bool, str], Transcribe]:
    def load(download: bool, _prompt: str) -> Transcribe:
        if not download:
            os.environ["HF_HUB_OFFLINE"] = "1"
        import onnx_asr
        import onnxruntime

        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads = THREADS
        model = onnx_asr.load_model(name, quantization=quantization, sess_options=opts)

        def run(audio: np.ndarray) -> str:
            return str(model.recognize(audio, sample_rate=SAMPLE_RATE)).strip()

        return run

    return load


# Name -> loader. Order is the default run order: current baseline first.
MODELS: dict[str, Callable[[bool, str], Transcribe]] = {
    "fw-small.en-b5": whisper("small.en", 5),
    "fw-small.en-b1": whisper("small.en", 1),
    "fw-base.en-b1": whisper("base.en", 1),
    "fw-distil-small.en-b5": whisper("distil-small.en", 5),
    "fw-distil-small.en-b1": whisper("distil-small.en", 1),
    "moonshine-base": moonshine("base"),
    "moonshine-tiny": moonshine("tiny"),
    "parakeet-v2-int8": onnx_asr_model("nemo-parakeet-tdt-0.6b-v2", "int8"),
}


def trim_silence(audio: np.ndarray, floor_db: float = -45.0, pad_s: float = 0.2) -> np.ndarray:
    """Cut leading/trailing silence (32 ms blocks below floor_db), keeping pad_s on each side.

    Moonshine base returns nothing for clips ending in ~2 s of silence; Swift
    could do the same trim cheaply before any model.
    """
    block = 512
    n = len(audio) // block
    if n == 0:
        return audio
    rms = np.sqrt(np.mean(audio[: n * block].reshape(n, block) ** 2, axis=1))
    loud = np.nonzero(20 * np.log10(np.maximum(rms, 1e-9)) >= floor_db)[0]
    if len(loud) == 0:
        return audio
    pad = int(pad_s * SAMPLE_RATE)
    return audio[max(0, loud[0] * block - pad) : min(len(audio), (loud[-1] + 1) * block + pad)]


def normalize(text: str) -> str:
    text = text.lower().replace("-", " ").replace("_", " ")
    text = re.sub(r"[^\w\s']", " ", text)
    return " ".join(text.split())


def wer(refs: list[str], hyps: list[str]) -> float:
    import jiwer

    pairs = [(r, h) for r, h in zip(refs, hyps) if r]
    return jiwer.wer([r for r, _ in pairs], [h if h else "<empty>" for _, h in pairs])


def config_prompt() -> str:
    import yaml

    path = REPO / "config.yaml"
    if not path.exists():
        return ""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return (data.get("stt") or {}).get("initial_prompt") or ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default=",".join(MODELS), help=f"comma-separated; any of: {', '.join(MODELS)}")
    ap.add_argument("--download", action="store_true", help="fetch the models, then exit")
    ap.add_argument("--no-prompt", action="store_true", help="run Whisper without config.yaml's initial_prompt")
    ap.add_argument("--limit", type=int, default=0, help="only the first N clips (quick check)")
    ap.add_argument("--no-trim", action="store_true", help="feed clips as recorded, silence included")
    args = ap.parse_args()

    names = [n.strip() for n in args.models.split(",") if n.strip()]
    unknown = [n for n in names if n not in MODELS]
    if unknown:
        raise SystemExit(f"unknown model(s): {', '.join(unknown)}")

    if args.download:
        for name in names:
            print(f"downloading {name} ...", flush=True)
            MODELS[name](True, "")
        print("done")
        return

    rows = [r for r in load_refs() if r.get("ref")]
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit(f"No test clips yet. Record some first: python spikes/stt/corpus.py read  ({CORPUS_DIR})")
    clips = [read_wav(CORPUS_DIR / r["wav"]).astype(np.float32) / 32768.0 for r in rows]
    if not args.no_trim:
        clips = [trim_silence(c) for c in clips]
    refs = [normalize(r["ref"]) for r in rows]
    audio_s = sum(len(c) for c in clips) / SAMPLE_RATE
    prompt = "" if args.no_prompt else config_prompt()
    info = machine_info()
    print(f"{len(clips)} clips, {audio_s:.0f} s of audio. Power: {info['power']}. Prompt: {'yes' if prompt else 'no'}")
    if info["power"] == "battery":
        print("WARNING: on battery; timings will be slower and noisier than plugged in.")

    results = []
    for name in names:
        print(f"\n== {name}", flush=True)
        try:
            t0 = time.perf_counter()
            run = MODELS[name](False, prompt)
            load_s = time.perf_counter() - t0
        except Exception as exc:  # noqa: BLE001 - a missing model shouldn't stop the others
            print(f"   skipped: {type(exc).__name__}: {str(exc)[:200]}  (try --download)")
            results.append({"model": name, "error": f"{type(exc).__name__}: {exc}"[:500]})
            continue
        run(clips[0])  # warm-up, not timed
        hyps, ms = [], []
        for clip in clips:
            t = time.perf_counter()
            hyps.append(normalize(run(clip)))
            ms.append((time.perf_counter() - t) * 1000)
        score = wer(refs, hyps)
        rtf = sum(ms) / 1000 / audio_s
        stats = summarize(ms)
        print(f"   WER {score:.1%}   median {stats['p50']:.0f} ms   p90 {stats['p90']:.0f} ms   RTF {rtf:.2f}   load {load_s:.1f} s")
        results.append({
            "model": name, "wer": round(score, 4), "load_s": round(load_s, 2), "rtf": round(rtf, 3),
            "ms": stats,
            "clips": [{"id": r["id"], "ref": ref, "hyp": h, "ms": round(m)} for r, ref, h, m in zip(rows, refs, hyps, ms)],
        })

    ok = sorted((r for r in results if "wer" in r), key=lambda r: (r["wer"], r["ms"]["p50"]))
    print("\nModel                     WER    median ms   p90 ms   RTF")
    for r in ok:
        print(f"{r['model']:<24}{r['wer']:>6.1%}{r['ms']['p50']:>11.0f}{r['ms']['p90']:>9.0f}{r['rtf']:>7.2f}")
    write_result("stt", "bench", {"clips": len(clips), "audio_s": round(audio_s, 1), "prompt": prompt, "results": results})


if __name__ == "__main__":
    main()
