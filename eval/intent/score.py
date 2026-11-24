"""Score how Swift understands a request against the intent set (docs/explorations/intent-architecture.md §4).

Usage:  PYTHONPATH=src python eval/intent/score.py [--show]

Each row of ``cases.jsonl`` says what the owner meant: system intents (``want`` a list), a workflow
(``{"workflow": name}``), the agent with a system part (``agent+system``), the agent alone (``agent``),
nothing at all (``nothing``: a negation), or a question back (``clarify``). The row's text is what speech
recognition wrote. The scorer runs the real code with no session and no real action: the router
(``rules.route``), the system grammar (``intents.parse``), the workflow library, and the check the agent's
``system_action`` tool makes (``owner_intents``), and reports what would happen:

- ``correct``: the system lane does exactly what was meant, or nothing when nothing was meant.
- ``slow_ok``: the agent gets it and ``system_action`` would accept the meant intents.
- ``asks``: ``system_action`` refuses but tells the agent to offer its guess (radios off, volume): recoverable.
- ``dead_end``: a system action was meant and no path accepts it (the owner's "Swift didn't accept the request").
- ``to_agent``: no lane took it; the agent may still manage (a workflow from the catalogue, a question back).
- ``wrong_route``: another workflow took it, or none of the system intents that were meant.
- ``false_action``: Swift acts (or answers from the system lane) on something not meant.
- ``wrong_confirm``: Swift asks to confirm a change that wasn't meant ("Turn off Wi-Fi?" after "don't ...").

No model runs: the light lane and the agent are not called. ``to_agent`` and ``slow_ok`` say where a
request went, not what the agent then said.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from swift.routing.rules import route
from swift.system import intents as it
from swift.workflows import system_tools as st
from swift.workflows.library import load_library

HERE = Path(__file__).parent
BAD = ("dead_end", "wrong_route", "false_action", "wrong_confirm")


def load() -> list[dict[str, Any]]:
    return [json.loads(x) for x in (HERE / "cases.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


def _slot_ok(want: Any, got: Any) -> bool:
    if isinstance(want, dict):
        return got is not None and all(getattr(got, k, None) == v for k, v in want.items())
    return want == got


def _same(want: dict[str, Any], got: it.Intent) -> bool:
    return want["name"] == got.name and all(_slot_ok(v, got.slots.get(k)) for k, v in want.get("slots", {}).items())


def _all_found(wants: list[dict[str, Any]], got: list[it.Intent]) -> bool:
    left = list(got)
    for w in wants:
        hit = next((g for g in left if _same(w, g)), None)
        if hit is None:
            return False
        left.remove(hit)
    return not left


def _accepts(wants: list[dict[str, Any]], said: str) -> str:
    """What the agent's system_action would answer for the meant intents: accept, ask (offer a guess) or refuse."""
    asked = st.owner_intents(said)
    if all(any(_same(w, a) for a in asked) for w in wants):
        return "accept"
    # A refusal offers a guess only for what an answer may unlock (system_tools.from_answer); the slots the
    # agent would pass are the meant ones, so build the intent the agent would send.
    if not all(w["name"] in st.FROM_ANSWERS and (w["name"] not in ("radio", "airplane") or not w.get("slots", {}).get("on", True))
               for w in wants):
        return "refuse"
    # The agent asks; the owner answers with the thing's name ("Wi-Fi", "down"). That answer must stand in for one
    # word of the request (owner_intents), or the second call is refused too.
    answers = [a for w in wants if (a := _answer(w))]
    asked = st.owner_intents(said, answers)
    return "ask" if all(any(_same(w, a) for a in asked) for w in wants) else "ask_refused"


def _answer(want: dict[str, Any]) -> str:
    """What the owner would answer to "Did you mean ...?": the name of the thing meant."""
    s = want.get("slots", {})
    return {
        "radio": {"wifi": "wifi", "bluetooth": "bluetooth"}.get(s.get("kind", ""), ""),
        "volume.step": "down" if s.get("delta", -1) < 0 else "up",
        "volume.set": str(s.get("level", "")),
        "theme": "dark mode" if s.get("dark", True) else "light mode",
        "mute": "mute",
    }.get(want["name"], "")


def judge(row: dict[str, Any], library: Any) -> tuple[str, str]:
    """(outcome, path) for one row."""
    text, want = row["text"], row["want"]
    r = route(text)
    if r.route == "local" and r.action == "system":
        got = it.parse(r.text) or []
        path = "system:" + ",".join(g.name for g in got)
        if isinstance(want, list):
            return ("correct" if _all_found(want, got) else
                    "wrong_confirm" if any(it.disruptive(g) for g in got) else "wrong_route"), path
        return ("wrong_confirm" if any(it.disruptive(g) for g in got) else "false_action"), path
    if r.route != "agent":
        path = f"{r.route}:{r.action}"
        if isinstance(want, list) or want == "agent+system":
            return "dead_end", path
        # A control word acts on what's running ("stop", "cancel"); another local answer is the wrong lane.
        return ("false_action" if r.route == "control" else "wrong_route"), path
    wf = library.match(r.text)
    path = f"workflow:{wf.package.name}" if wf else "agent"
    if isinstance(want, dict):
        if wf is None:
            return "to_agent", path
        return ("correct" if wf.package.name == want["workflow"] else "wrong_route"), path
    if want in ("agent", "clarify"):
        return ("wrong_route" if wf is not None else "correct" if want == "agent" else "to_agent"), path
    if want == "nothing":
        return ("wrong_route" if wf is not None else "correct"), path
    wants = row["system"] if want == "agent+system" else want
    if wf is not None and "system_action" not in wf.package.tools:
        return "dead_end", path + " (system_action outside the workflow)"
    verdict = _accepts(wants, text)
    return {"accept": "slow_ok", "ask": "asks", "ask_refused": "dead_end", "refuse": "dead_end"}[verdict], path + f" (system_action: {verdict})"


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    library = load_library(None)
    results = {r["id"]: judge(r, library) for r in rows}
    by_kind: dict[str, Counter[str]] = defaultdict(Counter)
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        by_kind[r["kind"]][results[r["id"]][0]] += 1
        by_family[r["family"]][results[r["id"]][0]] += 1
    return {"results": results, "total": Counter(o for o, _ in results.values()), "kind": by_kind, "family": by_family}


OUTCOMES = ("correct", "slow_ok", "asks", "to_agent", "dead_end", "wrong_route", "false_action", "wrong_confirm")


def _line(label: str, c: Counter[str]) -> str:
    return f"{label:12} " + " ".join(f"{c.get(o, 0):>6}" for o in OUTCOMES) + f" {sum(c.values()):>6}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="list every row that isn't correct")
    args = ap.parse_args()
    rows = load()
    s = score(rows)
    print(f"{'':12} " + " ".join(f"{o[:6]:>6}" for o in OUTCOMES) + f" {'n':>6}")
    print(_line("all", s["total"]))
    print()
    for k in ("variant", "stt", "question", "negation", "compound", "unsupported"):
        print(_line(k, s["kind"][k]))
    print()
    for f in sorted(s["family"]):
        print(_line(f, s["family"][f]))
    if args.show:
        print()
        for r in rows:
            outcome, path = s["results"][r["id"]]
            if outcome != "correct":
                print(f"{outcome:13} {r['id']:10} {r['text']!r:58} -> {path}")


if __name__ == "__main__":
    main()
