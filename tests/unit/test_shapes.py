"""B4: the worker's proposed shape, as Swift checks, sizes and marks it (swift/shapes.py, show_result)."""

from __future__ import annotations

from typing import Any

import pytest

from swift import shapes
from swift.executors.claude_code import ClaudeCodeExecutor, _Run, _show_result
from swift.executors.claude_mapping import Outcome

LAPTOPS: dict[str, Any] = {
    "shape": "compare", "title": "Laptops for travel", "items": ["Zenbook 14", "XPS 13", "Swift Go"],
    "rows": [{"label": "Weight", "values": ["1.2 kg", "1.2 kg", "1.3 kg"]},
             {"label": "Battery", "values": ["15 h", "12 h", "<10 h"]}],
    "pick": 0,
}


def test_a_comparison_is_kept_as_sent() -> None:
    shape, problems = shapes.check(LAPTOPS)
    assert problems == [] and shape == LAPTOPS  # "<10 h" isn't markup


@pytest.mark.parametrize("change", [
    {"items": ["Only one"]},
    {"items": ["a", "b", "c", "d", "e"]},
    {"rows": []},
    {"rows": [{"label": f"r{i}", "values": ["1", "2", "3"]} for i in range(13)]},
    {"rows": [{"label": "Weight", "values": ["1.2 kg", "1.2 kg"]}]},  # a value missing
    {"rows": [{"label": "Weight", "values": ["<img src=x onerror=alert(1)>", "1", "2"]}]},
    {"rows": [{"label": "Weight", "values": ["&lt;b&gt;", "1", "2"]}]},
    {"rows": [{"label": "Weight", "values": ["fine‮", "1", "2"]}]},  # a bidi override
    {"rows": [{"label": "", "values": ["1", "2", "3"]}]},
    {"rows": [{"label": "x" * 161, "values": ["1", "2", "3"]}]},
    {"pick": 3}, {"pick": -1}, {"pick": "0"},
    {"shape": "diagram"},
    {"onclick": "x"},  # nothing the schema doesn't name
])
def test_anything_out_of_shape_is_refused_whole(change: dict[str, Any]) -> None:
    shape, problems = shapes.check(LAPTOPS | change)
    assert shape is None and problems


def test_the_reasons_name_fields_never_the_workers_words() -> None:
    secret = "<b>Dr Ada's salary</b>"
    _, problems = shapes.check(LAPTOPS | {"rows": [{"label": secret, "values": ["1", "2", "3"]}]})
    assert problems == ["rows.label:value_error"] and not any("Ada" in p for p in problems)
    assert shapes.check("not a shape")[0] is None and shapes.check(None)[0] is None


def test_swift_sets_the_size_and_the_mark() -> None:
    shape, _ = shapes.check(LAPTOPS | {"by": "swift"})
    assert shape is None  # the worker can't say who made it
    card = shapes.details(shapes.check(LAPTOPS)[0])
    assert card["kind"] == "compare" and card["by"] == "worker" and card["size"] == "card" and "text" not in card
    rows = [{"label": f"r{i}", "values": ["1", "2", "3"]} for i in range(7)]
    assert shapes.details(shapes.check(LAPTOPS | {"rows": rows})[0])["size"] == "expanded"


def test_the_tool_keeps_a_checked_shape_and_a_done_answer_shows_it() -> None:
    run = _Run()
    assert "Swift will show this" in _show_result(run, LAPTOPS)
    outcome = Outcome("done", "The Zenbook fits travel best.", {"kind": "text", "text": "Prices vary."}, {})
    final = ClaudeCodeExecutor._final(run, outcome, None)
    assert final.status == "done" and final.summary == "The Zenbook fits travel best."
    assert final.details is not None and final.details["kind"] == "compare"
    assert final.details["items"] == LAPTOPS["items"] and final.details["text"] == "Prices vary."  # nothing lost


def test_a_refused_shape_leaves_the_words() -> None:
    run = _Run()
    assert "Answer in words" in _show_result(run, LAPTOPS | {"pick": 9})
    outcome = Outcome("done", "Zenbook.", {"kind": "list", "items": ["light"]}, {})
    assert ClaudeCodeExecutor._final(run, outcome, None).details == {"kind": "list", "items": ["light"]}


