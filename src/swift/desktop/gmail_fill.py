"""Gmail's compose window, filled in for the owner to send (ADR-012; A9 of the owner's run of 2026-11-13).

The steps run on the desktop thread against a ``ComposeScreen``: the real one is ``windows._GmailScreen``
(Win32 and UI Automation); tests drive a fake. Text read from the page is never logged: when a step fails,
the log gets its ``code`` and where the keyboard was, as words from a fixed list (``FOCUS_PLACES``).

Order: To, then the body, then the subject, set directly last, so a paste meant for the body that Gmail
sends to the field in focus can't end up in it (owner checks, 2026-10-27: the message landed in the subject).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from loguru import logger

from swift.desktop.base import DesktopError

FIELDS = ("to", "body", "subject")
# How long a field Swift put the cursor in has to take it, before a paste.
FOCUS_WAIT_S = 1.0
# Where the keyboard was when a field wouldn't take it: the only words about it the log gets.
FOCUS_PLACES = ("to", "body", "subject", "page", "other_window", "none")

# Why the compose window isn't ready to fill yet (``Waiting.reason``), and the error code if it never is.
WAIT_CODES = {
    "not_browser": "gmail_not_in_front",  # no browser in front, and no compose window found behind
    "not_loaded": "gmail_not_loaded",  # a browser in front, but not all three fields in it
    "in_use": "gmail_in_use",  # the fields found already hold a subject: not a window Swift opened
    "behind": "gmail_behind",  # the compose window is open behind, and Windows wouldn't bring it forward
}


class ComposeScreen(Protocol):
    """What filling in needs from the desktop. ``element`` is whatever ``fields`` returned."""

    def front(self) -> int: ...
    def front_label(self, hwnd: int) -> str: ...
    def is_browser(self, hwnd: int) -> bool: ...
    def private(self, hwnd: int) -> bool: ...
    def browser_windows(self) -> list[int]: ...
    def fields(self, hwnd: int) -> dict[str, Any]: ...
    def open_to(self, hwnd: int) -> bool: ...
    def subject_in_use(self, fields: dict[str, Any]) -> bool: ...
    def bring_forward(self, hwnd: int) -> bool: ...
    def settable(self, element: Any) -> bool: ...
    def set_value(self, element: Any, text: str) -> None: ...
    def value(self, element: Any) -> str | None: ...
    def set_focus(self, element: Any) -> None: ...
    def has_focus(self, element: Any) -> bool: ...
    def focus_place(self, fields: dict[str, Any], hwnd: int) -> str: ...
    def click(self, element: Any, hwnd: int) -> bool: ...
    def paste(self, text: str) -> None: ...


@dataclass(frozen=True)
class Waiting:
    """Not ready to fill yet; content-free, for the log if the wait runs out."""

    reason: str
    front: str
    found: tuple[str, ...] = ()


@dataclass(frozen=True)
class Clock:
    now: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


def find_compose(screen: ComposeScreen) -> tuple[int, dict[str, Any]] | Waiting:
    """The compose window to fill: the one in front, or one found behind and brought forward."""
    front = screen.front()
    label = screen.front_label(front)
    waiting: Waiting
    if screen.is_browser(front):
        if screen.private(front):
            raise DesktopError("Gmail opened in a private window.", "Open a normal window and try again.",
                               code="gmail_private")
        fields = _fields(screen, front)
        if len(fields) == len(FIELDS):
            if not screen.subject_in_use(fields):
                return front, fields
            waiting = Waiting("in_use", label, tuple(fields))
        else:
            waiting = Waiting("not_loaded", label, tuple(fields))
    else:
        waiting = Waiting("not_browser", label)
    # Windows keeps the foreground for the app the owner is in, so the compose window Swift asked the
    # browser for can open behind it. Find it there and bring it forward; never a window with a subject.
    for hwnd in screen.browser_windows():
        if hwnd == front or screen.private(hwnd):
            continue
        fields = _fields(screen, hwnd)
        if len(fields) < len(FIELDS) or screen.subject_in_use(fields):
            continue
        if screen.bring_forward(hwnd):
            logger.info("gmail compose brought forward", front=label)
            return hwnd, fields
        return Waiting("behind", label, tuple(fields))
    return waiting


def _fields(screen: ComposeScreen, hwnd: int) -> dict[str, Any]:
    """The compose fields in ``hwnd``, after opening a To row Gmail shows collapsed.

    A compose window that opens without the cursor in it shows To as a "Recipients" row with no To box
    (UIA tree read on this PC, 2026-11-14: the 12:30 run of check 252 found Subject and Body, no To).
    Putting the keyboard on that row opens the box. Only in an empty compose window: never a reply or a draft.
    """
    fields = screen.fields(hwnd)
    if set(fields) != {"subject", "body"} or screen.subject_in_use(fields) or not screen.open_to(hwnd):
        return fields
    fields = screen.fields(hwnd)
    logger.info("gmail to row opened", found=sorted(fields))
    return fields


def gave_up(waiting: Waiting | None, waited_s: float) -> DesktopError:
    """The error when the compose window was never ready, after logging why (content-free)."""
    reason = waiting.reason if waiting else "not_browser"
    logger.warning("gmail compose not filled", waited_s=round(waited_s, 1), reason=reason,
                   front=waiting.front if waiting else "", found=list(waiting.found) if waiting else [])
    code = WAIT_CODES.get(reason, "gmail_not_in_front")
    if reason == "behind":
        return DesktopError("Gmail's compose window opened behind another window, and Windows wouldn't let "
                            "Swift bring it forward.", "Click the Gmail window: Swift fills it in. Or ask again.",
                            code=code)
    return DesktopError("Gmail's compose window didn't appear.", "Check you're signed in to Gmail in your browser.",
                        code=code)


def fill(screen: ComposeScreen, hwnd: int, fields: dict[str, Any], to: list[str], subject: str, body: str,
         clock: Clock | None = None) -> None:
    clock = clock or Clock()
    for key, text in (("to", ", ".join(to)), ("body", body), ("subject", subject)):
        set_field(screen, hwnd, fields, key, text, clock)
    value = screen.value(fields["subject"])
    if value is not None and " ".join(value.split()) != " ".join(subject.split()):
        logger.warning("gmail subject was wrong after filling in: set again")
        screen.set_value(fields["subject"], subject)


def set_field(screen: ComposeScreen, hwnd: int, fields: dict[str, Any], key: str, text: str,
              clock: Clock | None = None) -> None:
    element = fields[key]
    if screen.settable(element):
        screen.set_value(element, text)
        return
    how = focus(screen, element, hwnd, clock or Clock())
    if how is None:
        place = screen.focus_place(fields, hwnd)
        logger.warning("gmail field didn't take the cursor", field=key,
                       focus=place if place in FOCUS_PLACES else "none")
        raise DesktopError(f"Swift couldn't put the cursor in Gmail's {key}, so it stopped there.",
                           "Finish the email yourself, or try again.", code=f"gmail_focus_{key}")
    if how != "set_focus":
        logger.info("gmail field focused", field=key, how=how)
    screen.paste(text)


def focus(screen: ComposeScreen, element: Any, hwnd: int, clock: Clock) -> str | None:
    """Put the keyboard in ``element``: how it got there, or None. A paste goes wherever the keyboard is."""
    screen.set_focus(element)
    if _wait_for_focus(screen, element, clock):
        return "set_focus"
    # Gmail can take the focus back while the compose window finishes loading: ask once more.
    screen.set_focus(element)
    if _wait_for_focus(screen, element, clock):
        return "set_focus_again"
    # A click in the field is what the owner does, and it works (run of 2026-11-13). Only at a point
    # that is inside this field, in the compose window in front: ``click`` checks both.
    if screen.click(element, hwnd) and _wait_for_focus(screen, element, clock):
        return "click"
    return None


def _wait_for_focus(screen: ComposeScreen, element: Any, clock: Clock) -> bool:
    deadline = clock.now() + FOCUS_WAIT_S
    while True:
        if screen.has_focus(element):
            return True
        if clock.now() > deadline:
            return False
        clock.sleep(0.05)
