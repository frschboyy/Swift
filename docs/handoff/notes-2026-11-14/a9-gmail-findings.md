# A9 (Gmail fill, check 252): findings so far (2026-11-14)

What the read-only UIA probes on this PC show (Chrome 157.0.8103.51, updated 2026-11-11):
- The compose window still open in Chrome (hwnd 133008) has all three fields the matcher looks for: combobox "To recipients" (role combobox), edit "Subject", edit "Message Body". So the field names haven't changed for a compose in the state it's in now.
- Chrome exposes only the tab in front of each window (the minimised windows' tabs show no Gmail elements).
- One scan of a window takes 0.2–1.3 s: not the bottleneck.
- The 12:26 `front='other'` is any app not in APP_NAMES. swift-overlay.exe, Task Manager and Settings are all "other", so it isn't proven to be Swift's overlay.

What I think happened (UNPROVEN): when the compose opens without the keyboard in it, Gmail collapses the To row to a "Recipients" placeholder, so there is no "To recipients" or "To" element and the fill waits for 20 s. That fits 12:30 (`found=['subject','body']`). 12:24 (`found=[]` with Chrome in front) still has no explanation.

What would prove it: the tree of a fresh compose with the keyboard in the body, which needs the owner (asked the orchestrator).
Probe scripts: in my scratchpad (`gmail_tree.py`, `gmail_tabs.py`); I'll copy them into `spikes/desktop/` in the branch.

## Update 13:05: one cause proven and fixed
- PROVEN, from the owner's compose with the cursor in the body: To becomes a "Recipients" text inside a focusable group (class `aoD hl`), with no "To recipients" or "To" element. SetFocus on that group brings back the "To recipients" combobox within 0.2 s.
- Fixed on `claude/a9-gmail-252-e5d21c`: f060c8b (root) and d9c431c (check 305, probe, A9 row). The real `_GmailScreen.open_to` opened a collapsed row in the live compose.
- Still unproven: 12:24 (found nothing with Chrome in front) and 12:26 (behind, SetForegroundWindow failed). Lead: UIA SetFocus on a field brought Chrome forward from a background python process, so it may replace or back up bring_forward.
