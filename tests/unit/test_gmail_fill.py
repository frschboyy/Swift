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
    to_closed: bool = False  # Gmail's To row collapsed to "Recipients": no To box until it has the keyboard


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
        window = self.windows[hwnd]
        return {key: (hwnd, key) for key in window.fields if not (key == "to" and window.to_closed)}

    def open_to(self, hwnd: int) -> bool:
        window = self.windows[hwnd]
        if not window.to_closed or "to" not in window.fields:
            return False
        window.to_closed = False
        self.steps.append(f"open to {hwnd}")
        return True

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


# ---- the compose window behind another app (check 258) -----------------------------------------------


def test_a_compose_window_behind_the_app_in_front_is_brought_forward_and_filled() -> None:
    screen = FakeScreen({WORD: Window(browser=False, label="Word"), COMPOSE: Window()}, front_hwnd=WORD)
    _fill(screen)
    assert screen.front_hwnd == COMPOSE and screen.text["body"] == BODY


def test_a_compose_window_windows_won_t_bring_forward_waits_and_says_so() -> None:
    screen = FakeScreen({WORD: Window(browser=False, label="Word"), COMPOSE: Window()}, front_hwnd=WORD,
                        forward=False)
    waiting = gmail_fill.find_compose(screen)
    assert waiting == gmail_fill.Waiting("behind", "Word", gmail_fill.FIELDS)
    error = gmail_fill.gave_up(waiting, 20)
    assert error.code == "gmail_behind" and "Click the Gmail window" in error.hint
    assert screen.text == {}  # nothing written into a window that isn't in front


def test_a_window_with_a_subject_is_never_filled_in_front_or_behind() -> None:
    """A reply or the owner's own draft: To would be replaced. Only an empty compose window is Swift's."""
    in_use = Window(subject="Re: their thread")
    assert gmail_fill.find_compose(FakeScreen({COMPOSE: in_use})) == gmail_fill.Waiting(
        "in_use", "Chrome", gmail_fill.FIELDS)
    screen = FakeScreen({WORD: Window(browser=False, label="Word"), OTHER_BROWSER: in_use}, front_hwnd=WORD)
    assert isinstance(gmail_fill.find_compose(screen), gmail_fill.Waiting) and screen.front_hwnd == WORD


def test_a_private_window_behind_is_skipped_not_filled() -> None:
    screen = FakeScreen({WORD: Window(browser=False, label="Word"), OTHER_BROWSER: Window(private=True)},
                        front_hwnd=WORD)
    assert gmail_fill.find_compose(screen) == gmail_fill.Waiting("not_browser", "Word")
    assert screen.front_hwnd == WORD


def test_the_click_carries_its_own_position_so_it_cannot_land_where_the_pointer_went_back() -> None:
    """An event without a position lands wherever the pointer is when Windows handles it (review of e845a8e)."""
    windows = pytest.importorskip("swift.desktop.windows")
    desk = (-1920, 0, 3840, 1080)  # a second monitor to the left
    down, up, back = windows._click_inputs(100, 540, (-500, 20), desk)
    placed = windows.MOUSEEVENTF_MOVE | windows.MOUSEEVENTF_ABSOLUTE | windows.MOUSEEVENTF_VIRTUALDESK
    for event in (down, up, back):
        assert event.type == windows.INPUT_MOUSE and event.u.mi.dwFlags & placed == placed
    assert down.u.mi.dwFlags & windows.MOUSEEVENTF_LEFTDOWN and up.u.mi.dwFlags & windows.MOUSEEVENTF_LEFTUP
    assert (down.u.mi.dx, down.u.mi.dy) == (up.u.mi.dx, up.u.mi.dy) == (2020 * 65535 // 3839, 540 * 65535 // 1079)
    assert (back.u.mi.dx, back.u.mi.dy) == (1420 * 65535 // 3839, 20 * 65535 // 1079)
    assert not back.u.mi.dwFlags & (windows.MOUSEEVENTF_LEFTDOWN | windows.MOUSEEVENTF_LEFTUP)


# ---- the To row Gmail shows collapsed (check 252, run of 2026-11-14) -----------------------------------


def test_a_collapsed_to_row_is_opened_and_the_email_filled() -> None:
    """12:30: Subject and Body found, no To, for 20 s. Gmail had To collapsed to "Recipients"."""
    screen = FakeScreen({COMPOSE: Window(to_closed=True)}, focused="body")
    sink = _captured()
    try:
        _fill(screen)
    finally:
        logger.remove()
    assert screen.steps[0] == f"open to {COMPOSE}"
    assert screen.text == {"to": TO[0], "body": BODY, "subject": SUBJECT}
    assert "gmail to row opened" in sink.getvalue()
    _content_free(sink.getvalue())


def test_a_collapsed_to_row_behind_is_opened_then_brought_forward() -> None:
    screen = FakeScreen({WORD: Window(browser=False, label="Word"), COMPOSE: Window(to_closed=True)},
                        front_hwnd=WORD)
    _fill(screen)
    assert screen.front_hwnd == COMPOSE and screen.text["to"] == TO[0]


def test_a_reply_s_collapsed_recipients_are_never_opened() -> None:
    """A reply or the owner's draft has a subject: its To row is left as it is, and nothing is filled."""
    screen = FakeScreen({COMPOSE: Window(to_closed=True, subject="Re: their thread")})
    assert gmail_fill.find_compose(screen) == gmail_fill.Waiting("not_loaded", "Chrome", ("body", "subject"))
    assert screen.steps == [] and screen.windows[COMPOSE].to_closed


def test_a_page_with_no_to_row_at_all_still_waits_as_not_loaded() -> None:
    screen = FakeScreen({COMPOSE: Window(fields=("body", "subject"))})
    assert gmail_fill.find_compose(screen) == gmail_fill.Waiting("not_loaded", "Chrome", ("body", "subject"))
