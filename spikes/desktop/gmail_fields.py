"""Read-only probe: Gmail's compose fields in each browser window, as Swift's matcher and UIA see them (A9).

Prints labels, roles and class names of the compose fields only: never a value, a title or the page's text.
Open a compose window yourself first (nothing is typed or sent). Run from the repository root:

    uv run python spikes/desktop/gmail_fields.py

2026-11-14: showed To collapsed to a "Recipients" line when the compose opened without the cursor in it.
"""

from __future__ import annotations

from swift.desktop import windows as w
from swift.desktop.base import NeverRead

KEYS = ("to", "recipient", "subject", "message", "body", "cc", "bcc")


def describe(uia: w._Uia, e: object) -> str:
    ct = w.CONTROL_TYPES.get(e.CurrentControlType, e.CurrentControlType)  # type: ignore[attr-defined]
    return (f"{ct} {e.CurrentName!r} role={e.CurrentAriaRole} class={e.CurrentClassName!r}"  # type: ignore[attr-defined]
            f" focusable={bool(e.CurrentIsKeyboardFocusable)} value_pattern={uia.value(e) is not None}")  # type: ignore[attr-defined]


def main() -> None:
    uia = w._Uia()
    screen = w._GmailScreen(uia, NeverRead())
    for hwnd in screen.browser_windows():
        if screen.private(hwnd):
            print(f"window {hwnd}: private, skipped")
            continue
        fields = screen.fields(hwnd)
        front = " (in front)" if hwnd == w._foreground() else ""
        print(f"window {hwnd}{front}: matcher found {sorted(fields)}")
        if "subject" not in fields and "body" not in fields:
            continue
        root = uia.automation.ElementFromHandle(hwnd)
        found = root.FindAll(uia.api.TreeScope_Descendants, uia.automation.CreateTrueCondition())
        for i in range(found.Length):
            e = found.GetElement(i)
            try:
                name = (e.CurrentName or "").lower()
                if len(name) < 40 and any(k in name.split() or name.startswith(k) for k in KEYS):
                    print("  ", describe(uia, e))
            except Exception:  # noqa: BLE001 - the page changed while being read
                continue


if __name__ == "__main__":
    main()
