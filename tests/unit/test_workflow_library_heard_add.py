"""Owner check 31 (2026-11-13): "add" heard as "had" or "Ad" reaches the calendar workflow, only as the first word."""

import pytest

from swift.workflows.library import load_library

LIB = load_library()


@pytest.mark.parametrize("said", ["had lunch with Test Me tomorrow at one.", "Ad lunch next week",
                                  "had a call with Ada on Friday at 3", "Hey Swift, had dinner with Sam on Friday"])
def test_add_as_heard_runs_the_calendar_workflow(said: str) -> None:
    m = LIB.match(said)
    assert m is not None and m.package.name == "calendar-event"


@pytest.mark.parametrize("said", ["I had lunch with Sam yesterday at noon", "had I added the meeting?",
                                  "what had the meeting covered", "Ad blocker settings", "had lunch with Sam?"])
def test_had_elsewhere_or_as_a_question_does_not(said: str) -> None:
    assert LIB.match(said) is None
