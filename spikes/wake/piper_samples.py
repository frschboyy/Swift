"""Synthetic speech for wake-word training, made on this PC with Piper's 904-speaker LibriTTS voice.

Two uses:
- openWakeWord's train.py imports `generate_samples` from `piper_sample_generator_path`.
  Its own generator (rhasspy/piper-sample-generator) is Linux-only; this is the same call on piper-tts,
  so point that path at the piper_sample_generator folder next to this file.
- `python piper_samples.py speech|babble --out DIR --n N` makes negatives: ordinary sentences in random
  voices, and office babble (3 to 5 voices talking over each other), for training and augmentation.

Needs piper-tts and the voice files (en_US-libritts_r-medium.onnx and .onnx.json) in $PIPER_VOICE_DIR.
Nothing leaves the PC.
"""

from __future__ import annotations

import argparse
import os
import random
import uuid
import wave
from pathlib import Path

import numpy as np

RATE = 16_000
VOICE = Path(os.environ.get("PIPER_VOICE_DIR", ".")) / "en_US-libritts_r-medium.onnx"
_voice = None


def voice():
    global _voice
    if _voice is None:
        from piper import PiperVoice

        _voice = PiperVoice.load(str(VOICE))
    return _voice


def say(text: str, speaker: int, length: float, noise: float, noise_w: float) -> np.ndarray:
    from piper import SynthesisConfig
    from scipy.signal import resample_poly

    v = voice()
    cfg = SynthesisConfig(speaker_id=speaker, length_scale=length, noise_scale=noise, noise_w_scale=noise_w)
    pcm = np.concatenate([c.audio_int16_array for c in v.synthesize(text, syn_config=cfg)])
    return np.clip(resample_poly(pcm.astype(np.float32), RATE, v.config.sample_rate), -32768, 32767).astype(np.int16)


def write(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(audio.tobytes())


def generate_samples(text, max_samples, output_dir, length_scales=(0.75, 1.0, 1.25), noise_scales=(0.667,),
                     noise_scale_ws=(0.8,), file_names=None, **_ignored) -> None:
    """openWakeWord's call: `max_samples` clips of `text` (a phrase or a list), random speakers and scales."""
    texts = [text] if isinstance(text, str) else list(text)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    n_speakers = voice().config.num_speakers
    for i in range(int(max_samples)):
        name = file_names[i] if file_names and i < len(file_names) else uuid.uuid4().hex + ".wav"
        audio = say(random.choice(texts), random.randrange(n_speakers),
                    random.choice(length_scales) * random.uniform(0.9, 1.1),
                    random.choice(noise_scales), random.choice(noise_scale_ws))
        write(out / name, audio)
        if i % 100 == 0:
            print(f"\r{out.name}: {i}/{max_samples}", end="", flush=True)
    print()


def sentences(rng: random.Random, n: int) -> list[str]:
    """Word strings from CMUdict's common words: varied speech sounds, not meaning. Never the name."""
    import pronouncing

    pronouncing.init_cmu()
    words = [w for w in pronouncing.lookup if w.isalpha() and 2 <= len(w) <= 9 and "wift" not in w]
    words = rng.sample(words, 20_000)
    return [" ".join(rng.choices(words, k=rng.randint(4, 14))) + rng.choice([".", "?", "!", ","]) for _ in range(n)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["speech", "babble"])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n", type=int, required=True, help="clips to write")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    random.seed(a.seed)
    a.out.mkdir(parents=True, exist_ok=True)
    n_speakers = voice().config.num_speakers
    for i, text in enumerate(sentences(rng, a.n * (4 if a.kind == "babble" else 1))):
        if i >= a.n:
            break
        if a.kind == "speech":
            audio = say(text, rng.randrange(n_speakers), rng.uniform(0.8, 1.3), 0.667, 0.8)
        else:  # several voices at different levels, offset in time: an office in the background
            parts = [say(t, rng.randrange(n_speakers), rng.uniform(0.8, 1.3), 0.667, 0.8).astype(np.float32)
                     * rng.uniform(0.2, 1.0) for t in sentences(rng, rng.randint(3, 5))]
            n = max(len(p) for p in parts) + RATE
            mix = np.zeros(n, np.float32)
            for p in parts:
                s = rng.randrange(0, n - len(p) + 1)
                mix[s:s + len(p)] += p
            audio = np.clip(mix * (8000 / (np.abs(mix).max() + 1)), -32768, 32767).astype(np.int16)
        write(a.out / f"{a.kind}_{a.seed}_{i:05d}.wav", audio)
        if i % 50 == 0:
            print(f"\r{a.kind}: {i}/{a.n}", end="", flush=True)
    print()


if __name__ == "__main__":
    main()
