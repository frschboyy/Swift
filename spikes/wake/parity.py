"""ADR-021 step 1: does Swift's own scorer (swift.wake_acoustic) give ViolaWake's scores?

Streams bench clips through HeySwiftScorer the way `wake_bench.py viola` streamed them through ViolaWake
(1 s of silence first, 0.5 s after, 20 ms blocks), then compares with that run's scores. The bench kept the
max of four 20 ms frames per 80 ms. Since a frame's score is the last chunk's, that's max(chunk k-1, chunk
k) for us. Passes if every score is within --tol, and every clip fires or not alike at 0.5.

  uv run --frozen --group spikes python spikes/wake/parity.py --out <bench> --tag viola_hey_swift \
      --models %LOCALAPPDATA%\\Swift\\corpus\\wake\\models --head hey_swift_viola.onnx
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from wake_bench import RATE, load_jsonl, read_wav

from swift.wake_acoustic import HeySwiftScorer


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tag", default="viola_hey_swift")
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--head", default="hey_swift_viola.onnx")
    ap.add_argument("--n", type=int, default=300, help="clips to compare (0 = all)")
    ap.add_argument("--tol", type=float, default=0.01)
    a = ap.parse_args()

    theirs = {r["id"]: r["scores"] for r in load_jsonl(a.out / f"oww_{a.tag}.jsonl")}
    ids = sorted(theirs)
    random.Random(0).shuffle(ids)
    ids = ids if a.n == 0 else ids[: a.n]
    scorer = HeySwiftScorer(a.models, head=a.head)
    worst, flips = 0.0, []
    for i, cid in enumerate(ids, 1):
        scorer.reset()
        audio = np.concatenate([np.zeros(RATE, np.int16), read_wav(a.out / "clips" / f"{cid}.wav"),
                                np.zeros(RATE // 2, np.int16)])
        ours: list[float] = []
        for j in range(0, len(audio) - 320 + 1, 320):
            ours += scorer.push(audio[j:j + 320])
        ours_80 = [max(ours[k - 1] if k else 0.0, ours[k]) for k in range(len(ours))]
        ref = theirs[cid]
        n = min(len(ref), len(ours_80))
        diff = float(np.max(np.abs(np.array(ref[:n]) - np.array(ours_80[:n])))) if n else 0.0
        worst = max(worst, diff)
        if (max(ref[:n], default=0) >= 0.5) != (max(ours_80[:n], default=0) >= 0.5):
            flips.append(cid)
        if len(ref) != len(ours_80) and abs(len(ref) - len(ours_80)) > 1:
            print(f"length differs on {cid}: {len(ref)} vs {len(ours_80)}")
        print(f"\r{i}/{len(ids)} worst difference so far {worst:.5f}", end="", flush=True)
    print(f"\n{len(ids)} clips: worst score difference {worst:.5f} (tolerance {a.tol}),"
          f" {len(flips)} clips fire differently at 0.5")
    if worst > a.tol or flips:
        sys.exit(f"PARITY FAILED: {flips[:5]}")
    print("parity ok")


if __name__ == "__main__":
    main()
