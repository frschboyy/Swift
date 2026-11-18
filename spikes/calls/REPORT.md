# Call / screen-share detector spike (Halo A3)

Probe: `spikes/calls/probe.py` (read only, no admin, no new dependency; uses `psutil`, already in the project venv).
Snapshot: `PYTHONPATH=src <venv>/python spikes/calls/probe.py`. Live watch while the owner runs a real call or share:
`... probe.py --watch 120` prints a line whenever any signal changes.

**Measured on this PC (2026-11-18): idle only.** No call or share was running, and I started none. The live rows
below are from documented Windows behaviour and the repo's earlier `preroll_probe.py` mic result, **not** from a call
here. Owner check needed before A3 is built on this: one Teams, one Zoom, one Meet-in-browser call and one share, with `--watch`.

| Signal | Detects | False positives / negatives | Cost per poll | Admin |
|---|---|---|---|---|
| Mic ConsentStore (`microphone\<app>`, `LastUsedTimeStop == 0`) | an app has the mic open (any call app, packaged or not; browsers show as `chrome.exe`/`msedge.exe`) | **FP: Swift's own mic** and any dictation/recorder/voice note (the key is per exe, so Swift's python/exe can be excluded by name). **FP: stale keys.** Found here: `Zoom.exe` has Stop=0 since 2026-08-03 though Zoom isn't running. Fix: require the exe to be running (done in probe; packaged-app keys carry no path and can't be checked this way). **FN:** a listen-only call (muted mic and app releases it); Teams/Zoom normally keep the mic open when muted, so unverified. | 3 ms (19 ms with the process check; cache the process list) | no |
| Camera ConsentStore (`webcam`) | camera open | FN when on a call without video; FP for the Camera app | ~3 ms | no |
| `SHQueryUserNotificationState` (shell32) | `BUSY`, `RUNNING_D3D_FULL_SCREEN`, `PRESENTATION_MODE` (Windows' own do-not-disturb state) | Fires for any full-screen app or game and for PowerPoint slide show / presenting mode, which is wanted. Does **not** fire for a plain window share in Teams/Zoom/Meet (not full screen). Idle value here: `ACCEPTS_NOTIFICATIONS`. | 0.3 ms | no |
| Window titles (`EnumWindows`) | Teams/Zoom/Meet/Discord meeting windows, Zoom/Teams "sharing" toolbar, "Slide Show" | Fragile: titles are localized and change by version; a browser tab title ("Meet - abc") shows only while that tab is active (background tabs invisible via EnumWindows); FP for a chat window named "Discord". Useful only as a share hint. | 1 ms | no |
| Audio sessions (WASAPI `IAudioSessionManager2`) | which process has active render/capture | Needs `pycaw`/comtypes (new dependency); not tried. Adds render (speaker) info, but a video also plays audio, so render alone isn't a call. | n/a | no |

Not tried: the sharing border (a drawn overlay, no stable API), Graphics Capture session flag (no process-level query exists).

## Recommendation

**Call** = (mic active by a running exe other than Swift's) **and** (that exe is on a call-app list: Teams, Zoom, Discord, a browser, Slack, WhatsApp), polled every 2 s, with ~5 s of hysteresis on the way out (the key flips to Stop≠0 when the stream closes, and apps reopen it between prompts).
**Share/present** = `SHQueryUserNotificationState` in {`PRESENTATION_MODE`, `BUSY`, `RUNNING_D3D_FULL_SCREEN`} **or** a call plus a title containing "sharing"/"presenting"/"slide show".
Total cost under 25 ms per poll even with the process check; no admin, no dependency.

## Risk

- Plain window sharing (not full screen, not a recognised title) can be missed, so a card could show on a shared screen. Mitigation: while a call is on, hide cards and treat any share as possible. That makes the safe default "hold during any call", which fits A3.
- Stale registry keys give a false "in a call" (seen here). The process check handles non-packaged apps; for packaged apps (Teams new, Slack, WhatsApp), check `LastUsedTimeStart` is recent or the app's window exists. Unverified.
- Browser calls can't be told from a browser recording a voice note or dictating; the result is a wrongly held card, which is the safe direction.
- Listen-only calls and video-only shares stay undetected. Numbers for latency (time from joining to the key flipping) are unmeasured; `--watch` gives them.
- Verdict: **buildable** with the mic + notification-state detector, held to "holding is safe, showing is not". Confirm with the owner check above before building.
