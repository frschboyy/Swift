# Handoff: Swift overlay redesign

## Overview
A redesign of Swift's always-on-top, transparent overlay for Windows 11. It covers the presence capsule (orb), main card, confirm card, question card, concurrent chips, waiting stack, typing box, timer/reminder cards and tray menu, each in dark and light themes. Direction chosen: **1a "Capsule"**. A small pill at the anchor is Swift's body, and every card grows out of it and folds back into it.

## About the design files
`Swift Overlay Redesign.dc.html` is a **design reference built in HTML**: static frames showing the intended look and behaviour. It is not production code. Recreate it in Swift's existing overlay code (plain HTML/CSS/TypeScript, no framework, the current `styles.css` + pane windows). Open the file in a browser next to `support.js` to view it. Ignore its inline-style authoring; implement with CSS custom properties and classes in `styles.css`.

## Fidelity
**High fidelity.** Colours, type, spacing, radii, copy and state rules are final. Match them exactly. Where this README and the HTML disagree, this README wins.

---

## Design tokens (replace `:root` in styles.css)
Theme comes from `data-theme="dark|light"` on `#stage`. The default follows Windows `AppsUseLightTheme`, and the theme updates live when Windows changes.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--panel` | `rgba(32,34,40,.88)` | `rgba(251,251,253,.88)` | Glass: answer card, chip, capsule |
| `--panel-solid` *(new)* | `#1F2127` | `#FFFFFF` | Confirm, stack, tray, reminders, paused capsule |
| `--panel-edge` | `rgba(255,255,255,.11)` | `rgba(0,0,0,.11)` | 1px borders, table rules |
| `--raise` | `rgba(255,255,255,.07)` | `rgba(0,0,0,.05)` | Ghost buttons, fact boxes |
| `--text` | `#F2F3F6` | `#15171C` | Answers, titles |
| `--muted` | `#C3C6D0` | `#454A57` | User's words, secondary |
| `--faint` | `#A0A4B0` | `#5C6170` | Byline, elapsed (≥4.5:1) |
| `--accent` | `#8AB4FF` | `#2357C9` | Listening, links, primary button |
| `--on-accent` *(new)* | `#0B1730` | `#FFFFFF` | Text on accent fills |
| `--accent-soft` *(new)* | `rgba(138,180,255,.16)` | `rgba(35,87,201,.12)` | Question halo, tags |
| `--accent-edge` *(new)* | `rgba(138,180,255,.5)` | `rgba(35,87,201,.45)` | Border of opened long answer |
| `--ok` | `#7FD8A4` | `#1B7F4B` | Done, "Got it" |
| `--on-ok` *(new)* | `#0A2416` | `#FFFFFF` | |
| `--bad` | `#FF8A80` | `#C0362C` | Failed |
| `--on-bad` *(new)* | `#2B0906` | `#FFFFFF` | |
| `--warn` | `#F5C26B` | `#F2B33D` | **Consequence only**: confirm band, Approve fill |
| `--on-warn` *(new)* | `#2A1C00` | `#2A1C00` | Text on amber |
| `--warn-text` *(new)* | `#F5C26B` | `#875800` | Amber used as text on panels |
| `--warn-soft` *(new)* | `rgba(245,194,107,.16)` | `rgba(242,179,61,.22)` | "Typing can't approve" row |
| `--warn-halo` *(new)* | `rgba(245,194,107,.18)` | `rgba(242,179,61,.25)` | 4px ring around confirm |
| `--shadow` | `0 18px 48px rgba(0,0,0,.42), 0 2px 8px rgba(0,0,0,.28)` | `0 18px 48px rgba(20,30,50,.18), 0 2px 8px rgba(20,30,50,.10)` | Cards |

`--accent-2` is retired. Glass surfaces also get `backdrop-filter: blur(24px) saturate(1.4)`. That is decoration only: legibility must hold without it, so never drop panel opacity below .86.

**Orb gradient** (unchanged brand): `radial-gradient(circle at 35% 30%, rgba(255,255,255,.9), transparent 42%), radial-gradient(circle, #8AB4FF, #4F7BDC 78%)`.

