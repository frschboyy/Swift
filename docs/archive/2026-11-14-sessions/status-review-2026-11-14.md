# Status review: every decision and exploration against the code (2026-11-14)

Checked against `main` at `a8f12ce` (plus `549a3c3`, a docs-only commit with the owner's modes-study decisions). The owner asked for it.
Method: each ADR's status line and "implementation status" sections, the handoff and workstreams, owner-check status in
`docs/testing/owner-checks.md`, and grep or reads of the code named below. No code was changed, run or tested; "done" means the
code is on `main`, not that the owner has seen it on the real PC (check status is noted where it matters).

Statuses: **done**, **partly**, **not started**, **superseded**, **waiting** (on what).

## What the review changed (status lines only)

- ADR-013, 014, 016, 017, 018, 019: status lines now say what is on `main` (ADR-018 and 019 were the stale ones: Step 1 and Step B are merged).
- ADR-019 §9's heading no longer says "not merged".
- Handoff README: the "product roadmap hasn't started / groundwork not started" lines, Halo Step B, item 9's first half and the
  `WorkerTask` grant sentence now match the code.

## Three findings that matter

1. **Groundwork is mostly built, and the handoff said none was.** Run records (`src/swift/runs.py`, `RunRecords`, `tests/unit/test_runs.py`),
   the memory store (`src/swift/memory.py`, `test_memory.py`: "remember", "forget", versions, one writer), `WorkerTask` and `Grant`
   (`executors/base.py:127,146`, `test_worker_task.py`), the step grant (`executors/step_grant.py`, B2) and N2's `origin`
   (`ORIGINS` in `ipc/protocol.py`, `abc1f1f`). Not built: the `session.py` split (still 5,008 lines; a session is on it), ADR-014 L3.
2. **Review item 9 is half built.** Merged: the acknowledgement of what was drawn (`drawn.py`, `6aadae9`) and one clock for a card's
   countdown (`f0970e6`). Not built: the versioned snapshot (`front`, `behind`, `stack`) and the inbound "busy" signal. ADR-018 Step 2
   and the interaction layer both wait on the rest. `roadmap.md` still shows item 9 as unticked, which is right.
3. **The decided-but-unbuilt design work is B3–B7, Halo's ADR-019 §8 items, and the modes study.** Nothing in `overlay/src` renders tables,
   comparisons, diagrams or document previews (no Mermaid anywhere in `src` or `overlay/src`), cards only have `CardSpec.size: "fit"`,
   and the watch window is unchanged.

## ADR-000 to ADR-008

| Doc | Decided | Status | Evidence | Next |
|---|---|---|---|---|
| ADR-000 Phase 0 plan | Repo, runtime, wake phrase "Hey Swift", personal use, Google account, connector-ready | **done** | Historic record; the wake phrase and repo are as decided | None |
| ADR-005 Connector-ready | Connector boundary; built-in Google first; plugin/MCP host later | **partly** | `connectors/base.py`, `gmail.py`, `google_calendar.py`, `fake.py`; no plugin or MCP host (Phase 7 / ADR-016 E) | Host only when a second source is needed |
| ADR-006 Voice overlay MVP | Tauri overlay, Python backend over a token WebSocket, Claude Code executor | **done** | `overlay/`, `src/swift/ipc/server.py`, `executors/claude_code.py` | None |
| ADR-007 Routing layer | Rules, local classifier, model per demand, escalation, lanes (§10); Hermes "not now" | **done** | `routing/` (rules, classifier, demand, fast, light, local), `executors/claude_code.py` and `config` models per demand. Hermes: **not started** by decision. Open: the light lane (seams decision 2) | Owner's call on retargeting or turning off the light lane |
| ADR-008 Identity and providers | Two layers; `ProviderInfo`; generic status labels | **done** | `executors/providers.py`, `identity.py`, `ExecEvent` | None |

## ADR-009 to ADR-012

| Doc | Decided | Status | Evidence | Next |
|---|---|---|---|---|
| ADR-009 Overlay UX | Readable failures, movable placement, visible status | **done**, its "not done, possible later" items **superseded** | Placement and flip in the Rust overlay; free positioning came with ADR-015 §12 ("a dragged card stays where it was dropped") | None |
| ADR-010 Workflows and show me | Artifacts, gateway, show me, confirm cards | **done** | §13 table: `workflows/artifacts.py`, `security/gateway.py`, `security/journal.py`, `tools.py`, `scope.py` | None |
| ADR-011 Workflow ecosystem | W1 playbooks; W2 capability registry and file tools; W3 recipes; W4 creating by voice; W5 schedules and hardening; watchers; learning | W1 **done**; W2–W5 **not started**; watchers **not started** | W1: `workflows/library.py`, three packages in `workflows/library/` (calendar-event, email-draft, research-into-word). `library.py` reports `recipe`, `schedule`, `watch` as "not supported yet". No file tools anywhere in `src`; no `gmail.metadata` scope (`connectors/google.py` says it waits for watchers). The Grant scope exists only per run (`workflows/scope.py`) | W2 file tools next, after the modes study's build (roadmap step 8); needs the Recycle Bin question of ADR-019 §7.2 settled first |
| ADR-012 Desktop interaction | D1–D2 context and writing in Word, Gmail, Outlook; D3 Chrome extension; D4–D5 vision | D1–D2 **done**; D3 **not started** (only if daily use asks); D4–D5 **waiting** on the owner's yes (decision 26) | `desktop/base.py`, `windows.py`, `fake.py`, `gmail_fill.py`, `workflows/desktop_tools.py`. A9 fixed Gmail's collapsed To row (`f060c8b`; check 310 never run) | Real-PC checks 252, 310 |

## ADR-013 to ADR-016

| Doc | Decided | Status | Evidence | Next |
|---|---|---|---|---|
| ADR-013 Attention threads and concurrent requests | Threads, deadlines instead of timers, up to 3 requests at once, per-run tool scopes | phases A and B **done**; its listed "not done" (harness replay buttons for several requests, collapsed count of others, per-run HTTP MCP tokens) **not started** | `overlay/src/presenter.ts`, `session.py` (`Run`, `MAX_RUNS`), `attention.py`, `tests/unit/test_runs.py` | None needed; the Deck (ADR-018) amended its front-taking rule |
| ADR-014 Presence and lifecycle | L1 presence and lock; L2 held cards and parking; mid-task redirects; **L3 quiet modes and call detection** | L1, L2, redirects **done**; L3 **not started** | `presence.py`, `lifecycle.py`, `parked.py`, `attention.py`; no quiet hours or call detection anywhere in `src` (the roadmap's groundwork list names it) | L3 before anything proactive (watchers, notifications at rest) |
| ADR-015 Overlay windows and card timing | Pane windows, countdown only while seen, waiting stack, typing to Swift, Read more in place | **done**; the waiting stack's "unseen answers vanish" problem is being worked as A4 (**fixed**, check 256 waits) | `attention.py` (`set_seen`), `stack.py`, `overlay/src/stack.ts`, `panes.ts`, `lib.rs`; A10 added `cover.rs` | Checks 256, 257 on the real PC |
| ADR-016 Assistant parity | Phases A system lane, B Swift speaks, C dialogue (built); D proactive, E connector host and wave 1, F screen awareness, G offline, H voice ID and phone, I context and writing | A, B, C **done**; D, E, F, G, H **not started**; I **partly** (typed input is built; the cheap web lane, rewrite, index, automations are not) | `system/` (intents, control, scheduler, lane), `speech.py`, `dialogue.py`, `stack.py`. Decisions 16–21, 26–28 are still open in the handoff §5 | Per the handoff: each only when its trigger appears; none now |

## ADR-017 to ADR-021

| Doc | Decided | Status | Evidence | Next |
|---|---|---|---|---|
| ADR-017 Capsule overlay | Capsule design, dark and light, tray, live view (§7) | **done** (the look is replaced by Halo only when the owner switches it) | `overlay/src/capsule.ts`, `live.ts`, `views.ts`, `theme.ts`. Checks 63–75: mostly passed, 63–67, 70, 72–75 never run | Owner runs the never-run checks, or retires them when Halo becomes the default |
| ADR-018 The Deck | Step 1 overlay only; Step 2 hold, in-line and ready rules; one-window spike | Step 1 **done** (was recorded as unmerged: corrected); Step 2 **waiting** on item 9's versioned snapshot; spike **not started**, **waiting** on Step 2 and the owner's "keep Step 1?" call | `overlay/src/deck.ts`, `deckdraw.ts`, `shuffle.ts`. Item 9: only acknowledgement and clock merged | Owner decides "keep Step 1?" after checks 168 and 173 (173 never run) |
| ADR-019 Halo design system | Halo as the look; N2 origin; §8 findings; Step B one renderer; proposals one at a time | Step A **done**; Step B **done** (merged 2026-11-14); N2 **done**; §8's six items **not started**; making Halo the default and deleting the old look **waiting** on the owner seeing it; the approval ladder **partly** (B2's step grant only; no plan card); attention policy and "while you were away" **not started** | `overlay/src/look/`, `overlay/src/card.ts`, `blocks.ts`; `ORIGINS`; `executors/step_grant.py`. Checks 216–221: 221 never run, 218 must be re-run (it changed since it failed), the rest are not in the never-run list | After the 305 fix: §8 items with B3 |
| ADR-020 One record per conversation | A, then B's model where grammar fails; try a dedicated wake model; its step 1 (`conversation.py`) dropped | **partly**. Step 1 dropped by the owner; the open-question slot claims and "same request said again" are built as A7 | `restated.py`, `same_request.py`, `dialogue.py`, `exchange.py`. Wake model: see ADR-021 | Checks 201–211 (not 211: blocked); 204/304 wait on a second review |
| ADR-021 Wake phrase second way in | Acoustic detector behind `wake.acoustic` | steps 1–6 **done**, still **off by default**; **waiting** on owner checks 228–232 with it on | `wake_acoustic.py`, `settings.py:142` (`acoustic: False`). 228 and 232 passed; 229–231 never run | Owner runs 229–231 with `wake.acoustic: true`, then decides to turn it on |

## Halo design system (`docs/design/halo-system/`)

| Item | Status | Evidence | Next |
|---|---|---|---|
| `DIRECTION.md` (one run, one anatomy, a block catalog) | **partly**: one card renderer and `origin` exist; the block catalog is only today's blocks | `card.ts`, `blocks.ts`, `ORIGINS` | Grow the catalog as B4 adds shapes |
| `SPEC.md` §3–§5 anatomy, states, blocks | **partly**: the seven states are in `CardState`, Halo has the colours (check 218 passed), but states are not yet all truthful or distinct (B3) | `card.ts` | B3 |
| `SPEC.md` §7 deck sizes, §9 positions and tail, §10 compact confirm | **partly**: positions and tail drawn; folding the deck for a compact confirm not built (ADR-019 §8) | `look/geometry.ts` | §8 items, one commit each |
| `SPEC.md` §8 presence in three parts | **not started** (the capsule's states are unchanged) | `capsule.ts` | With the attention policy, later |
| `SPEC.md` §11 approval ladder, plan card | **partly**: one step grant built; plan card **not started**; the modes study decided its build | `step_grant.py` | Modes study part 2, last |
| `SPEC.md` §12 attention, "while you were away" | **not started** | none in `src` | Roadmap step 4, after L3 |
| `SPEC.md` §13 accessibility | **waiting** on real-PC checks (R2 of the UX research) | none | Owner |
| `SPEC.md` §15 real-PC checks | **partly**: 221 (motion) never run and 218 to re-run; the others not in the never-run list, and B7 says it was too quick to see | owner-checks status | B7 |
| `tokens.css`, `halo.pen`, `boards/` | **done** as design sources; a new pen.dev prompt that extends Halo is in the owner's hands (B8) | | Owner |

## Explorations

| Doc | Status | Evidence | Next |
|---|---|---|---|
| `product-direction.md` | its §8.2 order is **partly** done: items 3 (split `session.py`) in progress, 4 (run records) **done**, 5 (memory) **done**, 6 (`WorkerTask`) **done**, 7 (L3) **not started**; "Next" items 8–13 **not started** | `runs.py`, `memory.py`, `executors/base.py`; no watchers, recipes, Swift window or file tools in `src`. §8.3 item 5 (a policy table) has `security/gateway.py` risk classes, not a settings-driven table | Update the handoff's §4 order (done in this review); the owner's six-week test still decides the rest |
| `assistant-ux-research.md` | recommendations R1–R17 **not started** except R5 (origin, **partly**) and R6 (policy table, **not started**); R13 "try rivals first" **waiting** on the owner | `ORIGINS` | R3 (approval counts in the usage report) is the cheapest |
| `ui-reach.md` | analysis only; its "durability" recommendations are **partly** answered by A4 (rows kept until read) and run records; "recall by voice" **not started**; heard words editable by typing **not started** | `runs.py` | After B-order work; start with the report counts (§5, "Measure it first") |
| `interaction-layer.md` | exploration, nine owner decisions **waiting**; nothing built; spikes S1/S2 answered by `desktop-choreography.md` | none | Owner decides; not before item 9's second half and daily use |
| `desktop-choreography.md` | spike results only (`spikes/desktop/`); five decisions **waiting** | spikes | Owner; delete or keep the spike code |
| `context-aware-speech.md` | step 1 **done** (`eval/stt/gate.py`, `stt/improve.py` normalise); step 2 **waiting** on the owner's yes to the labelling card; step 3 **waiting** on a model download OK; 4–5 **not started** | gate script | Owner's yes on seams decision 7 |
| `modes-study.md` | seven decisions taken 2026-11-14 evening, all as recommended; **not started** (no code) | `workstreams.md`, commit `549a3c3` | Build in its order after the queued B work: "ask me about everything", learned trust (Wi-Fi off, Bluetooth off, airplane mode on), then the plan card |
| `workflows/` (five examples) | **superseded as a build target for now**: ADR-011 W1 does not load them (`library.py` skips `recipe`); they stay as format tests for W3 | `docs/explorations/workflows/README.md`, `library.py` | Revisit at W2/W3 |

## Workstream items B3–B8 (decided, not built)

| Item | Status | Evidence | Next |
|---|---|---|---|
| B3 distinct state looks | **not started** | `card.ts` has the states; Halo has colours; no truthful per-state treatment yet | With §8 |
| B4 results laid out to fit | **not started**; the vetted set is approved; the plan is in a session's notes (four steps, checks 340–351) | no Mermaid, no table or comparison renderer beyond today's `blocks.ts` | After the 305 fix |
| B5 growing and expandable cards | **not started** | `CardSpec.size` is `"fit"` only | With B7 |
| B6 the watch as a monitor | **decided, not started** | `live.ts`/`views.ts` unchanged | Last of the B order |
| B7 motion that is seen | **not started** | `showCard`/`hideCard` in `main.ts` | With B5 |
| B8 pen.dev prompt | **waiting** on the owner | | Owner |

## Next, in order

1. **The 305 fix** (Read more cut off; repeated paragraph): **merged** into `main` on 2026-11-14 (`59fa830`, check 340). B4 is unblocked.
2. **B4**: results laid out to fit, in the plan's four steps, one at a time. Needs the vetted set (approved) and checks 340–351.
3. **ADR-019 §8 items with B3**: six items, one commit each, each with a seam scenario and owner checks. They share `card.ts` and `main.ts` with B4, so one at a time.
4. **B5 with B7**: growing cards and visible motion, together, since both change `showCard`/`hideCard`.
5. **B6**: the watch as its own window, last, since it is the one that needs a new window.
6. **The modes study's build**, interleaved so it never touches the same card files at once: "ask me about everything" first (small: one setting, two gateway checks, a tray label), then learned trust for the three radio kinds, then the plan card (needs the grant and the card renderer, so after B4).
7. **Not blocked on the B order, can run in parallel**: the `session.py` split (its own session); review item 9's second half (kept only if the total deletes code); the owner's real-PC checks (252, 255, 306, 310, 320, 330, 216–221, 229–231); ADR-014 L3 before anything proactive.
8. **After that**: notifications at rest and "while you were away", watchers v1 (needs decision 22), recipes from runs, the Swift window, W2 file tools. All unchanged from the handoff.

## What I could not check

- No tests were run. "Done" is from reading code and the owner-check status block as of `c497419`.
- Real-PC behaviour: most "done" items have checks the owner has not run (111 never-run checks as of that block).
- ADR-007 §6 (escalation mid-run) and ADR-016's lane tables were confirmed by the existence of their modules and settings, not by tracing behaviour.
