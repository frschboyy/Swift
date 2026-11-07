# Halo: system spec (N5)

The build reference for the Halo design system. It covers the overlay and the future Swift window, so both are drawn from the same parts. The reasoning is in [`DIRECTION.md`](DIRECTION.md); the decision record is [ADR-019](../../decisions/ADR-019-halo-design-system.md) (proposed). Values are in [`tokens.css`](tokens.css). The source design is [`halo.pen`](halo.pen) (open in pen.dev); exports are in [`boards/`](boards/).

| Board | What |
|---|---|
| `boards/1-components.png` | The component library (33 parts) and two cards built only from instances |
| `boards/2-system.png` | Sections 1–8: anatomy, seven states, origins and the confusion test, block catalog, the previously missing states, presence, the approval ladder, six positions |
| `boards/3-baseline.png` | The Halo baseline: the eight brief states and the nine system checks, dark and light |

Everything marked **proposal** describes behaviour Swift doesn't have yet. Draw it as a proposal; don't build it without the owner's go-ahead.

## 1. Principles

1. **Everything Swift shows is a run.** A request, a reminder, a watcher's finding, a scheduled recipe, a suggestion, a memory proposal.
2. **The state sets the treatment; the blocks carry the content.** Content can never make a card look like a confirm card, or the reverse.
3. **Workers never draw.** A worker returns data; Swift picks a block from its own catalog. Every consequential fact is drawn by Swift from the action itself.
4. **Who started it, by side.** Things the owner asked for sit on the right; things Swift started sit on the left with their mark.
5. **Amber means an OK is waiting now,** and nothing else.
6. **A word with every state mark.** Never colour alone.

## 2. The run

| Field | Values |
|---|---|
| **Origin** | `asked` (said or typed) · `scheduled` · `watching` · `reminder` · `noticed` · `learned` · `away` (the "while you were away" summary) |
| **State** | `working` · `done` · `ok` (Needs your OK) · `waiting` (Waiting for you) · `stopped` · `failed` · `due` |
| **Body** | Ordered blocks (§5) |
| **Actions** | Up to three buttons from the verbs (§6) |
| **Meta** | Worker ("via Claude"), source app, time, a link to the run record |

**Protocol note (N2, for the run-records groundwork):** runs, rows and results gain `origin`. Today a due item is recognised by its run id (`due-timer-…`, `session.py:3579–3582`); `origin: "reminder"` replaces that. Nothing in the overlay should parse run ids.

## 3. Card anatomy

Width `--card-w` (512). Radius `--radius-card` (22); the corner that meets the deck is `--radius-card-inner` (12). Top to bottom:

| # | Slot | Spec |
|---|---|---|
| 1 | **State line** | 40 px high, padding 0 10 0 20, gap 8. Mark (18 px disc or 16 px spinner) · state word 13/600 in the state colour · "· time" 13 `--faint` · spacer · close (28 × 28, 16 px ×). Variants in §4. |
| 2 | **Origin line** | Asked: words right-aligned, 14 `--muted`, wrap to two lines, then the 14 px mic or keyboard mark; padding 0 20 4 22. Swift started: 20 px disc (`--raise`, 13 px icon `--muted`) · label 13/600 `--muted` · "· detail" 13 `--faint`; padding 0 22 4 20. |
| 3 | **Body** | Padding 8 22 12 22, gap 12. Blocks only. Optional title: 20–22/600 Display. |
| 4 | **Facts** | Only on Needs your OK and permission cards. A facts box (§5); drawn from the action, never from a worker's text. |
| 5 | **Footer** | Padding 4 14 12 22, gap 8. Left: byline (10 px orb dot · "Swift · via Claude" 13 `--faint` · "· Why?" 13/600 `--accent`), or a key hint ("Esc stops"). Right: at most three buttons, primary last. |
| 6 | **Hint** | Optional, one line, 12 px `--faint` with a 12 px lightbulb; padding 0 22 12 22. Shown 3 times per hint and kind of card, then dropped; stops early once the owner uses it. Never on Needs your OK. |
| — | **Progress** | Optional bottom bar, 3 px, inset 22, track `--raise` (or `--warn-halo` for a countdown). |