**Type:** Segoe UI Variable. Use *Display* for ≥20px and *Text* below. No uppercase labels and no letter-spacing. Changing numbers use `font-variant-numeric: tabular-nums`.
| Role | Size/line | Weight |
|---|---|---|
| display (one-line answer) | 28/34 | 600 |
| title (confirm, question, reminder) | 20/26 | 600 |
| answer | 17/26 | 400 |
| body (request, steps, lists, chip title) | 15/22 | 400 (chip title 600) |
| label (status, byline, chip activity, captions) | 13/18 | 600 / 400 |
| kbd | 12 | 600, 1px border, radius 5 |

**Spacing:** 4 · 8 · 12 · 16 · 20 · 24. Card padding: 18px left/right, 12px top, 12–14px bottom.
**Radius:** kbd 6 · buttons 8 · fact boxes 10 · chips/stack 12 · `--radius` 14 (cards) · capsule 999.
**Elevation:** chip/capsule `--shadow`; confirm adds `0 0 0 4px var(--warn-halo)`; question and timer cards add `0 0 0 5px var(--accent-soft)`.
**Motion:** `--dur-press 80ms` (scale .98), `--dur-fast 120ms` (hover, fades, heard), `--dur-base 160ms` (enter/exit, chip↔card), `--dur-slow 200ms` (Read more, stack fan). `--ease: cubic-bezier(.2,.8,.2,1)` on enter, `--ease-exit: cubic-bezier(.4,0,1,1)`. Never overshoot.
**Icons:** 24-unit viewBox at 16/20px, 2px stroke, round caps/joins, `currentColor`. A word always accompanies each state icon.

---

## Surfaces and states

### 1. Presence capsule (`.voice` → `.capsule`)
44px high, radius 22, padding `0 18px 0 10px`, gap 12, 120–512px wide (hugs content), 15px text. Orb 24px.
| State | Visual | Text |
|---|---|---|
| idle | 12px orb dot, opacity .6 (or hidden, per setting) | — |
| heard | 1px `--accent` border; orb gets rings `0 0 0 4px rgba(138,180,255,.35), 0 0 0 9px rgba(138,180,255,.14)` | **Listening…** (600) |
| listening | orb `scale(1 + .12·level)` + 5 bars (3px wide, 6–20px tall, `--accent`) driven by mic RMS at 30fps | live transcript |
| transcribing | orb opacity .7 | transcript in `--muted` + "· · ·" |
| can't hear | orb .5, bars flat 3px `--faint` | "I can't hear you. Check your microphone." (after 4s below room noise) |
| working | 24px ring spinner (2.5px, track `rgba(138,180,255,.25)`, two sides `--accent`) | **Working on it** + elapsed |
| speaking | orb + 6 wave bars `--text` + pill button **Stop** with Esc kbd | **Speaking** |
| paused (mic off) | `--panel-solid`, **1px dashed `--muted`** border, hollow ring with diagonal slash | **Not listening** · Mic off · [Resume] |
| paused (locked) | same, lock glyph in ring | **Not listening** · Screen locked |

The paused capsule **persists** while paused. It is the privacy indicator, so it never fades.

### 2. Main card (`.card`)
512px wide, `--panel`, 1px `--panel-edge`, radius 14, `--shadow`, `overflow:hidden` (**remove the horizontal scrollbar**: no `overflow-x:auto` anywhere; tables fit by wrapping).
Layout from top to bottom:
1. **Head row**: 14px modality icon (mic or keyboard, `--faint`) · the user's words in quotes (15/1.4 `--muted`, wraps to 2 lines max, no ellipsis on line 1) · 32×32 close button.
2. **Status row** (working only): 18px spinner · step verb 17px 600 · elapsed right (15px `--faint`). Earlier steps below, indented 46px, 15px `--muted`, with a green 14px check.
3. **Answer** (largest text): one line → display 28/34; otherwise 17/26 with paragraphs separated by 10px (**never run paragraphs together; bold weight max 600**).
4. **Footer**: byline left (13px `--faint`, "Swift · via Claude", or the source, e.g. "Swift · Outlook calendar") · ghost buttons right (Show, Copy). Ghost button: 32h, padding 0 12, radius 8, `--raise`, 1px edge, 14px 600, 15px icon + label.
5. **Reading-time bar**: 3px at the bottom edge, `--accent` at .6 opacity, scaleX 1→0.

