"""Tier 2 of the router (ADR-007 §4): a local demand classifier.

A small sentence-embedding model (bge-small-en-v1.5, ONNX, on onnxruntime)
turns a request into a vector; its nearest labeled examples vote on demand
(light or standard) and, as a hint only, on route. The examples are the train
split of eval/routes.jsonl (``examples.jsonl`` next to this file) plus any the
owner approved with ``spikes/routing/learn_demand.py``.

Light is predicted only when the vote is confident (``threshold``); otherwise
the classifier abstains and the caller's default (standard) applies, because an
under-estimate costs an escalation while an over-estimate only costs money.
The route vote is never acted on: control and local need an action only the
rules can supply, so it is only logged (``route_hint``) to show which rules to add.

The same model also votes on a request's *family* ("timer", "radio", ...) over ``families.jsonl`` (the parity set's
labelled rows, ``eval/parity/parity.jsonl``: a system row's category, anything else ``other``). That vote is only
Swift's guess about a command the grammar missed (IA-01 phase 2, ``system/understand.py``): it may make Swift ask,
never act. It runs even while the demand vote is off (``demand=False``). It also counts the guess examples the
owner kept after a yes to a guess (``guess_examples``; ``spikes/routing/learn_demand.py --guesses``, IA-01 phase 4):
those feed the vote only, never the grammar (``intents.parse``).

The model is never downloaded here (README has the one-time command). Loading
takes a few seconds and happens in the background; until it is ready, and if it
fails, the keyword estimate in ``demand.py`` answers.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from loguru import logger

from swift.routing import demand as keywords
from swift.routing import rules

MODEL_NAME = "bge-small-en-v1.5"
BASE_EXAMPLES = Path(__file__).with_name("examples.jsonl")
FAMILY_EXAMPLES = Path(__file__).with_name("families.jsonl")
# Route names from before ADR-008, still found in examples learned earlier.
LEGACY_ROUTES = {"claude": "agent"}
MAX_TOKENS = 64


class ClassifierUnavailable(RuntimeError):
    pass


class Embedder:
    """bge-small: CLS token of the last hidden state, L2-normalized."""

    def __init__(self, model_dir: Path, quantized: bool = True, threads: int = 2) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model = model_dir / "onnx" / ("model_int8.onnx" if quantized else "model.onnx")
        tokenizer = model_dir / "tokenizer.json"
        missing = [p for p in (model, tokenizer) if not p.exists()]
        if missing:
            raise ClassifierUnavailable(f"missing {', '.join(str(p) for p in missing)}; see README (demand classifier)")
        self.tokenizer = Tokenizer.from_file(str(tokenizer))
        self.tokenizer.enable_truncation(MAX_TOKENS)
        self.tokenizer.enable_padding()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model), opts, providers=["CPUExecutionProvider"])

    def embed(self, texts: list[str]) -> np.ndarray:
        enc = self.tokenizer.encode_batch(texts)
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        hidden = self.session.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)})[0]
        cls = hidden[:, 0, :]
        return cls / np.linalg.norm(cls, axis=1, keepdims=True)


@dataclass(frozen=True)
class Example:
    text: str
    route: str
    demand: str | None


def load_examples(paths: Iterable[Path]) -> list[Example]:
    """JSON lines with ``text``, ``route`` (default agent) and ``demand``. Missing files are skipped.

    ``"claude"``, the route's name before ADR-008, is read as ``"agent"``: examples learned
    earlier keep working.
    """
    out: list[Example] = []
    for path in paths:
        if not path.exists():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("rejected"):  # the owner said no in learn_demand.py
                    continue
                route = LEGACY_ROUTES.get(row.get("route", "agent"), row.get("route", "agent"))
                demand = row.get("demand") if route == "agent" else None
                if route not in ("control", "local", "agent") or (route == "agent" and demand not in ("light", "standard")):
                    raise ValueError(f"bad labels {route}/{demand}")
                out.append(Example(row["text"], route, demand))
            except (ValueError, KeyError, TypeError) as exc:
                logger.warning("skipping a demand example", file=str(path), line=n, error=str(exc))
    return out


@dataclass(frozen=True)
class Prediction:
    route: str
    route_conf: float
    # None when the classifier abstains (not confident enough that it is light).
    demand: str | None
    # Share of the neighbors' weight voting light, among the claude examples.
    p_light: float


class DemandClassifier:
    """Weighted k nearest neighbors over the example embeddings."""

    def __init__(self, embed: Callable[[list[str]], np.ndarray], examples: list[Example],
                 k: int = 7, threshold: float = 0.7) -> None:
        if not examples:
            raise ClassifierUnavailable("no demand examples")
        self.embed = embed
        self.k = k
        self.threshold = threshold
        self.examples = examples
        self.vectors = np.concatenate([embed([e.text for e in examples[i:i + 32]]) for i in range(0, len(examples), 32)])
        self._agent = np.array([e.route == "agent" for e in examples])
        self._light = np.array([e.demand == "light" for e in examples])

    def _vote(self, sims: np.ndarray, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        idx = np.flatnonzero(rows)
        top = idx[np.argsort(-sims[idx])[: self.k]]
        return top, np.maximum(sims[top], 1e-6) ** 4

    def predict(self, text: str) -> Prediction:
        sims = self.vectors @ self.embed([keywords.strip_lead(text)])[0]
        top, w = self._vote(sims, np.ones(len(sims), dtype=bool))
        scores: dict[str, float] = {}
        for i, wi in zip(top, w):
            scores[self.examples[i].route] = scores.get(self.examples[i].route, 0.0) + float(wi)
        route = max(scores, key=scores.__getitem__)
        top, w = self._vote(sims, self._agent)
        p_light = float(w[self._light[top]].sum() / w.sum())
        return Prediction(route, scores[route] / sum(scores.values()), "light" if p_light >= self.threshold else None, p_light)


class FamilyVote:
    """Weighted k nearest neighbours over ``families.jsonl``: (family, share of the neighbours' weight)."""

    def __init__(self, embed: Callable[[list[str]], np.ndarray], rows: list[tuple[str, str]], k: int = 7) -> None:
        if not rows:
            raise ClassifierUnavailable("no family examples")
        self.embed, self.k = embed, k
        self.families = [f for _, f in rows]
        self.vectors = np.concatenate([embed([t for t, _ in rows[i:i + 32]]) for i in range(0, len(rows), 32)])

    def __call__(self, text: str) -> tuple[str, float]:
        sims = self.vectors @ self.embed([keywords.strip_lead(text)])[0]
        top = np.argsort(-sims)[: self.k]
        scores: dict[str, float] = {}
        for i in top:
            scores[self.families[i]] = scores.get(self.families[i], 0.0) + float(max(sims[i], 1e-6) ** 4)
        family = max(scores, key=scores.__getitem__)
        return family, scores[family] / sum(scores.values())


def guess_examples(examples_file: Path) -> Path:
    """Where the guess examples the owner kept live (``learn_demand.py --guesses``), beside the demand examples."""
    return examples_file.with_name("guess_examples.jsonl")


def load_families(path: Path = FAMILY_EXAMPLES, learned: Iterable[Path] = ()) -> list[tuple[str, str]]:
    """The family examples, and the learned ones the owner kept (never one marked rejected). A yes to a guess is
    never one by itself: it is a candidate until the owner keeps it (R4)."""
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    for extra in learned:
        if extra.exists():
            rows += [r for x in extra.read_text(encoding="utf-8").splitlines() if x.strip()
                     if not (r := json.loads(x)).get("rejected")]
    return [(r["text"], r["family"]) for r in rows]


class ClassifierEstimate:
    """``demand_fn`` for ``rules.route``: the keyword estimate first, the classifier where it abstains.

    Keywords catch the clear cases (they were tuned on the same train split); the
    classifier decides the requests they can't place, which would otherwise start on
    Sonnet. Safe to call while loading: until the classifier is ready, or if it
    failed to load, it is the keyword estimate alone.
    """

    def __init__(self, model_dir: Path, example_files: list[Path], threshold: float = 0.7,
                 k: int = 7, quantized: bool = True, demand: bool = True, family_files: Iterable[Path] = ()) -> None:
        self.model_dir = model_dir
        self.example_files = example_files
        self.family_files = list(family_files)  # the guess examples the owner kept (``guess_examples``)
        self.threshold = threshold
        self.k = k
        self.quantized = quantized
        self.classifier: DemandClassifier | None = None
        # The demand vote on (settings.demand_classifier.enabled); off, only the family vote loads.
        self.demand = demand
        self.families: FamilyVote | None = None
        self.error: str | None = None
        self.hint: tuple[tuple[str, object], ...] = ()

    def start_loading(self) -> None:
        threading.Thread(target=self.load, name="demand-classifier", daemon=True).start()

    def load(self) -> None:
        started = time.monotonic()
        try:
            embedder = Embedder(self.model_dir, quantized=self.quantized)
            self.families = FamilyVote(embedder.embed, load_families(learned=self.family_files))
            examples = load_examples(self.example_files) if self.demand else []
            if self.demand:
                self.classifier = DemandClassifier(embedder.embed, examples, k=self.k, threshold=self.threshold)
        except Exception as exc:  # noqa: BLE001 - any failure leaves the keyword estimate in charge
            self.error = str(exc)
            logger.warning("local classifier unavailable: keywords set demand, and Swift makes no guesses", error=self.error)
            return
        logger.info("demand classifier ready", examples=len(examples), load_ms=round((time.monotonic() - started) * 1000))

    def __call__(self, request: str) -> str | None:
        found = keywords.estimate(request)
        classifier = self.classifier
        if classifier is None:
            return found
        p = classifier.predict(request)  # also when the keywords decided: its route vote goes on the record
        if p.route != "agent":
            # A pattern of these means a rule is missing (IA-01). A name and a number: no words.
            self.hint = (("route_hint", p.route), ("route_conf", round(p.route_conf, 2)))
        return found or p.demand

    def route(self, text: str) -> rules.Route:
        """``rules.route`` with this as its demand estimate, carrying the classifier's route vote when it thinks a
        rule missed the request (``Route.hint``), so the run record says so beside the request it was about."""
        self.hint = ()
        found = rules.with_guess(rules.route(text, demand_fn=self), self.families)
        return replace(found, hint=self.hint) if self.hint else found
