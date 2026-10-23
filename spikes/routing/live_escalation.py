"""Live check of ADR-007 step 2 through Swift's own router and executor (costs about $0.05-0.10).

Usage: uv run python spikes/routing/live_escalation.py

1. A light question: should run on Haiku, no escalation.
2. A demanding change forced to start on Haiku: Haiku should ask for a
   stronger model. Every confirm card (file edits) is rejected, so nothing changes.
3. A standard question: starts on Sonnet.
Prints route, models, escalations, time and cost for each.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from swift.executors.claude_code import ClaudeCodeExecutor  # noqa: E402
from swift.routing import route  # noqa: E402

CASES = [
    ("What files are in src/swift/routing?", None),
    ("Refactor the demand estimate in src/swift/routing/demand.py into a class with one method per signal.", "light"),
    ("Why does the router send 'open my project' to Claude Code instead of handling it locally?", None),
]


async def main() -> None:
    ex = ClaudeCodeExecutor(cwd=str(REPO))
    ex.prepare()
    for text, force in CASES:
        await asyncio.sleep(6)  # let the next spare connect
        r = route(text)
        demand = force or r.demand
        t0 = time.perf_counter()
        run_id = await ex.start(r.text, demand=demand, override=r.override)
        steps = []
        async for e in ex.events(run_id):
            if e.type == "confirm":
                await ex.reply(e.request_id, False)
                steps.append(f"[rejected] {e.text}")
            else:
                steps.append(e.text)
        res = await ex.result(run_id)
        print(f"\n> {text}\n  route={r.route} demand={r.demand}{' (forced ' + force + ')' if force else ''}")
        print(f"  {res.status} in {time.perf_counter() - t0:.1f}s, cost ${res.meta.get('cost_usd')}, models {res.meta.get('models')}")
        for esc in res.meta.get("escalations", []):
            print(f"  escalated to {esc['to']} by {esc['by']} at {esc['t_ms']} ms: {esc['reason']}")
        print("  steps:", " | ".join(s[:70] for s in steps[:8]))
        print("  answer:", res.summary[:160])
    await ex.close()


asyncio.run(main())
