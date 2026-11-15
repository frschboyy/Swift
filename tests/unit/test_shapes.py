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
