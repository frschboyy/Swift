# Brief: Halo, the overlay's new look (ADR-019)

The task for the session that builds Halo. Read this whole brief first, then, in order:

1. [`docs/design/halo-system/SPEC.md`](../design/halo-system/SPEC.md): the build reference. Every measurement, colour and rule is there.
2. [ADR-019](../decisions/ADR-019-halo-design-system.md): what the owner decided, what's proposal only, and the order.
3. [`docs/design/halo-system/tokens.css`](../design/halo-system/tokens.css): the values, on the existing token names.
4. [`boards/`](../design/halo-system/boards/): what it should look like (`3-baseline.png` for today's states, `2-system.png` for the anatomy and states, `1-components.png` for the parts). The source is `halo.pen` (pen.dev).
5. [`DIRECTION.md`](../design/halo-system/DIRECTION.md): why, if a choice in the spec seems odd.

The working rules are `CLAUDE.md`: a worktree, one finding per commit, a seam test for any fix to what's on screen, the product rules (now including "deleting a file always asks"), never push, merge only when the owner says so.

## Where this sits in the order of work

ADR-019 §5 and handoff §4: Halo doesn't go ahead of the reliability work, the short real-PC checks or the two weeks of daily use **unless the owner says so**, as they did for the Deck. **Ask the owner before starting Step B.** Step A is small and changes nothing in the release build, so it can go first if the owner wants the look checked early.

## Step A: a look spike (dev builds only)

**Goal:** the owner sees Halo on the real PC and runs the checks in `SPEC.md` §15 before anything is built for real.

- **A Halo look behind a dev-only switch:** for example `?look=halo` in the harness and an environment variable in debug builds. Release builds never show it. The default look stays exactly as it is.
- **Tokens:** `tokens.css`'s values under the switch (`#stage[data-look="halo"]` or similar), on the existing names.
- **Draw today's states in Halo, with today's behaviour:** the eight brief states (listening, not listening, working, an answer, needs your OK with the email, the question waiting, requests behind the card, a long answer open with the deck folded), plus the shrunk working card, failed, timer due, and the six anchors. Use the existing `__design` states; add the few that are missing.
- **What's in:** the glass card with the rim gradient, the tail (positioned after layout, `SPEC.md` §9), the state line above the origin line, the amber band and halo, the accent halo, tinted opaque edges, the sleeping orb, pill buttons, the compact confirm rule (§10).
- **What's out:** every item marked "proposal" in the spec or ADR. That includes the plan card, run permission, standing rules, the attention policy, "while you were away", watcher cards, "Working in your app", partial-results failure, hints, and the waiting badge and orbit ring (they need state the overlay doesn't have yet). No protocol or backend change.

**Done when:**
- The harness shows every state above in Halo, dark and light, at all six anchors, and the default look is pixel-identical to before (compare the pen-dev handoff screenshots, `docs/design/pen-dev-handoff/screens/`).
- A debug build on the owner's PC can switch to Halo.
- Owner checks for `SPEC.md` §15's six items are numbered in `docs/testing/owner-checks.md`, with report lines in `spikes/owner_checks/report.py`.
- `tsc --noEmit`, `npm test` and the Python suite pass.

**Then stop** and let the owner run the checks. Record what they find in ADR-019 (a "§8 Step A: checked" section), and change the spec where the PC disagrees with the canvas.

## Step B: Halo for real, behind today's behaviour (after the owner's go-ahead)

- **Halo becomes the only look;** the switch and the old styles go.
- **One card renderer:** state line + origin line + blocks + footer (`SPEC.md` §3–§6), replacing the per-kind drawing in `main.ts`. Map today's messages as in `SPEC.md` §14. Small modules with narrow interfaces, not more `main.ts`.
- **No new features, no protocol change.** Origin is inferred where the overlay already knows it (the owner's words on a request; `due-*` run ids for reminders, until N2 replaces them). Don't add an `origin` field yet; that's N2, with the run-records groundwork (ADR-019 §4).
- **Structural steps delete code:** keep the renderer only if it removes more than it adds. Prototype it on the branch first.

**Must keep working:**
- the Deck: one body, edges, the landing "Got it", folding on Read more, what takes the front, a plain "stop" asking which;
- click-through: only painted parts take the pointer, the capsule only when it shows a button; no focus stealing (the typing box excepted);
- Not listening never fades; amber only when an OK waits; Approve ignores clicks for 400 ms; a countdown never answers;
- every product rule in `CLAUDE.md`: in particular, the confirm card's facts come from the action, never from a worker's text;
- reduced motion (a 120 ms fade only) and forced colours (the amber band becomes Highlight);
- the existing owner checks for the overlay, and the seam replay test.

**Proof:**
- Seam scenarios in `tests/unit/test_seam_replay.py` for each state the renderer draws, failing with the renderer undone.
- Every suite and routing parity, as in `CLAUDE.md`.
- Before-and-after screenshots of every `__design` state, dark and light.
- An ADR-019 "§9 Step B: built" section: what changed, the line count before and after, what wasn't checked on the real PC.

## Not this brief

- **N2, `origin` in the protocol:** with run records (handoff §4 groundwork).
- **The proposals:** each with its feature, one at a time (ADR-019 §5 step 5).
- **The Swift window:** handoff §4 item 7. When it comes, it uses the same tokens and blocks (`SPEC.md`, ADR-019 decision 15).
