"""B4: a result laid out to fit it (docs/design/b4-adaptive-results.md §2).

The worker proposes a shape through the ``show_result`` tool; this module is where Swift checks it, sizes it
and marks it. What the worker sends is untrusted data: every field is checked here (lengths, counts, no markup,
no hidden characters), and anything that fails is refused whole, so the card falls back to today's text. The
overlay draws the frame as data with textContent (``overlay/src/blocks.ts``), never as HTML.

Shapes so far (owner's order, §7.5): ``compare``, ``diagram`` (Mermaid source, drawn by the overlay's pinned
Mermaid in strict mode), ``mindmap`` (a small tree of short labels, drawn by Swift's own code), and ``preview``
(a local document path rendered by Swift), ``chart`` (a small bar or line chart), and ``cards`` (project cards).
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator, BaseModel, ConfigDict, Field, FiniteFloat, StringConstraints, ValidationError, model_validator,
)

from swift.previews import PreparedPreview

MAX_ITEMS = 4
MAX_ROWS = 12
CELL_MAX = 160
TITLE_MAX = 120
# More rows than a card shows (``renderDetails``' six) opens the answer in full (B5's expanded card later).
CARD_ROWS = 6

# A diagram: Mermaid source in one of the kinds §4 vetted, small enough for a card or the reader.
SOURCE_MAX = 3000
SOURCE_LINES = 40
# A diagram with more statements than this opens in full; the tall kinds grow downwards, so fewer fit.
CARD_LINES = 12
CARD_LINES_TALL = 6
DIAGRAM_KINDS = {
    "flowchart": False, "graph": False, "stateDiagram": False, "stateDiagram-v2": False, "classDiagram": False,
    "erDiagram": False, "quadrantChart": False,
    "sequenceDiagram": True, "timeline": True, "gantt": True, "journey": True,
}
# A mind map: the vetted set's limits (§4, row 1): three levels of ideas under the root, thirty in all.
LABEL_MAX = 60
MAP_DEPTH = 3
MAP_IDEAS = 30
# Four branches with twelve ideas fill a card (§6); more opens the answer in full.
CARD_IDEAS = 12
# A chart has up to eight categories; six fit in the card, and the rest open in the reader.
CHART_POINTS = 8
CARD_CHART_POINTS = 6
CHART_SERIES = 4
CHART_LABEL_MAX = 8
CHART_VALUE_MAX = 1_000_000_000
PROJECT_CARDS = 8
CARD_PROJECT_CARDS = 3
PROJECT_TITLE_MAX = 80
PROJECT_DETAIL_MAX = 120
PROJECT_META_MAX = 48
PROJECT_TEXT_UNITS = 240
# What Mermaid can be told to do besides draw: clicks, links, callbacks, directives and front matter, styles (the
# colours are Swift's, and url() fetches), and images or icons on nodes (``A@{ img: ... }``). Refused whole.
_MERMAID_ACTIVE = re.compile(
    r"^\s*(click|callback|links?|style|classDef|linkStyle|cssClass)\b|\bhref\b|\bcall\s+[\w.$]+\s*\(|%%\{|@\{|\burl\s*\(|javascript:|://|^\s*---",
    re.IGNORECASE | re.MULTILINE)
# Mermaid's own entity codes (``#quot;``, ``#60;``) turn into markup after the check; refused like ``&lt;``.
_MERMAID_ENTITY = re.compile(r"#\w+;")

# A tag or an entity: drawn as text it would be harmless, but a worker sending markup is refused (§2.1).
_MARKUP = re.compile(r"<\s*/?\s*[A-Za-z!?]|&#?\w+;")


def _plain(text: str) -> str:
    if _MARKUP.search(text):
        raise ValueError("no markup")
    if any(unicodedata.category(c) in ("Cc", "Cf") for c in text):
        raise ValueError("no control or format characters")
    return text


def _words(n: int) -> Any:
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=n), AfterValidator(_plain)]


Cell = _words(CELL_MAX)


def _mermaid(source: str) -> str:
    if _MARKUP.search(source) or _MERMAID_ENTITY.search(source):
        raise ValueError("no markup")
    if any(unicodedata.category(c) in ("Cc", "Cf") and c not in "\n\t" for c in source):
        raise ValueError("no control or format characters")
    if _MERMAID_ACTIVE.search(source):
        raise ValueError("no clicks, links, directives or styles that fetch")
    lines = _statements(source)
    if not lines or lines[0].split()[0] not in DIAGRAM_KINDS:
        raise ValueError("a diagram kind Swift draws")
    if len(lines) > SOURCE_LINES:
        raise ValueError("too many lines")
    return source


def _preview_path(path: str) -> str:
    if any(unicodedata.category(c) in ("Cc", "Cf") for c in path) or path.lower().startswith(
        ("http://", "https://", "file://")
    ):
        raise ValueError("a local path")
    if os.path.splitext(path)[1].lower() not in {".pdf", ".docx", ".pptx", ".xlsx"}:
        raise ValueError("a supported document")
    return path


def _statements(source: str) -> list[str]:
    """The source's lines that say something: not blank, not a ``%%`` comment."""
    return [line.strip() for line in source.splitlines() if line.strip() and not line.strip().startswith("%%")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Row(_Strict):
    label: Cell
    values: list[Cell]


class Compare(_Strict):
    shape: Literal["compare"]
    title: _words(TITLE_MAX) | None = None
    items: list[Cell] = Field(min_length=2, max_length=MAX_ITEMS)
    rows: list[Row] = Field(min_length=1, max_length=MAX_ROWS)
    pick: int | None = None

    @model_validator(mode="after")
    def _fits(self) -> Compare:
        if any(len(r.values) != len(self.items) for r in self.rows):
            raise ValueError("every row needs one value per item")
        if self.pick is not None and not 0 <= self.pick < len(self.items):
            raise ValueError("pick is the index of one of the items")
        return self


class Diagram(_Strict):
    shape: Literal["diagram"]
    title: _words(TITLE_MAX) | None = None
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=SOURCE_MAX),
                      AfterValidator(_mermaid)]


