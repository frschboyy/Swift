"""ADR-019 §8.3: "Try again from step N" tells the worker where to pick up, as Swift's note, never the owner's words."""

from swift import retrying


def test_only_a_step_past_the_first_is_believed() -> None:
    assert retrying.resume_from({"from_step": 3}) == 3
    assert retrying.resume_from({}) is None
    for bad in (1, 0, -2, True, "3", 3.0, retrying.MAX_STEP + 1):
        assert retrying.resume_from({"from_step": bad}) is None, bad


def test_the_note_is_for_a_retry_only() -> None:
    note = retrying.note({"source": "retry", "resume_from": 3})
    assert note.startswith("Swift's note:") and "from step 3" in note and "Steps 1 to 2" in note
    assert "Step 1 of" in retrying.note({"source": "retry", "resume_from": 2})
    assert retrying.note({"source": "voice", "resume_from": 3}) == ""  # a request never carries it
    assert retrying.note({"source": "retry", "resume_from": None}) == ""