The tail (24 × 11) sits outside the card on the orb side (§9).

## 4. States and their treatments

| State | Surface | Border and halo | State line | Fades? |
|---|---|---|---|---|
| **Working** | Glass `--panel` | 1 px rim gradient (`--rim-hi` → `--rim`) | Spinner · "Working" `--accent` · time | No; shrinks to one line after 12 s without news |
| **Done** | Glass | Rim | Green check disc · "Done" `--ok` · time | Yes, after its reading time (bar drains) |
| **Needs your OK** | Solid `--panel-solid`, no blur | 2 px `--warn` + 4 px `--warn-halo` ring | **Amber band**, 42 px, `--warn` fill, square bottom corners: shield · "Needs your OK" 14/700 `--on-warn` · countdown pill (`#2A1C001F`), or "Paused · you're away" | Never answers; on expiry it goes to the stack |
| **Waiting for you** | Glass | 2 px `--accent` + 5 px `--accent-soft` ring | Tag: "Waiting for you", `--accent` fill, `--on-accent` text | Never says Done; on silence it goes to the stack |
| └ while Swift speaks | Glass | 2 px `--accent`, no ring | Tag: "Swift is asking", `--accent-soft` fill, `--accent` text; no timer | — |
| **Stopped** | Glass | Rim | Square disc · "Stopped" `--muted`; no body | Yes, after 4 s |
| **Failed** | Glass | Rim | Bad disc · "Failed" `--bad` · time | No |
| **Due** | Solid | 1 px `--accent` + 5 px `--accent-soft` ring | Bell disc · "Due" `--accent` · "now"; no close (Done ends it) | Never |

**Failed, proposal:** keep partial results (steps block with done, done, failed) and offer "Try again from step N". Today a failure ends the whole run.

## 5. Block catalog

Each block looks the same on a card, an expanded card, the Swift window and a digest. Add a block only when two capabilities need it.