class Idea(_Strict):
    label: _words(LABEL_MAX)
    children: list[Idea] = Field(default_factory=list, max_length=MAP_IDEAS)


def _ideas(ideas: list[Idea], depth: int = 1) -> int:
    """How many ideas the branches hold; deeper than the limit is refused."""
    if ideas and depth > MAP_DEPTH:
        raise ValueError("at most three levels under the root")
    return sum(1 + _ideas(i.children, depth + 1) for i in ideas)


class MindMap(_Strict):
    shape: Literal["mindmap"]
    title: _words(TITLE_MAX) | None = None
    root: _words(LABEL_MAX)
    children: list[Idea] = Field(min_length=1, max_length=MAP_IDEAS)

    @model_validator(mode="after")
    def _fits(self) -> MindMap:
        if _ideas(self.children) > MAP_IDEAS:
            raise ValueError("at most thirty ideas")
        return self


class Preview(_Strict):
    shape: Literal["preview"]
    path: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32767),
                    AfterValidator(_preview_path)]


class ChartSeries(_Strict):
    name: _words(40)
    values: list[FiniteFloat] = Field(min_length=2, max_length=CHART_POINTS)


class Chart(_Strict):
    shape: Literal["chart"]
    title: _words(TITLE_MAX) | None = None
    type: Literal["bar", "line"]
    x: list[_words(CHART_LABEL_MAX)] = Field(min_length=2, max_length=CHART_POINTS)
    series: list[ChartSeries] = Field(min_length=1, max_length=CHART_SERIES)
    unit: _words(16) | None = None

    @model_validator(mode="after")
    def _fits(self) -> Chart:
        if any(len(s.values) != len(self.x) for s in self.series):
            raise ValueError("each series needs one value per category")
        if any(abs(value) > CHART_VALUE_MAX for s in self.series for value in s.values):
            raise ValueError("chart values are out of range")
        if len({s.name.casefold() for s in self.series}) != len(self.series):
            raise ValueError("series names must be distinct")
        return self


class ProjectCard(_Strict):
    title: _words(PROJECT_TITLE_MAX)
    detail: _words(PROJECT_DETAIL_MAX) | None = None
    meta: _words(PROJECT_META_MAX) | None = None


class Cards(_Strict):
    shape: Literal["cards"]
    title: _words(TITLE_MAX) | None = None
    cards: list[ProjectCard] = Field(min_length=1, max_length=PROJECT_CARDS)


MODELS: dict[str, type[_Strict]] = {
    "compare": Compare, "diagram": Diagram, "mindmap": MindMap, "preview": Preview, "chart": Chart, "cards": Cards,
}


# What the tool's input schema says, for the SDK's own check; the backend checks again above.
_CELL = {"type": "string", "maxLength": CELL_MAX}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "shape": {"type": "string", "enum": list(MODELS)},
        "title": {"type": "string", "maxLength": TITLE_MAX},
        "items": {"type": "array", "items": _CELL, "minItems": 2, "maxItems": MAX_ITEMS},
        "rows": {"type": "array", "maxItems": MAX_ROWS, "minItems": 1, "items": {
            "type": "object", "properties": {"label": _CELL, "values": {"type": "array", "items": _CELL}},
            "required": ["label", "values"]}},
        "pick": {"type": "integer", "minimum": 0},
        "source": {"type": "string", "maxLength": SOURCE_MAX},
        "root": {"type": "string", "maxLength": LABEL_MAX},
        "children": {"type": "array", "maxItems": MAP_IDEAS, "items": {
            "type": "object", "properties": {"label": {"type": "string", "maxLength": LABEL_MAX},
                                             "children": {"type": "array", "items": {"type": "object"}}},
            "required": ["label"]}},
        "path": {"type": "string", "minLength": 1, "maxLength": 32767},
        "type": {"type": "string", "enum": ["bar", "line"]},
        "x": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": CHART_LABEL_MAX},
              "minItems": 2, "maxItems": CHART_POINTS},
        "series": {"type": "array", "minItems": 1, "maxItems": CHART_SERIES, "items": {
            "type": "object", "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 40},
                "values": {"type": "array", "items": {
                    "type": "number", "minimum": -CHART_VALUE_MAX, "maximum": CHART_VALUE_MAX,
                }, "minItems": 2, "maxItems": CHART_POINTS},
            }, "required": ["name", "values"]}},
        "unit": {"type": "string", "minLength": 1, "maxLength": 16},
        "cards": {"type": "array", "minItems": 1, "maxItems": PROJECT_CARDS, "items": {
            "type": "object", "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": PROJECT_TITLE_MAX},
                "detail": {"type": "string", "minLength": 1, "maxLength": PROJECT_DETAIL_MAX},
                "meta": {"type": "string", "minLength": 1, "maxLength": PROJECT_META_MAX},
            }, "required": ["title"]}},
    },
    "required": ["shape"],
}

