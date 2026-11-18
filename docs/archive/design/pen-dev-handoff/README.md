# Swift overlay: brief for redesign concepts

Give pen.dev this file, `INTERACTION.md`, `tokens.css`, `icon-source.png` and the `screens/` folder. Everything here is checked against `main` at `6cdc25f` (2026-11-07). `CHANGES.md` is for the owner, not pen.dev: it lists what changed from the earlier pack.

## What Swift is

Swift is a voice-first assistant for Windows 11. You talk to it (or type), and it answers, does research, and handles things like email and calendar events after you approve them. Its whole interface is a small always-on-top overlay floating over whatever you're doing. There is no main app window.

The owner's principle: **"Swift adapts to the user, not the user to Swift."**

## What we want

**3–4 distinct visual directions**, each drawn on the same eight states below in dark and light, so they can be compared side by side. They should differ in real ways (form, hierarchy, material, how Swift shows it's present), not just in colour.

| # | State | Why it matters | Screenshot |
|---|---|---|---|
| 1 | Listening | Swift's presence, seen many times a day | `03-capsuleListening` |
| 2 | Not listening | The privacy indicator | `08-pausedMic` |
| 3 | Working | Progress while you get on with something else | `10-working` |
| 4 | An answer | The most common card | `12-answerText` |
| 5 | Needs your OK | The most important card: it can send an email | `23-confirmEmail` |
| 6 | Swift's question | Must not look like a finished answer | `27-questionWaiting` |
| 7 | Requests behind the card | How several requests share the screen | `28-concurrent` |
| 8 | A long answer open, with others behind | The deck has to give way | `d06-deckFoldedRunning` |

The current visual design is the **Capsule**: a small pill at the screen edge is Swift's body, and every card grows out of it. **The look of this is open to change.** A direction can keep the pill or replace it, as long as Swift's presence and the privacy indicator stay clear.

**How requests share the screen is decided: it's the Deck** (ADR-018, the owner's choice). Draw these as they are, in your own visual language:

- One card in front, and other requests as labelled edges behind it, in the same window.
- A new request landing as an edge that says "Got it: …", with no separate pill.
- The capsule shrinking to the orb while a card is open, unless it's listening, speaking or paused.
- Amber only when an OK is waiting.
- Read more folding the deck to one edge.
- The waiting stack staying a separate window in a corner.

`INTERACTION.md` has the rules, and what isn't built yet (Step 2). If a direction wants to change the model itself, label that as a proposal, separate from the visual direction.

## What bothers us now

*Draft from notes and screenshots. The owner should edit this before sending.*

- The cards read as a generic dark panel. Swift doesn't have much character of its own.
- A footer has a visibly different band across the card. It's darker than the card in dark and whiter in light (`12-answerText`, `10-working`, `27-questionWaiting`). Treat this as a defect, not part of the look. It's still in the app today.
- The edges use the same dark panel as everything else, so a stack of them is close in tone to the card (`28-concurrent`, `d05-deckOverflow`).
- The tray menu is tall for what it does (`light/p05-trayMenu`).

## Must hold in every direction

**The overlay's situation**
- It floats over any wallpaper or app, so text must stay readable on white, black and busy backgrounds (`screens/on-busy-wallpaper/`). Don't rely on blur for legibility.
- It never takes keyboard focus, except the typing box. Only painted parts catch clicks, and the capsule only when it shows a button; everything else lets clicks pass through to the app beneath.
- **The main window is a fixed 720×560,** holding the capsule, the card and the deck together. It can sit at any of six screen positions (top or bottom; left, centre or right), so the card and deck must work growing up or down (`d12-deckTopAnchor`). Cards are currently up to 512 px wide.
- The tightest case is a confirm card with three edges behind it (`d13-deckConfirmTight`). Its buttons must stay in sight.
- Dark and light follow the Windows setting. It must work at 150% scaling.
- The font is Segoe UI Variable, native to Windows 11. A different one needs a good reason.

**Trust and safety (not negotiable)**
- "Needs your OK" must be impossible to mistake for an ordinary answer. It shows the facts of the action (the recipient, the time, a change as Now → After, or the full command), with Reject, Change and Approve. Email's Approve button says Send.
- A countdown never answers for the user. When it runs out, the card waits in the stack.
- Never suggest that saying a bare "yes" or "approve" is enough. Hands-free approval needs push-to-talk or Swift's name. The only exception is Swift's own question about a reversible change the user just asked for, such as "Turn off Wi-Fi?". **Don't copy the wording in `p03-typeConfirm`** ("or say “approve”"): it falls short of this rule, and it's been reported as a bug.
- Typing never approves, and the typing box says so.
- A said or typed answer reaches only what's on screen, so what's in front must be obvious at a glance.
- "Not listening" stays visible for as long as the mic is off, whatever else is on screen.
- Amber means an OK is waiting, and nothing else.
- Status labels stay generic, such as "Working on it" or "Searching". Never show internal tool names or "Claude Code is…".
- Every state icon comes with a word. Don't rely on colour alone. That includes the edges: each has a name and a state in words.

**Real features only.** Draw only what Swift can do, and don't invent data or controls. If a direction needs something new, label it as a proposal.

## Motion

Describe each direction's motion in words. The rules today:

- One curve, never overshooting: 280 ms for anything that moves, 160 ms for surfaces, and 80–200 ms for press, hover and Read more.
- A request has one body: words, edge, card and fold-back are one element changing shape, so it never shows in two places.
- The card in front never moves because of something else.
- Reduced motion is a 120 ms fade or nothing.
- Nothing can move between separate windows, so a card reaching the stack is only a short gesture towards it.

## What's in `screens/`

All content is stand-in data from the dev harness, shown on a stand-in wallpaper. The real overlay has a transparent background. Overlay states were taken at the real 720×560 window, at 2× pixels.

| Files | What |
|---|---|
| `dark/`, `light/` `01`–`35` | Overlay states. `35` is new: a working card shrunk to one line |
| `dark/`, `light/` `d01`–`d15` | The Deck: one behind, landing, ready, amber, "+1", folded, behind a confirm card or a question, behind while speaking, hover, top anchor, the tightest fit, no card in front, behind a shrunk card |
| `dark/`, `light/` `p01`–`p12` | Separate windows: typing box, tray menu, stack, live view |
| `on-busy-wallpaper/` | Eight key states in both themes, as a legibility test |

Things to read correctly:

- **`28-concurrent` is what the app draws.** The harness now uses the app's own drawing for the edges.
- `06-capsuleWorking` shows a working card with the orb. That's correct: while a card is open the capsule is just the orb, so its "Working on it" pill doesn't appear here. That pill's state still exists in the code for a request working with no card on screen, but we couldn't reach it from the harness.
- `stackClosed` and `stackOpen` appear twice. `29`/`30` are drawn inside the harness, with extra room, and `p07`/`p08` are the real window. Use `p07`/`p08`.
- `liveResearch` and `liveDone` appear the same way: `33`/`34` are drawn beside the card with extra room, and `p09`–`p11` are the real window.
- `p09` and `p11` show one source of four because the rest of the list is scrolled out of view inside the panel.
- `d14-deckNoCard` shows an answer that finished behind a card, with nothing in front any more. It's brief: it stays for 20 s or until clicked.
- Scrollbars don't show in any of these. The capture browser hides them, so a card with more to scroll (`16-answerLongOpen`, `d06`) looks cut off where the real one has a thin scrollbar.
- Card text such as "Swift · via Claude" is real: it credits the assistant that answered.