| Block | Spec | Today |
|---|---|---|
| Display line | 28/600 Display | One-line answer |
| Text | 17–18/1.45, paragraphs 10 px apart, bold ≤ 600 | Answer paragraphs |
| Long text | Clipped at six lines with Read more ⌄ · "N min read"; opens in place | Read more / Read less |
| List | Rows: title 14/600 + detail 13 `--muted`, time 13 `--faint` right; 1 px `--rim` between rows | `details.list` |
| Table | `auto 1fr auto`, rows 6–8 px, 1 px `--rim` top rule, times `--muted` tabular | `details.table`, calendar |
| Steps | 28 px rows: 10 px dot (`--ok` done; `--accent` with 4 px `--ring` now; 14 px bad disc failed) · label (`--muted` done, 600 now, `--bad` failed) | Working card steps |
| Facts | Box `--raise`, radius 14, padding 12 14, gap 8; key column 66 px `--muted`, key value 600 | Confirm facts |
| Change | Facts row: before struck through `--muted` · 13 px arrow · after 600 | Now → After |
| Preview | Box `--panel-solid` or 1 px `--rim`, radius 10, padding 10 12, `--muted` 1.5 line height | Email body |
| Command | Box `--raise`, radius 10, mono 13, whole command, hidden characters shown (↵) | Command text |
| Sources | Rows: 16 px state disc (read, reading ring, failed) · title 13/600 · site 12 `--faint` | Live view sources |
| Choice | Title 20/600 · option buttons; the voice line only where a plain "yes" is allowed (Swift's own question about a reversible change) | Wi-Fi Yes/No, listening pill |
| Progress | 3 px bar with label 12 `--faint` | Reading time, countdowns |
| Listening | 48 px pill `--accent-soft`: ringed orb · "Listening for your answer" 600 · time | Question card |

## 6. Verbs and buttons

| Verb | Means | Shown on |
|---|---|---|
| Stop | End the run | Working (always visible while running), shrunk card, Speaking |
| Change | Edit what's about to happen | Needs your OK, plan |
| Show me / Watch | Expand, or open the live view | Any run |
| Later | Put it in Waiting for you | Any run in front |
| Undo | Reverse what was just done | Done, when reversible |
| Why? | Origin, worker, reason, rules applied | Byline of any run |
| Remember / Not now / Never | Accept, defer or stop a suggestion | Learned runs |

Buttons are 32 px pills, padding 0 14, 14 px icon, label 13/600. Ghost: `--raise`. Primary: `--accent` / `--on-accent` 700. Approve: `--warn` / `--on-warn` 700, and its label says what it does (Send, Approve, Allow for this run). Approve ignores clicks for its first 400 ms.

## 7. The deck and the sizes of a run

- **Edges:** 34 px, radius `--radius-edge` on the side away from the card, opaque `--edge-1/2/3` (nearest to farthest), 1 px `--edge-line`, each 20 px narrower than the one nearer the card (492, 472, 452). Content: state mark · (origin mark, if Swift started it) · title 13/600 · activity 13 `--muted` · time 12 `--faint`. Amber edge: 1 px `--warn` border, activity in `--warn-text`. "Got it": 1 px `--ok` border for 2.5 s. Hover: 1.5 px `--accent` border, the time gives way to Watch and Open (24 px buttons).
- **At most three edges;** the farthest then reads "+N more" with the breakdown in words.
- **Read more folds the deck** to one edge: "2 more running", plus "· 1 needs your OK" in amber with a `--warn` border if one does.
- **One run, five sizes:** badge on the orb → edge → card → expanded card (today's live view and reader) → record in the Swift window. Same marks, words and colours at every size.

## 8. Presence: three independent parts

| Part | Values | Drawing |
|---|---|---|
| Mic | Listening for its name · Heard · Listening · Paused (mic off, locked, asleep) | Idle: 14 px orb dot at 70%, shown by default; a tray toggle hides it (never the paused state). Heard: pill, `--accent-edge` border, orb with two `--ring` rings, "Listening…". Listening: pill, orb with one ring, 5 level bars `--accent`, live words. Paused: pill on `--panel-solid`, 1.5 px `--muted` border, the sleeping orb (`--sleep`, mic-off or lock glyph), "Not listening" + reason, Resume. Never fades. |
| Activity | Idle · Working · Speaking · Working in an app (proposal) | Working with no card open: an orbit ring around the orb (track `--spin-track`, arc `--accent`). Speaking: pill with six bars `--text`, "Speaking", Stop with Esc. In an app: orbit ring · app icon · "Writing in Word" · Stop. |
| Waiting | A count | Badge at the orb's top-right, 22 px: neutral `--panel-solid` + `--edge-line`, or `--warn` with a shield when an OK waits. |

While a card is open the capsule is the orb alone, except while listening, speaking or paused. Quiet mode and call detection change what the attention policy lets through, not the orb.

## 9. Positions and the tail

- Six anchors: top or bottom × left, centre or right. Gutter 16.
- The card grows away from the orb; edges sit on the far side of the card.
- **Tail x** = orb centre − card left − 12, clamped to 28 … card width − 52. At side anchors the orb centre is `--tail-inset` (44) from the card's edge, giving 32 (left) and 456 (right); centre is 244.
- Bottom anchors: the tail on the card's bottom edge, pointing down; the card's square corners (12) face the deck above. Top anchors: the tail on the top edge, pointing up; square corners face the deck below.
- The tail's fill is the card's surface (`--panel` or `--panel-solid`). Set its position after layout: the card's height isn't known before.

## 10. Compact confirm (rule)

Applies only when edges are behind a Needs your OK card and card + deck would exceed the window's free height (560 − gutters − orb − gap).

| Part | Normal | Compact |
|---|---|---|
| Band | 42 px | 36 px |
| Body gap | 14 | 10 |
| Facts padding | 12 14 | 10 14 |
| Email preview | 3 lines | clamped to 2, clip at the line (no part line showing) |
| Footer padding | 4 14 14 22 | 2 14 10 22 |

Never removed: any fact, the voice rule, any button, the countdown. Measured on the canvas: 412 → 341 px, so three edges fit in 443 of 466 px. If it still doesn't fit, fold the deck to one edge. The confirm card never scrolls and its buttons never leave the window.

## 11. The approval ladder (designed, not built)

| Rung | Card | State |
|---|---|---|
| One action | Today's confirm card | Needs your OK |
| A plan | The steps, each marked "Runs" or "Asks you first"; Cancel · Change · Start | **Waiting for you**, not amber: starting a plan pre-approves nothing consequential; a step whose facts aren't known yet asks on its own card later |
| Permission for this run | Facts: what, from, to, up to, until "this run ends"; Reject · One at a time · Allow for this run | Needs your OK |
| A standing rule | Swift window, "What Swift may do": Do · Ask · Never per kind of action; a lock marks a floor | — |

Floors no rung lowers (all product rules in `CLAUDE.md`): recipients only from contacts; a bare "yes" never approves; typing never approves; deleting a file always asks (added 2026-11-07; whether a move to the Recycle Bin counts as reversible is decided with W2). Learning never climbs the ladder.

## 12. Attention (proposal)

| Urgency | Appears |
|---|---|
| Now | Takes the front (today's rules: its answer, its OK, its question, a request you're speaking to) |
| Soon | An edge, "Ready to read" |
| At the next break | Held until you stop typing, a call ends or you come back, for at most 2 minutes (per-source setting); then an edge, never the front |
| In the digest | The "while you were away" card or a scheduled digest |
| Silent | The run record only |

Owners set the urgency per source, by voice or in the Swift window. Nothing proactive interrupts speech, a call or quiet mode, except a due reminder the owner set.

## 13. Accessibility

- Body text ≥ 14 px on cards (17–18 for answers); `--faint` ≥ 4.5:1 on both surfaces.
- Reduced motion: a 120 ms fade only; static rings; spinners become a static ¾ arc.
- Forced colours: Canvas / CanvasText surfaces, ButtonText borders; the amber band becomes Highlight; halos drop.
- Every state mark has a word; the waiting badge's amber always carries a shield.
- 100–200% scaling in CSS px; check 150% on the real PC.

## 14. Mapping to today's code

| Today (`overlay/src`) | Becomes |
|---|---|
| Card kinds rendered one by one in `main.ts` (2,236 lines) | One card renderer: state line + origin line + blocks + footer |
| `result.status` done / cancelled / error / rejected | States done / stopped / failed / stopped |
| `confirm.request` + artifact kinds | State ok + facts / change / preview / command blocks |
| `followup {question}` | State waiting (+ "Swift is asking" while speaking) |
| `due-*` run ids | `origin: "reminder"`, state due |
| `details` text / list / table, live `source` / `doing` | Text, list, table, sources, steps blocks |
| `runs.rows[]` | Edges, with origin when it isn't `asked` |
| `StackEntry.kind` | Waiting for you rows, later the "while you were away" card |

Build order, when the owner says so: tokens and the card renderer behind the current behaviour (no new features), then origin (N2, with run records), then the proposals one at a time.

## 15. Before building: real-PC checks

Nothing in Halo has been seen on the owner's screen. Check, on the real PC, before the build:

1. Glass at 94% over real apps and wallpapers, dark and light (text readable without blur).
2. The tail at all six anchors, and at 150% scaling.
3. The amber band and halo against the accent halo, side by side: never confused.
4. Edges' tinted tone against the card: distinct at a glance.
5. The sleeping orb: visible as "not listening" from normal viewing distance.
6. Motion of a card growing from the orb, the tail settling last (280 ms, no overshoot).
