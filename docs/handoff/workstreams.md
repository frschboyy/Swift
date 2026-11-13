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
| A2 | A question showed "Working on it", with no question to answer (lunch, 13:51:57; also 206, 211) | 206, 211, 218 | defect, unproven | The backend asked it on screen and sent the `ask` frame; the overlay logs nothing, so whether it was refused or mis-drawn is unproven. Next: replay in the harness |
| A3 | The spinner beside "Working" doesn't turn | 206 | defect, unproven | Not looked at |
| A4 | Cards behind the main one vanish before they've been seen (research behind an email) | 208, 219 | defect, unproven | The owner's rule: a card never seen doesn't run out; one waiting for them pauses while out of sight |
| A5 | A card's lifetime should fit the request (a command, a research, a question) | 210 | design | Works; the owner wants lifetimes from the request's kind and whether it needs them |
| A6 | Opening a card from the stack seemed to restart it, and some stayed "Working on it" | (new check) | defect, unproven | Whether it resumes or restarts, and whether the run is still alive, isn't known |
| A7 | One ask became two requests ("How are you? Can you turn off the Wi-Fi?" and "Turn off the Wi-Fi") | 204, 205, 197 | defect, partly proven | 197's duplicate is proven (`_same_request` compares exact words); 204/205 not looked at. 204's report FAIL: an agent approval card for a radio (14:44:20) |
| A8 | Said "Playing." and nothing played | 235, 262 | defect, proven | **Fixed** on `claude/workstreams` (`41a1773`): Swift listens for sound for 2 s after the key and otherwise says nothing started. Check 262 |
| A9 | Gmail: nothing written unless the cursor is already in the body | 242 (seen during), 49, 215 | defect, unproven | The focus check in `desktop/windows.py`; `fill_in_email` fails as `connector_failed` with no reason logged |
| A10 | Swift stayed behind an always-on-top Task Manager | 203 | defect, unproven | Not looked at |
| A11 | A command Swift understood wasn't done ("I didn't turn off Wi-Fi") | 239 | defect | The wafer cases are A1; any other "I didn't…" still lands here |

**The architecture underneath** (handoff §2, "Root causes still open"): the overlay can refuse a frame and the backend
isn't told; frames go out through two doors; each countdown runs on both sides. Review item 9 (one versioned screen
snapshot, acknowledged when drawn) is the structural fix for A2–A6. Run records (groundwork) are the fix for A6:
a card from the stack would point at a run that still exists, or say it ended.

## B. Adaptive UI and UX

How results and requests look. Mostly design for the owner, built on Halo (ADR-019): extend it, don't start again.

| # | What the owner wants | Checks | Kind | What's known |
|---|---|---|---|---|
| B1 | An approval card leads with a plain sentence: what it will do, why, what comes of it; the command folded underneath | 238, 199 | design, then code | Today the command is the card. A small change to the card; the sentence must come from Swift, not only the agent (a worker's text on a card is marked as such, X-17) |
| B2 | Fewer approvals: one task's commands grouped, with one grant for a coherent step | 238 | design + architecture | Needs the `WorkerTask` grant (groundwork) and a rule for what one approval may cover |
| B3 | Distinct looks for working, waiting for an answer, waiting for an OK, doing, failed or timed out | 206, 211, 218 | design + defect | Shares its defect with A2; Halo has the colours (218 passed), the states must be truthful first |
| B4 | Results laid out to fit: tables, comparisons, project cards, real diagrams, document previews | 238 | design + capability | Halo Step B (one card renderer) is the base; the interaction layer's decisions decide the rest |
| B5 | Overlays that grow when the content needs it, and can be expanded by hand, without covering the work | — | design | The owner leans to both |
| B6 | The watch (live view) and working surfaces distinct; the watch keeps a technical feel | 93, 95 | design | — |
| B7 | Motion that's seen: the card growing from the orb (unsure), transitions that feel alive | 221, 178 | design | 221 was too quick to see |
| B8 | A pen.dev prompt that extends Halo | — | owner | The owner is drafting it; `docs/design/halo-system/` is the base |

## C. Agent autonomy

Swift as an agent that works out how to reach a goal, inside the product rules, rather than a set of commands.

| # | What the owner wants | Checks | Kind | What's known |
|---|---|---|---|---|
| C1 | Never invent a fact it doesn't have: the distance to CBD was guessed at 4 km (really 10–11) with no location | 259–261 | defect, fixed on `claude/c1-grounded-facts-556f60` | Proven: the weather tool's fixed wttr.in request places the PC by its internet address ("Nairobi Industrial Area", 3–4 km from CBD); the agent took that for the owner's location and gave a distance from memory, 2 of 2 times when replayed. Fixed: the agent is told Swift doesn't know where the user is and must ask for a starting point, and the weather's area now reaches it labelled as the forecast's only. Replayed with the fix: it asks where you're starting from (3 of 3), and the weather still answers without asking |
| C2 | Book an Uber, a flight to Abidjan: find the way, ask for sign-in and details, do it with the owner watching, confirm before paying | 238 | capability | Refused today. Paying always needs the owner's OK; sign-in is the owner's (product rule) |
| C3 | Opening a website failed (Blackboard, 15:07) | 238 | defect, unproven | Not looked at |
| C4 | Find and use a tool it lacks (diagrams): explain why, ask before installing, ask for sign-in | 238 | capability | Installing needs the owner's OK every time |
| C5 | Reminders, schedules and repeating automations ("every Monday at nine") | 237, 239 | capability | One-off reminders only; recipes from runs (product step 6) and a repeating reminder (§4 leftover) |
| C6 | "Play some music": find out how the owner plays music (an app, YouTube, a folder, a service) and check it started | 235 | capability (after A8) | — |
| C7 | "Remember that my manager is Ada" | 237 | capability | The settings and memory store (groundwork) |
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
