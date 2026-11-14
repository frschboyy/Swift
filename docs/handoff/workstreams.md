# Three workstreams (from the owner's run of 2026-11-13)

The owner's run of 2026-11-13 (10:05 and 13:37) failed more than a list of checks. Its failures share three causes
underneath, so they're tracked as three workstreams. Each item names what the owner saw, the checks that prove it,
what kind of work it is, and what's known. `roadmap.md` has one line per item with its checks, so `ROADMAP.md` shows
where each stands. The owner's notes are in the ledger (`owner-checks-ledger.yaml`, 2026-11-13 13:37).

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
| A9 | Gmail: drafted, but nothing filled in (check 252 failed twice, 2026-11-14) | 252, 310 | defect, partly proven | Three failures in the 2026-11-14 run, from the `gmail_fill` log. (1) 12:30 `not_loaded`, Subject and Body found but no To: **proven** from the UIA tree of a compose window the owner opened. When the compose opens without the cursor in it, Gmail shows To as a "Recipients" line with no To box, and focusing that line opens the box. **Fixed** (`f060c8b`, root; merged 2026-11-14), check 310. (2) 12:24 `not_loaded` with nothing found and Chrome in front: unproven (the page not loaded, or the tab not in front). (3) 12:26 `gmail_behind`: the compose was found behind, and SetForegroundWindow didn't bring it forward; unproven. In the probe, UIA `SetFocus` on a compose field brought Chrome forward from a background process: a candidate fix once it's seen from Swift. Probe: `spikes/desktop/gmail_fields.py` |
| A10 | Swift stayed behind an always-on-top Task Manager | 203, 253, 254, 320 | defect, proven | Proven by check 254 (2026-11-14): Task Manager on top is in z-order band 16 ("system tools"), Swift in band 1 like every ordinary app, and no band-1 window can come in front of band 16. Ordinary always-on-top windows: Swift comes in front of them on "Hey Swift" (`cd15d23`, check 253). The owner decided to move out from under it (below): **fixed** (`8e42954`, root; merged 2026-11-14). When a card is about to show (heard, a card, an open question) or the overlay is placed, the overlay lists the always-on-top windows in a higher band than its own (`cover.rs`, `GetWindowBand`, no polling); if one covers the cards' area at the owner's spot, the cards go to the nearest uncovered anchor (`placement::uncovered_anchor`), and back home once nothing covers it. Focus is never taken (`SWP_NOACTIVATE`). Check 320. Not covered: pane windows (the stack, the reader) stay where they are |
| A11 | A command Swift understood wasn't done ("I didn't turn off Wi-Fi") | 239 | defect | The wafer cases are A1; any other "I didn't…" still lands here |

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

## C. Agent autonomy

Swift as an agent that works out how to reach a goal, inside the product rules, rather than a set of commands.

| # | What the owner wants | Checks | Kind | What's known |
|---|---|---|---|---|
| C1 | Never invent a fact it doesn't have: the distance to CBD was guessed at 4 km (really 10–11) with no location | 259–261 | defect, fixed | Proven: the weather tool's fixed wttr.in request places the PC by its internet address ("Nairobi Industrial Area", 3–4 km from CBD); the agent took that for the owner's location and gave a distance from memory, 2 of 2 times when replayed. **Fixed** (`8f2c0d2`, `7b08ba4`; merged 2026-11-13): the agent is told Swift doesn't know where the user is and must ask for a starting point, and the weather's area reaches it labelled as the forecast's only. Replayed with the fix: it asks where you're starting from (3 of 3). Checks 259–261 wait |
| C2 | Book an Uber, a flight to Abidjan: find the way, ask for sign-in and details, do it with the owner watching, confirm before paying | 238 | capability | Refused today. Paying always needs the owner's OK; sign-in is the owner's (product rule) |
| C3 | Opening a website failed (Blackboard, 15:07) | 238, 255, 330 | defect; 255's step 2 proven | No tool could open a web address: `desktop_open(url=…)` now opens one the owner said in this request (`a7343e3`, check 255). Check 255 (2026-11-14 12:35): "open usiu dot ac dot ke" opened; 28 s later "Open my university's website." was refused twice, and the owner's yes to the address the agent offered didn't count. The owner decided (2026-11-14, below): an address the owner said or typed earlier in the same conversation, in the last 10 minutes, may be opened. **Fixed** (`27bcdbe`; second review done, merged 2026-11-14), check 330 |
| C4 | Find and use a tool it lacks (diagrams): explain why, ask before installing, ask for sign-in | 238 | capability | Installing needs the owner's OK every time |
| C5 | Reminders, schedules and repeating automations ("every Monday at nine") | 237, 239 | capability | One-off reminders only; recipes from runs (product step 6) and a repeating reminder (§4 leftover) |
| C6 | "Play some music": find out how the owner plays music (an app, YouTube, a folder, a service) and check it started | 235 | capability (after A8) | — |
| C7 | "Remember that my manager is Ada" | 237, 290–293 | capability | **Built** (`423dd92`, `fee9a38`; merged 2026-11-14): "remember", "forget" and "what do you know about me", plain files under `%LOCALAPPDATA%\Swift\memory`; card and ID numbers refused. Checks 290–293 wait |
| C8 | GitHub: create a repository and pull it down | 238 | worked | It asked for approvals with raw commands: B1, B2 |

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
