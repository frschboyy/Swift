"""Can a speaker check tell the owner's voice from other people's?

Usage (from the repo root):
  python spikes/stt/speaker_bench.py --others DIR [--enroll N]

Enrolls the owner from every 4th clip of the STT corpus (corpus.py) as the mean
of their WeSpeaker embeddings, then scores (cosine similarity) the rest:

  owner          the owner's held-out clips, clean
  owner+voices   the same clips with two other voices behind them at 10/5/0 dB
  other          one other speaker alone
  voices         two to four other speakers at once, nobody addressing Swift

DIR holds 16 kHz mono WAVs of people who are not the owner. With no real
recordings, Windows' TTS voices at several pitches and rates stand in for them,
which makes "other" easier to reject than real people would be.

Model: WeSpeaker ResNet34-LM (VoxCeleb, CC-BY-4.0), 26.5 MB, in
%LOCALAPPDATA%\\Swift\\models\\wespeaker-resnet34. Results go to spikes/stt/results/.
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
from bench import trim_silence  # noqa: E402
from corpus import CORPUS_DIR, SAMPLE_RATE, load_refs, read_wav  # noqa: E402
from noise_bench import mix, speech_rms  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"
THRESHOLDS = [0.2, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6]


def load_se():
    from onnx_asr.loader import Manager

    return Manager().create_se(None, models_dir() / "wespeaker-resnet34")


def unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-9)


def read(path: Path) -> np.ndarray:
    return trim_silence(read_wav(path).astype(np.float32) / 32768.0).astype(np.float64)


def voices(others: list[np.ndarray], n: int, length: int, rng: np.random.Generator) -> np.ndarray:
    """n other speakers talking at once, each at the same speech level."""
    out = np.zeros(length)
    for k in rng.choice(len(others), n, replace=False):
        src = others[k]
        start = int(rng.integers(0, max(1, len(src) // 2)))
        src = np.tile(np.roll(src, -start), int(np.ceil(length / len(src))))[:length]
        out += src / (speech_rms(others[k]) + 1e-9)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--others", type=Path, required=True)
    ap.add_argument("--enroll", type=int, default=0, help="enroll on only the first N enrollment clips")
    args = ap.parse_args()

    owner = [read(CORPUS_DIR / r["wav"]) for r in load_refs() if r.get("ref")]
    others = [read(p) for p in sorted(args.others.glob("*.wav"))]
    enroll_clips = owner[::4][: args.enroll or None]
    test = [c for i, c in enumerate(owner) if i % 4]
    se = load_se()
    emb = lambda a: unit(se.embedding(a.astype(np.float32)))  # noqa: E731

    t0 = time.perf_counter()
    profile = unit(np.mean([emb(c) for c in enroll_clips], axis=0))
    rng = np.random.default_rng(5)
    rows: list[dict] = []

    def score(kind: str, audio: np.ndarray, **extra) -> None:
        t = time.perf_counter()
        s = float(emb(audio) @ profile)
        rows.append({"kind": kind, "score": round(s, 3), "ms": int((time.perf_counter() - t) * 1000),
                     "audio_s": round(len(audio) / SAMPLE_RATE, 2), **extra})

    for c in test:
        score("owner", c)
        for snr in (10, 5, 0):
            score("owner+voices", mix(c, voices(others, 2, len(c), rng), snr), snr=snr)
    for o in others:
        score("other", o)
    for _ in range(60):
        n = int(rng.integers(2, 5))
        length = int(rng.uniform(1.5, 4.0) * SAMPLE_RATE)
        v = voices(others, n, length, rng)
        score("voices", (v / np.sqrt(np.mean(v**2)) * 10 ** (-30 / 20)).astype(np.float32), n=n)

    kinds = ["owner", "owner+voices", "other", "voices"]
    print(f"enrolled on {len(enroll_clips)} clips; {len(test)} owner test clips; {len(others)} other clips "
          f"({time.perf_counter() - t0:.0f}s)\n")
    for k in kinds:
        groups = [(k, None)] if k != "owner+voices" else [(k, s) for s in (10, 5, 0)]
        for kind, snr in groups:
            s = sorted(r["score"] for r in rows if r["kind"] == kind and (snr is None or r.get("snr") == snr))
            q = [s[int(p * (len(s) - 1))] for p in (0, 0.1, 0.5, 0.9, 1)]
            label = kind + (f" {snr} dB" if snr is not None else "")
            print(f"{label:20} n={len(s):3} min/p10/median/p90/max = {' / '.join(f'{x:.2f}' for x in q)}")
    print("\nthreshold | owner rejected | owner+voices rejected (10/5/0 dB) | other accepted | voices accepted")
    for t in THRESHOLDS:
        rate = lambda kind, below, snr=None: np.mean([  # noqa: E731
            (r["score"] < t) == below for r in rows if r["kind"] == kind and (snr is None or r.get("snr") == snr)
        ])
        ov = " / ".join(f"{rate('owner+voices', True, s):.2f}" for s in (10, 5, 0))
        print(f"   {t:.2f}   |      {rate('owner', True):.2f}      |        {ov}         |"
              f"      {rate('other', False):.2f}      |      {rate('voices', False):.2f}")
    ms = [r["ms"] for r in rows if r["kind"] == "owner"]
    print(f"\nembedding time on owner clips: median {int(np.median(ms))} ms")

    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"speaker-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"machine": machine_info(), "enroll": len(enroll_clips), "rows": rows}, indent=1),
                    encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