Variants:
- **Table** (calendar): a 3-column grid (`auto 1fr auto`), 15px, rows 8px vertical, 1px top rule. Time in `--muted` tabular.
- **Long, collapsed**: body clipped at 6 lines (156px), bottom mask `linear-gradient(#000 70%, transparent)`. Footer: **Read more ⌄** (15px 600 `--accent`) · "· N min read" · Copy.
- **Long, open**: grows **in place** (200ms height) to max `min(70vh, 720px)` minus capsule; only the body scrolls (thin scrollbar, `overscroll-behavior: contain`, text selectable). Border becomes `--accent-edge`. Footer gets a top rule: **Read less ⌃** · "Stays while open" · Show in Word · Copy. No fade while open.
- **Failed**: 20px `--bad` circle with "!" · title 17px 600 in plain words ("Couldn't send the email") · reason 15px `--muted` + what did/didn't happen ("Nothing was sent.") · footer: "Details" text link (expands a mono block) · **Try again** primary (`--accent` fill, `--on-accent`).
- **Cancelled / Not approved**: a compact one-row card (8px padding): icon · **Stopped** / **Not done** (15/600) · description (`--muted`, ellipsis) · Undo or ×. Fades after 4s.

### 3. Confirm card (`.card--confirm`)
**Must look different from an answer:** solid `--panel-solid` (no blur), 1px `--warn` border + 4px `--warn-halo` ring, and a **40px amber header band** (`--warn` bg, `--on-warn` text): shield icon · **Needs your OK** (14/700) · countdown right (`0:42`, tabular) or "Paused · you're away".
- Title: an action sentence, 20/26 600 ("Add to your calendar", "Move "Design review"", "Send this email"). **Never show internal tool names** (`create_calendar_event` must not appear).
- Facts box: `--raise`, radius 10, padding 12/14, grid `76px 1fr`, 15/22. Labels `--muted`; the key value is 600. Email adds a 66px-high body preview with a 1px border.
- Change: columns `76px | Now | → | After`. "Now" values are struck through in `--muted`; "After" values are 600.
- Voice hint: 13px `--muted` mic icon, "Or say "approve", "reject", or what to change".
- Buttons (36h, 15px): **Reject**, **Change** (ghost, left) … **Approve** (right, `--warn` fill, `--on-warn`, 700, check icon). For email, the primary label is **Send**. The old "Later" button is removed (timeout goes to the stack). All buttons must fit in 512px; the cut-off bug is fixed.
- 3px `--warn` countdown bar at the bottom edge.
- The countdown (45s default) runs **only** while the card is visible AND the user is present (input within 60s, screen unlocked). When it ends → the card moves to the stack as "Held". **Never auto-approve or auto-reject.**
- Approve ignores clicks for the first 400ms after the card appears.

### 4. Question card
Glass panel with a **2px `--accent` border**.
- While Swift is speaking: the tag **Swift is asking** (`--accent-soft` bg, `--accent` text) and a pill "Speaking… I'll listen when I'm done". No timer.
- While waiting: the tag **Waiting for you** (`--accent` fill, `--on-accent`), a 5px `--accent-soft` halo, and the question at 20/26 600. A listening pill (44h, radius 22, `--accent-soft`) holds the orb with its ring · **Listening for your answer** · `0:18` · a 3px `--accent` bar. A 20s timer starts after TTS ends. Footer: "Or type Ctrl Space" · Answer later · Cancel request.
- Never labelled "Done". Silence → goes to the stack as "Unanswered question".

### 5. Concurrent requests
- **"Got it" pill**: 36h, radius 18, a 20px `--ok` check circle · **Got it:** (600) · title. Shown within 300ms of the 2nd/3rd request; click-through; fades after 2.5s.
- **Chip** (its own window): 280w, ~56h, padding 10 14 10 12, radius 12, glass. Left: a 18–20px state icon (spinner = running; amber rounded square with shield = needs you; green circle check = ready). Text column: title 15/600 (single-line ellipsis only on the title) + activity 13px `--muted`. Elapsed right (13px `--faint`). For needs-you chips, the activity is "Needs your OK" in `--warn-text` 600 and the border is `--warn`. Hover: border `--accent` and the elapsed time is replaced by "Open". Click → bring forward (160ms swap with the front card). Drag → move; the position persists.
- Max 3 running: 1 front card + 2 chips.

