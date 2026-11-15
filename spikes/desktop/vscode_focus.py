"""Probe: can Swift tell VS Code's editor from its terminal panel? (OCT-01; the owner's decision of 2026-11-15)

Every write into VS Code gets the terminal's own card, because Swift can't tell where the keyboard is in it.
This reads what UI Automation reports for the focused element while VS Code is in front: its ControlType,
ClassName, AutomationId and Name (cut to 60 characters), and each ancestor's ControlType and ClassName. It never
reads a Value or Text pattern (the file's or the terminal's content), and never types, clicks or brings anything
forward. It prints only when the focus changes.

    uv run python spikes/desktop/vscode_focus.py            # 60 seconds; Ctrl+C stops it sooner

While it runs: click into a file in VS Code's editor and wait two seconds, then into its terminal panel and wait
two seconds, then back. Paste what it printed into the chat. Names can hold a file or terminal tab's name.
"""

from __future__ import annotations

import argparse
import time

from swift.desktop import windows as w

VSCODE = ("code.exe", "code - insiders.exe")
MAX_ANCESTORS = 12


def control(e: object) -> str:
    ct = e.CurrentControlType  # type: ignore[attr-defined]
    return f"{w.CONTROL_TYPES.get(ct, ct)} class={e.CurrentClassName!r}"  # type: ignore[attr-defined]


def describe(uia: w._Uia, e: object) -> list[str]:
    name = e.CurrentName or ""  # type: ignore[attr-defined]
    lines = [f"focused: {control(e)} automation_id={e.CurrentAutomationId!r} "  # type: ignore[attr-defined]
             f"name={name[:60]!r}{'...' if len(name) > 60 else ''}"]
    walker = uia.automation.ControlViewWalker
    parent = walker.GetParentElement(e)
    for depth in range(1, MAX_ANCESTORS + 1):
        if not parent:
            break
        lines.append(f"  {'  ' * depth}^ {control(parent)}")
        parent = walker.GetParentElement(parent)
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=60.0, help="how long to watch (default 60)")
    args = parser.parse_args()
    uia = w._Uia()
    print("Watching the focus while VS Code is in front. Click into the editor, then the terminal panel.")
    last: list[str] = []
    end = time.monotonic() + args.seconds
    try:
        while time.monotonic() < end:
            time.sleep(0.5)
            if w._process(w._foreground())[2].lower() not in VSCODE:
                continue
            try:
                lines = describe(uia, uia.focused())
            except Exception as exc:  # noqa: BLE001 - the element went away mid-read
                lines = [f"unreadable ({type(exc).__name__})"]
            if lines != last:
                print(f"[{time.strftime('%H:%M:%S')}]", *lines, sep="\n")
                last = lines
    except KeyboardInterrupt:
        pass
    print("Done. Nothing was typed, clicked or read from the editor or terminal.")


if __name__ == "__main__":
    main()
