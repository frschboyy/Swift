# The interaction layer: Swift beyond the overlay (2026-11-10)

- **Status:** exploration, not decided. No ADR yet. Nothing here is built.
- **The page:** [Swift Interaction Layer](https://claude.ai/artifact/27DQ3hRe4qaxkwCFrSAecg), private to the owner. It has the storyboards, the transitions demo, the weight calculator and the full tables. Read it with the Artifact tool (`action: "read"`), not a web fetch.
- **Builds on:** ADR-018 (the Deck), ADR-019 and [`DIRECTION.md`](../design/halo-system/DIRECTION.md) (Halo: one run, many sizes; the attention policy).

## Why

The owner asked whether the overlay limits Swift's interaction model, and asked for a design exploration before any ADR. They challenged the first proposal (five surfaces) on three points: how the owner interacts is separate from where Swift appears; Swift must know when not to show UI; and the owner must stay in control.

## The model, in short

1. **Task and facets.** The task (today's run) keeps identity, state, Stop, "Why?" and the record. It shows itself through facets: confirmation, progress, question, decision, result, workspace, acting in an app. Each facet is placed on its own.
2. **Interaction mode,** one of twelve: Voice, Glance, Conversation, Deciding, Collaborating, Steering, Supervising, Monitoring, Pointing, Manipulating, Recalling, Teaching.
3. **Presentation policy:** a weight per facet (0 silent, 1 signal, 2 glimpse, 3 card, 4 pinned or attached, 5 Space) and a timing (now, soon, next break, digest, silent).
4. **The owner's overrides** (pins, placements, per-source rules), saved only from the owner's Yes on a one-time offer.
5. **Surface and placement:** orb, glimpse, card, edge, pinned, attached, Space, corner stack. Aggregates (badge, edges, corner) hold facets from several tasks.
6. **Limits,** checked last: the product rules. No preference lowers them.

Growth rule: the owner can jump any distance. Swift grows a facet one step, at a pause, never opens the Space, and pins only what the owner asked to keep running.

## Decisions waiting on the owner

1. Rewrite ADR-018 rule 3 ("one body") as "one identity per task; each facet in one place at a time".
2. Make the facet the unit of layout (facets need their own ids within a run: a protocol change).
3. The growth rule above.
4. Pinning: Swift pins only what the owner asked to keep running.
5. Approvals on a Swift card in front, or inside the Space while it's in front; never on attached, pinned, toasts or pages Swift drives. This touches a product rule, so it needs a second reviewer.
6. Learned placements only from the owner's Yes, with their source.
7. A spike on one stage window per monitor replacing the pane windows, kept only if it deletes more than it adds.
8. The Space as a normal, snappable window, excluded from capture by default.
9. Full screen and slideshows: voice and the orb only.

## Spikes, in order

- **S1, stage window per monitor:** idle cost, click-through at full size, DPI, virtual desktops.
- **S2, following another window:** moving, snapping, minimizing, being covered, another desktop.
- **S3, handoff into the Space** with no visible jump.
- **S4, keyboard and Narrator path.**

## When

Not before review item 9 (one versioned snapshot, acknowledged per window) and the two weeks of daily use (handoff §4). Every new surface is another place a frame can be refused silently. The cheapest early piece is the glimpse for simple confirmations such as timers.

## Unverified

These come from forum reports, or were not checked against Swift's behaviour:

- that tool windows show on every virtual desktop;
- whether Windows' text-size setting reaches WebView2;
- reading Do Not Disturb state;
- the research rows marked † on the page.
