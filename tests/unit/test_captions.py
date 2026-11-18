"""A6, captions: off by default, on and off by the owner's words, and only while on does the speech frame carry
what Swift is saying."""

from __future__ import annotations

from pathlib import Path

from swift import captions, memory
from swift.memory import Store


def test_the_phrases() -> None:
    for on in ("captions on", "Hey Swift, turn captions on", "show captions", "turn on the captions"):
        assert captions.parse(on) == "captions_on", on
    for off in ("captions off", "Swift, turn off captions", "hide the captions", "no more captions"):
        assert captions.parse(off) == "captions_off", off
    assert captions.parse("what are captions") is None and memory.parse("captions on") == ("captions_on", "")


def test_off_by_default_on_from_the_owners_words_and_the_frame_carries_text_only_then(tmp_path: Path) -> None:
    store = Store(tmp_path)
    assert captions.spoken(store, "It's 3:42 pm.") == {}  # off by default
    memory.answer(store, "Swift, captions on", "click", "r1")  # a button a worker may have worded: no
    assert not captions.is_on(store)
    memory.answer(store, "captions on", "voice", "r2")
    assert captions.spoken(store, "It's 3:42 pm.") == {"text": "It's 3:42 pm."} and captions.spoken(store, "") == {}
    assert captions.is_on(Store(tmp_path))  # kept across restarts
    assert memory.answer(store, "what do you know about me", "voice", "r3")[0].startswith("You haven't")  # a setting
    memory.answer(store, "captions off", "typed", "r4")
    assert captions.spoken(store, "It's 3:42 pm.") == {}
