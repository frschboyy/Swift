"""B4: a result laid out to fit it (docs/design/b4-adaptive-results.md §2).

The worker proposes a shape through the ``show_result`` tool; this module is where Swift checks it, sizes it
and marks it. What the worker sends is untrusted data: every field is checked here (lengths, counts, no markup,
no hidden characters), and anything that fails is refused whole, so the card falls back to today's text. The
overlay draws the frame as data with textContent (``overlay/src/blocks.ts``), never as HTML.

Only ``compare`` today (owner's order, §7.5): diagram, mind map, preview, chart and cards are later shapes.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

MAX_ITEMS = 4
MAX_ROWS = 12
CELL_MAX = 160
TITLE_MAX = 120
# More rows than a card shows (``renderDetails``' six) opens the answer in full (B5's expanded card later).
CARD_ROWS = 6

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


# What the tool's input schema says, for the SDK's own check; the backend checks again above.
_CELL = {"type": "string", "maxLength": CELL_MAX}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "shape": {"type": "string", "enum": ["compare"]},
        "title": {"type": "string", "maxLength": TITLE_MAX},
        "items": {"type": "array", "items": _CELL, "minItems": 2, "maxItems": MAX_ITEMS},
        "rows": {"type": "array", "maxItems": MAX_ROWS, "minItems": 1, "items": {
            "type": "object", "properties": {"label": _CELL, "values": {"type": "array", "items": _CELL}},
            "required": ["label", "values"]}},
        "pick": {"type": "integer", "minimum": 0},
    },
    "required": ["shape", "items", "rows"],
}

DESCRIPTION = (
    "Show the result on the user's card in a shape that fits it, instead of only words. shape 'compare': "
    "2-4 options (items) side by side on up to 12 measures (rows: a label and one short value per item); "
    "pick: the index of the option you recommend, if any. Use it when the answer compares options. Keep "
    "the data out of your final answer: that answer is said aloud, so make it the conclusion in one or two "
    "sentences. Call it at most once, before your final answer; if it's refused, answer in words."
)


def check(args: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """The worker's shape as Swift will draw it, or None and why not: field roles and error kinds only,
    never the worker's words, so the reasons can go to the log as they are."""
    try:
        shape = Compare.model_validate(args)
    except ValidationError as exc:
        return None, sorted({f"{'.'.join(str(p) for p in e['loc'] if not isinstance(p, int)) or 'shape'}:{e['type']}"
                             for e in exc.errors()})
    return shape.model_dump(exclude_none=True), []


def details(shape: dict[str, Any], rest: str = "") -> dict[str, Any]:
    """The result's ``details`` frame: the checked shape, its size and who made it, all set by Swift. ``rest``:
    the answer's words after the spoken summary, kept under the shape so nothing the worker wrote is lost."""
    size = "expanded" if len(shape["rows"]) > CARD_ROWS else "card"
    return {"kind": "compare", **{k: v for k, v in shape.items() if k != "shape"}, "by": "worker", "size": size,
            **({"text": rest} if rest.strip() else {})}
