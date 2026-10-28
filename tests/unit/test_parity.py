"""The parity set (ADR-016 §9.1): well-formed, reproducible, never harmful, and never going backwards."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module(name: str):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, ROOT / "eval" / "parity" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[f"parity_{name}"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


build = _module("build")
score = _module("score")
ROWS = score.load()


def test_the_file_is_what_the_builder_makes() -> None:
    assert ROWS == json.loads(json.dumps(build.build()))  # regenerate: uv run python eval/parity/build.py


def test_every_row_is_well_formed() -> None:
    ids = [r["id"] for r in ROWS]
    assert len(ids) == len(set(ids)) and len(ROWS) >= 350
    for r in ROWS:
        assert r["ideal"] in ("system", "fast", "light", "web", "agent", "control", "excluded"), r["id"]
        assert r.get("must_not") in (None, "system"), r["id"]
        assert r["ideal"] != "excluded" or r.get("note"), r["id"]  # an exclusion says why


def test_nothing_harmful() -> None:
    assert score.score(ROWS)["harmful"] == []


def test_the_ratchet_holds() -> None:
    passing = set((ROOT / "eval" / "parity" / "passing.txt").read_text(encoding="utf-8").split())
    now = score.score(ROWS)["passed"]
    lost = sorted(passing - now)
    assert not lost, f"these passed before and don't now: {lost[:10]}"
