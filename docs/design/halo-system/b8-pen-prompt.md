# B8: the pen.dev prompt that extends Halo

The owner's roadmap item B8. Paste everything below the line into pen.dev with `halo.pen` open (this folder).
It describes Halo as it is on `main` after the B work (2026-11-17) and asks for the next round of design. Sources:
`SPEC.md`, `tokens.css`, ADR-019, `docs/handoff/workstreams.md` §B, `docs/design/b4-adaptive-results.md`,
`docs/design/b6-live-view.md`, and the B UI review of 2026-11-17 (branch `claude/b-ui-review`).

---

## Brief: extend Halo for Swift's next round

You're extending **Halo**, the design system in this file, for **Swift**: a voice-first assistant that lives on
the owner's Windows desktop. Work inside Halo: same tokens, components and anatomy. **Don't start a new
direction.** Add frames, components and variants to this file, and mark anything that isn't built yet as
**proposal**.

### 1. What Swift is, and what the surface must feel like

- The owner says "Hey Swift…" or holds a hotkey. Swift answers aloud in a sentence or two, and the screen shows
  the rest. Most of the time Swift is just a small **orb** at a screen anchor. Every card is something the orb
  *says*: a bubble with a tail pointing back at it.
- The owner's principle: **"Swift adapts to the user, not the user to Swift."** The surface is quiet until it
  has something to say, and never covers the owner's work without a reason.
- It's an overlay above every app. It never takes keyboard focus (the typing box is the one exception), and only
  painted pixels take clicks. Everything else passes through to the app underneath.
- Swift speaks as itself. **No card, label or byline names the model provider** ("Claude", "via Claude"). Use
  "Swift", or "the worker" for the agent doing the work. Fix this wherever the current frames show "via Claude".

### 2. Halo as it is (keep all of this)

**Principles.**
1. Everything Swift shows is a **run**.
2. **The state sets the treatment; blocks carry the content.** Content can never make a card look like a confirm.
3. **Workers never draw:** Swift picks every block from its own catalog.
4. **Who started it, by side:** the owner's words on the right; things Swift started on the left, with a mark.
5. **Amber means an OK is waiting now**, and nothing else.
6. Every state mark has a word. Never colour alone.

**Card anatomy, top to bottom:** state line (40 px) · origin line · body (blocks) · facts (approval cards only) ·
footer (byline left, at most three pill buttons right, primary last) · optional hint · optional 3 px progress bar.
The card is 512 px wide, radius 22, with the inner corner 12 where it meets the deck. The tail (24 × 11) sits on
the orb side.

**Seven states:**

| State | Treatment |
|---|---|
| Working | glass + rim; shrinks to one line after 12 s without news |
| Done | glass; fades after its reading time |
| Needs your OK | solid, 2 px amber border and halo, a 42 px amber band with a countdown pill |
| Waiting for you | glass, 2 px accent border and an accent ring; while Swift is speaking, the tag reads "Swift is asking" |
| Stopped | muted; fades after 4 s |
| Failed | red mark; stays |
| Due | solid, accent ring, no close button |

**Glass** is 94% opaque. Blur is decoration only, and text must be readable without it. **Edges** in the deck
are opaque and accent-tinted, never glass. Font: Segoe UI Variable, plus Cascadia Mono for technical text.
Tokens: this file's `b-*` variables, dark and light.

**Six anchors:** top or bottom × left, centre or right, with a 16 px gutter. The card grows away from the orb,
and the deck's edges sit on the far side. Tail x = orb centre − card left − 12, clamped to 28 … width − 52.

**The deck:** at most three edges (34 px tall, each 20 px narrower than the one before), then "+N more". Read more
folds the deck to one edge. One run has five sizes: badge on the orb → edge → card → expanded card → record.

**Presence** has three independent parts:
- **Mic:** idle dot · Heard · Listening (level bars, live words) · Paused, shown as the sleeping orb with "Not
  listening" and a reason. Paused never fades.
- **Activity:** working shows an orbit ring; speaking shows a pill with Stop and Esc.
- **Waiting:** a count badge, amber with a shield when an OK waits.

### 3. What the B work added since the last canvas (draw these as they are now)

- **B1, the approval card:** it leads with the worker's own plain sentence (what it will do and why), marked as
  the worker's. The command's first line always shows under it; only the rest folds.
- **B2, the step card:** one approval for one coherent step of a task, its commands listed inside. Anything
  irreversible (delete, send, pay, run in a terminal) still gets its own card.
- **B3:** working, waiting for you, Needs your OK, stopped and failed now look different on screen.
- **B4, results shaped to fit:** the worker proposes a shape as data, and Swift draws it from its own blocks.
  Shapes only appear on Done results and in the reader, never on an approval or a question.
  - **Built:** compare.
  - **Drawn, not merged:** diagram, mind map, document preview, chart and project cards.
  - The worker's choice is labelled **"Worker's pick"**, in grey, never in Swift's blue.
  - A grey bar marks content that was "Compared by the worker, not checked by Swift".
- **B6, the live view ("Watch"):** its own window, restyled as a monitor:
  - solid near-black (`#0d1018`) in both themes;
  - a title bar with a pulsing blue **● LIVE** (`#8ab4ff` in both themes), the title, a running clock and ×;
  - Cascadia Mono for steps, the clock and results;
  - a white "paper" surface when something visible is being made (Word, email), with one console line always
    under it;
  - the console and its sources list when there's nothing to see;
  - footer: Show in *app*, Stop.
