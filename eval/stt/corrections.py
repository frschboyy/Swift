"""What Swift keeps mishearing: a report over the owner's corrections (docs/design/heard-corrections.md).

Usage:  python eval/stt/corrections.py [--data DIR] [--json]

Reads the clips the owner corrected on the card (``corrected``, with the heard words and the kind) and the
clips whose words a repeat gave (``known`` only), from the test set and the recordings index, on this PC.
Prints, for prioritising speech work:

- corrections by kind, by source (wake, hotkey…), and by room (quiet or noisy, by the clip's noise dB);
- the words most often missed or misheard, and what each was heard as (the name "Swift" first);
- the word error rate of the heard words against the corrected ones, week by week, and by speech model.

Words stay on this PC: this prints to the terminal only. The speech gate (gate.py) and the improvement
pass already score these clips, since a correction puts them in the test set.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from swift.stt.improve import align, edits, normalize

# The noise dB above which a room counts as noisy (session.NOISY_DB, where a voice "approve" needs a second).
NOISY_DB = -50.0
NAME = "swift"


def load(data: Path) -> list[dict[str, Any]]:
    """Every clip with known words, the test set's entry winning (it outlives the recordings' keep_days)."""
    clips: dict[str, dict[str, Any]] = {}
    for folder in ("audio", "stt_testset"):
        index = data / folder / "index.json"
        if index.exists():
            for c in json.loads(index.read_text(encoding="utf-8")).get("clips", []):
                if c.get("known"):
                    clips[c["id"]] = c
    return sorted(clips.values(), key=lambda c: c.get("corrected_at") or c.get("ts") or c.get("added") or 0)


def room(c: dict[str, Any]) -> str:
    db = c.get("noise_db")
    return "unknown" if db is None else "noisy" if db > NOISY_DB else "quiet"


def week(c: dict[str, Any]) -> str:
    t = c.get("corrected_at") or c.get("ts") or c.get("added")
    return time.strftime("%G-W%V", time.localtime(t)) if t else "unknown"


def report(clips: list[dict[str, Any]]) -> dict[str, Any]:
    fixed = [c for c in clips if c.get("heard")]
    missed: Counter[str] = Counter()
    heard_as: dict[str, Counter[str]] = defaultdict(Counter)
    rates: dict[str, dict[str, list[int]]] = {"week": defaultdict(lambda: [0, 0]), "model": defaultdict(lambda: [0, 0])}
    for c in fixed:
        ref, hyp = normalize(c["known"]), normalize(c["heard"])
        for op, r0, r1, h0, h1 in align(ref, hyp):
            if op in ("sub", "del"):
                word = ref[r0]
                missed[word] += 1
                heard_as[word][" ".join(hyp[h0:h1]) or "(nothing)"] += 1
        for key, value in (("week", week(c)), ("model", c.get("stt_model") or "unknown")):
            rates[key][value][0] += len(ref)
            rates[key][value][1] += edits(ref, hyp)
    wer = {k: {v: round(e / w, 3) if w else None for v, (w, e) in sorted(rows.items())} for k, rows in rates.items()}
    return {
        "corrections": len(fixed),
        "known_by_repeat": len(clips) - len(fixed),
        "by_kind": dict(Counter(c.get("kind", "other") for c in fixed).most_common()),
        "by_source": dict(Counter(c.get("source", "unknown") for c in fixed).most_common()),
        "by_room": {r: dict(Counter(c.get("kind", "other") for c in fixed if room(c) == r).most_common())
                    for r in sorted({room(c) for c in fixed})},
        "most_missed": [[w, n, dict(heard_as[w].most_common(3))] for w, n in missed.most_common(15)],
        "name_heard_as": dict(heard_as[NAME].most_common()),
        "wer_by_week": wer["week"],
        "wer_by_model": wer["model"],
    }


def show(r: dict[str, Any]) -> str:
    lines = [f"{r['corrections']} corrections typed on the card; {r['known_by_repeat']} more clips known from a repeat."]
    if not r["corrections"]:
        return lines[0] + "\nNothing to report yet: use the flag on a card's heard words when Swift gets them wrong."

    def table(title: str, counts: dict[str, Any]) -> None:
        lines.append(f"\n{title}")
        lines.extend(f"  {k:24} {v}" for k, v in counts.items())

    table("By kind", r["by_kind"])
    table("By source", r["by_source"])
    table("By room (kinds)", {k: ", ".join(f"{kind} {n}" for kind, n in v.items()) for k, v in r["by_room"].items()})
    table('"Swift" heard as', r["name_heard_as"] or {"(never misheard)": ""})
    table("Most missed words (heard as)", {w: f"{n}  ({', '.join(f'{h} {m}' for h, m in as_.items())})"
                                           for w, n, as_ in r["most_missed"]})
    table("Word error rate by week", r["wer_by_week"])
    table("Word error rate by speech model", r["wer_by_model"])
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=None, help="Swift's data folder (default: the one Swift uses)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args()
    if args.data is None:
        from swift.config.paths import app_paths

        args.data = app_paths().data_dir
    r = report(load(args.data))
    print(json.dumps(r, indent=1, ensure_ascii=False) if args.json else show(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
