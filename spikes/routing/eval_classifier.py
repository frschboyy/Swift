"""Score the local demand classifier (ADR-007 §4) and measure its cost on this machine.

Usage (needs the bge-small model, see README):
  uv run python spikes/routing/eval_classifier.py                 # test split: rules+keywords vs rules+keywords+classifier
  uv run python spikes/routing/eval_classifier.py --fp32           # the fp32 model instead of int8
  uv run python spikes/routing/eval_classifier.py --write-examples # regenerate src/swift/routing/examples.jsonl

The classifier learns from the train split only (src/swift/routing/examples.jsonl,
a copy of it); this script scores the test split. It also reports load time,
per-request latency and the process memory the model adds.
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "spikes" / "routing"))

import eval_routes  # noqa: E402
from swift.config.paths import app_paths  # noqa: E402
from swift.routing import rules  # noqa: E402
from swift.routing.classifier import BASE_EXAMPLES, MODEL_NAME, ClassifierEstimate  # noqa: E402


def write_examples() -> None:
    rows = [r for r in eval_routes.load("train")]
    lines = [json.dumps({"text": r["text"], "route": r["route"], "demand": r["demand"]}, ensure_ascii=False) for r in rows]
    BASE_EXAMPLES.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} examples to {BASE_EXAMPLES}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fp32", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.7)
    ap.add_argument("--split", choices=["test", "train", "all"], default="test")
    ap.add_argument("--write-examples", action="store_true")
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()
    if args.write_examples:
        write_examples()
        return

    rows = eval_routes.load(args.split)
    adapt = lambda r: (r.route, r.demand)  # noqa: E731
    eval_routes.report("rules + keywords (classifier off)", eval_routes.score(lambda t: adapt(rules.route(t)), rows), args.show)

    proc = psutil.Process()
    before = proc.memory_info().rss
    estimate = ClassifierEstimate(app_paths().models_dir / MODEL_NAME, [BASE_EXAMPLES], threshold=args.threshold,
                                  quantized=not args.fp32)
    started = time.perf_counter()
    estimate.load()
    load_s = time.perf_counter() - started
    if estimate.classifier is None:
        raise SystemExit(f"classifier unavailable: {estimate.error}")
    router = functools.partial(rules.route, demand_fn=estimate)
    name = f"rules + keywords + classifier ({'fp32' if args.fp32 else 'int8'}, threshold {args.threshold})"
    eval_routes.report(name, eval_routes.score(lambda t: adapt(router(t)), rows), args.show)

    texts = [r["text"] for r in rows] * 3
    times = []
    for t in texts:
        t0 = time.perf_counter()
        estimate.classifier.predict(t)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    print(f"\n   load {load_s:.1f} s ({len(estimate.classifier.examples)} examples)   per request: "
          f"median {times[len(times) // 2]:.1f} ms, p95 {times[int(len(times) * 0.95)]:.1f} ms"
          f"   memory added {(proc.memory_info().rss - before) / 2**20:.0f} MB")


if __name__ == "__main__":
    main()