### 6. Waiting stack (its own window)
- **Closed**: 280×80. Two back layers (inset 16px at .6 opacity, then 8px at .85, each offset 5px) behind a 64h top layer: a 28px amber count badge · "**3 things need you**" · "Next: <title>" (13px `--muted`). Double-click opens.
- **Open**: 320w, `--panel-solid`, radius 14, padding 12, gap 8. Header "Needs you" · count. Rows: a 16px type icon (shield `--warn-text` = held confirm; ? `--accent` = unanswered question; pause `--muted` = unfinished). Title 15/600 **wraps, no truncation**. Reason 13px `--muted` ("Waiting for your OK · held while you were away"). The selected/hovered row shows `--raise` bg and buttons **Open** (primary) · **Skip** · **End** (30h). Max 6 rows, then scroll. Click outside or Esc → collapse (200ms).

### 7. Typing box
512×52, glass, **2px `--accent` border**, keyboard icon `--accent`, 17px input text, placeholder "Type to Swift" in `--faint`, hint "Enter sends · Esc closes" (13px). It is the only surface that takes focus. While a confirm is open, a 36px row above it reads (`--warn-soft` bg): shield · "**Typing can't approve.** Click Approve, or say "approve"." and the hint becomes "Enter = Change".

### 8. Timers, alarms, reminders
512w, `--panel-solid`, 1px `--accent` border + 5px `--accent-soft` halo, padding 14 12 14 18. 40px `--accent` circle icon (timer/bell, `--on-accent`) · label 13/600 `--muted` ("Timer · 10 minutes") · title 20/26 600 ("Tea's ready") · ghost secondary (+5 min / Later) · primary **Done**. One soft chime. **Never fades**; stays until handled (goes to the stack if the user is away).

### 9. Tray menu
280w, radius 10, `--panel-solid`, 4px padding, item rows 10/12 padding, 14px. Header: 20px orb · **Swift** · live status ("Listening for "Hey Swift"" / "Not listening · Mic off"). **Position**: current value + a 3×2 anchor picker (the selected cell filled `--accent`). **Smart placement** toggle (36×20) + help text "Moves away from the text cursor and full-screen apps." Then Pause listening, Type to Swift (Ctrl+Space), Settings, Quit Swift. Hotkey labels are placeholders; use the real bindings.

---

## Interactions and behaviour

### Request timeline (answer)
| t | State | Rule |
|---|---|---|
| 0ms | heard | Capsule + ring rendered ≤100ms after wake/hotkey, before ASR |
| ~0.2s | listening | bars live, transcript live |
| end of speech | transcribing → card | card grows up from the capsule (160ms) |
| result | answer | status replaced in place; height animates from the anchor side; TTS starts, capsule shows Stop |
| reading time | fade | `clamp(4s, words × 240ms, 20s)`; bar drains; **paused** by hover, Read more open, scroll, text selection; resumes 1.5s after leave |
| end | idle | card fades (160ms, ease-exit) into the capsule → idle dot |

### Request timeline (with confirm)
heard → working → **confirm** (120ms cross-fade to the solid surface; countdown starts now) → [away: countdown pauses → on expiry, held in the stack] → approve → back to glass, "Adding the event" → done "Added to Friday, 13:00" (Show opens the app) → fade.

### Shrinking
A working card with no hover for 12s, or one displaced by a newer request, shrinks to a chip (160ms). Answers that finish while in a chip turn the chip into "Ready to read" (green); it stays until opened or for 60s.

### Placement
6 anchors (top/bottom × left/centre/right) from the tray; drag anywhere and the position persists per monitor. After a drop, cards grow **down** if the card's centre is in the top half of the screen, otherwise **up**. Horizontal alignment follows the nearest third. Chips sit on the side of the card toward the screen centre. Keep a 16px gutter inside the overlay.

