"""S2: Ollama prefill/decode throughput, cold vs warm vs prefix-cached, and RAM.

Usage:  uv run --group spikes python spikes/latency/llm_bench.py [--models ...] [--reps 3]

For each model and each prompt size (~500/1500/3000 tokens):
  cold          model unloaded first (keep_alive=0), then one request
  warm          model resident, a *different* prompt of the same size (full prefill)
  prefix_cached model resident, same long prefix, a short new suffix
Numbers come from Ollama's own counters (ns): load_duration,
prompt_eval_count/duration, eval_count/duration. num_ctx and keep_alive are set
explicitly (§3); think=False; temperature=0; num_predict=--decode.
RAM: Ollama runner private bytes (psutil) and /api/ps size while loaded.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _util import summarize, write_result  # noqa: E402

DEFAULT_MODELS = ["qwen3:1.7b", "qwen3.5:4b", "qwen3:8b"]
SIZES = [500, 1500, 3000]
NUM_CTX = 8192

WORDS = (
    "the project report meeting supervisor draft email calendar schedule results data analysis chapter "
    "figure table issue deadline review update weekly status pipeline test failure error fixed pending "
    "approved budget experiment sample method conclusion introduction literature model training "
    "evaluation accuracy latency memory server client request response file folder document version "
    "change commit branch release note summary outstanding action item owner priority risk blocker "
    "next step tuesday friday morning afternoon minutes agenda decision follow up thanks regards"
).split()

SYSTEM = (
    "You are the reasoning component of a local desktop assistant. Answer concisely. "
    "Summarize the outstanding issues in the document below as a short bullet list."
)


def filler(n_tokens: int, seed: int) -> str:
    # ~1.3 tokens per word for this vocabulary; actual counts are reported from Ollama.
    rng = random.Random(seed)
    words = [rng.choice(WORDS) for _ in range(int(n_tokens / 1.3))]
    sentences = [" ".join(words[i : i + 12]).capitalize() + "." for i in range(0, len(words), 12)]
    return " ".join(sentences)


def runner_private_mb() -> float:
    total = 0
    for p in psutil.process_iter(["name"]):
        name = (p.info["name"] or "").lower()
        if name.startswith("ollama") or "llama" in name:
            try:
                mi = p.memory_info()
                total += getattr(mi, "private", mi.rss)
            except psutil.Error:
                pass
    return round(total / 2**20, 1)


def call(client, model: str, prompt: str, decode: int, keep_alive: str | int = "10m") -> dict:
    r = client.generate(
        model=model,
        system=SYSTEM,
        prompt=prompt,
        think=False,
        keep_alive=keep_alive,
        options={"num_ctx": NUM_CTX, "temperature": 0, "num_predict": decode, "seed": 0},
    )
    ns = 1e9
    pe_n, pe_d = r.prompt_eval_count or 0, (r.prompt_eval_duration or 0) / ns
    ev_n, ev_d = r.eval_count or 0, (r.eval_duration or 0) / ns
    return {
        "load_s": round((r.load_duration or 0) / ns, 3),
        "prompt_tokens": pe_n,
        "prefill_s": round(pe_d, 3),
        "prefill_tok_s": round(pe_n / pe_d, 1) if pe_d else None,
        "decode_tokens": ev_n,
        "decode_s": round(ev_d, 3),
        "decode_tok_s": round(ev_n / ev_d, 2) if ev_d else None,
        "total_s": round((r.total_duration or 0) / ns, 3),
    }


def unload(client, model: str) -> None:
    client.generate(model=model, prompt="", keep_alive=0)


def agg(runs: list[dict]) -> dict:
    keys = ["load_s", "prompt_tokens", "prefill_s", "prefill_tok_s", "decode_tok_s", "total_s"]
    return {k: summarize([r[k] for r in runs if r.get(k) is not None]) for k in keys} | {"raw": runs}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--decode", type=int, default=128)
    args = ap.parse_args()

    import ollama

    client = ollama.Client(host="http://127.0.0.1:11434")
    out: dict[str, dict] = {}
    for model in args.models:
        print(f"== {model}")
        res: dict[str, dict] = {}
        for size in SIZES:
            cold, warm, cached = [], [], []
            for rep in range(args.reps):
                unload(client, model)
                cold.append(call(client, model, filler(size, seed=1000 + rep), args.decode))
                # Different content, same size: full prefill with the model resident.
                warm.append(call(client, model, filler(size, seed=2000 + rep), args.decode))
                # Same long prefix as the previous call plus a short new question.
                base = filler(size, seed=2000 + rep)
                cached.append(call(client, model, base + f"\n\nQuestion {rep}: which item is most urgent?", args.decode))
                print(
                    f"  {size}t rep{rep}: cold load {cold[-1]['load_s']}s prefill {cold[-1]['prefill_tok_s']} t/s | "
                    f"warm prefill {warm[-1]['prefill_tok_s']} t/s decode {warm[-1]['decode_tok_s']} t/s | "
                    f"cached prompt_tokens {cached[-1]['prompt_tokens']} total {cached[-1]['total_s']}s"
                )
            res[f"{size}"] = {"cold": agg(cold), "warm": agg(warm), "prefix_cached": agg(cached)}

        ps = client.ps()
        loaded = [m for m in ps.models if m.model == model or m.name == model]
        res["ram"] = {
            "ollama_private_mb_loaded": runner_private_mb(),
            "api_ps_size_mb": round(loaded[0].size / 2**20, 1) if loaded else None,
            "num_ctx": NUM_CTX,
        }
        unload(client, model)
        res["ram"]["ollama_private_mb_unloaded"] = runner_private_mb()
        out[model] = res

    write_result(
        "latency",
        "llm",
        {
            "reps": args.reps,
            "decode_tokens": args.decode,
            "num_ctx": NUM_CTX,
            "models": out,
            "method": "ollama generate, think=False, temperature=0; Ollama-reported durations",
        },
    )


if __name__ == "__main__":
    main()
