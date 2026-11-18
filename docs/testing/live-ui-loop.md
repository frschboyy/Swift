# The live UI loop: design → build → run → interact → observe → refine

How to run Swift's real overlay on this PC, drive it with real input, read what it actually shows, and check that it
stays coherent when the owner behaves unpredictably. Written from runs on 2026-11-17/18 (driver in `spikes/live_ui`).

## 1. Who can do what

| | Can do | Can't |
|---|---|---|
| **pen.dev directly** | Design and compare on the canvas; `browser` nodes load web pages (the overlay's dev harness at `localhost:1431/dev/harness.html`, `dev/pane.html`) and its CDP tool clicks, types and evaluates in them; screenshots of those pages onto the canvas. | Show or drive a native Windows window: the Tauri overlay, its click-through, hotkeys, focus, other apps. Canvas browsers only run while their document is the active tab. |
| **Its agent (Claude Code) + MCP + CLI** | Everything below: build an isolated copy of the real overlay, start the debug backend, attach to the overlay's WebView2 over CDP, send frames as if spoken, read the real DOM and presenter, press real keys and clicks through Windows, read both logs, put the results back on the canvas. | Hear: there is no way yet to feed recorded audio in (see §5). |
| **External automation** (here: CDP + Win32 from PowerShell, no extra installs) | Real hotkeys (`keybd_event`), real mouse clicks through Windows hit-testing, foreground/focus checks, window rects. A full UI-Automation or computer-use tool would add little: the overlay's content is a webview, read better through CDP. | Reliable physical coordinates on mixed-DPI monitors without the hover trick in §3. |
| **Only a person** | Real speech: accents, mumbling, talking over Swift, a TV in the room; how it *feels* (timing, distraction, trust); Windows' foreground-lock behaviour in daily use; the owner checks. | — |

## 2. Setup (never touches the owner's Swift)

The owner's Swift is a debug build loading its UI from port 1420 with the real hotkeys. The test copy differs in four
ways, each needed:

1. **Its own app identifier**, or the single-instance plugin hands the launch to the owner's Swift and exits:
   ```powershell
   cd overlay\src-tauri; $env:CARGO_TARGET_DIR="C:\st\t"
   $env:TAURI_CONFIG='{"identifier":"dev.swift.overlay.test","build":{"devUrl":"http://localhost:1431"}}'; cargo build
   ```
   No tracked file changes. The UI comes live from `vite --port 1431` (any branch's `overlay/`: hot reload works).
2. **A debug backend** with fakes, the echo worker, files in `%TEMP%`, wake off and **test hotkeys**
   (`Ctrl+Alt+Shift+F7` push-to-talk, `F8` text box, `F9` debug): `overlay/dev/harness-config.yaml` plus a `hotkeys:`
   block, run with `--port 8765 --token devharness-token-0123456789abcdef --console`.
3. **Environment for the test copy only:** `SWIFT_BACKEND_PORT=8765`, `SWIFT_SESSION_TOKEN=…`,
   `SWIFT_DEV_ALLOW_CAPTURE=1` (otherwise it's excluded from capture), `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9230`,
   and `LOCALAPPDATA` pointed at a temp folder so it can't write the owner's `overlay.json`.
4. **The driver** (`spikes/live_ui`): `live.mjs` launches it, finds the overlay's backend socket with
   `Runtime.queryObjects` (no reload, no race; the Vite socket is skipped), sends frames as the overlay
   (`debug.ask` for a new request, `debug.say` for words into an open run, `debug.run` for scripted demos), and
   reads the real DOM plus `window.__overlay` (the presenter). `desk.ps1` does real keys, clicks, focus and rects.
   `seq.mjs` holds the scenarios: `node seq.mjs <outdir> messy,conflict,repeat,timeout,hotkeys,engine`.

**Safety rules the driver enforces:** keys and typing go only to a window whose process is checked first (it refused to
type into the owner's VS Code with an unsaved `config.yaml`); clicks go only where `WindowFromPoint` names the test
overlay; no full-desktop captures (they record the owner's other windows) — only the overlay's own webview.

## 3. What each step checks

After every action: wait, read the DOM (capsule, stage, the card, its buttons, whether it's inside its window, deck
rows), the presenter, the frames in and out, the foreground window, page errors; save a webview capture. Invariants:
one card element; the card inside its window; no duplicate deck rows; never "listening" over a confirm card; the
capsule agrees with `speaking`; the foreground never moves to the overlay unless the text box was asked for; no page
errors.

**Clicks on a mixed-DPI desktop:** the overlay is click-through until the pointer is over a card (a 33 ms poll in
`hit.rs`), and `WindowFromPoint` skips click-through windows. So: move the pointer to each candidate mapping, wait
150 ms, then check the owner of the point, then click.

## 4. What the runs found

| # | Sequence | Observed | Verdict |
|---|---|---|---|
| 1 | The same question 2–3 times | Two or three identical "what time is it · Ready to read" rows, plus "+2" | **UX:** can't tell them apart; same words within a minute could fold into one row with a count, or show the time |
| 2 | "stop" while Swift is still listening or transcribing | The request vanishes; capsule idle; no "Stopped" card | **UX:** stopped during a run shows "Stopped"; here nothing says it was dropped |
| 3 | An OK left to lapse, then new requests | Lapses into the stack correctly, but 18 s later `debug.run ignored: busy \| state='confirm'`; after an unrelated push-to-talk error the overlay sent `focus` and the lapsed OK came back to the front with a fresh 45 s countdown; a fresh overlay start showed it as the front card with no countdown | **Bug candidates** (session state after `_expire_card`; the overlay's focus after an error). Needs a seam scenario |
| 4 | After the OK lapsed | Card gone, `#stage[data-state]` still `confirm` | **Minor:** stale stage; check what else reads it (Esc grab, hit regions) |
| 5 | Questions answered while an OK waits | OK stays in front; answers go to the deck | As designed |
| 6 | Real double click on Send, 150 ms apart | One `confirm.reply`; the run goes on | As designed |
| 7 | "approve" via the test input | Approves (or asks once more when noisy) | As designed: `debug.say` stands for speech with the hotkey (`intake.SPOKEN_LIKE`) |
| 8 | Push-to-talk tapped, held in silence, ten fast taps | "Hold to talk"; "I didn't catch that"; room audio once heard as "Um" → "Say that again?"; taps over an OK give voice hints, never an approval | Clear feedback |
| 9 | Answers arriving while another app is in front | Foreground never moved | As designed |
| 10 | Text box hotkey with the owner in VS Code | Once: the box didn't get the keyboard; later (test copy in front): it did | **Human check:** Windows' foreground lock; worth an owner check |
| 11 | Engine killed mid-run, then restarted | "Reconnecting to Swift…" (once; another run caught idle first); reconnects by itself; first request answers | Recovers without a restart |
| 12 | Interrupt a run with a new question, then a correction | Both answered; the run stops on "stop" | As designed (with the echo worker, the correction can't show understanding) |

## 5. Gaps, and the smallest tooling that closes them

1. **Audio in.** Speech irregularities, noise, talking over Swift and the no-name voice rule can't be driven: the
   recorder opens the default device. A debug-only `audio_file` source in `audio/recorder.py` (play a WAV as the mic)
   would let `eval/stt` clips and noise recordings run through the real UI. Highest value.
2. **Pane windows over CDP.** The text box, stack, tray and live panes didn't appear as DevTools targets: the
   stack and text box can only be observed through frames. Find where panes create their WebView2 environment.
3. **A dev-only send hook** (`window.__overlay.send`) would replace the socket lookup with one line.
4. **Speaking.** The test config uses `replies: never`; a fake speaker that reports speaking without sound would let
   "interrupt while speaking" run.
5. **Make it a check, not a run:** turn findings 1–4 into seam scenarios (`tests/unit/test_seam_replay.py`) so they
   stay fixed; keep `seq.mjs` for exploration and for checking a design change on the real window.
