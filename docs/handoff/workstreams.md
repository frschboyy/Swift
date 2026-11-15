# Three workstreams (from the owner's run of 2026-11-13)

The owner's run of 2026-11-13 (10:05 and 13:37) failed more than a list of checks. Its failures share three causes
underneath, so they're tracked as three workstreams. Each item names what the owner saw, the checks that prove it,
what kind of work it is, and what's known. `roadmap.md` has one line per item with its checks, so `ROADMAP.md` shows
where each stands. The owner's notes are in the ledger (`owner-checks-ledger.yaml`, 2026-11-13 and 2026-11-14).
A12, B9 to B14 and C9 come from notes there that hadn't been carried over (added 2026-11-15).

Kinds: **defect** (Swift does the wrong thing; *proven* means the cause is reproduced), **architecture** (a structure
that keeps producing defects), **design** (how it should look or behave; the owner decides), **capability** (not
built).

The owner's test for all three: at every moment they can tell what Swift understood, what it's doing, what it needs
from them, why it asks for a permission, whether it really finished, and what happened if it failed.

## A. Task orchestration and state

What runs, what it's waiting for, and whether the screen says so. Most of the run's confusion is here.

| # | What the owner saw | Checks | Kind | What's known |
|---|---|---|---|---|
| A1 | "Turn off the wafer" asked "Wi-Fi or Bluetooth?" and never finished | 201, 206, 239, 243 | defect, proven | **Fixed** (merged 2026-11-13, `225ca9b`, `106b6dd`, `541ea7c`); check 243 waits. A1b, the agent's refusal text giving "Wi-Fi or Bluetooth" as its example: **fixed** on `claude/workstreams` (`1429e81`). Left for the owner: a click on an option the agent wrote never counts (product rule) |
| A2 | A question showed "Working on it", with no question to answer (lunch, 13:51:57; also 206, 211) | 206, 211, 218, 250 | defect, proven | **Fixed** (`75c3118`, root; merged 2026-11-13): after two requests ran together, a lone new request was never sent as the one in front, so its question was taken for another's and drawn as the working card. Proven in the seam replay and the harness. Check 250 waits |
| A3 | The spinner beside "Working" doesn't turn | 206, 251 | defect, proven | **Fixed** (merged 2026-11-13), two causes: Windows' Animation effects off made the spinner a still arc (`5aa1aa1`, root: it now turns slowly under reduced motion, a design call the owner can veto), and the one-line card was redrawn every second, restarting it (`db4f0d3`, root). Check 251 waits |
| A4 | Cards behind the main one vanish before they've been seen (research behind an email) | 208, 219, 256 | defect, proven in the seam | **Fixed** (`5a22432`, root for the backend's row ageing; merged 2026-11-13): an answer that ends behind a card keeps its row until it has been read. Whether that is all the owner saw is unproven until check 256 runs |
| A5 | A card's lifetime should fit the request (a command, a research, a question) | 210 | design | Works; the owner wants lifetimes from the request's kind and whether it needs them |
| A6 | Opening a card from the stack seemed to restart it, and some stayed "Working on it" | 257 | defect, unproven | Not reproduced (`8a0111c`): replayed through the real session and presenter, a card brought back from the stack carries on and starts nothing new. The DOM, or a run that died underneath, are still open; check 257 looks on the real PC |
| A7 | One ask became two requests ("How are you? Can you turn off the Wi-Fi?" and "Turn off the Wi-Fi") | 204, 205, 197, 303, 304 | defect, proven | 197's duplicate: **fixed** (`4b9ecd9`). 204, from this PC's logs of 2026-11-13: (1) the real attempt, at 14:35:17, was said with a false start ("... Can you set can you turn off the Wi-Fi?"). The system grammar missed it, so it went to the agent. A request begun again is now Swift's own: **fixed** on `claude/a7-check-204-df2c13` (`b4768b3`), check 303. (2) The 14:44:20 approval card: "Turn off the Wi Fi." was unanswered and parked, then opened from the stack; the owner said the request again (misheard "He has turn off Wi Fi."). That counted as `elsewhere`, so the question parked and the request went to the agent beside it. On `main` (replay `test_the_request_said_again_to_its_question_reopened_from_the_stack_is_not_a_second_request`) no agent runs any more, but the restatement is lost: the Wi-Fi stays on and the question parks again. The owner decided A+B (2026-11-14, below): the same request said again is the yes, and what only sounds like it asks again. **Fixed** on the same branch, check 304; it waits on a second review (product rule). `fbdaed2`'s premise (a greeting ended by a comma) was wrong: no such utterance was in the run. The change is harmless and kept. Also suspected: that a request said while a question is open always starts on the agent. **Disproven** (`ebd73f7`): it is routed like any fresh request, so a system command gets the system lane; the replay guards it |
| A8 | Said "Playing." and nothing played | 235, 262 | defect, proven | **Fixed** (`41a1773`, merged 2026-11-13): Swift listens for sound for 2 s after the key and otherwise says nothing started. Check 262 waits |
| A9 | Gmail: drafted, but nothing filled in (check 252 failed twice, 2026-11-14) | 252, 310, 311 | defect, partly proven | Three failures in the 2026-11-14 run, from the `gmail_fill` log. (1) 12:30 `not_loaded`, Subject and Body found but no To: **proven** from the UIA tree of a compose window the owner opened. When the compose opens without the cursor in it, Gmail shows To as a "Recipients" line with no To box, and focusing that line opens the box. **Fixed** (`f060c8b`, root; merged 2026-11-14), check 310. (2) 12:24 `not_loaded` with nothing found and Chrome in front: unproven (the page not loaded, or the tab not in front). (3) 12:26 `gmail_behind`: the compose was found behind, and SetForegroundWindow didn't bring it forward; unproven. In the probe, UIA `SetFocus` on a compose field brought Chrome forward from a background process: a candidate fix once it's seen from Swift. Probe: `spikes/desktop/gmail_fields.py` (4) 2026-11-14 16:00, other PC: `gmail_focus_body` twice after the compose was brought forward, with the keyboard on the page, then in To. Not reproduced here, because on this PC the body is set directly (it has a writable Value pattern) and never needs the cursor. Unproven; one guess is that Gmail's address suggestions, opened by setting To, take the focus or cover the click point. `20f07e5` (safeguard, on `claude/a9-body-focus`) logs what the click would have hit and whether the body was settable; check 311 and `spikes/desktop/gmail_body_focus.py` prove it on the other PC |
| A10 | Swift stayed behind an always-on-top Task Manager | 203, 253, 254, 320 | defect, proven | Proven by check 254 (2026-11-14): Task Manager on top is in z-order band 16 ("system tools"), Swift in band 1 like every ordinary app, and no band-1 window can come in front of band 16. Ordinary always-on-top windows: Swift comes in front of them on "Hey Swift" (`cd15d23`, check 253). The owner decided to move out from under it (below): **fixed** (`8e42954`, root; merged 2026-11-14). When a card is about to show (heard, a card, an open question) or the overlay is placed, the overlay lists the always-on-top windows in a higher band than its own (`cover.rs`, `GetWindowBand`, no polling); if one covers the cards' area at the owner's spot, the cards go to the nearest uncovered anchor (`placement::uncovered_anchor`), and back home once nothing covers it. Focus is never taken (`SWP_NOACTIVATE`). Check 320. Not covered: pane windows (the stack, the reader) stay where they are |
| A11 | A command Swift understood wasn't done ("I didn't turn off Wi-Fi") | 239 | defect | The wafer cases are A1; any other "I didn't…" still lands here |
| A12 | A spoken Reject on an approval card was slow to be heard; the click worked | 195 | defect, unproven | The owner's note on check 195 (ledger, 2026-11-13 10:05); check 195 passed. Not investigated: the log's timings for that run would show whether the wait was wake, speech recognition or the card |

