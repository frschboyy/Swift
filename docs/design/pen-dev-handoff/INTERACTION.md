# Swift overlay: interaction model

This is how the overlay works on `main` at `6cdc25f`. The Deck is current behaviour, not a proposal: the owner chose it (ADR-018, 2026-11-06) and Step 1 is built. Step 2 isn't built, and the last section lists what it would change.

The Deck has not been run on the owner's real PC yet. Everything here comes from the code, its tests, ADR-018 and the dev harness.

## Asking

- Say "Hey Swift", hold the push-to-talk hotkey (Ctrl+Shift+Space), or press Ctrl+Space to type.
- The capsule shows one state at a time, most urgent first:
  1. You talking: listening, transcribing, or can't hear you after 4 s.
  2. Heard: "Listening…", before anything is transcribed.
  3. Speaking, with Stop.
  4. Paused: mic off with Resume, or screen locked or PC asleep. This is the privacy indicator and it never fades.
  5. **A card open: the orb alone.** The card says the rest.
  6. Working, with its clock, when no card is open.
  7. The idle dot.
- A click passes through the capsule unless it's showing a button.

## Three places

A request is in one of three places, and each place has one meaning.

| Place | What's there | Where |
|---|---|---|
| **In front** | The one thing you're dealing with, and the only thing a said or typed answer can reach | The main card, growing out of the capsule |
| **Behind** | Everything still in flow: running, waiting to start, ready to read | Labelled edges behind the card, in the same window |
| **In the corner** | What was put aside and waits for you | The waiting stack, its own window |

## The card in front

- A card grows out of the capsule and folds back into it. Its head row shows how you asked (mic or keyboard) and your words.
- **Working:** the current step and earlier steps, with Stop, Watch and "Esc stops". With no news for 12 s and no pointer on it, it shrinks to one line (`35-workingShrunk`). Pointing at the card itself opens it again; pointing at an edge behind it doesn't.
- **Answer:** a one-liner is large display text. A long answer is clipped at six lines and opens in place. A reading-time bar runs along the bottom, and the card then fades.
- **Failed:** what went wrong and what did or didn't happen, with Details, Open logs and Try again.
- **Stopped / Not done:** a compact one-row card.
- **Timers and reminders:** stay until you press Done.
- **The card never moves because of something else arriving.** The exceptions are listed under "What takes the front".

## The deck behind it

- **Edges** sit on the far side of the card from the capsule: above the card at the bottom anchors, below it at the top ones. They stay in the main window and move with the card. They can't be dragged on their own.
- **At most three edges.** Past that, the last one says "+N". Each edge is narrower than the one before it, and the second and third are slightly dimmer. A new request goes on the far end, so nothing already there moves.
- **What an edge says:** a state mark, the title, what it's doing, and its clock. The marks are a spinner (running), a dashed mark ("Waiting to start"), a green check ("Ready to read") and an amber shield ("Needs your OK").
- **Hover:** the clock gives way to Watch (while it runs) and Open.
- **Click:** brings that request forward. The edge and the card swap as one body moving.
- **Watch** opens the free-floating live view and brings nothing forward.
- **Amber means an OK is waiting,** and nothing else: an amber edge, an amber stack badge, or the confirm card itself.

### A new request landing

There's no "Got it" pill any more, and no chip window. A new request's edge starts at the capsule and moves to its slot behind the card, with a green border, saying "Got it: “your words”" for 2.5 s. Then it settles to its title and activity. An answer that arrives within 600 ms (the time, say) never shows an edge, so nothing flashes up.

### What takes the front

Only what you must see:

- its answer or an error;
- its confirm card;
- its question;
- a request you're speaking to.

Progress stays on its edge. A long request finishing behind the card still comes forward, even over a card being read. Holding it until you're clear is Step 2. An answer it displaces stays as an edge for 20 s, and a click opens it. Only the newest request said comes forward: an older one says "Ready to read" for 20 s.

### Read more folds the deck

While a long answer is open, two or more edges fold to one: "2 more running", or "2 more running · 1 needs your OK" in amber. The answer isn't squeezed. Clicking that edge closes the answer and the edges open again. A single edge doesn't fold.

### Stopping when several are running

- A plain "stop" means the card on screen. But while the request you just said hasn't been in front yet, a plain "stop" or "actually …" asks which, and nothing stops.
- Naming one ("stop the research one"), "stop everything", Esc and the card's Stop button work as you'd expect.
- With an answer on the card, a spoken "stop" reaches what's behind it. By hotkey or typing, it brings the one behind forward without stopping it.

## When Swift needs you

- **Needs your OK:** a solid card with an amber band and a countdown (45 s by default). The countdown runs only while the card is on screen and you're present. If you're away, it says "Paused · you're away". When time runs out, the card goes to the stack with its whole time back. Approve ignores clicks for the first 400 ms.
- **A due confirm card takes the front at once** in Step 1, moving there rather than cross-fading.
- **Change** opens the typing box. Typing can change a request but never approve it.
- **Swift's question:** "Swift is asking" while it speaks, with no timer, then "Waiting for you" with a 25 s reply window. Answer later moves it to the stack, and Cancel request drops it.
- **An answer reaches only what's on screen,** whether it's said or typed. Only a click on the question's own button is exempt.

## The stack

- A small window in a corner holding held approvals, unanswered questions and unfinished requests. Double-click to expand, click outside to fold. Each row has Open, Skip and End.
- **Its badge is neutral unless a card inside needs an OK** (`p07` is amber, `p12` is neutral).
- A card joining it hands off towards the stack's side of the screen. It can't really fly there, because they're separate windows.

## Live view

Watch, or saying "show me", opens a window for a running request: what it's doing now, the sources it found, notes, and the text being written. It doesn't bring the request forward. Up to three can be open.

## Windows and placement

- **The main window** holds the capsule, the card and the deck. It's a fixed 720×560, transparent, and only painted parts take clicks.
- **Separate windows:** the stack, the typing box, the tray menu, the reader and live views. Other requests no longer have windows.
- A left click on the tray icon opens the tray menu: position, smart placement, pause listening, typing, settings, improving speech recognition, clearing saved recordings, restart and quit.

## Motion

- One curve for everything that moves: `cubic-bezier(.2,.8,.2,1)`, never overshooting.
- 280 ms for moves (`shuffle.ts`), 160 ms for surfaces, and the older 80–200 ms rules for press, hover and Read more.
- With reduced motion: a 120 ms fade, or nothing.
- Moves can't cross windows, which is why the handoff to the stack is only a gesture. A spike on one large window (ADR-018 §6) would change this. It's unbuilt and unmeasured.

## Not built yet: Step 2 (needs review item 9)

Don't draw these as current. A concept may propose them, labelled as Step 2:

- A due card holding as an amber edge until you're clear, with no countdown until it's on screen. Today it takes the front at once.
- Nothing swapping under the pointer or while you're talking.
- Cards in line leaving the stack list and showing only as edges.
- The displaced card coming back when the front is free, instead of the newest.
- Ready answers coming forward by themselves, replacing the 20 s row.

## Rejected, for the record

- **Beads** (dots on the capsule): no names on screen, which breaks "a word with every state icon".
- **Field** (one surface, everything flies): pulls the eye away from the active card, and needs the unmeasured one-window surface from day one.
- **A tear-off chip:** would keep free-moving chips, but also the window code. The owner chose to drop them.
