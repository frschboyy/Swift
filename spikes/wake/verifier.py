"""Stage 2 that knows the owner's voice: a verifier behind an acoustic stage 1, scored out of fold.

This is what phone assistants do after the small always-on detector fires: a second model, trained on the
owner's own "Hey Swift"s, checks the stretch of audio the detector fired on. It's openWakeWord's
custom-verifier recipe (a logistic regression on the 16 openWakeWord embeddings ending at the detection),
generalised to any stage 1 that wake_bench scored.

- Positives: windows of the owner's positive clips ending at stage 1's detection (or, if it didn't fire,
  at the name's end from align.json), a frame either side.
- Negatives: every window of the owner's negative clips.
- Out of fold by day: a clip is only scored by a verifier that saw none of that day's clips. Clips with no
  date (recorded takes, corpus) are spread over the folds by id.

Prints wake_bench's rows for stage 1 alone and stage 1 + verifier at each verifier threshold. Nothing
leaves the PC.

  uv run --frozen --group spikes --with openwakeword==0.6.0 python spikes/wake/verifier.py --out <bench> \
      --labels <labels.json> --oww viola_hey_swift --threshold 0.5
"""

from __future__ import annotations

import argparse
import json
import sys
import zlib
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from train_head import WIN, embed, frame_of, windows
from wake_bench import detections, labelled, read_wav, summary


def fold_of(r: dict) -> str:
    if r.get("ts"):
        return datetime.fromtimestamp(r["ts"]).date().isoformat()
    return f"h{zlib.crc32(r['id'].encode()) % 4}"  # stable across runs, unlike hash()


def main() -> None:
    from openwakeword.utils import AudioFeatures
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--oww", nargs="*", default=[], help="stage 1: an oww/viola tag")
    ap.add_argument("--porcupine", nargs="*", default=[], help="stage 1: a porcupine tag")
    ap.add_argument("--threshold", type=float, default=0.5, help="stage 1 threshold (oww/viola)")
    ap.add_argument("--verify", type=float, nargs="*", default=[0.1, 0.3, 0.5, 0.7, 0.9])
    a = ap.parse_args()

    rows = labelled(a.out, a.labels)
    align = json.loads((a.out / "align.json").read_text())
    feats = AudioFeatures(inference_framework="onnx")
    for r in rows:
        r["emb"], r["fold"] = windows(embed(feats, read_wav(a.out / "clips" / f"{r['id']}.wav"))), fold_of(r)

    def window_at(r: dict, t: float) -> int:
        """The window (index into r["emb"]) that ends just after t seconds into the clip."""
        return min(max(frame_of(t) - (WIN - 1), 0), len(r["emb"]) - 1)

    for name, hit in detections(a.out, rows, a.oww, [a.threshold], 1, a.porcupine):
        prob: dict[str, float] = {}
        for f in sorted({r["fold"] for r in rows}):
            xs, ys = [], []
            for r in rows:
                if r["fold"] == f or not len(r["emb"]):
                    continue
                if r["label"] == "neg":
                    xs.append(r["emb"]), ys.append(np.zeros(len(r["emb"])))
                elif (t := hit[r["id"]] if hit[r["id"]] is not None else align.get(r["id"])) is not None:
                    k = window_at(r, t)
                    keep = [j for j in (k - 1, k, k + 1) if 0 <= j < len(r["emb"])]
                    xs.append(r["emb"][keep]), ys.append(np.ones(len(keep)))
            clf = make_pipeline(StandardScaler(), LogisticRegression(C=0.001, class_weight="balanced", max_iter=3000))
            clf.fit(np.concatenate(xs), np.concatenate(ys))
            for r in rows:
                if r["fold"] == f and hit[r["id"]] is not None and len(r["emb"]):
                    k = window_at(r, hit[r["id"]])
                    # The detection and the 0.3 s after it, as stage 2 would see them live.
                    prob[r["id"]] = float(clf.predict_proba(r["emb"][k:k + 4])[:, 1].max())
        fired = {r["id"]: hit[r["id"]] is not None for r in rows}
        print(summary(rows, fired, name))
        for v in a.verify:
            print(summary(rows, {r["id"]: prob.get(r["id"], 0.0) >= v for r in rows}, f"  + own-voice verifier {v}"))


if __name__ == "__main__":
    main()
