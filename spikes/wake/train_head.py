"""A "hey swift" head on openWakeWord's fixed speech embeddings, trained and scored on this PC only.

openWakeWord ships no "hey swift" model. Its own recipe trains one from thousands of synthetic TTS clips
plus large public negative sets (tens of GB). This spike tries the small version that fits here: a
logistic regression on 16 consecutive openWakeWord embeddings (~2 s of audio), with positives from the
owner's own clips (aligned with Parakeet's token times) and/or a local Piper voice. Scores are out of fold,
by day: a clip is only ever scored by a model that never saw that day's clips.

Writes <out>/oww_<tag>.jsonl in wake_bench's format, so `wake_bench.py report --oww <tag>` compares it.

  uv run --frozen --group spikes --with openwakeword==0.6.0 python spikes/wake/train_head.py --out <scratch> \
      --labels <labels.json> --positives owner+tts --tag head_both
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from wake_bench import RATE, SWIFT, labelled, read_wav, save_jsonl

WIN = 16  # embeddings per window, as openWakeWord's own models use
PAD = RATE  # 1 s of silence in front, as when streaming
TTS_POS = ["Hey Swift.", "Hey Swift", "Hey, Swift!", "Hey Swift?", "Hey swift,"]
TTS_NEG = ["Hey.", "Swift.", "Hey Steve.", "Hey shift.", "They sift.", "Hey sweetie.", "A swift reply.",
           "Hey Siri.", "Hello there.", "Pay with this.", "He is fit.", "Hey, what's up?", "Okay, sure."]


def hiss(n: int) -> np.ndarray:
    # Room-level noise, not digital zeros: a model can learn "zeros, then speech" as the phrase.
    return np.random.default_rng(n).normal(0, 8, n).astype(np.int16)


def embed(feats, audio: np.ndarray) -> np.ndarray:
    audio = np.concatenate([hiss(PAD), audio, hiss(RATE // 2)])
    return feats._get_embeddings(audio)  # (N, 96); embedding e ends 0.08 e + 0.76 s into the padded audio


def windows(emb: np.ndarray) -> np.ndarray:
    if len(emb) < WIN:
        return np.zeros((0, WIN * emb.shape[1]), np.float32)
    return np.stack([emb[e - WIN + 1:e + 1].reshape(-1) for e in range(WIN - 1, len(emb))])


def frame_of(t: float) -> int:
    """The embedding that ends just after time t (seconds from clip start)."""
    return int(np.ceil((t + PAD / RATE - 0.76) / 0.08))


def swift_end(asr, audio: np.ndarray) -> float | None:
    """When the word heard as the name ends: the next word's first token, from Parakeet's token times."""
    r = asr.recognize(audio.astype(np.float32) / 32768.0, sample_rate=RATE)
    if not r.tokens or not r.timestamps:
        return None
    starts, words = [], []
    for tok, ts in zip(r.tokens, r.timestamps, strict=False):
        if tok.startswith((" ", "▁")) or not words:
            words.append(tok.strip(" ▁").lower())
            starts.append(ts)
        else:
            words[-1] += tok.lower()
    near = [i for i, w in enumerate(words[:4]) if SequenceMatcher(None, w.strip(".,!?'"), "swift").ratio() >= 0.5]
    i = near[0] if near else min(1, len(words) - 1)
    return starts[i + 1] if i + 1 < len(starts) else r.timestamps[-1] + 0.3


def tts_clips(n_each: int) -> tuple[list[np.ndarray], list[np.ndarray]]:
    from piper import PiperVoice, SynthesisConfig
    from scipy.signal import resample_poly

    voice = PiperVoice.load(str(SWIFT / "models" / "piper" / "en_US-lessac-medium" / "en_US-lessac-medium.onnx"))
    rng = np.random.default_rng(0)

    def say(text: str) -> np.ndarray:
        cfg = SynthesisConfig(length_scale=rng.uniform(0.8, 1.3), noise_scale=rng.uniform(0.4, 1.0),
                              noise_w_scale=rng.uniform(0.5, 1.0), volume=rng.uniform(0.3, 1.0))
        pcm = np.concatenate([c.audio_int16_array for c in voice.synthesize(text, syn_config=cfg)])
        audio = resample_poly(pcm.astype(np.float32), RATE, voice.config.sample_rate)
        noise = rng.normal(0, rng.uniform(20, 300), len(audio))  # a little room hiss
        return np.clip(audio + noise, -32768, 32767).astype(np.int16)

    pos = [say(TTS_POS[i % len(TTS_POS)]) for i in range(n_each)]
    neg = [say(TTS_NEG[i % len(TTS_NEG)]) for i in range(n_each)]
    return pos, neg


def main() -> None:
    from openwakeword.utils import AudioFeatures
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--positives", choices=["owner", "tts", "owner+tts"], default="owner+tts")
    ap.add_argument("--tts", type=int, default=300, help="synthetic clips of each kind")
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()

    rows = labelled(a.out, a.labels)
    feats = AudioFeatures(inference_framework="onnx")
    align_path = a.out / "align.json"
    align = json.loads(align_path.read_text()) if align_path.exists() else {}
    if missing := [r for r in rows if r["label"] == "pos" and r["id"] not in align]:
        import onnx_asr

        asr = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v2", SWIFT / "models" / "parakeet-tdt-0.6b-v2",
                                  quantization="int8").with_timestamps()
        for r in missing:
            align[r["id"]] = swift_end(asr, read_wav(a.out / "clips" / f"{r['id']}.wav"))
        align_path.write_text(json.dumps(align))

    for r in rows:
        r["emb"] = embed(feats, read_wav(a.out / "clips" / f"{r['id']}.wav"))
        # Fold = the day it was recorded; corpus clips have no time, so they spread over the folds by id.
        r["fold"] = datetime.fromtimestamp(r["ts"]).date().isoformat() if r.get("ts") else f"h{hash(r['id']) % 4}"

    def examples(r: dict) -> tuple[np.ndarray, np.ndarray]:
        w = windows(r["emb"])
        if r["label"] == "neg":
            return w, np.zeros(len(w))
        end = align.get(r["id"])
        if end is None:
            return w[:0], np.zeros(0)
        e = frame_of(end) - (WIN - 1)
        keep = [k for k in (e, e + 1, e + 2) if 0 <= k < len(w)]
        # The same clip before the phrase is done, and well after it, is not the moment to fire.
        other = [k for k in range(len(w)) if k < e - 3 or k > e + 10]
        return w[keep + other], np.r_[np.ones(len(keep)), np.zeros(len(other))]

    tts_x, tts_y = [], []
    if "tts" in a.positives:
        pos, neg = tts_clips(a.tts)
        for clip, y in [(c, 1) for c in pos] + [(c, 0) for c in neg]:
            w = windows(embed(feats, clip))
            if y:  # the synthetic phrase ends where its audio ends (plus PAD)
                e = frame_of(len(clip) / RATE) - (WIN - 1)
                w = w[[k for k in (e - 1, e, e + 1) if 0 <= k < len(w)]]
            tts_x.append(w)
            tts_y.append(np.full(len(w), y))

    out_rows = []
    folds = sorted({r["fold"] for r in rows})
    for f in folds:
        xs, ys = list(tts_x), list(tts_y)
        for r in rows:
            if r["fold"] == f or (r["label"] == "pos" and "owner" not in a.positives):
                continue
            x, y = examples(r)
            xs.append(x), ys.append(y)
        clf = make_pipeline(StandardScaler(), LogisticRegression(C=0.05, class_weight="balanced", max_iter=2000))
        clf.fit(np.concatenate(xs), np.concatenate(ys))
        for r in rows:
            if r["fold"] == f:
                p = clf.predict_proba(windows(r["emb"]))[:, 1]
                # Score k belongs to embedding k + WIN - 1, ending at 0.08 (k + WIN - 1) + 0.76 - PAD s.
                out_rows.append({"id": r["id"], "scores": [round(float(s), 4) for s in p]})
        print(f"fold {f}: trained on {sum(len(y) for y in ys)} windows, scored {sum(r['fold'] == f for r in rows)} clips")
    offset = 0.08 * (WIN - 1) + 0.76 - PAD / RATE
    save_jsonl(a.out / f"oww_{a.tag}.jsonl", [{**r, "offset": round(offset, 2)} for r in out_rows])


if __name__ == "__main__":
    main()
