"""Probe: why Gmail's body won't take the cursor after To is set (A9, check 252, run of 2026-11-14 16:00).

A dry run by default: it only reads. With ``--write --hwnd N`` (N: the compose window the owner named, from a
dry run) it brings that window forward, writes one placeholder address (``probe@example.com``) into To, as Swift does, then asks the body for the cursor as Swift does, and prints
what had the keyboard and what lies under the point Swift would click. It never clicks, types anything
else, or sends. Close the compose window afterwards with its X (Gmail keeps it as a draft: discard it).
Prints roles, class names and rectangles only: never a value, a title or a suggestion's name.

    uv run python spikes/desktop/gmail_body_focus.py                          # dry run: reads only
    uv run python spikes/desktop/gmail_body_focus.py --write --hwnd 133008   # only with the owner's OK
"""

from __future__ import annotations

import argparse
import time
from ctypes import wintypes

from swift.desktop import windows as w
from swift.desktop.base import NeverRead

PLACEHOLDER = "probe@example.com"


def role(uia: w._Uia, e: object) -> str:
    if e is None:
        return "none"
    try:
        ct = w.CONTROL_TYPES.get(e.CurrentControlType, e.CurrentControlType)  # type: ignore[attr-defined]
        name = e.CurrentName or ""  # type: ignore[attr-defined]
        label = name if name in ("To recipients", "Subject", "Message Body", "Recipients") else f"<{len(name)} chars>"
        return f"{ct} {label} class={e.CurrentClassName!r} role={e.CurrentAriaRole}"  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        return f"unreadable ({type(exc).__name__})"


def popups(uia: w._Uia, root: object) -> str:
    api = uia.api
    found = []
    for ct, word in ((50008, "list"), (50007, "list item"), (50011, "menu item")):
        cond = uia.automation.CreatePropertyCondition(api.UIA_ControlTypePropertyId, ct)
        items = root.FindAll(api.TreeScope_Descendants, cond)  # type: ignore[attr-defined]
        rects = []
        for i in range(min(items.Length, 40)):
            e = items.GetElement(i)
            if e.CurrentIsOffscreen:
                continue
            r = e.CurrentBoundingRectangle
            if r.right > r.left:
                rects.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        found.append(f"{word}s on screen: {len(rects)} {rects[:3]}")
    return "; ".join(found)


def report(step: str, uia: w._Uia, screen: w._GmailScreen, hwnd: int, fields: dict) -> None:
    body = fields["body"]
    r = body.CurrentBoundingRectangle
    width, height = r.right - r.left, r.bottom - r.top
    point = wintypes.POINT(r.left + min(24, width // 4), r.top + min(16, height // 4))
    under = uia.automation.ElementFromPoint(point)
    print(f"[{step}] front is compose: {w._foreground() == hwnd}; keyboard in: {screen.focus_place(fields, hwnd)}"
          f" ({role(uia, uia.focused())})")
    print(f"   body rect {(r.left, r.top, width, height)}, settable={screen.settable(body)};"
          f" click point {(point.x, point.y)} is the body: {screen._inside(under, body)} ({role(uia, under)})")
    print("  ", popups(uia, uia.automation.ElementFromHandle(hwnd)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hwnd", type=int, help="the compose window's id, from a dry run; required with --write")
    parser.add_argument("--write", action="store_true", help="write the placeholder into To and ask the body for "
                        "the cursor; without it, the probe only reads")
    args = parser.parse_args()
    uia = w._Uia()
    screen = w._GmailScreen(uia, NeverRead())
    if not args.write:
        # Dry run: read every browser window's compose fields; change nothing, bring nothing forward.
        for hwnd in screen.browser_windows():
            fields = {} if screen.private(hwnd) else screen.fields(hwnd)
            empty = "subject" in fields and not screen.subject_in_use(fields)
            print(f"window {hwnd}: fields {sorted(fields)}{'  <- empty compose' if empty else ''}")
            if empty and "body" in fields:
                report("dry run", uia, screen, hwnd, fields)
        print("Nothing written. To write, run again with --write --hwnd <the compose window's id>.")
        return
    if args.hwnd is None:
        parser.error("--write needs --hwnd: the id of the compose window the owner named")
    hwnd = args.hwnd
    fields = screen.fields(hwnd) if hwnd in screen.browser_windows() and not screen.private(hwnd) else {}
    if "subject" not in fields or "body" not in fields or screen.subject_in_use(fields):
        print(f"window {hwnd} isn't an empty compose window; nothing written.", sorted(fields))
        return
    if not screen.bring_forward(hwnd):  # Swift's own step before filling in
        print("Windows wouldn't bring the window forward; nothing written.")
        return
    if "to" not in fields and screen.open_to(hwnd):
        time.sleep(0.3)
        fields = screen.fields(hwnd)
    if "to" not in fields:
        print("No To box; nothing written.", sorted(fields))
        return
    print("fields:", sorted(fields), "to settable:", screen.settable(fields["to"]))
    report("before", uia, screen, hwnd, fields)
    screen.set_value(fields["to"], PLACEHOLDER)
    for wait in (0.1, 0.5):
        time.sleep(wait)
        report(f"{wait}s after To set", uia, screen, hwnd, fields)
    for attempt in (1, 2):
        screen.set_focus(fields["body"])
        time.sleep(1.0)
        report(f"after body SetFocus {attempt}", uia, screen, hwnd, fields)


if __name__ == "__main__":
    main()
