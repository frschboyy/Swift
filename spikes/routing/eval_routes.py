"""Score a router on the route and demand eval set (ADR-007 §8; labels: eval/routes.md).

Usage:
  uv run python spikes/routing/eval_routes.py                       # baselines, test split
  uv run python spikes/routing/eval_routes.py --split all
  uv run python spikes/routing/eval_routes.py --router mymodule:route_fn

A router is a function text -> (route, demand), where demand is "light",
"standard" or None (for control/local). Metrics, worst errors first:
  dropped          a request for Claude Code was taken as control/local: it is lost
  under-estimates  standard work predicted light: costs an escalation mid-run
  detoured         control/local sent to Claude Code: works, slower and costs money
  over-estimates   light work predicted standard: works, costs more
plus route accuracy and demand accuracy (on requests both sides send to Claude Code).
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "eval" / "routes.jsonl"

Router = Callable[[str], tuple[str, str | None]]


def load(split: str = "test") -> list[dict]:
    rows = [json.loads(line) for line in ROUTES.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows if split == "all" else [r for r in rows if r["split"] == split]


def score(router: Router, rows: list[dict]) -> dict:
    n = len(rows)
    route_ok = dropped = detoured = 0
    demand_n = demand_ok = under = over = 0
    mistakes = []
    for r in rows:
        route, demand = router(r["text"])
        if route == r["route"]:
            route_ok += 1
        elif r["route"] == "agent":
            dropped += 1
            mistakes.append(("dropped", r, route, demand))
        else:
            if route == "agent":
                detoured += 1
            mistakes.append(("route", r, route, demand))
        if r["route"] == "agent" and route == "agent":
            demand_n += 1
            if demand == r["demand"]:
                demand_ok += 1
            elif r["demand"] == "standard":
                under += 1
                mistakes.append(("under", r, route, demand))
            else:
                over += 1
                mistakes.append(("over", r, route, demand))
    standard_n = sum(1 for r in rows if r["route"] == "agent" and r["demand"] == "standard")
    light_n = sum(1 for r in rows if r["route"] == "agent" and r["demand"] == "light")
    return {
        "n": n,
        "route_acc": route_ok / n if n else 0.0,
        "dropped": dropped,
        "detoured": detoured,
        "demand_acc": demand_ok / demand_n if demand_n else 0.0,
        "under": under,
        "under_rate": under / standard_n if standard_n else 0.0,
        "over": over,
        "over_rate": over / light_n if light_n else 0.0,
        "mistakes": mistakes,
    }


# ---- baselines -----------------------------------------------------------------


def everything_standard(text: str) -> tuple[str, str | None]:
    """Swift before ADR-007: every request to Claude Code, on one strong model."""
    return "agent", "standard"


def everything_light(text: str) -> tuple[str, str | None]:
    """Start everything on Haiku and rely on escalation."""
    return "agent", "light"


BASELINES: dict[str, Router] = {"everything-standard": everything_standard, "everything-light": everything_light}


def report(name: str, s: dict, show: int) -> None:
    print(f"\n== {name}  ({s['n']} requests)")
    print(f"   route accuracy {s['route_acc']:.1%}   dropped {s['dropped']}   detoured {s['detoured']}")
    print(f"   demand accuracy {s['demand_acc']:.1%}   under-estimates {s['under']} ({s['under_rate']:.0%} of standard)"
          f"   over-estimates {s['over']} ({s['over_rate']:.0%} of light)")
    order = {"dropped": 0, "under": 1, "route": 2, "over": 3}
    for kind, r, route, demand in sorted(s["mistakes"], key=lambda m: order[m[0]])[:show]:
        print(f"   {kind:<8} {r['id']:<5} want {r['route']}/{r['demand']}  got {route}/{demand}: {r['text']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=["test", "train", "all"], default="test")
    ap.add_argument("--router", help="module:function to score instead of the baselines (module importable from the repo)")
    ap.add_argument("--show", type=int, default=12, help="mistakes to list per router")
    args = ap.parse_args()

    rows = load(args.split)
    if args.router:
        sys.path.insert(0, str(ROOT / "src"))
        sys.path.insert(0, str(ROOT / "spikes" / "routing"))
        module, _, fn = args.router.partition(":")
        routers = {args.router: getattr(importlib.import_module(module), fn)}
    else:
        routers = BASELINES
    for name, router in routers.items():
        report(name, score(router, rows), args.show)


if __name__ == "__main__":
    main()