def test_a_shape_never_reaches_an_answer_that_isnt_done() -> None:
    """§7.6: shapes on Done results only, never on a stop, a refusal or a failure."""
    for setup in ("cancelled", "rejected", "error"):
        run = _Run()
        _show_result(run, LAPTOPS)
        if setup == "cancelled":
            run.cancelled = True
        if setup == "rejected":
            run.stopped_by = ("reject", "Edit")
        outcome = Outcome("error", "Failed.", None, {}) if setup == "error" else Outcome("done", "x", None, {})
        assert ClaudeCodeExecutor._final(run, outcome, None).details is None, setup


# ---- diagram: Mermaid source, refused unless it only draws ---------------------------------------------------

FLOW: dict[str, Any] = {"shape": "diagram", "title": "How a request runs",
                        "source": "flowchart LR\n  A[You ask] --> B{Needs an OK?}\n  B -->|yes| C[Card]\n  B -->|no| D[Done]"}


def test_a_diagram_is_kept_as_sent_and_sized_by_swift() -> None:
    shape, problems = shapes.check(FLOW)
    assert problems == [] and shape == FLOW
    card = shapes.details(shape)
    assert card["kind"] == "diagram" and card["by"] == "worker" and card["size"] == "card"
    long = "flowchart TD\n" + "\n".join(f"  N{i} --> N{i + 1}" for i in range(12))
    assert shapes.details(shapes.check(FLOW | {"source": long})[0])["size"] == "expanded"
    seq = "sequenceDiagram\n" + "\n".join(f"  A->>B: step {i}" for i in range(6))  # tall: six messages fill a card
    assert shapes.details(shapes.check(FLOW | {"source": seq})[0])["size"] == "expanded"
    for kind in ["graph TD", "stateDiagram-v2", "classDiagram", "erDiagram", "timeline", "gantt", "quadrantChart",
                 "journey", "sequenceDiagram"]:
        assert shapes.check(FLOW | {"source": f"%% a comment\n{kind}\n  x"})[1] == [], kind
    assert shapes.check(FLOW | {"source": "classDiagram\n  Animal <|-- Duck\n  A --> B : call it"})[1] == []


@pytest.mark.parametrize("source", [
    "pie\n  \"a\" : 1",  # not a kind §4 vetted
    "mindmap\n  root",  # tiny leaves it out; Swift draws mind maps itself
    "architecture-beta\n  service a",
    "---\nconfig:\n  securityLevel: loose\n---\nflowchart LR\n  A --> B",  # front matter
    "%%{init: {'securityLevel': 'loose'}}%%\nflowchart LR\n  A --> B",
    "flowchart LR\n  A --> B\n  click A \"https://example.com\"",
    "flowchart LR\n  A --> B\n  click A call alert(1)",
    "flowchart LR\n  A --> B\n  CLICK A callback",
    "classDiagram\n  class A\n  link A \"x\"",
    "flowchart LR\n  A[\"<img src=x onerror=alert(1)>\"] --> B",
    "flowchart LR\n  A[\"<b>bold</b>\"] --> B",
    "flowchart LR\n  A[\"#lt;script#gt;\"] --> B",
    "flowchart LR\n  A[\"&lt;b&gt;\"] --> B",
    "flowchart LR\n  A --> B\n  style A fill:url(https://x/y.svg)",
    "flowchart LR\n  A --> B\n  classDef red fill:red",
    "flowchart LR\n  A@{ img: \"https://x/p.png\" } --> B",
    "flowchart LR\n  A[see https://example.com] --> B",
    "flowchart LR\n  A[javascript:alert] --> B",
    "flowchart LR\n  A[fine‮] --> B",  # a bidi override
    "flowchart LR\r  A --> B",
    "flowchart LR\n" + "\n".join(f"  N{i} --> N{i + 1}" for i in range(40)),  # 41 lines
    "flowchart LR\n  " + "A --> B " * 400,  # over 3000 characters
    "", "   ", "%% only a comment",
])
def test_a_diagram_that_does_more_than_draw_is_refused_whole(source: str) -> None:
    shape, problems = shapes.check(FLOW | {"source": source})
    assert shape is None and problems == ["source:" + problems[0].split(":", 1)[1]]


