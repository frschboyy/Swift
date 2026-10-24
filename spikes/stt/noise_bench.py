"""How Parakeet copes with noise, and whether denoising or confidence helps.

Usage (from the repo root):
  uv run --group sttbench python spikes/stt/noise_bench.py [--limit N]

Takes the clean clips from corpus.py, mixes in noise at several SNRs and
transcribes each mix, raw and after a spectral (Wiener) denoiser. It records the
WER and Parakeet's token log-probabilities, to see whether confidence separates
right transcripts from wrong ones. It also feeds noise with no speech at all,
to see what the model invents and how sure it is.

Noise types (synthetic, no downloads): white, pink, mains hum, static
(crackle bursts over hiss) and babble (four other clips from the corpus summed).
SNR is measured against the speech blocks of the clean clip.
Results go to spikes/stt/results/ (gitignored).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _util import machine_info, models_dir  # noqa: E402
from bench import normalize, trim_silence, wer  # noqa: E402
from corpus import CORPUS_DIR, SAMPLE_RATE, load_refs, read_wav  # noqa: E402

SNRS = [None, 10, 5, 0]
NOISES = ["white", "pink", "hum", "static", "babble"]
RESULTS = Path(__file__).resolve().parent / "results"


def speech_rms(x: np.ndarray) -> float:
    n = len(x) // 512
    blocks = x[: n * 512].reshape(n, 512)
    rms = np.sqrt(np.mean(blocks**2, axis=1))
    loud = rms[20 * np.log10(np.maximum(rms, 1e-9)) >= -45]
    return float(np.sqrt(np.mean(loud**2))) if len(loud) else float(np.sqrt(np.mean(x**2)))


def make_noise(kind: str, n: int, rng: np.random.Generator, others: list[np.ndarray]) -> np.ndarray:
    if kind == "white":
        return rng.standard_normal(n)
    if kind == "pink":
        spec = np.fft.rfft(rng.standard_normal(n))
        f = np.arange(len(spec))
        spec[1:] /= np.sqrt(f[1:])
        return np.fft.irfft(spec, n)
    if kind == "hum":
        t = np.arange(n) / SAMPLE_RATE
        return sum(np.sin(2 * np.pi * 60 * k * t) / k for k in (1, 2, 3, 5, 7)) + 0.05 * rng.standard_normal(n)
    if kind == "static":
        hiss = 0.3 * rng.standard_normal(n)
        crackle = np.zeros(n)
        for _ in range(int(n / SAMPLE_RATE * 40)):  # ~40 bursts a second
            i = int(rng.integers(0, n - 80))
            crackle[i : i + 80] += rng.standard_normal(80) * rng.uniform(1, 6)
        return hiss + crackle
    if kind == "babble":
        out = np.zeros(n)
        for o in rng.choice(len(others), 4, replace=len(others) < 4):
            src = np.tile(others[o], int(np.ceil(n / len(others[o]))))[:n]
            out += src / (speech_rms(others[o]) + 1e-9)
        return out
    raise ValueError(kind)


def mix(clean: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    noise = noise * speech_rms(clean) / (np.sqrt(np.mean(noise**2)) + 1e-12) / 10 ** (snr_db / 20)
    out = clean + noise
    peak = np.max(np.abs(out))
    return (out / peak * 0.99 if peak > 0.99 else out).astype(np.float32)


def wiener(x: np.ndarray, floor: float = 0.15) -> np.ndarray:
    """Spectral Wiener filter, noise PSD from the quietest 15% of frames per bin."""
    from scipy.signal import istft, stft

    _, _, z = stft(x, SAMPLE_RATE, nperseg=512, noverlap=384)
    power = np.abs(z) ** 2
    noise = np.percentile(power, 15, axis=1, keepdims=True)
    snr_post = np.maximum(power / (noise + 1e-12) - 1, 0)
    # Smooth the a-priori SNR over time (decision-directed, alpha 0.98) to avoid musical noise.
    snr_prio = np.empty_like(snr_post)
    prev = snr_post[:, 0]
    for t in range(power.shape[1]):
        prev = 0.98 * prev + 0.02 * snr_post[:, t]
        snr_prio[:, t] = np.maximum(prev, snr_post[:, t] * 0.5)
    gain = np.maximum(snr_prio / (1 + snr_prio), floor)
    _, y = istft(z * gain, SAMPLE_RATE, nperseg=512, noverlap=384)
    return y[: len(x)].astype(np.float32)


def load_model():
    import os

    os.environ["HF_HUB_OFFLINE"] = "1"
    import onnx_asr
    import onnxruntime

    opts = onnxruntime.SessionOptions()
    opts.intra_op_num_threads = 4
    opts.inter_op_num_threads = 1
    return onnx_asr.load_model(
        "nemo-parakeet-tdt-0.6b-v2", models_dir() / "parakeet-tdt-0.6b-v2", quantization="int8", sess_options=opts
    ).with_timestamps()


def word_probs(res) -> list[float]:
    """Probability of each word: the least likely of its tokens."""
    words: list[float] = []
    for tok, lp in zip(res.tokens or [], res.logprobs or []):
        if tok.startswith((" ", "▁")) or not words:
            words.append(lp)
        else:
            words[-1] = min(words[-1], lp)
    return [float(np.exp(w)) for w in words]


def run_one(model, audio: np.ndarray) -> dict:
    res = model.recognize(trim_silence(audio), sample_rate=SAMPLE_RATE)
    probs = word_probs(res)
    return {
        "hyp": res.text.strip(),
        "min_p": round(min(probs), 3) if probs else None,
        "mean_lp": round(float(np.mean(res.logprobs)), 3) if res.logprobs else None,
        "low_frac": round(sum(p < 0.5 for p in probs) / len(probs), 3) if probs else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = [r for r in load_refs() if r.get("ref")]
    if args.limit:
        rows = rows[: args.limit]
    clips = [read_wav(CORPUS_DIR / r["wav"]).astype(np.float64) / 32768.0 for r in rows]
    refs = [normalize(r["ref"]) for r in rows]
    model = load_model()
    run_one(model, clips[0].astype(np.float32))  # warm-up

    out: list[dict] = []
    t0 = time.perf_counter()
    for noise_kind in NOISES:
        for snr in SNRS:
            if snr is None and noise_kind != NOISES[0]:
                continue
            for proc in ("raw", "wiener"):
                rng = np.random.default_rng(7)
                for i, clean in enumerate(clips):
                    others = [c for j, c in enumerate(clips) if j != i]
                    audio = clean.astype(np.float32) if snr is None else mix(
                        clean, make_noise(noise_kind, len(clean), rng, others), snr
                    )
                    if proc == "wiener":
                        audio = wiener(audio)
                    r = run_one(model, audio)
                    r.update(noise="clean" if snr is None else noise_kind, snr=snr, proc=proc, id=rows[i]["id"],
                             ref=refs[i], wer=round(wer([refs[i]], [normalize(r["hyp"])]), 3))
                    out.append(r)
                cell = [o for o in out if o["noise"] == ("clean" if snr is None else noise_kind)
                        and o["snr"] == snr and o["proc"] == proc]
                w = wer([o["ref"] for o in cell], [normalize(o["hyp"]) for o in cell])
                print(f"{cell[0]['noise']:7} snr={str(snr):4} {proc:6} WER={w:.3f}  ({time.perf_counter() - t0:.0f}s)",
                      flush=True)

    # Noise with no speech: does the model invent words, and how sure is it?
    rng = np.random.default_rng(11)
    for noise_kind in NOISES:
        for k in range(10):
            n = int(2.5 * SAMPLE_RATE)
            noise = make_noise(noise_kind, n, rng, clips)
            noise = (noise / np.sqrt(np.mean(noise**2)) * 10 ** (-35 / 20)).astype(np.float32)  # -35 dBFS
            r = run_one(model, noise)
            r.update(noise=noise_kind, snr="noise_only", proc="raw", id=f"noise-{k}", ref="", wer=None)
            out.append(r)
        invented = [o for o in out if o["snr"] == "noise_only" and o["noise"] == noise_kind and o["hyp"]]
        print(f"noise only {noise_kind:7}: text on {len(invented)}/10 "
              f"{[(o['hyp'], o['min_p']) for o in invented][:4]}", flush=True)

    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"noise-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"machine": machine_info(), "rows": out}, indent=1), encoding="utf-8")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
