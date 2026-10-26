# Desktop probe (ADR-012): owner-run

The probe measures how much of your apps Swift could see and act on through Windows' structured interfaces (Win32 and UI Automation) instead of screenshots, and how fast.

It reports **numbers only**:
- element counts by type;
- timings;
- which actions the focused element supports;
- the lengths of the selection and the document.

No window title, element name or text is printed or saved. It reads only, except `-Word` (below). It needs nothing installed: it uses the UI Automation client built into Windows.

## Run it

From the repository root, once per app. **Open and set up the app yourself first** (see the table); the probe measures whichever window is in front when its 5-second countdown ends, and prints which app that was:

```powershell
powershell -ExecutionPolicy Bypass -File spikes\desktop\uia_probe.ps1 -Label word
```

| Label | Before the countdown ends, have open and in front |
|---|---|
| `word` | A Word document with some text selected |
| `chrome-gmail` | Gmail in Chrome, with a message open |
| `vscode` | VS Code with a file open |
| `explorer` | A File Explorer folder with two files selected |
| `notepad` | Notepad with some text |
| any other | An app you'd want Swift to work in |

Then, once:

```powershell
powershell -ExecutionPolicy Bypass -File spikes\desktop\uia_probe.ps1 -Word
```

This opens a **new blank** Word document and writes five lines into it while you watch. It reads them back through UI Automation, undoes them, and closes the document **without saving**. Your other documents aren't touched.

Results are appended to `%TEMP%\swift-desktop-probe.jsonl`. Paste that file's contents into the chat; it contains no text from your screen.

## What the numbers answer

| Field | Question |
|---|---|
| `basics_ms`, `focus.focus_ms` | How fast Swift knows which app and which control you're in |
| `focus.patterns`, `focus.selection_chars` | Can Swift read your selection and type into the focused control? |
| `tree.named_pct`, `tree.automation_id_pct` | How much of the window is labelled well enough to act on reliably |
| `tree.interactive_onscreen`, `tree.snapshot_tokens_est` | How big a structured "what's on screen" description would be, compared with a screenshot (roughly 1,500+ tokens) |
| `tree.walk_ms`, `tree.bulk_ms` | How long a snapshot takes. The numbers are upper bounds: Swift would use native UI Automation with scoped queries. |
| `tree_second_walk` (browsers) | Whether web page content appears once the browser has built its accessibility tree |
| `word.insert_ms_per_paragraph`, `word.chars_via_uia`, `word.undo_ms` | Live writing through Word's object model, reading it back without a screenshot, and undo |

Measured on this machine by the developer session (taskbar only, as a test): 36 elements, 83 % named, 13 interactive, snapshot of about 126 tokens, 220 ms for an element-by-element walk, 135 ms for a bulk fetch.
