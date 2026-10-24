"""The route and demand eval set (eval/routes.jsonl) stays well-formed, and its scorer counts right."""

from __future__ import annotations

import importlib.util
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROWS = [json.loads(line) for line in (ROOT / "eval" / "routes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

_spec = importlib.util.spec_from_file_location("eval_routes", ROOT / "spikes" / "routing" / "eval_routes.py")
eval_routes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_routes)  # type: ignore[union-attr]


def test_every_row_follows_the_schema() -> None:
    for r in ROWS:
        assert set(r) <= {"id", "text", "route", "demand", "override", "tags", "split", "source"}, r["id"]
        assert r["route"] in ("control", "local", "agent"), r["id"]
        assert (r["demand"] in ("light", "standard")) if r["route"] == "agent" else r["demand"] is None, r["id"]
        assert r.get("override") in (None, "opus", "haiku"), r["id"]
        assert r["split"] in ("train", "test") and r["source"] in ("v2", "prompts", "new"), r["id"]
        assert r["text"].strip() and isinstance(r["tags"], list), r["id"]


def test_ids_are_unique() -> None:
    ids = [r["id"] for r in ROWS]
    assert len(ids) == len(set(ids))


def test_same_request_never_lands_in_both_splits() -> None:
    splits: dict[str, set[str]] = defaultdict(set)
    for r in ROWS:
        text = re.sub(r"^hey swift[, ]*", "", r["text"].lower())
        splits[" ".join(re.findall(r"[a-z0-9']+", text))].add(r["split"])
    leaked = [t for t, s in splits.items() if len(s) > 1]
    assert not leaked, leaked


def test_test_split_covers_every_label() -> None:
    labels = {(r["route"], r["demand"]) for r in ROWS if r["split"] == "test"}
    assert {("agent", "light"), ("agent", "standard"), ("control", None), ("local", None)} <= labels


def test_scorer_separates_the_error_kinds() -> None:
    rows = [
        {"id": "a", "text": "stop", "route": "control", "demand": None},
        {"id": "b", "text": "fix the bug", "route": "agent", "demand": "standard"},
        {"id": "c", "text": "what time is it", "route": "local", "demand": None},
        {"id": "d", "text": "list the files", "route": "agent", "demand": "light"},
        {"id": "e", "text": "refactor it", "route": "agent", "demand": "standard"},
    ]
    answers = {
        "stop": ("control", None),            # right
        "fix the bug": ("agent", "light"),   # under-estimate
        "what time is it": ("agent", "light"),  # detoured
        "list the files": ("agent", "standard"),  # over-estimate
        "refactor it": ("local", None),       # dropped
    }
    s = eval_routes.score(lambda t: answers[t], rows)
    assert s["route_acc"] == 3 / 5
    assert (s["dropped"], s["detoured"], s["under"], s["over"]) == (1, 1, 1, 1)
    assert s["demand_acc"] == 0.0  # neither of the two Claude-Claude pairs matched