DESCRIPTION = (
    "Show the result on the user's card in a shape that fits it, instead of only words. shape 'compare': "
    "2-4 options (items) side by side on up to 12 measures (rows: a label and one short value per item); "
    "pick: the index of the option you recommend, if any. Use it when the answer compares options. shape "
    "'diagram': Mermaid source (one of flowchart, sequenceDiagram, stateDiagram-v2, classDiagram, erDiagram, "
    "timeline, gantt, quadrantChart, journey; at most 40 lines, plain labels, no click, links, style, classDef or "
    "init directives). Use it when a picture of steps or parts explains the answer. shape 'mindmap': a root "
    "label and its children, each {label, children}, at most 3 levels under the root and 30 ideas, labels up to "
    "60 characters of plain text. Use it for ideas grouped under a theme. shape 'preview': a local path to a "
    "PDF, DOCX, PPTX or XLSX file the user asked about and you have read; Swift makes the preview from the file. "
    "shape 'chart': a simple bar or line chart; x has 2-8 short category labels and series has 1-4 named sets "
    "of finite numbers, one per category. An optional unit labels the values. shape 'cards': 1-8 project cards, "
    "each with a short title and optional detail and meta. Use cards for a small set of projects, not a long list. "
    "Keep "
    "the data out of your final answer: that answer is said aloud, so make it the conclusion in one or two "
    "sentences. Call it at most once, before your final answer; if it's refused, answer in words."
)


def check(args: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """The worker's shape as Swift will draw it, or None and why not: field roles and error kinds only,
    never the worker's words, so the reasons can go to the log as they are."""
    name = args.get("shape") if isinstance(args, dict) else None
    model = MODELS.get(name) if isinstance(name, str) else None
    if model is None:
        return None, ["shape:unknown"]
    try:
        shape = model.model_validate(args)
    except ValidationError as exc:
        return None, sorted({f"{'.'.join(str(p) for p in e['loc'] if not isinstance(p, int)) or 'shape'}:{e['type']}"
                             for e in exc.errors()})
    return shape.model_dump(exclude_none=True), []


def extent(shape: dict[str, Any]) -> tuple[int, int]:
    """How much a checked shape holds, and how much of that a card shows (the rest opens with Read more)."""
    if shape["shape"] == "preview":
        return 1, 1
    if shape["shape"] == "diagram":
        lines = _statements(shape["source"])
        return len(lines), CARD_LINES_TALL if DIAGRAM_KINDS[lines[0].split()[0]] else CARD_LINES
    if shape["shape"] == "mindmap":
        return _ideas([Idea.model_validate(i) for i in shape["children"]]), CARD_IDEAS
    if shape["shape"] == "chart":
        return len(shape["x"]), CARD_CHART_POINTS
    if shape["shape"] == "cards":
        text_units = len(shape.get("title", "")) + sum(
            len(card["title"]) + len(card.get("detail", "")) + len(card.get("meta", "")) for card in shape["cards"]
        )
        return len(shape["cards"]) + text_units // PROJECT_TEXT_UNITS, CARD_PROJECT_CARDS
    return len(shape["rows"]), CARD_ROWS


def details(shape: dict[str, Any], rest: str = "", preview: PreparedPreview | None = None) -> dict[str, Any]:
    """The result's ``details`` frame: the checked shape, its size and who made it, all set by Swift. ``rest``:
    the answer's words after the spoken summary, kept under the shape so nothing the worker wrote is lost."""
    if shape["shape"] == "preview":
        if preview is None:
            raise ValueError("a preview must be prepared before it is sent to the overlay")
        size = "expanded" if preview.excerpt and len(preview.excerpt) > 240 else "card"
        return {
            "kind": "preview", "path": preview.path, "title": preview.title, "file_type": preview.kind,
            "thumbnail": preview.thumbnail, "pages": preview.pages, "excerpt": preview.excerpt, "by": "swift",
            "size": size, **({"text": rest} if rest.strip() else {}),
        }
    held, fits = extent(shape)
    size = "expanded" if held > fits else "card"
    return {"kind": shape["shape"], **{k: v for k, v in shape.items() if k != "shape"}, "by": "worker", "size": size,
            **({"text": rest} if rest.strip() else {})}