def test_a_diagram_takes_nothing_else() -> None:
    for change in ({"source": None}, {"source": ["flowchart"]}, {"items": ["a", "b"]}, {"by": "swift"}):
        assert shapes.check(FLOW | change)[0] is None, change
    assert shapes.check({"shape": ["diagram"]}) == (None, ["shape:unknown"])


# ---- mind map: a small tree of short labels, drawn by Swift's own code ----------------------------------------

PARTY: dict[str, Any] = {"shape": "mindmap", "title": "Party ideas", "root": "Birthday party", "children": [
    {"label": "Games", "children": [{"label": "Treasure hunt", "children": []}, {"label": "Musical chairs", "children": [
        {"label": "Needs a speaker", "children": []}]}]},
    {"label": "Food", "children": [{"label": "Pizza", "children": []}]},
]}


def _tree(depth: int) -> dict[str, Any]:
    """One idea per level, ``depth`` levels deep (built in a loop: a deep one must not overflow here)."""
    node: dict[str, Any] = {"label": "level 1", "children": []}
    for level in range(2, depth + 1):
        node = {"label": f"level {level}", "children": [node]}
    return node


def test_a_mind_map_is_kept_as_sent_and_sized_by_swift() -> None:
    shape, problems = shapes.check(PARTY)
    assert problems == [] and shape == PARTY
    card = shapes.details(shape)
    assert card["kind"] == "mindmap" and card["by"] == "worker" and card["size"] == "card" and card["root"] == "Birthday party"
    assert shapes.check(PARTY | {"children": [{"label": "Games"}]})[0] == PARTY | {"children": [{"label": "Games", "children": []}]}
    thirteen = [{"label": f"Idea {i}"} for i in range(13)]
    assert shapes.details(shapes.check(PARTY | {"children": thirteen})[0])["size"] == "expanded"
    thirty = [{"label": f"Branch {b}", "children": [{"label": f"Idea {b}.{i}"} for i in range(5)]} for b in range(5)]
    assert shapes.check(PARTY | {"children": thirty})[1] == []  # 5 branches + 25 ideas: the limit
    assert shapes.check(PARTY | {"children": [_tree(3)]})[1] == []  # three levels under the root


@pytest.mark.parametrize("change", [
    {"children": []},
    {"children": [_tree(4)]},  # a fourth level
    {"children": [_tree(2000)]},  # far too deep: refused, not a crash
    {"children": [{"label": f"Branch {b}", "children": [{"label": f"Idea {b}.{i}"} for i in range(5)]} for b in range(6)]},  # 36
    {"root": ""}, {"root": "x" * 61},
    {"children": [{"label": "<script>alert(1)</script>"}]},
    {"children": [{"label": "Games", "children": [{"label": "&amp; more"}]}]},
    {"children": [{"label": "line\nbreak"}]},
    {"children": [{"label": "fine​"}]},  # a zero-width space
    {"children": [{"label": ""}]},
    {"children": [{"label": "Games", "colour": "red"}]},
    {"children": ["Games"]},
    {"source": "flowchart LR"},
])
def test_a_mind_map_out_of_shape_is_refused_whole(change: dict[str, Any]) -> None:
    shape, problems = shapes.check(PARTY | change)
    assert shape is None and problems


def test_a_preview_is_a_supported_local_document_and_swift_sets_its_frame() -> None:
    from swift.previews import PreparedPreview

    shape, problems = shapes.check({"shape": "preview", "path": r"C:\Users\owner\Documents\brief.pdf"})
    assert problems == [] and shape == {"shape": "preview", "path": r"C:\Users\owner\Documents\brief.pdf"}
    preview = PreparedPreview(r"C:\Users\owner\Documents\brief.pdf", "brief.pdf", "pdf", "cG5n", 4)
    details = shapes.details(shape, preview=preview)
    assert details == {
        "kind": "preview", "path": preview.path, "title": "brief.pdf", "file_type": "pdf",
        "thumbnail": "cG5n", "pages": 4, "excerpt": None, "by": "swift", "size": "card",
    }


@pytest.mark.parametrize("path", [
    "https://example.test/brief.pdf",
    r"C:\Users\owner\Documents\notes.txt",
    "brief.pdf\u202e",
    "",
])
def test_a_preview_refuses_nonlocal_unsupported_or_hidden_paths(path: str) -> None:
    shape, problems = shapes.check({"shape": "preview", "path": path})
    assert shape is None and problems
