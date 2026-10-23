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

The model is never downloaded here (README has the one-time command). Loading
takes a few seconds and happens in the background; until it is ready, and if it
fails, the keyword estimate in ``demand.py`` answers.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from loguru import logger

from swift.routing import demand as keywords

MODEL_NAME = "bge-small-en-v1.5"
BASE_EXAMPLES = Path(__file__).with_name("examples.jsonl")
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
    """JSON lines with ``text``, ``route`` (default claude) and ``demand``. Missing files are skipped."""
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
                route = row.get("route", "claude")
                demand = row.get("demand") if route == "claude" else None
                if route not in ("control", "local", "claude") or (route == "claude" and demand not in ("light", "standard")):
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
        self._claude = np.array([e.route == "claude" for e in examples])
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
        top, w = self._vote(sims, self._claude)
        p_light = float(w[self._light[top]].sum() / w.sum())
        return Prediction(route, scores[route] / sum(scores.values()), "light" if p_light >= self.threshold else None, p_light)


class ClassifierEstimate:
    """``demand_fn`` for ``rules.route``: the keyword estimate first, the classifier where it abstains.

    Keywords catch the clear cases (they were tuned on the same train split); the
    classifier decides the requests they can't place, which would otherwise start on
    Sonnet. Safe to call while loading: until the classifier is ready, or if it
    failed to load, it is the keyword estimate alone.
    """

    def __init__(self, model_dir: Path, example_files: list[Path], threshold: float = 0.7,
                 k: int = 7, quantized: bool = True) -> None:
        self.model_dir = model_dir
        self.example_files = example_files
        self.threshold = threshold
        self.k = k
        self.quantized = quantized
        self.classifier: DemandClassifier | None = None
        self.error: str | None = None

    def start_loading(self) -> None:
        threading.Thread(target=self.load, name="demand-classifier", daemon=True).start()

    def load(self) -> None:
        started = time.monotonic()
        try:
            embedder = Embedder(self.model_dir, quantized=self.quantized)
            examples = load_examples(self.example_files)
            self.classifier = DemandClassifier(embedder.embed, examples, k=self.k, threshold=self.threshold)
        except Exception as exc:  # noqa: BLE001 - any failure leaves the keyword estimate in charge
            self.error = str(exc)
            logger.warning("demand classifier unavailable; using keywords", error=self.error)
            return
        logger.info("demand classifier ready", examples=len(examples), load_ms=round((time.monotonic() - started) * 1000))

    def __call__(self, request: str) -> str | None:
        if found := keywords.estimate(request):
            return found
        classifier = self.classifier
        if classifier is None:
            return None
        p = classifier.predict(request)
        if p.route != "claude":
            # No transcript here: swift.log stays redacted. A pattern of these means a rule is missing.
            logger.info("classifier thinks a rule missed this", route_hint=p.route, confidence=round(p.route_conf, 2))
        return p.demand
