# ADR-019: Halo, and a design system that grows with Swift

- **Status:** Accepted as the design direction (2026-11-07). The owner chose Halo as the baseline and accepted the recommended answers to the open questions (§7). The decisions in §3 stand unless the real-PC checks (§5 step 2) say otherwise. Only Step A's look spike is built (§8), on `main` behind a dev-only switch.
- **Decided by:** Owner
- **Date:** 2026-11-07
- **Amends:** ADR-017 (the Capsule's look: Halo replaces it, keeping the capsule as Swift's body and cards growing out of it). ADR-018 (the Deck) is kept as the attention model; this ADR only changes how its parts are drawn and adds origins.
- **Design:** [`docs/design/halo-system/`](../design/halo-system/): `DIRECTION.md` (assessment and reasoning), `SPEC.md` (build reference), `tokens.css`, `halo.pen` (pen.dev source), `boards/` (exports)

## 1. Why

The owner asked for 3–4 visual directions on the pen.dev brief (`docs/design/pen-dev-handoff/`), then for a step back: is the design robust and adaptable enough for where Swift is going (watchers, recipes, memory, the Swift window, several workers), not only for today?

Three directions were drawn on the eight brief states and nine system checks: Paper, Halo and Rail. The owner took the recommendation: **Halo**, with Rail's named state line folded in. The assessment (`DIRECTION.md` §5) found that the interaction model holds, but the card layer won't scale: every card assumes the owner just asked for something, and every capability has had its own card.

## 2. Decision: Halo as the baseline

- Swift is the orb, and every card is something it says: a bubble with a tail pointing at the orb.
- Tinted glass at 94% (blur is decoration only), a rim of light on the top edge; Needs your OK and Due cards are solid.
- Opaque, accent-tinted edges in the deck, so a stack never blends into the card.
- The sleeping orb for Not listening.
- Segoe UI Variable stays the font.

## 3. System decisions

| # | Decision | Why | Board |
|---|---|---|---|
| 1 | **Everything is a run** with an origin, a state, blocks and actions | Watchers, schedules, reminders and suggestions get honest cards without new designs | 2-system §1–3 |
| 2 | **One card anatomy:** state line, origin line, body, facts, footer, hint | About fifteen card designs become one | §1 |
| 3 | **The state line comes first,** above the origin line | What kind of card it is reads first; the amber band stays on top of a confirm | §1, §2 |
| 4 | **Seven states set the treatment;** blocks carry content | Content can never make a card look like a confirm | §2 |
| 5 | **Who started it, by side:** owner's words on the right, Swift-started on the left with a mark | Reads as a conversation; proactive work is never disguised as a request | §3 |
| 6 | **A Swift-owned block catalog** (13 blocks); workers return data, never UI | Agent-neutral down to the pixels; safe against agent-made UI | §4 |
| 7 | **Presence as three parts:** mic, activity, waiting badge | New features stop adding capsule states | §6 |
| 8 | **The approval ladder:** one action, a plan, permission for one run, a standing rule | Avoids chains of amber cards for multi-step work | §7 |
| 9 | **A plan card is Waiting for you, not amber;** a step whose facts aren't known yet asks on its own card later | Amber keeps one meaning; nothing consequential is approved in advance | §7 |
| 10 | **New product rule: deleting a file always asks** (added to `CLAUDE.md`) | Files (W2) are next on the roadmap, and a wrong delete is the hardest mistake to undo | §7 |
| 11 | **Watcher findings wait for the next break,** then take an edge, never the front | Bounded deferral; the owner's work isn't interrupted | §5f |
| 12 | **One "while you were away" card** replaces the stack, the unfinished line and separate offers on return | Product direction §5.3 | §5g |
| 13 | **Compact confirm rule** (`SPEC.md` §10) | Halo only fits the tightest case (a confirm with three edges) with it | baseline 12, §8 |
| 14 | **Tail rule at six anchors** (`SPEC.md` §9) | Halo has to work at every position | §8 |
| 15 | **One component set for the overlay and the Swift window** | The window shouldn't become a second app | 1-components |

## 4. N2: origin in the protocol (requirement for groundwork, not built now)

