"""S2 diagnostic: does Ollama's thread count explain the slow LLM numbers?

Usage: uv run --group spikes python spikes/latency/thread_probe.py [--model qwen3:1.7b]

Same ~500-token prompt, warm model, num_thread in {default, 4, 8}, 2 reps each.
Also records system CPU% and available RAM before each run so contention is visible.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _util import write_result  # noqa: E402
from llm_bench import SYSTEM, filler  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3:1.7b")
    ap.add_argument("--reps", type=int, default=2)
    args = ap.parse_args()

    import ollama

    client = ollama.Client(host="http://127.0.0.1:11434")
    client.generate(model=args.model, prompt="", keep_alive="10m")
    rows = []
    for label, threads in [("default", None), ("4", 4), ("8", 8)]:
        for rep in range(args.reps):
            opts = {"num_ctx": 8192, "temperature": 0, "num_predict": 64, "seed": 0}
            if threads:
                opts["num_thread"] = threads
            cpu = psutil.cpu_percent(interval=1.0)
            avail = round(psutil.virtual_memory().available / 2**30, 1)
            r = client.generate(
                model=args.model, system=SYSTEM, prompt=filler(500, seed=50 + rep), think=False, keep_alive="10m", options=opts
            )
            pe = (r.prompt_eval_duration or 1) / 1e9
            ev = (r.eval_duration or 1) / 1e9
            row = {
                "num_thread": label, "rep": rep, "cpu_before_pct": cpu, "avail_ram_gb": avail,
                "prefill_tok_s": round((r.prompt_eval_count or 0) / pe, 1), "decode_tok_s": round((r.eval_count or 0) / ev, 2),
            }
            rows.append(row)
            print(row)
    top = sorted(psutil.process_iter(["name", "cpu_percent"]), key=lambda p: p.info["cpu_percent"] or 0, reverse=True)[:5]
    write_result("latency", "thread_probe", {"model": args.model, "rows": rows, "top_procs": [p.info for p in top]})


if __name__ == "__main__":
    main()
