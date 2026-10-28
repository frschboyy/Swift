"""Score the router against the parity set (ADR-016 §9.1).

Usage:  uv run python eval/parity/score.py [--show 20]

Prints coverage overall and per category: how many requests take the lane they should once
the gap is closed. ``excluded`` rows are listed, not scored. Any ``must_not`` violation is a
failure whatever the coverage. ``passing.txt`` is the ratchet: ids that pass today, which
tests/unit/test_parity.py keeps passing (regenerate with --write-passing after an improvement).
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from swift.routing import route

HERE = Path(__file__).parent


def load() -> list[dict]:
    return [json.loads(x) for x in (HERE / "parity.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


def lane(text: str) -> str:
    """The lane the router takes today, in the parity set's terms."""
    r = route(text)
    if r.route == "control":
        return "control"
    if r.route == "local":
        return {"system": "system", "answer": "fast"}.get(r.action or "", "fast" if r.action in ("time", "date") else "local")
    return "light" if r.action == "quick" else "agent"


def score(rows: list[dict]) -> dict:
    scored = [r for r in rows if r["ideal"] != "excluded"]
    results = {r["id"]: lane(r["text"]) for r in scored}
    passed = {i for i, r in ((r["id"], r) for r in scored) if results[i] == r["ideal"]}
    harmful = [r for r in scored if r.get("must_not") and results[r["id"]] == r["must_not"]]
    by_cat: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in scored:
        by_cat[r["category"]][1] += 1
        by_cat[r["category"]][0] += r["id"] in passed
    return {"total": len(scored), "passed": passed, "harmful": harmful, "results": results, "by_cat": dict(by_cat),
            "excluded": [r for r in rows if r["ideal"] == "excluded"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=20)
    ap.add_argument("--write-passing", action="store_true")
    args = ap.parse_args()
    rows = load()
    s = score(rows)
    pct = 100 * len(s["passed"]) / s["total"]
    print(f"\nParity: {len(s['passed'])}/{s['total']} ({pct:.1f}%) take the lane they should; "
          f"{len(s['excluded'])} excluded (not on a PC); harmful: {len(s['harmful'])}\n")
    for cat, (ok, n) in sorted(s["by_cat"].items(), key=lambda kv: kv[1][0] / kv[1][1]):
        print(f"  {cat:11} {ok:3}/{n:<3} {100 * ok / n:5.0f}%")
    misses = [r for r in rows if r["ideal"] != "excluded" and r["id"] not in s["passed"]]
    print(f"\nMisses ({len(misses)}), first {args.show}:")
    for r in misses[: args.show]:
        print(f"  {r['id']:15} want {r['ideal']:7} got {s['results'][r['id']]:7} {r['text']}")
    for r in s["harmful"]:
        print(f"  HARMFUL {r['id']}: {r['text']} went to {r['must_not']}")
    if args.write_passing:
        (HERE / "passing.txt").write_text("".join(f"{i}\n" for i in sorted(s["passed"])), encoding="utf-8")
        print(f"\nwrote {len(s['passed'])} ids to passing.txt")


if __name__ == "__main__":
    main()
