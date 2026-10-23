"""Where does Claude Code's per-request startup time go? (MVP latency diagnostic)

Usage: uv run python spikes/latency/claude_startup.py [--reps 3]

Uses Swift's own ClaudeCodeExecutor options (read-only tools, no settings, no
session persistence) and a tiny prompt. For each rep it measures:
  - cold:   query() from scratch, as Swift does today: spawn -> init -> first text -> result
  - warm:   ClaudeSDKClient connected ahead of time; time from sending the prompt
            -> init -> first text -> result. connect_s is the hidden part.
Each request costs about $0.01-0.05.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "spikes"))

from _util import write_result  # noqa: E402

PROMPT = "Reply with just the word: hi"


def options():
    from swift.executors.claude_code import ClaudeCodeExecutor, _Run

    ex = ClaudeCodeExecutor(cwd=str(REPO))
    return ex.options(_Run(), "cc-bench")


async def cold() -> dict:
    from claude_agent_sdk import query

    t0 = time.perf_counter()
    marks: dict[str, float] = {}
    async for m in query(prompt=PROMPT, options=options()):
        kind = type(m).__name__
        if kind == "SystemMessage" and getattr(m, "subtype", "") == "init":
            marks.setdefault("init_s", time.perf_counter() - t0)
        elif kind == "AssistantMessage":
            marks.setdefault("first_text_s", time.perf_counter() - t0)
        elif kind == "ResultMessage":
            marks["result_s"] = time.perf_counter() - t0
            marks["api_ms"] = getattr(m, "duration_api_ms", None)
    return marks


async def warm() -> dict:
    from claude_agent_sdk import ClaudeSDKClient

    t0 = time.perf_counter()
    client = ClaudeSDKClient(options())
    await client.connect()
    connect_s = time.perf_counter() - t0
    await asyncio.sleep(1.0)  # the gap between "ready" and the user's request
    t1 = time.perf_counter()
    marks: dict[str, float] = {"connect_s": connect_s}
    await client.query(PROMPT)
    async for m in client.receive_response():
        kind = type(m).__name__
        if kind == "SystemMessage" and getattr(m, "subtype", "") == "init":
            marks.setdefault("init_s", time.perf_counter() - t1)
        elif kind == "AssistantMessage":
            marks.setdefault("first_text_s", time.perf_counter() - t1)
        elif kind == "ResultMessage":
            marks["result_s"] = time.perf_counter() - t1
            marks["api_ms"] = getattr(m, "duration_api_ms", None)
    await client.disconnect()
    return marks


def show(label: str, rows: list[dict]) -> None:
    keys = [k for k in ("connect_s", "init_s", "first_text_s", "result_s", "api_ms") if any(k in r for r in rows)]
    parts = []
    for k in keys:
        vals = [r[k] for r in rows if r.get(k) is not None]
        parts.append(f"{k}={statistics.median(vals):.2f}" if vals else f"{k}=-")
    print(f"{label:<6} median of {len(rows)}: " + "  ".join(parts))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()
    import claude_agent_sdk  # noqa: F401 - import cost is not what we're measuring

    res = {"cold": [], "warm": []}
    for i in range(args.reps):
        res["cold"].append(await cold())
        res["warm"].append(await warm())
        print(f"rep {i + 1}: cold {res['cold'][-1]}\n       warm {res['warm'][-1]}", flush=True)
    show("cold", res["cold"])
    show("warm", res["warm"])
    write_result("latency", "claude_startup", res)


if __name__ == "__main__":
    asyncio.run(main())