### Click-through and focus
- Overlay 720×560, transparent. Only painted rects take the pointer: forward mouse events and toggle ignore-mouse when the pointer enters/leaves a registered rect.
- Click-through: empty space, gutters, shadows, halos, idle dot, "Got it", heard/listening/transcribing capsule.
- Clickable: card/chip bodies (drag from any non-control area), buttons, capsule while speaking (Stop) or paused (Resume), stack.
- All overlay windows are `WS_EX_NOACTIVATE` and never steal focus, except the typing box. The mouse wheel scrolls a long answer without focus.
- Keyboard: Esc stops speaking, then closes the front card, then collapses the open stack. All buttons are reachable through the global talk-to-card hotkey; typing cannot approve.

### Accessibility
WCAG AA everywhere: body ≥15px, contrast as per the tokens. State is never carried by colour alone (shape + word). `prefers-reduced-motion`: no translate/scale, 120ms opacity only; the heard pulse becomes a static ring; spinners become a static ¾ arc. `forced-colors`: Canvas/CanvasText surfaces, ButtonText borders, the amber band becomes Highlight. Support 100–200% scaling (CSS px throughout).

### Copy rules
Status never names the AI provider ("Working on it", "Searching the web", "Writing in Word"). The byline may say "Swift · via Claude". No internal identifiers or raw errors on the surface; put those under "Details".

---

## State model (suggested)
```ts
type Presence = 'idle'|'heard'|'listening'|'transcribing'|'working'|'speaking'|'paused-mic'|'paused-locked'|'cant-hear';
type CardKind = 'working'|'answer-line'|'answer-text'|'answer-table'|'answer-long'|'failed'|'cancelled'|'not-approved'|'confirm'|'question'|'reminder';
interface Request { id; words; modality:'voice'|'typed'; kind:CardKind; steps:{text,done}[]; startedAt; readMs; open?:boolean; held?:boolean; countdownMs?:number; }
interface Overlay { presence:Presence; front?:id; chips:id[] /*≤2*/; stack:id[]; stackOpen:boolean; typing:boolean; anchor; theme:'dark'|'light'; }
```
Timers that pause: reading-time (hover/open/scroll), confirm countdown (visible && present), question timer (starts at TTS end).

---

## Acceptance checklist (make every designed state functional)
Add each state to the dev harness and verify it:
- [ ] Every capsule state above, including both paused states and can't-hear
- [ ] Heard capsule appears ≤100ms after wake/hotkey (log the timing)
- [ ] Cards: working, one-line, paragraph, table, long collapsed/open (scrolls, no fade while open), failed + retry + details, cancelled + undo, not approved
- [ ] No horizontal scrollbar on any card
- [ ] Confirm: add, change (before→after), email. No raw tool name; all buttons visible at 512px; countdown pauses when away/locked; expiry → stack; Approve ignores the first 400ms
- [ ] Question: no timer while speaking; 20s timer after; never "Done"; silence → stack
- [ ] 3 concurrent requests: "Got it" pill, 2 chips, click to swap, drag to move and persist
- [ ] Stack: closed, double-click opens, Open/Skip/End work, click outside/Esc collapses, titles wrap
- [ ] Typing box focus + "Typing can't approve" notice
- [ ] Timer and reminder cards never fade
- [ ] Tray: 6 anchors, smart placement, pause, type, settings, quit
- [ ] All six anchors + a mid-screen drop: grow direction correct
- [ ] Dark + light over white, black and busy wallpapers; 100%, 150%, 200% scaling
- [ ] Reduced motion, forced colours, Esc order
- [ ] No focus stealing (type in Notepad while cards appear)

## Files
- `Swift Overlay Redesign.dc.html`: the reference board (open in a browser, with `support.js` beside it). Sections: 01 Direction, 02 System, 03 Presence, 04 Main card, 05 Confirm & question, 06 Concurrent & stack, 07 Typing/alarms/tray, 08 Timelines, 09 Developer notes. The Tweaks props `themes` and `wallpaper` switch the views.
- `support.js`: the runtime needed to view the board. Not part of the product.