- **A10, moving out from under:** when a window from a higher layer (Task Manager, say) covers the orb or the card
  area, Swift draws at the nearest anchor that isn't covered, then goes back once it's clear.
- **Smart placement:** the card moves away from where the owner is typing.

### 4. Rules no design may break

Draw these exactly. Don't soften them for looks.

- An approval card (Needs your OK) is approved only by a click on Swift's own button, the same button pressed from
  the keyboard (Tab, then Enter), or speech said with Swift's name or with the hotkey held. **Typed words never
  approve.** Approve ignores clicks for its first 400 ms.
- **Every consequential fact is drawn by Swift from the action itself:** recipient, path, command, amount.
  Anything the worker wrote is marked as the worker's.
- Irreversible actions, anything reaching another person, and the owner's accounts always get **their own card**.
  No step card, plan or setting covers them. **Paying is approved by a gesture only.** Deleting a file always asks.
- **A countdown never answers.** A card that runs out goes to the stack.
- The confirm card **never scrolls, and its buttons never leave the window**. The compact rule (band 36 px,
  tighter gaps, email preview clamped to two lines) applies first, then the deck folds to one edge.
- Accessibility:
  - body text at least 14 px (answers 17–18);
  - `--faint` at least 4.5:1 on both surfaces;
  - reduced motion means a 120 ms fade only;
  - forced colours: the amber band becomes Highlight and halos drop;
  - check legibility at 150% scaling.

### 5. What to design now (B5–B14 and the open Halo items)

For each item, give frames in **dark and light**, at a **bottom-right** and a **top-left** anchor (all six where
placement matters), and note any new token or component.

1. **B5, cards that grow, and expand by hand.** A card grows with its content up to a limit that never covers the
   owner's work (the window's free height is 560 px minus gutters, orb and gap). Beyond that:
   - a hand-expand affordance;
   - the expanded card;
   - how it collapses back.
   Show a long answer, a big comparison table and a diagram at each size, and how the deck's edges behave while a
   card is expanded.
2. **B7, motion you can see.** Storyboard, with frame timings:
   - the card growing out of the orb and the tail settling last (280 ms, no overshoot), against today's fade;
   - a card folding back into the orb;
   - an edge coming forward to become the card;
   - Done draining away.
   Today's transitions are 120/160/200 ms, too fast to see. Propose durations and easing, plus the
   reduced-motion version.
3. **B6 + B9 + B11, the watch as a monitor, docked.**
   - Polish the monitor frame above.
   - Draw three placements: beside the card (today), a docked sidebar at a screen edge, and a mini sidebar in a
     corner.
   - Give each one progress and life (B11): steps ticking by, the LIVE pulse, a progress bar. None of it may look
     like a working card or an approval.
   - Include the Word "paper" view and the research console view.
4. **B10, the watch stays connected to its request.** While the watch is open, the request's card shouldn't
   vanish, and the watch shouldn't say "closes by itself". Show how the card and the watch read as one run at two
   sizes: a shared title, a shared clock, a visible link. Show what each one does when the run ends.
5. **B12, "Open the answer".** Show where it leads from a finished watch: the reader with the whole answer, even
   after its card has faded. Draw the finished watch, its "ENDED" state after a Stop, and the reader opening.
6. **B13, file lists as a tree.** A new block for the catalog: folders and files, collapse and expand, long names,
   about 40 items, the selected item. On a Done card and in the reader.
7. **B14, a discreet running-timer indicator.** A timer the owner set, counting down without a card. Try it on the
   orb (a badge or arc), as a stack row, and as an edge. Then show it becoming the Due card with "+5 min" and Done.
8. **Halo's open items (ADR-019 §8)**, each as its own frame:
   - the confirm and question cards with an origin line;
   - "just now" and duration times instead of clock times;
   - Failed that doesn't fade;
   - a problem with no request shown as Failed;
   - the orb staying put at a right anchor when the capsule grows into a pill;
   - the compact confirm that still doesn't fit, folding the deck to one edge.
9. **The remaining B4 shapes in Halo's language:** diagram, mind map, document preview (a PDF page or a text
   excerpt), chart and project cards. Make them consistent with compare: the "Worker's pick" grey marking, the
   footer byline without the provider, and the fallback to plain text when a shape doesn't fit.
10. **B3, the states side by side.** One board with every state at card, edge and badge size, plus the
    confusion test: amber band vs accent halo, Waiting for you vs Working, Stopped vs Failed. Each must be
    distinguishable in grayscale and at a glance.

### 6. What to hand back

- **New frames** in `halo.pen`, grouped by item (B5, B7, …), each labelled **built** (drawn as it is now) or
  **proposal**.
- **New or changed components** in the component board, as instances, with no detached copies.
- **New or changed tokens**, named in the `b-*` scheme, dark and light, with contrast checked.
- **Exports** for the boards: `4-growth-motion.png`, `5-watch.png`, `6-new-blocks.png`, `7-open-items.png`.
- **A one-paragraph note per item:** what you chose, what you rejected and why, and any question for the owner.

### 7. Don't

- Don't add a new card design per capability. Use one anatomy, states and blocks.
- Don't put shapes, charts or worker content on Needs your OK or Waiting for you cards.
- Don't use amber for anything but an OK waiting now. Don't use red except for failure.
- Don't let glass carry legibility. Don't let anything scroll a confirm card.
- Don't name the model provider anywhere on screen.
- Don't design surfaces that take focus, or full-screen takeovers. In full screen and slideshows, Swift is voice
  and the orb only.
