"""B14: "done" and "5 more" act only while a timer's Due card is in front (swift/timers.py ``heard``)."""

from types import SimpleNamespace

from swift import timers


def _session(front: str | None) -> SimpleNamespace:
    return SimpleNamespace(_drawn=SimpleNamespace(front=front), system=None)


def test_done_needs_a_timers_due_card_in_front() -> None:
    tea = SimpleNamespace(kind="timer", label="tea")
    timers.remember("due-timer-1", [tea])
    assert timers.heard(_session(None), "done") is None  # nothing in front: an ordinary request
    assert timers.heard(_session("a-run"), "done") is None
    assert timers.heard(_session("due-timer-1"), "what's the weather") is None
    assert timers.heard(_session("due-timer-1"), "Hey Swift, done.") == ("Done: Tea timer.", None)
    assert timers.heard(_session("due-timer-1"), "done") is None  # answered: the card's items are gone


def test_a_reminder_is_not_a_timer() -> None:
    timers.remember("due-reminder-2", [SimpleNamespace(kind="reminder", label="call Ada")])
    assert timers.heard(_session("due-reminder-2"), "five more") is None
