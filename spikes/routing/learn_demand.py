"""Learn demand examples from Swift's own history, with your approval for each one (ADR-007 §4, §8 step 4).

Usage (from the repo root, in a normal terminal, so %LOCALAPPDATA% is the real one):
  uv run python spikes/routing/learn_demand.py            # review new examples
  uv run python spikes/routing/learn_demand.py --list     # show saved examples
  uv run python spikes/routing/learn_demand.py --log path\\to\\interactions.jsonl
  uv run python spikes/routing/learn_demand.py --guesses  # review what you said yes to Swift's guess of

How it works:
1. Reads the interaction log (logging.interactions, default %LOCALAPPDATA%\\Swift\\interactions.jsonl).
2. Proposes two kinds of example from routed Claude Code requests:
   - started light and escalated (by the model or by Swift): a **standard** example,
     so similar requests start on Sonnet next time;
   - started standard, finished in one or two turns, no escalation, nothing edited
     or written: a **light** candidate, so similar requests can start on Haiku.
   Runs where you named the model ("use opus ...") are skipped: the model wasn't a guess.
3. Shows each one: y keeps it, n rejects it (never asked again), s skips it for now,
   q saves and quits. "Light" candidates deserve a look: a short run can still have
   needed judgment.

Kept examples go to demand_classifier.examples_file (default
%LOCALAPPDATA%\\Swift\\demand_examples.jsonl); Swift adds them to its built-in
examples at startup. Rejected ones stay in the same file marked "rejected".

--guesses (IA-01 phase 4, P4-2; CLAUDE.md "Memory is written only from the owner's words or an approved card"):
each request where you said yes to Swift's guess ("Set a timer for 2 minutes?") is a candidate: the words Swift
heard and the kind of command it was. A yes approved that action only, and may have come from the room, so a
candidate is used only after you keep it here. Kept ones go to guess_examples.jsonl beside the demand examples
(classifier.guess_examples) and only make Swift's guesses likelier: they never make Swift act or count as you
asking.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from swift.routing.classifier import BASE_EXAMPLES, guess_examples, load_examples, load_families  # noqa: E402
from swift.settings import load_settings  # noqa: E402
from swift.system.understand import FAMILY_OF  # noqa: E402

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
MAX_LIGHT_TURNS = 2


def key(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", text.lower()))


def read_log(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def propose(records: list[dict], known: set[str]) -> list[dict]:
    """New examples, one per distinct request: {text, demand, why, ts}. ``known`` holds key()s to skip."""
    out: dict[str, dict] = {}
    for r in records:
        text = (r.get("transcript") or "").strip()
        if r.get("route") not in ("agent", "claude") or not text or r.get("override") or key(text) in known:
            continue
        escalations = r.get("escalations") or []
        if r.get("demand") == "light" and escalations:
            first = escalations[0]
            why = f"started light, escalated to {first.get('to')} by {first.get('by')}: {first.get('reason') or 'no reason given'}"
            out[key(text)] = {"text": text, "demand": "standard", "why": why, "ts": r.get("ts")}
        elif (
            r.get("demand") == "standard"
            and r.get("status") == "done"
            and not escalations
            and (r.get("turns") or 0) <= MAX_LIGHT_TURNS
            and not any(a.get("tool") in EDIT_TOOLS for a in r.get("approvals") or [])
            and key(text) not in out
        ):
            why = f"started standard, done in {r.get('turns')} turn(s), nothing edited, ${r.get('cost_usd') or 0:.3f}"
            out[key(text)] = {"text": text, "demand": "light", "why": why, "ts": r.get("ts")}
    return list(out.values())


def propose_guesses(records: list[dict], known: set[str]) -> list[dict]:
    """Candidates from yeses to Swift's guess, one per distinct request: {text, family, why, ts}."""
    out: dict[str, dict] = {}
    for r in records:
        text, understood = (r.get("transcript") or "").strip(), r.get("understood")
        if (not isinstance(understood, dict) or understood.get("source") not in ("similar", "heard")
                or r.get("confirmed") is not True or not text or key(text) in known or key(text) in out):
            continue
        family = FAMILY_OF.get((understood.get("family") or [""])[0])
        if family:
            why = f"you said yes to Swift's guess ({understood['source']}: {understood['family'][0]})"
            out[key(text)] = {"text": text, "family": family, "why": why, "ts": r.get("ts")}
    return list(out.values())


def append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=REPO / "config.yaml")
    ap.add_argument("--log", type=Path, help="interaction log to read instead of logging.interactions")
    ap.add_argument("--list", action="store_true", help="show saved examples and exit")
    ap.add_argument("--guesses", action="store_true", help="review yeses to Swift's guess instead (IA-01 phase 4)")
    args = ap.parse_args()

    settings = load_settings(args.config)
    store = Path(settings.demand_classifier.examples_file)
    if args.guesses:
        store = guess_examples(store)
    log = args.log or Path(settings.logging.interactions)
    if args.list:
        print(f"{store}:")
        if args.guesses:
            rows = [json.loads(x) for x in store.read_text(encoding="utf-8").splitlines() if x.strip()] if store.exists() else []
            saved = [(r["family"], r["text"]) for r in rows if not r.get("rejected")]
        else:
            saved = [(e.demand, e.text) for e in load_examples([store])]
        for label, text in saved:
            print(f"  {label:<10} {text}")
        return
    if not log.exists():
        raise SystemExit(f"No interaction log at {log}. Pass --log if Swift writes it elsewhere.")

    if args.guesses:
        known = {key(t) for t, _ in load_families()}
    else:
        known = {key(e.text) for e in load_examples([BASE_EXAMPLES])}
    if store.exists():
        known |= {key(json.loads(line)["text"]) for line in store.read_text(encoding="utf-8").splitlines() if line.strip()}
    new = (propose_guesses if args.guesses else propose)(read_log(log), known)
    if not new:
        print("No new examples to review.")
        return

    print(f"{len(new)} possible examples. y = keep, n = reject, s = skip for now, q = quit.\n")
    kept = 0
    try:
        for ex in new:
            label = ex.get("family") or ex["demand"]
            print(f"{label.upper():<10} {ex['text']}")
            print(f"           {ex['why']}")
            answer = input("  keep? [y/n/s/q] ").strip().lower()
            if answer == "q":
                break
            added = datetime.now().astimezone().isoformat(timespec="seconds")
            row = ({"text": ex["text"], "family": ex["family"], "source": "learned", "added": added} if args.guesses
                   else {"text": ex["text"], "route": "agent", "demand": ex["demand"], "source": "learned", "added": added})
            if answer == "y":
                append(store, row)
                kept += 1
            elif answer == "n":
                append(store, row | {"rejected": True})
    except (EOFError, KeyboardInterrupt):
        print("\nStopped; keeping the answers given so far.")
    print(f"\nKept {kept} new examples in {store}. Restart Swift to use them.")


if __name__ == "__main__":
    main()
