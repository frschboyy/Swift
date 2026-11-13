"""Gmail's compose window, filled in (A9, owner's run of 2026-11-13): against a fake screen.

The real screen is ``windows._GmailScreen`` (Win32 and UI Automation); these drive the steps in
``desktop/gmail_fill.py`` as it calls them. Nothing here touches a real window.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import pytest
from loguru import logger

from swift.desktop import gmail_fill
from swift.desktop.base import DesktopError
from swift.logging_setup import make_patcher

TO = ["ada@example.com"]
SUBJECT = "Lunch on Friday"
BODY = "Hi Ada,\nShall we have lunch on Friday?\nFrancis"
WORDS = ("Lunch", "Friday", "Ada", "Shall", "ada@example.com")  # none of the email may reach the log

COMPOSE, OTHER_BROWSER, WORD = 10, 20, 30


@dataclass
class Window:
    browser: bool = True
    fields: tuple[str, ...] = gmail_fill.FIELDS
    subject: str = ""
    private: bool = False
    label: str = "Chrome"


@dataclass
class FakeScreen:
    """Windows and Gmail's fields as ``gmail_fill`` sees them.

    ``focus_after``: how many ``set_focus`` calls on the body before the keyboard is in it (0: never;
    the owner's run: Gmail's body didn't take it). ``click_lands``: whether a click at the body's top
    left is the body. ``forward``: whether Windows lets Swift bring a window forward.
    """

    windows: dict[int, Window]
    front_hwnd: int = COMPOSE
    focus_after: int = 1
    click_lands: bool = True
    forward: bool = True
    focused: str | None = "to"  # Gmail puts the cursor in To when a compose window opens
    focus_calls: int = 0
    clicks: list[tuple[str, int]] = field(default_factory=list)
    text: dict[str, str] = field(default_factory=dict)
    steps: list[str] = field(default_factory=list)

    def front(self) -> int:
        return self.front_hwnd

    def front_label(self, hwnd: int) -> str:
        return self.windows[hwnd].label if hwnd in self.windows else "none"

    def is_browser(self, hwnd: int) -> bool:
        return hwnd in self.windows and self.windows[hwnd].browser

    def private(self, hwnd: int) -> bool:
        return self.windows[hwnd].private

    def browser_windows(self) -> list[int]:
        return [h for h, w in self.windows.items() if w.browser]

    def fields(self, hwnd: int) -> dict[str, Any]:
        return {key: (hwnd, key) for key in self.windows[hwnd].fields}

    def subject_in_use(self, fields: dict[str, Any]) -> bool:
        return bool(self.windows[fields["subject"][0]].subject)

    def bring_forward(self, hwnd: int) -> bool:
        if self.forward:
            self.front_hwnd = hwnd
        return self.forward

    def settable(self, element: Any) -> bool:
        return element[1] != "body"  # To and Subject have a Value pattern; the body is rich text

    def set_value(self, element: Any, text: str) -> None:
        self.text[element[1]] = text
        self.steps.append(f"set {element[1]}")

    def value(self, element: Any) -> str | None:
        return self.text.get(element[1], "")

    def set_focus(self, element: Any) -> None:
        if element[1] == "body":
            self.focus_calls += 1
            if self.focus_after and self.focus_calls >= self.focus_after:
                self.focused = "body"

    def has_focus(self, element: Any) -> bool:
        return self.focused == element[1] and self.front_hwnd == element[0]

    def focus_place(self, fields: dict[str, Any], hwnd: int) -> str:
        return self.focused or "none"

    def click(self, element: Any, hwnd: int) -> bool:
        if self.front_hwnd != hwnd or not self.click_lands:
            return False
        self.clicks.append((element[1], hwnd))
        self.focused = element[1]
        return True

    def paste(self, text: str) -> None:
        assert self.focused is not None
        self.text[self.focused] = self.text.get(self.focused, "") + text
        self.steps.append(f"paste {self.focused}")


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def _clock() -> gmail_fill.Clock:
    c = FakeClock()
    return gmail_fill.Clock(now=c.now, sleep=c.sleep)


def _captured() -> io.StringIO:
    sink = io.StringIO()
    logger.remove()
    logger.configure(patcher=make_patcher(False), extra={"_extra": "", "_exc": ""})
    logger.add(sink, format="{message}{extra[_extra]}\n", level="INFO", backtrace=False, diagnose=False)
    return sink


def _fill(screen: FakeScreen) -> None:
    found = gmail_fill.find_compose(screen)
    assert not isinstance(found, gmail_fill.Waiting), found
    gmail_fill.fill(screen, *found, TO, SUBJECT, BODY, clock=_clock())


def _content_free(log: str) -> None:
    for word in WORDS:
        assert word not in log, (word, log)


# ---- the log says why (check 256) -------------------------------------------------------------------


def test_a_body_that_won_t_take_the_cursor_says_so_in_the_log_without_the_email() -> None:
    screen = FakeScreen({COMPOSE: Window()}, focus_after=0, click_lands=False)
    sink = _captured()
    try:
        with pytest.raises(DesktopError) as failed:
            _fill(screen)
    finally:
        logger.remove()
    log = sink.getvalue()
    assert failed.value.code == "gmail_focus_body"
    assert "gmail field didn't take the cursor" in log and "field='body'" in log and "focus='to'" in log, log
    assert "body" not in screen.text  # nothing was pasted anywhere
    _content_free(log)


def test_a_compose_window_that_never_appears_says_which_step_it_waited_on() -> None:
    screen = FakeScreen({WORD: Window(browser=False, label="Word")}, front_hwnd=WORD)
    waiting = gmail_fill.find_compose(screen)
    assert waiting == gmail_fill.Waiting("not_browser", "Word")
    sink = _captured()
    try:
        error = gmail_fill.gave_up(waiting, 20.4)
    finally:
        logger.remove()
    assert error.code == "gmail_not_in_front"
    assert "reason='not_browser'" in sink.getvalue() and "front='Word'" in sink.getvalue(), sink.getvalue()


def test_a_page_still_loading_is_not_loaded_with_the_fields_found_so_far() -> None:
    screen = FakeScreen({COMPOSE: Window(fields=("to",))})
    waiting = gmail_fill.find_compose(screen)
    assert waiting == gmail_fill.Waiting("not_loaded", "Chrome", ("to",))
    assert gmail_fill.gave_up(waiting, 20).code == "gmail_not_loaded"


def test_a_private_window_in_front_is_refused_with_its_own_code() -> None:
    with pytest.raises(DesktopError) as failed:
        gmail_fill.find_compose(FakeScreen({COMPOSE: Window(private=True)}))
    assert failed.value.code == "gmail_private"


async def test_the_gateway_logs_the_desktop_s_reason_code() -> None:
    """End to end through the workflow tool: the line the owner's log had with no reason now has one."""
    from test_desktop import make

    host, desktop, _, _ = make(said="email my lecturer")
    found = await host.call("find_contact", {"query": "lecturer"})
    draft = await host.call("draft_email", {"to": [found.data["candidates"][0]["email"]], "subject": SUBJECT,
                                            "message": BODY})

    async def refused(*_: Any) -> str:
        raise DesktopError("Swift couldn't put the cursor in Gmail's body, so it stopped there.", "",
                           code="gmail_focus_body")

    desktop.fill_in_email = refused  # type: ignore[method-assign]
    sink = _captured()
    try:
        result = await host.call("fill_in_email", {"draft_id": draft.data["draft_id"]})
    finally:
        logger.remove()
    _content_free(sink.getvalue())
    assert not result.ok
    assert "action failed" in sink.getvalue() and "code='gmail_focus_body'" in sink.getvalue(), sink.getvalue()


# ---- the body takes the cursor (check 257) --------------------------------------------------------------


def test_the_body_is_pasted_into_once_it_has_the_cursor_and_the_subject_is_set_last() -> None:
    screen = FakeScreen({COMPOSE: Window()})
    _fill(screen)
    assert screen.steps == ["set to", "paste body", "set subject"]
    assert screen.text == {"to": TO[0], "body": BODY, "subject": SUBJECT} and not screen.clicks


def test_gmail_taking_the_cursor_back_once_is_asked_again() -> None:
    screen = FakeScreen({COMPOSE: Window()}, focus_after=2)
    sink = _captured()
    try:
        _fill(screen)
    finally:
        logger.remove()
    assert screen.text["body"] == BODY and screen.focus_calls == 2 and not screen.clicks
    assert "how='set_focus_again'" in sink.getvalue()


def test_a_body_that_ignores_set_focus_is_clicked_in_like_the_owner_does() -> None:
    """The owner's run: nothing was written unless the cursor was already in the body."""
    screen = FakeScreen({COMPOSE: Window()}, focus_after=0)
    sink = _captured()
    try:
        _fill(screen)
    finally:
        logger.remove()
    assert screen.clicks == [("body", COMPOSE)]
    assert screen.text == {"to": TO[0], "body": BODY, "subject": SUBJECT}
    assert "how='click'" in sink.getvalue()
    _content_free(sink.getvalue())


def test_no_click_lands_outside_the_body_and_nothing_is_pasted() -> None:
    screen = FakeScreen({COMPOSE: Window()}, focus_after=0, click_lands=False)
    with pytest.raises(DesktopError):
        _fill(screen)
    assert not screen.clicks and "paste body" not in screen.steps


def test_the_cursor_already_in_the_body_still_works() -> None:
    screen = FakeScreen({COMPOSE: Window()}, focused="body", focus_after=0)
    _fill(screen)
    assert screen.text["body"] == BODY and not screen.clicks


def test_a_window_with_a_subject_is_never_filled() -> None:
    """A reply or the owner's own draft: To would be replaced. Only an empty compose window is Swift's."""
    assert gmail_fill.find_compose(FakeScreen({COMPOSE: Window(subject="Re: their thread")})) == gmail_fill.Waiting(
        "in_use", "Chrome", gmail_fill.FIELDS)
