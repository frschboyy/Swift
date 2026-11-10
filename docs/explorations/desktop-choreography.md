# Desktop choreography: Swift and Windows as one experience (2026-11-11)

- **Status:** exploration with spike results, not decided. No ADR. Nothing here is in Swift: it's all in throwaway spikes under `spikes/desktop/`.
- **The spikes:** [`spikes/desktop/card_origin.py`](../../spikes/desktop/card_origin.py) (native windows) and [`spikes/desktop/card_overlay/`](../../spikes/desktop/card_overlay/) (a small separate Tauri app: one transparent, click-through window per monitor, as the overlay would draw).
- **Builds on:** [`interaction-layer.md`](interaction-layer.md). This answers most of its spikes S1 (stage window) and S2 (following another window).
- **Evidence:** every result below is from the owner's own PC (Windows build 26300, an Insider build, one monitor, dark theme). Each says how it was judged: by the owner's eye, by a measurement, or by the spike's self-test.

## Why

The owner asked what's possible beyond Swift floating on top of Windows: whether Swift's UI can respond to the desktop, move with it, and appear to interact with it, so the two feel like one experience. Their picture was the video trick where a person seems to hit an animated character: nothing connects them, but the timing makes it read as one event.

They later named four directions and wanted all of them, minus whatever turned out infeasible: Swift reacts to Windows, Windows reacts to Swift, the two move as one, and the two look made of the same stuff.

## What was found

| Direction | What works | How it was judged |
|---|---|---|
| **Swift reacts to Windows** | A stand-in for Swift's presence nods toward a window that comes forward, leans toward one being dragged, steps aside when one is dropped on it, and dips when one is minimised. Reacting to every window felt fine, not twitchy. | Owner's eye |
| | A mark drawn inside the overlay follows a dragged window closely enough. | Owner's eye |
| **Windows reacts to Swift** | A real window eases aside on the same beat as Swift's card arriving ("one hit"). | Owner's eye |
| | The desktop dims behind a card, and lifts when the owner turns to another window. | Owner's eye |
| | A real window appears to swell and settle. The window isn't touched: Windows keeps a live copy of it that Swift draws on top and resizes. | Owner's eye; self-test |
| **They move as one** | A window's card sweeps into the taskbar as the window is minimised, and returns with it on restore. | Owner's eye; self-test |
| | Windows reports when a window leaves or returns to the current virtual desktop. The overlay itself shows on every desktop. | Owner's run (the log) |
| **Made of the same stuff** | Swift's marks take Windows' accent colour. | Read correctly; not judged by eye |

Timing, measured: a window's move reaches Swift a median 2.5 ms after it happens, one per frame. The webview begins an animation 2 to 9 ms after being told. Finding the focused control through UI Automation took 2 to 100 ms, and re-reading its position 0.5 ms.

## What doesn't work

- **Moving one of Swift's own windows every frame to follow another.** It trails, and each move costs 2 to 4 ms. The fix was to never move the window: draw inside one window that stays put. (Owner's eye; measured.)
- **Windows' blur behind Swift's cards.** Measured with `cargo run -- --glasstest`: Windows draws acrylic only for the window that has focus, and Swift's cards never take focus. Mica, the older blur and an undocumented older acrylic all draw a flat colour. A frosted card would have to be drawn by Swift from a capture of the screen. (Measured.)
- **Taking colour from the window underneath.** It works, and nobody could see it: on dark windows a dark card tinted dark grey looks the same. (Owner's eye.)
- **Not tried:** making a real window ripple, tilt or bend, and glass that refracts what's behind it. Both need a native renderer fed by screen capture.

## Rules that worked

These came from the owner's reactions, one correction at a time.

1. **Swift starts the motion where it can.** Then Swift owns the clock. For the push, the webview says when its animation began and the real window moves from that moment.
2. **Read where things are once,** when the action starts. Do no work at rest: the spike sleeps until a key or one of a few rare events.
3. **A card belongs to its window without chasing it.** It lets go (lifts, dims) when the window is dragged and re-settles when it's dropped.
4. **A card that only hides folds away where it is.** Flying it to a corner while it faded read as a flicker.
5. **A card waiting on an answer never hides itself.** When another window takes the front it travels to Swift's own place and stays visible there.
6. **A window the owner dragged is theirs to place.** Swift never puts it back.
7. **Marks hide at once and return late.** A ring on a control disappears the moment anything moves, and comes back only after 400 ms of stillness. Returning at once made it blink.
8. **Hiding is quiet.** A mark that grew as it faded drew the eye; a plain quick fade didn't.
9. **A restored window is named "in front" before it arrives,** while its position still reads as far off screen. Use where Windows says it will return to, not where it is.

## Product-rule points to settle before any of this is designed in

- **Approvals stay on screen.** Rule 5 above exists because a plain "yes" counts only while the question is visible. Anything that lets a waiting card be covered, hidden or left on another virtual desktop breaks that. This touches a product rule, so it needs a second reviewer.
- **Reading control positions is a new kind of sensing.** The ring reads a control's rectangle and its type, never its name or text. It should be held to the audio rule's standard: never logged, never leaving the PC. Reading screen pixels (the tint, the glass test) is a further step and was only done in spikes.
- **Moving the owner's windows is intrusive.** It worked, and should happen only when it clearly serves the owner.
- **Swift never takes focus.** That is why Windows' blur is unavailable. The glass test takes focus briefly; nothing else in the spikes does.
- **Respect Windows' own settings:** transparency effects, animations off, the accent colour.

## What this answers in the interaction layer's spikes

- **S1, stage window per monitor.** Works as a full-monitor, click-through, never-focused window. Made one pixel shorter than the monitor, on the belief that a topmost window covering all of it counts as full screen and holds notifications back (not measured). It shows on every virtual desktop. Not measured: its idle cost. Not tried: a second monitor, mixed DPI.
- **S2, following another window.** Moving, dropping, minimising, restoring, losing the front and another desktop all work by the rules above. Not tried: snapping, and a window that is covered without losing the front.

## Decisions waiting on the owner

1. Which of these belong on Swift's real orb, Deck and cards, and when. This is the design work the spikes can't do: the feeling the owner is after comes from all of them applied consistently, not from any one.
2. Whether Swift's presence reacting to windows (nod, lean, step aside) is wanted on the real orb. The owner said the orb's current design is fine and didn't want it following windows; the stand-in reacting in place felt right.
3. Whether a frosted look is worth the heavy route (screen capture and a native renderer), given Windows' own blur is out.
4. Whether reading control positions is acceptable, and under what rule.
5. Whether to keep the spike code or delete it once this is read.

## When

Nothing here should be built into Swift before item g (one versioned screen snapshot) and the two weeks of daily use (item d) in the handoff. It then feeds Halo's design work and the interaction layer's ADR.

## Unverified

- Everything was on one PC, one monitor, one Insider build. A regular release of Windows may differ, in the blur result especially.
- The minimise sweep's timing (320 ms, gathering speed) is tuned by eye. Windows doesn't say how long its own animation takes, and it could change between builds.
- The card's return with a restored window was changed after the owner last saw it, and passes the self-test only.
- One self-test run in about twenty failed on a step that otherwise passes. The owner's own window switches reach the test while it runs, which is the likeliest cause, unproven.
- Apps that expose no controls (games, custom-drawn apps) and apps running as administrator were not tried.
- Chromium apps report a whole document as the focused control in some cases, so a ring there circles the page.
