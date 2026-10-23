"""Can a running Claude Code request move to a stronger model? (ADR-007 escalation check)

Usage: uv run python spikes/latency/model_switch.py

Starts a pre-connected ClaudeSDKClient on Haiku with an in-process tool,
request_stronger_model. The prompt asks Claude to call it. The tool handler
calls client.set_model(Sonnet) and returns; the script then reports which
model wrote each assistant message, to see whether the switch takes effect
within the same request. Costs about $0.01.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

START, STRONGER = "claude-haiku-5-5", "claude-sonnet-5-5"


async def main() -> None:
    from claude_agent_sdk import ClaudeSDKClient, create_sdk_mcp_server, tool

    from swift.executors.claude_code import ClaudeCodeExecutor, _Run

    holder: dict = {}
    calls: list[tuple[float, str]] = []

    @tool("request_stronger_model", "Ask Swift to continue this request on a stronger model.", {"reason": str})
    async def request_stronger_model(args: dict) -> dict:
        calls.append((time.perf_counter(), args.get("reason", "")))
        await holder["client"].set_model(STRONGER)
        return {"content": [{"type": "text", "text": f"Switched to {STRONGER}. Continue."}]}

    options = ClaudeCodeExecutor(cwd=str(REPO)).options(_Run(), "cc-switch")
    options.mcp_servers = {"swift": create_sdk_mcp_server("swift", tools=[request_stronger_model])}
    options.allowed_tools = [*options.allowed_tools, "mcp__swift__request_stronger_model"]
    options.tools = [*options.tools, "mcp__swift__request_stronger_model"]
    options.model = START

    client = ClaudeSDKClient(options)
    holder["client"] = client
    await client.connect()
    t0 = time.perf_counter()
    await client.query(
        "This is a test of model switching. First call the request_stronger_model tool with reason 'test'. "
        "After it returns, reply with one sentence naming which model you are."
    )
    async for m in client.receive_response():
        kind = type(m).__name__
        if kind == "AssistantMessage":
            texts = [getattr(b, "text", None) or type(b).__name__ for b in m.content]
            print(f"{time.perf_counter() - t0:5.2f}s assistant model={m.model}: {texts}")
        elif kind == "ResultMessage":
            print(f"{time.perf_counter() - t0:5.2f}s result: cost={m.total_cost_usd} usage_models={list((getattr(m, 'model_usage', None) or {}).keys())}")
    print("tool calls:", [(round(t - t0, 2), r) for t, r in calls])

    # Second request on the same client: does the switch persist?
    await client.query("Reply with just the word: ok")
    async for m in client.receive_response():
        if type(m).__name__ == "AssistantMessage":
            print("next request model:", m.model)
    await client.disconnect()


asyncio.run(main())