**The architecture underneath** (handoff §2, "Root causes still open"): the overlay can refuse a frame and the backend
isn't told; frames go out through two doors; each countdown runs on both sides. Review item 9 (one versioned screen
snapshot, acknowledged when drawn) is the structural fix for A2–A6. Run records (groundwork) are the fix for A6:
a card from the stack would point at a run that still exists, or say it ended.

## B. Adaptive UI and UX

How results and requests look. Mostly design for the owner, built on Halo (ADR-019): extend it, don't start again.

| # | What the owner wants | Checks | Kind | What's known |
|---|---|---|---|---|
| B1 | An approval card leads with a plain sentence: what it will do, why, what comes of it; the command folded underneath | 238, 199, 263, 264 | design, then code | **Built** (`bce7b36`, `2b1003b`; merged 2026-11-14) as decided (below): the agent's own sentence leads, marked as the agent's; the command's first line always shows, only the rest folds. Checks 263–264 wait |
| B2 | Fewer approvals: one task's commands grouped, with one grant for a coherent step | 238, 300–302 | design + architecture | **Built** on the `WorkerTask` grant (`59d7f37`, `f64f4a2` root, `2897e94` safeguard; merged 2026-11-14): one approval covers a step's commands, listed on B1's card; deletes, sends and unknown commands still ask. Checks 300–302 wait |
| B3 | Distinct looks for working, waiting for an answer, waiting for an OK, doing, failed or timed out | 206, 211, 218 | design + defect | Shares its defect with A2; Halo has the colours (218 passed), the states must be truthful first |
| B4 | Results laid out to fit: tables, comparisons, project cards, real diagrams, document previews | 238 | design + capability | Halo Step B (one card renderer) is the base; the interaction layer's decisions decide the rest |
| B5 | Overlays that grow when the content needs it, and can be expanded by hand, without covering the work | — | design | The owner leans to both |
| B6 | The watch (live view) and working surfaces distinct; the watch keeps a technical feel | 93, 95 | design | **Decided** 2026-11-14 after the study (`674c17d`, `5e7b1e8`; below): its own window as a monitor, visual where something is made, the LIVE mark in Halo's blue. Not built yet |
| B7 | Motion that's seen: the card growing from the orb (unsure), transitions that feel alive | 221, 178 | design | 221 was too quick to see |
| B8 | A pen.dev prompt that extends Halo | — | owner | The owner is drafting it; `docs/design/halo-system/` is the base |
| B9 | The watch (live view) docked as a sidebar, or a mini sidebar, at a corner or screen edge, instead of a window beside the card | 305 | design | The owner's note on check 305 (ledger, 2026-11-14 16:06): "Watch in a corner or sidebar". Today it opens beside the card (B6's decision: its own window, restyled as a monitor). Nearest ideas: Halo's "one run, five sizes" (`SPEC.md`), ADR-018's one-large-window spike, and the 2026-10 overlay study's docked ribbon (rejected then for the whole overlay, not for the watch). Not decided, not built |
| B10 | The watch feels disconnected from its request: the main card goes soon after Watch opens, and "closes by itself" shows while the watch stays open | 305 | design, maybe defect | The owner's note on check 305. The card's lifetime ignores an open watch (A5's rules say nothing about it), and the label is `overlay/src/views.ts`. Not investigated |
| B11 | Progress or animation in the watch, so it's seen to be working | 305 | design | The owner's note on check 305. Belongs with B6's monitor restyle and B7's motion |
| B12 | "Open answer" leads back to the answer | 305 | design, maybe defect | The owner's note on check 305. Where it leads today isn't recorded. Not investigated |
| B13 | File lists shown as a tree | 305 | design | The owner's note on check 305. A layout for B4's renderer (B4's vetted set covers tables and diagrams, not trees yet) |
| B14 | A discreet indicator of a running timer, perhaps in the stack | 305 | design | The owner's note on check 305. Related, older: handoff §4 i (the timer widget, after review item 9) and running-default decision 5 (a timer card with "+5 min") |

## C. Agent autonomy

Swift as an agent that works out how to reach a goal, inside the product rules, rather than a set of commands.

| # | What the owner wants | Checks | Kind | What's known |
|---|---|---|---|---|
| C1 | Never invent a fact it doesn't have: the distance to CBD was guessed at 4 km (really 10–11) with no location | 259–261 | defect, fixed | Proven: the weather tool's fixed wttr.in request places the PC by its internet address ("Nairobi Industrial Area", 3–4 km from CBD); the agent took that for the owner's location and gave a distance from memory, 2 of 2 times when replayed. **Fixed** (`8f2c0d2`, `7b08ba4`; merged 2026-11-13): the agent is told Swift doesn't know where the user is and must ask for a starting point, and the weather's area reaches it labelled as the forecast's only. Replayed with the fix: it asks where you're starting from (3 of 3). Checks 259–261 wait |
| C2 | Book an Uber, a flight to Abidjan: find the way, ask for sign-in and details, do it with the owner watching, confirm before paying | 238 | capability | Refused today. Paying always needs the owner's OK; sign-in is the owner's (product rule) |
| C3 | Opening a website failed (Blackboard, 15:07) | 238, 255, 330 | defect; 255's step 2 proven | No tool could open a web address: `desktop_open(url=…)` now opens one the owner said in this request (`a7343e3`, check 255). Check 255 (2026-11-14 12:35): "open usiu dot ac dot ke" opened; 28 s later "Open my university's website." was refused twice, and the owner's yes to the address the agent offered didn't count. The owner decided (2026-11-14, below): an address the owner said or typed earlier in the same conversation, in the last 10 minutes, may be opened. **Fixed** (`27bcdbe`; second review done, merged 2026-11-14), check 330. The owner's 15:00 run of check 330: "open my university's website" opened usiu.ac.ke, and he objects: he never said that was his university. His second decision (below): a recent address only when the request points at it, a description only from a memory he taught. **Built** on `claude/c3-pointing-address`, check 330 re-worded; it waits on a second review (product rule) |
| C4 | Find and use a tool it lacks (diagrams): explain why, ask before installing, ask for sign-in | 238 | capability | Installing needs the owner's OK every time |
| C5 | Reminders, schedules and repeating automations ("every Monday at nine") | 237, 239 | capability | One-off reminders only; recipes from runs (product step 6) and a repeating reminder (§4 leftover) |
| C6 | "Play some music": find out how the owner plays music (an app, YouTube, a folder, a service) and check it started | 235 | capability (after A8) | — |
| C7 | "Remember that my manager is Ada" | 237, 290–293 | capability | **Built** (`423dd92`, `fee9a38`; merged 2026-11-14): "remember", "forget" and "what do you know about me", plain files under `%LOCALAPPDATA%\Swift\memory`; card and ID numbers refused. Checks 290–293 wait |
| C8 | GitHub: create a repository and pull it down | 238 | worked | It asked for approvals with raw commands: B1, B2 |
| C9 | "What's on my screen right now?" named Chrome only | 237 | capability | The owner's note on check 237 (ledger, 2026-11-13 10:05). Screen awareness is deferred (handoff §4, ADR-016 F, decision 26), so the answer only knows the front window |

**Using the PC's location (C1, needs the owner's OK):** the owner's alternative to asking is to use the PC's own location with permission. That is Windows Location (the WinRT `Geolocator`), a new capability and a new dependency or native call, so it isn't built. If wanted: a `location` tool that asks on a card the first time, says plainly when the location is off or unknown, and never falls back to the internet address.

A **credentials vault** (the owner's idea for C2 and C4) touches a product rule: sign-in is the owner's. It needs a
decision before anything is built: what may be stored, who enters it, and what Swift may do with it.

## The order

1. The proven defects: A8 (music), A1b (the agent's example text).
2. Reproduce A2 and A4 in the harness: they are the most confusing and share a cause with review item 9.
3. A7, A10, C3, A9: look, prove, fix.
4. C1: an agent instruction and a test, with a check.
5. B1 (a plain sentence on approval cards): the first design item that is a small change.
6. Review item 9, then Halo Step B and the interaction layer's decisions, for B3–B7.
7. Groundwork (run records, the grant, the memory store), then C2, C4, C5, C7.

## The owner's design decisions (2026-11-13)

Taken from the orchestrator's recommendations, except B4 and B6, which are the owner's own:

- **A5:** a command's card goes a few seconds after it's done; an answer stays until it has been seen; a question stays while it waits for the owner and pauses its countdown out of sight.
- **B2:** one approval covers one coherent step of a task, with its commands listed inside; anything outside that step asks again, and anything irreversible (deleting, paying, sending) always has its own card. Built after the grant (groundwork).
- **B4:** not a fixed list of layouts. For each result Swift works out how best to show it, visually and in words (a table, a comparison, a diagram, a preview, plain text), and the card's look follows. Swift may use free tools to do that, so it is flexible rather than limited to what's built in. Decided: a vetted set of free tools ships with Swift (the owner approves the list once); anything outside that set is installed only when needed, asking on a card every time, as C4 says.
- **B5:** both: a card grows with its content up to a limit that never covers the owner's work, and can be expanded by hand beyond that.
- **B6:** to study before building: whether the live view ("watch me") is a card of its own, and whether it feels technical (steps ticking by) or visual: the email being written or the deck being built, shown as it happens, as pen.dev does.
- **B7:** transitions slow enough to see; the card growing out of the orb is tried in the harness before the owner chooses.

## The owner's decisions of 2026-11-14

All taken from the orchestrator's recommendations:

- **B1:** the agent's own sentence leads, marked as the agent's; the command's first line always shows under it, and only the rest folds.
- **Review item 9:** carries on, on its branch: with B1 in, the countdowns move to one side; it merges only if the total deletes code.
- **B4:** the vetted set is approved: Swift's own code (text, tables, comparisons, simple charts), Mermaid's tiny build (diagrams), Windows' PDF renderer and a text excerpt (documents). A mind-map shape is prototyped now; a map that grows as the owner talks is a later item, on run records and memory.
- **Halo Step B:** go, after item 9's countdown move (both change how cards are drawn).
- **B6:** its own window restyled as a monitor; visual where there's something to see, technical otherwise; the LIVE mark in Halo's accent blue (red means failure); email shows the finished draft first, streaming later; the visual deck waits for a deck capability.
- **Memory store:** plain files under `%LOCALAPPDATA%\Swift\memory`; "forget" doesn't ask, since every version is kept. Card and ID numbers are refused, like passwords and PINs.
- **B2:** built now, on the `WorkerTask` grant; Swift, never the agent, decides what's irreversible.
- **A10:** waits for owner check 254 before any fix (a signed install only if nothing else works).
- **A10, after check 254** (Task Manager on top is in band 16, Swift in band 1): **move out from under it.** When a
  window in a higher band than Swift's covers the orb or the card's area, Swift draws its card at the nearest anchor that
  isn't covered, and returns to the owner's chosen anchor once it's uncovered. No signed or UI-access install. Merged 2026-11-14 from
  `claude/a10-uncovered-anchor-9b3922`, check 320.
- **A7, saying the request again to Swift's own open question** (product rule, A+B): if the owner says it (never types it) and it parses to exactly the same system intent and slots, it is their yes. If it only sounds like the request (as at 14:44:20), it approves nothing: the question stays and is asked once more. Another intent ("turn on" for "Turn off Wi-Fi?") never answers it. Built on `claude/a7-check-204-df2c13`, check 304; reviewed by the orchestrator before it goes to the owner.
- **Halo Step B's three open points** (the one renderer, merged 2026-11-14, checks 305–306):
  ADR-019 §8's six items are built on a separate branch after Step B merges, one commit each, with owner checks;
  both looks stay for now, and a small branch makes Halo the default and deletes the old look only after the owner
  has seen Halo on the real PC (checks 216–221); deck edges and stack rows stay out of the renderer, revisited with B5.
- **C3, a web address the owner gave earlier** (product rule, from check 255): `desktop_open(url=…)` may open an address the owner said or typed themselves earlier in this conversation, in the last 10 minutes. The source is Swift's own record of the owner's words (each request's transcript and their answers to its questions, kept with the conversation's exchanges), never the agent's text or what a page or tool read. A yes to an address the agent made up still never counts. When no address the owner gave fits, the agent asks the owner to say it instead of offering one. Merged 2026-11-14 after a second review, check 330.
- **C3, which earlier address a request means** (product rule, after check 330's run at 15:00): a recent address (the owner's own words, last 10 minutes, same conversation) is reused only when the request points at it ("open that site again", "the one I just opened", "open it"). A description ("my university's website") is reused only through a memory written from the owner's words ("remember my university is usiu.ac.ke"). Otherwise Swift asks him to say the address and offers none. Built on `claude/c3-pointing-address`, check 330 re-worded; reviewed by the orchestrator before it goes to the owner.
- **Modes study's seven decisions** (`docs/explorations/modes-study.md`, 2026-11-14 evening): all seven taken as recommended.
  Learned trust starts with Wi-Fi off, Bluetooth off and airplane mode on only; a spoken "always do X" may create a
  trust for a kind on the table, a typed one may not; `config.yaml` can't set a trust; a read folder outside the read
  folders is offered through the same card and added to `executor.read_dirs` (never-read places are never offered);
  the plan card covers commands only at first, as B2; "ask me about everything" covers every action and command except
  reads inside the read folders and volume up or down, and stays on until turned off; an offer comes after 3 approvals
  in 3 runs within 14 days with none rejected, once per kind. Built in the study's order after the queued B work,
  starting with "ask me about everything".
- **The foundation review** (`docs/explorations/foundation-rules-review.md`, 2026-11-15): all 14 decisions accepted as
  recommended. One approval model (levels 0–3 from reversibility, reach, channel, presence and origin) replaces the
  rules' exceptions; typed words never approve anywhere (settles check 387 and HA-HEAR-01); Tab and Enter on the
  card's own button is a click; a yes with the hotkey held is a gesture; web addresses not in this request's words are
  asked about ("Open usiu.ac.ke?") instead of matched by regex; an address in the owner's own words can be a recipient,
  marked on the send card; an unclear write into an app is asked about with a preview, and a terminal always gets its
  own card; a Recycle Bin move is a card that a step card may cover, a permanent delete its own card; `swift.log` gains
  reason codes (never content); paying by gesture only; `intake.approves` is the one decider, tested against
  `CLAUDE.md`'s table; provisional check ids renumbered at merge; the generated run list in its own file
  (`merge=ours`); moving between PCs by `git bundle` on request, still never push; `CLAUDE.md` lists this PC's working
  commands. `CLAUDE.md`'s rules are rewritten to the model, with a note of what isn't built yet.
- **The correction offer's level** (2026-11-15, after the second review of decisions 1, 3 and 10): level 1, like
  Swift's own question. While "Say yes and I'll send a correction" is on screen, a plain spoken "yes" takes it, with
  no need for Swift's name; typed words never do. What it starts is a new request, whose actions still get their own
  cards.
- **Type and run in a terminal after its card** (the owner's decision, 2026-11-15, replacing "no Enter" from earlier
  the same day): an approved terminal card types the command and runs it. The card says "Run this in …? Swift types
  it and presses Enter." with every character; approving it is the level 3 approval for running code. One command
  only: text with a line break is refused, since each line would run. The window is checked before typing and again
  right before Enter; changed in between, the command is left typed and unrun, and Swift says so. VS Code keeps its
  card on every write but Swift never presses Enter there (it can't tell the editor from the terminal yet). Check 397.
- **VS Code's card** (the orchestrator's recommendation, accepted 2026-11-15): every write into VS Code keeps the
  terminal's card until the read-only probe `spikes/desktop/vscode_focus.py` (check 399)
  shows UI Automation tells its editor from its terminal panel; then only the terminal needs it (OCT-01).