Runs, rows and results gain `origin` (`asked`, `scheduled`, `watching`, `reminder`, `noticed`, `learned`, `away`). Today a due item is recognised by its run id (`session.py:3579–3582`, `due-timer-…`). This belongs with the run-records groundwork (handoff §4), so it lands before watchers exist. Nothing else in this ADR changes the backend.

## 5. Order

Nothing here goes ahead of the handoff's order: the reliability work, the short real-PC checks and two weeks of daily use come first.

1. ~~Owner confirms or changes §3.~~ Done 2026-11-07 (§7).
2. **Real-PC checks of the Halo look** (`SPEC.md` §15) before any build.
3. **Build Halo behind today's behaviour:** tokens and one card renderer, no new features. One commit per step; the seam test for anything on screen.
4. **N2 with run records** (groundwork).
5. **Proposals one at a time,** each with its trigger: the attention policy and "while you were away" with notifications at rest; the plan card and run grants with W2; "Working in your app" with more desktop adapters.

## 6. Rejected, for the record

- **Paper** (opaque editorial sheets): refined, but does least for Swift's character, and fits the tightest case with only 7 px to spare.
- **Rail** (native Windows, state spine): the clearest at "what's in front", and its state line is adopted here; on its own it risked feeling generic.
- **A card design per capability:** the current path; it grows by one card and one artifact kind per feature.
- **Agent-made UI shown as it comes** (MCP Apps unmapped): breaks the rule that Swift draws every consequential fact.

## 7. The owner's answers (2026-11-07)

| # | Question | Answer |
|---|---|---|
| 1 | Who started it, by side? | **Yes.** The owner's words on the right; things Swift started on the left with their mark |
| 2 | "Deleting a file always asks" as a product rule? | **Yes.** Added to `CLAUDE.md`'s product rules: a path that breaks it is a critical bug, and a fix to it needs a second reviewer. Whether a move to the Recycle Bin counts as reversible (and so may run under a run's permission) is decided when the W2 file tools are designed; permanent deletes always ask |
| 3 | How many times does a hint show? | **3** per hint and kind of card, and it stops early once the owner uses what it suggests. "What can you do here?" answers at any time. Never on Needs your OK |
| 4 | How long can a finding wait for the next break? | **2 minutes** by default, set per source (for example, "Janet: at the next break"; "tech news: morning digest"). Due reminders the owner set are never held |
| 5 | Keep the idle dot? | **Yes, by default,** with a tray toggle to hide it. Closes ADR-017 owner question 1. Not listening is never hidden, whatever the toggle says |

## 8. Step A: built, not yet checked (2026-11-07)

A look spike behind a dev-only switch (`overlay/src/look/`), on `main` since 2026-11-10. Owner checks 216–221 run `SPEC.md` §15; their findings go here, and the spec changes where the PC disagrees with the canvas. Nothing has been seen on the real PC.

**Measured in the harness:** the release bundle is byte-identical to `main`'s; the default look has no pixel differences from `main` across 34 states, dark and light, at bottom-centre; Halo drew 12 states at all six anchors in both themes (144 captures), each with its card and tail, inside the window, nothing scrolling. That was headless Edge at 100%, with a stand-in wallpaper: not the app's window, its glass over real apps, or 150% scaling.

**Where the spike differs from the canvas, each because today's overlay doesn't have it (Step B or later):**
- The confirm and question cards have no origin line: the confirm card has no words to show today, and the question keeps its "about …" beside the tag.
- Done and Failed show the clock time, not "just now" or a duration.
- Failed still fades as it does today (`SPEC.md` §4 says it doesn't), and a problem with no request keeps today's plain card rather than saying Failed.
- At a right anchor, the orb moves when the capsule grows into a pill (the pill stays at the edge), so the tail moves with it.
- If a compact confirm still doesn't fit, it scrolls as today: folding the deck (`SPEC.md` §10) needs the presenter, so it waits for Step B. It didn't happen in the tightest case drawn: a compact confirm of 316 px with three edges.
- The panes (typing box, stack, live view, tray) take the tokens and buttons only.
