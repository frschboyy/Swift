"""Router tier 2 (ADR-007 §4): the demand classifier, its examples and the learning loop. No model needed."""

from __future__ import annotations

import functools
import importlib.util
import json
import zlib
from pathlib import Path

import numpy as np
import pytest

from swift.routing import route
from swift.routing.classifier import BASE_EXAMPLES, ClassifierEstimate, DemandClassifier, Example, load_examples
from swift.settings import Settings

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location("learn_demand", ROOT / "spikes" / "routing" / "learn_demand.py")
learn_demand = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(learn_demand)  # type: ignore[union-attr]


def fake_embed(texts: list[str]) -> np.ndarray:
    """Bag of words hashed into 256 dims: texts sharing words are close, like a real embedding."""
    out = np.zeros((len(texts), 256), dtype=np.float32)
    for i, t in enumerate(texts):
        for w in t.lower().replace("?", " ").replace(".", " ").split():
            out[i, zlib.crc32(w.encode()) % 256] += 1.0
    return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)


EXAMPLES = [
    Example("what is the weather like today", "claude", "light"),
    Example("what is in the notes folder", "claude", "light"),
    Example("what is the capital of france", "claude", "light"),
    Example("refactor the session module into smaller pieces", "claude", "standard"),
    Example("refactor the overlay code and the session module", "claude", "standard"),
    Example("stop", "control", None),
]


def classifier(threshold: float = 0.7) -> DemandClassifier:
    return DemandClassifier(fake_embed, EXAMPLES, k=3, threshold=threshold)


def test_light_when_the_nearest_examples_agree() -> None:
    p = classifier().predict("what is the weather in paris")
    assert p.demand == "light" and p.p_light == pytest.approx(1.0) and p.route == "claude"


def test_abstains_when_neighbors_say_standard() -> None:
    p = classifier().predict("refactor the session module please")
    assert p.demand is None and p.p_light < 0.7


def test_threshold_decides_a_split_vote() -> None:
    text = "what is in the session module"
    p_light = classifier().predict(text).p_light
    assert 0 < p_light < 1
    assert classifier(threshold=p_light - 0.01).predict(text).demand == "light"
    assert classifier(threshold=p_light + 0.01).predict(text).demand is None


def test_route_vote_is_a_hint_only() -> None:
    p = classifier().predict("stop")
    assert p.route == "control"
    estimate = ClassifierEstimate(Path("unused"), [])
    estimate.classifier = classifier()
    # The router still sends it to Claude Code when the rules don't match: a hint never drops a request.
    assert route("stop the weather", demand_fn=estimate).route == "claude"


def test_load_examples_skips_rejected_bad_and_missing(tmp_path: Path) -> None:
    f = tmp_path / "ex.jsonl"
    f.write_text(
        "\n".join([
            json.dumps({"text": "list my files", "demand": "light"}),
            json.dumps({"text": "fix the bug", "demand": "standard", "rejected": True}),
            json.dumps({"text": "no demand", "route": "claude"}),
            "not json",
            json.dumps({"text": "stop", "route": "control", "demand": None}),
            "",
        ]),
        encoding="utf-8",
    )
    got = load_examples([f, tmp_path / "missing.jsonl"])
    assert got == [Example("list my files", "claude", "light"), Example("stop", "control", None)]


def test_keywords_answer_until_the_classifier_is_ready() -> None:
    estimate = ClassifierEstimate(Path("unused"), [])
    assert estimate("fix the failing test") == "standard"
    assert estimate("what's in the notes folder") == "light"
    assert estimate("the weather in paris") is None


def test_keywords_come_before_the_classifier() -> None:
    estimate = ClassifierEstimate(Path("unused"), [])
    estimate.classifier = classifier()
    # The classifier would say light (weather words), but "why is" asks for investigation.
    assert estimate("why is the weather slow") == "standard"
    # Keywords abstain here; the classifier decides.
    assert estimate("the weather in paris") == "light"
    assert route("the weather in paris", demand_fn=estimate).demand == "light"
    assert route("the session module", demand_fn=estimate).demand == "standard"


def test_missing_model_leaves_keywords_in_charge(tmp_path: Path) -> None:
    estimate = ClassifierEstimate(tmp_path / "no-model", [BASE_EXAMPLES])
    estimate.load()
    assert estimate.classifier is None and "missing" in (estimate.error or "")
    assert estimate("fix the failing test") == "standard"
    assert estimate("the weather in paris") is None


def test_built_in_examples_are_the_train_split() -> None:
    rows = [json.loads(line) for line in (ROOT / "eval" / "routes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    train = [Example(r["text"], r["route"], r["demand"]) for r in rows if r["split"] == "train"]
    # Regenerate with: uv run python spikes/routing/eval_classifier.py --write-examples
    assert load_examples([BASE_EXAMPLES]) == train


def test_settings_default_to_the_classifier_off_with_learned_examples() -> None:
    # Off until it matches the keywords' 0 under-estimates (owner decision 2026-10-23).
    cfg = Settings().demand_classifier
    assert not cfg.enabled and cfg.quantized and cfg.threshold == 0.7
    assert cfg.model_dir.endswith("bge-small-en-v1.5") and cfg.examples_file.endswith("demand_examples.jsonl")


def test_backend_router_uses_the_classifier_when_enabled() -> None:
    from swift.backend.__main__ import _make_router

    on = Settings.model_validate({"demand_classifier": {"enabled": True}})
    router, estimate = _make_router(on)
    assert isinstance(router, functools.partial) and isinstance(estimate, ClassifierEstimate)
    assert estimate.example_files[0] == BASE_EXAMPLES
    assert _make_router(Settings()) == (route, None)  # off by default
    assert _make_router(Settings.model_validate({"routing": False})) == (None, None)


# ---- learning loop (spikes/routing/learn_demand.py) ---------------------------------


def record(text: str, demand: str, **kw) -> dict:
    return {"route": "claude", "transcript": text, "demand": demand, "status": "done", "turns": 1, **kw}


def test_escalated_light_requests_become_standard_examples() -> None:
    esc = [{"to": "claude-sonnet-5-5", "by": "model", "reason": "needs changes in 3 files", "t_ms": 2000}]
    got = learn_demand.propose([record("Tidy up the scripts", "light", escalations=esc, turns=6)], set())
    assert [(g["text"], g["demand"]) for g in got] == [("Tidy up the scripts", "standard")]
    assert "by model" in got[0]["why"] and "3 files" in got[0]["why"]


def test_short_read_only_standard_runs_become_light_candidates() -> None:
    records = [
        record("What does the README say", "standard", turns=2),
        record("Make a note file", "standard", approvals=[{"tool": "Write", "decision": "allow"}]),
        record("Look into the crash", "standard", turns=9),
        record("Check the logs", "standard", escalations=[{"to": "claude-opus-5-5", "by": "swift"}]),
        record("Count files", "standard", status="error"),
        record("Use opus to explain this", "standard", override="opus"),
        {"route": "control", "transcript": "stop", "status": "done"},
    ]
    got = learn_demand.propose(records, set())
    assert [(g["text"], g["demand"]) for g in got] == [("What does the README say", "light")]


def test_known_and_repeated_requests_are_proposed_once() -> None:
    records = [record("What does the README say?", "standard"), record("what does the readme say", "standard"),
               record("List my files", "standard")]
    got = learn_demand.propose(records, {learn_demand.key("list my files")})
    assert [g["text"] for g in got] == ["What does the README say?"]
