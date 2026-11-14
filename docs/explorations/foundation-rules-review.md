# Swift's foundation: a review of the product rules (2026-11-15)

Asked for by the owner after QA 3 found that a typed "Swift, yes" approves Swift's own "Turn off Wi-Fi?" in code
(check 387), while `CLAUDE.md` says "typing never approves". The question: are the rules in `CLAUDE.md` flawed,
limited, inconsistent or inflexible, measured against the owner's principle, **"Swift adapts to the user, not the
user to Swift"**?

This is a document only. No product code and no owner checks were changed. Every disagreement below is proven by a
code trace, a test already in the repository, or the short script in the appendix (run on `main` at `e18af1b`).
What's unproven says so.

## In short

- **The rules are right about what to protect, and wrong in how they're written.** Each is an absolute sentence
  ("never", "only", "always"), and each later case the sentence didn't fit became an exception, a special case in
  code, or a regex. The bare-yes rule now has four exceptions (on screen, reversible, Swift's own, A+B), and three
  places in code decide approval outside the one table that claims to be the only one.
- **Five wording disagreements are proven** (D1 to D5 below). The typed "Swift, yes" (D1) isn't a slip. It came from
  a set named `SYSTEM_YES_NEEDS_NAME` (2026-11-04), was copied into `intake.approves` as "behaviour unchanged"
  (2026-11-05), and the owner ruled the same shape for the correction offer on 2026-11-07. The health audit raised
  it on 2026-11-12 (HA-HEAR-01, a strict xfail test) and it's still open.
- **Three rules are enforced by matching words** (web addresses, writing into apps, restated requests). The address
  regex has been rewritten three times in two days and QA still finds bypasses. Each guards an action whose worst
  case is small and reversible, so **one plain question on screen is safer than a better regex**.
- **One model replaces the rules' exceptions** (the proposed foundation): five inputs (how the request
  arrived, whether the owner is there and the thing is on screen, how reversible it is, who it reaches, and where its
  content came from) decide one of four levels. The hard lines stay hard lines, stated once.
- **The working rules fail in four known ways** (check numbers clash, generated sections merged by hand, "never
  push" with two PCs, and commands in `CLAUDE.md` that hang on this PC). Each has a small fix.
- **14 decisions for the owner** are at the end, each with a recommendation and what changes in code.

## 1. Why the rules keep needing exceptions

Every product rule in `CLAUDE.md` is written as a sentence about one mechanism ("typing", "a bare yes", "contacts",
"the owner's words"), not about the risk behind it. When a real case didn't fit, two things happened:

1. **The sentence grew an exception.** "A bare yes never approves" became "...the one exception is Swift's own
   question about a reversible change the owner just asked for, where a plain spoken yes or a click does it while the
   question is open and on screen" (2026-11-04, 2026-11-05), and then A+B (2026-11-14) added "saying the request
   again" as a second kind of yes.
2. **The code grew a special case without the sentence changing.** The typed-with-name row in `intake.approves`,
   the correction offer's own check (`session._fix_refused`), `restated`'s own `source != "typed"`, the push-to-talk
   "yes" on a card. None of these is in `CLAUDE.md`.

Copies of the rules' wording live in `CLAUDE.md`, ADR-015 §10, `dialogue.py`, `docs/design/halo-system/SPEC.md`
line 148, the modes study, the README's "Answered" list and two hint strings. They disagree with each other (D1, D3).

The real rule underneath is visible in the code: **a deliberate act aimed at the thing approves it; anything that
might not be aimed at it doesn't.** A click is aimed at a card. Holding the hotkey while a card is up is aimed at
it. "Swift, ..." on the open microphone is aimed at Swift. A plain "yes" on the open microphone might be to someone
in the room, so it counts only for a small, reversible thing Swift just asked about, on screen. The proposed model
says that once (§4).

## 2. The rules, one by one

Verdicts: **keep**, **reword** (the behaviour is right, the sentence isn't), **change** (the behaviour should
change), **merge** (folded into another rule or the model).

| # | Rule (`CLAUDE.md`) | Came from | Risk it guards | Where code enforces it | Code vs wording | Friction it caused | Verdict |
|---|---|---|---|---|---|---|---|
| R1 | Recipients only from contacts or `find_contact` | ADR-010 §4 (gateway), X-01 (2026-11-05), X-02 | Mail to an address a page or the agent made up (prompt injection), or to a misheard person | `workflows/tools.py:156` `find_contact`; `draft_email` refuses an address not resolved (`tools.py:384`); gateway `email.send` always confirm (ADR-010 policy) | Agrees | An address the owner reads out or types can't be used at all; they must add a contact first. X-01's guess limits (README §2) | **Change**: an address in the owner's own words may be a recipient, marked "not in your contacts" on the send card. Never from a worker's text (decision 5) |
| R2 | Approving hands-free needs Swift's name, and a bare "yes" never approves; the one exception is Swift's own question about a reversible change the owner just asked for, while it's open and on screen | ADR-014 T2; owner 2026-11-04 (check 124, `cd3f97b`); owner 2026-11-05 (on screen); A+B 2026-11-14 | A "yes" said to someone else approving something | `intake.approves`, `session.py:2464` (cards), `:3528` (questions), `_on_screen` (`:3387`), `restated.py:49`, `_fix_refused` (`:3916`) | **Disagrees** (D2, D3): a bare "yes" with the hotkey held approves any card; three deciders outside the "one table" | Four exceptions in two weeks; the A+B case took a decision, a branch and a review | **Merge** into the model's channel rule (§4) |
| R3 | Typing never approves | ADR-015 §10 (2026-10-27) | Text in the box approving: a stale draft resent, keystrokes meant for another app, an approval not aimed at a card | `session.py:1549` (cards); `intake.approves` typed row; `restated.py:49` | **Disagrees** (D1): typed "Swift, yes" approves Swift's reversible question; the correction offer takes it by the owner's ruling (2026-11-07) | Check 387; HA-HEAR-01 open since 2026-11-12; the hint "Typing can't turn it off" is false when the name is typed | **Change**: typed words never approve, with no name exception, and a keyboard way to press the card's own button (decisions 1, 2) |
| R4 | No hands-free listening while locked | ADR-014 (T7) | Someone at a locked PC commanding it; Swift recording a room nobody is at | Presence step (`intake.STEPS`), `session.py:909-916`, peek checks `_deaf()` (HA-HEAR-02, fixed) | Agrees (HA-HEAR-02's gap fixed, needs its second review) | None seen | **Keep**, reword to cover away/paused too, as the code does |
| R5 | Logs content-free (transcripts redacted), except the owner's local interaction log | §3/§11 of the architecture; X-03/04/05/19 | The owner's words, contacts, addresses and file contents in a log that gets shared or uploaded | `logging_setup.py` (redact on every record), `runlog.py:45` `SUMMARY_FIELDS` allow-list, `memory.py` logs kinds only | Agrees | Causes unprovable from logs: "connector_failed; the log doesn't say why" (README §2, check 215); "answers aren't saved" (README §2, A7's 14:14 answers); A9's 12:24 has no UIA state | **Reword**: content stays out of `swift.log`, but structure (reason codes, error classes, field roles, timings) must be in it, and the local interaction log keeps the owner's answers (decision 8) |
| R6 | Status labels generic (never "Claude Code is...") | ADR-008 (identity and providers) | Swift appears to be a front for a named product; trust and confusion | `executors/mock.py`, `claude_mapping.py`, B-10 open | Agrees, with setup errors naming the program (`claude_code.py:488`, "Claude Code isn't installed") | B-10 (handoff step names providers) open | **Reword**: Swift speaks as itself; a provider is named only in setup errors and the settings that choose it |
| R7 | Audio never leaves the PC | ADR-006; X-07 | Recordings of the owner's room uploaded | Local STT only (no cloud STT in `src/swift`); `read_scope.py:39` never-reads `AppData/Local/Swift` so a worker can't read clips | Agrees | None | **Keep**, reword so it doesn't suggest transcripts stay local: a request's words do go to the model that answers it |
| R8 | Swift writes into apps only when the owner's own words asked | ADR-012 (desktop interaction) | An injected instruction typing into the owner's apps (a terminal runs code) | `desktop_tools.py:71-90` (`_WRITE_WORDS`, `_EMAIL_WORDS` regexes), `system_tools.owner_intents` | **Partly** (D4): the regex both lets through requests that ask for no writing and refuses ones that do | Refusals the owner can't predict; OCT-01 (VS Code's terminal not recognised as a terminal) | **Change**: when the words don't clearly ask, ask on screen with a preview instead of refusing; typing into a terminal is "runs code", always its own card (decision 6) |
| R9 | Memory is written only from the owner's words or an approved card, never from what a worker read | Memory store decision 2026-11-14; modes study decision 2 | A page or a worker planting a "fact" or a trust | `memory.py:105-110` (`said` must contain the text, `approved` needs a card, `inferred` refused) | Agrees. Typed "remember X" writes memory (`OWNER_WORDS` includes typed); typed "always do X" can't make a trust (decision 2 of the modes study) | B4's growing map and learned trust both fit; the "review job" (§5.6) is the only inference path, via a card | **Keep**, as one case of the model's origin line |
| R10 | Deleting a file always asks on a card, whatever a setting or a run's permission says | ADR-019 §7 item 2 (2026-11-14) | The hardest mistake to undo | `step_grant.REVERSIBLE` has no delete; gateway "destructive" class (ADR-016 §3.1: empty Recycle Bin always the card) | Agrees (no file tools yet) | The Recycle Bin question is open; Windows deletes some files permanently even when asked to recycle (too large for the bin, network and some removable drives), so "a move to the Recycle Bin" isn't always one | **Keep**, and decide now: a Recycle Bin move asks but can be listed on a plan card; a permanent delete, or a recycle Swift can't confirm happened, has its own card (decision 7) |
| R11 | (Implied, not in `CLAUDE.md`) A recent web address is reused only when the request points at it | Owner 2026-11-14 (C3, checks 255, 330) | The agent opening an address from a page; the wrong one of the owner's addresses | `owner_address.py:22-30` `_POINTS_BACK` (main); rewritten as `_CLAUSES`/`_LEAD`/`_TRAIL`/`_POINTING_CLAUSE` on `claude/qa1-pstack-*` | **Disagrees** with its own intent (D5): "show this week's timetable" points back on `main` | Three rewrites in two days, QA-02 and QA-04 (22 bypasses by the orchestrator's count, 2026-11-15) | **Change**: ask "Open usiu.ac.ke?" with the owner's own address, plain yes (decision 4) |
| R12 | (Implied) Saying the request again to Swift's own question is a yes, if spoken and the same intent and slots (A+B) | Owner 2026-11-14 (A7, check 204/304) | A misheard request taken as a new one; a lookalike approving | `restated.py` | Consistent with R3 but **not** with `intake.approves` (D1b: typed "Swift, yes" approves, typed "Swift, turn off the Wi-Fi" doesn't) | It took a branch and a review | **Merge** into the model: restating is a yes at level 1, through the same channel table |
| R13 | (Implied) A click on an option the agent wrote never counts as the owner's words | A1 (2026-11-13) | A worker's wording becoming the owner's answer (and from there memory or a recipient) | `session.py` `_take_answer` keeps the owner's own words, not the option's | Agrees | None | **Merge** into the origin line |

Working rules that shape the product are in §6.

## 3. Proven disagreements

Each was run on `main` at `e18af1b`; the script is in the appendix.

**D1. A typed "Swift, yes" approves Swift's own reversible question.** `intake.approves("typed", named=True,
target="reversible")` is `Verdict(allowed=True)`. The path: `_start_typed` → `_midrun_text(source="typed")` →
`_take_answer` → `session.py:3528`, which re-asks only when `approves` says no. The repository already proves it end
to end: `tests/unit/test_health_HEAR.py::test_a_typed_swift_yes_doesnt_turn_the_wifi_off` is a **strict xfail**
(it fails because the Wi-Fi goes off). Where it came from, by `git log -S`:
- 2026-10-28 (`e75ee56`): `SYSTEM_YES_NEEDS_NAME = {"followup", "typed", "answer"}`: sources that need the name, so a
  typed yes *with* the name passed.
- 2026-11-04 (`cd3f97b`): the owner ruled "typing doesn't"; the set shrank to `{"typed"}` but still meant "typed
  needs the name", not "typed never".
- 2026-11-05 (`d44cac0`): the one table copied it, "behaviour unchanged", with the row `typed | never | only with name`.
- 2026-11-07 (`77794dd`): the owner ruled the same shape for the correction offer ("typed only with Swift's name"),
  in its own check (`_fix_refused`), and the hint `FIX_TYPED_HINT` tells the owner to type "Swift, yes".

So it's two owner rulings that disagree (11-04 "typing doesn't", 11-07 "typed with the name"), not a bug against one.
The hint the owner sees for a typed "yes" (`SYSTEM_YES_NAME_HINT`, `session.py:290`) says "Typing can't turn it off",
which is false once the name is typed, and wrong for "Turn on ...?" questions.

**D1b. Within code, the typed rule is two rules.** `restated("Swift, turn off the wifi", q, "typed", named=True)`
returns `"again"` (no yes) because `restated.py:49` adds its own `source != "typed"`; a typed "Swift, yes" to the
same question is a yes. Same owner, same question, same keyboard.

**D2. A bare "yes" approves any card when the hotkey is held.** `intake.approves("voice", named=False,
target="card")` is allowed; `_answer_by_voice` (`session.py:4670`) sends a push-to-talk "yes" on an open confirm card
straight to `_answer_text`. That includes sending an email. `CLAUDE.md` says "a bare 'yes' never approves". The
behaviour is sound (holding the key while a card is up is as deliberate as a click), the wording is not.

**D3. "One table" isn't one.** `intake.py`'s docstring says the rules "live here once; every door calls them". The
correction offer decides in `session._fix_refused` (`:3916`) without calling `approves`; `restated.py` overrides it;
the hands-free fix offer takes "Swift, yes" at `session.py:2472` by its own condition. Three deciders, so three
places for D1-like drift.

**D4. "Writes into apps only when the owner's words asked" is a regex, and it's wrong both ways.**
`owner_asked_to_write("what's here on my screen?")` and `("correct me if I'm wrong, is it raining?")` are `True`
(`\bhere\b`, `correct`); `("reply to Ada saying thanks")` and `("answer Ada: see you at 3")` are `False`, and neither
counts as email for `owner_asked_for_email`. A false `True` only matters if a worker then tries to write (the
injection case the rule exists for); a false `False` is a refusal the owner can't predict.

**D5. A recent address is reused for requests that don't point at it.** On `main`, `points_back` is `True` for
"show this week's timetable", "find my university's website and open it", "open that one drive folder" and "what was
that site again". `claude/qa1-pstack-*` fixes these with a fourth design (every clause must be pointing words, after
stripping fillers, browsers and "again"). It's a better regex; it's still a regex over open English, and each fix so
far has needed the next.

**Not proven (said plainly):** whether the owner ever *wanted* typed approvals generally. The 11-07 ruling suggests
they accept "Swift, yes" typed for an offer; the 11-04 ruling says typing doesn't do the Wi-Fi. Decision 1 asks.

## 4. A simpler foundation: one model

### The inputs

Five things Swift already knows for every action decide what it needs:

1. **Channel**, how the approval or request arrived:
   - **gesture**: a click on Swift's own button, the same button pressed from the keyboard, or speech with the hotkey held;
   - **named voice**: the open microphone with Swift's name ("Swift, yes");
   - **plain voice**: the open microphone without the name;
   - **typed words**: text in the box, with or without the name (the name adds nothing here: it proves speech is
     addressed to Swift, and typing into Swift's box already is).
2. **Presence**: the owner is here (unlocked, not away, listening not paused), the thing is **on screen and in
   front**, and it wasn't heard over Swift's own voice. A click needs no on-screen check: it was on the thing.
3. **Reversibility**, decided by Swift, never the agent (B2's rule): read; reversible (has an undo); disruptive (the
   owner loses something until they put it back: Wi-Fi off); irreversible (deleting permanently, sending, paying,
   publishing, pushing, running code).
4. **Reach**: only the owner's PC; someone else (send, invite, publish, share); money; the owner's accounts
   (sign-in, credentials).
5. **Origin** of what the action uses (a recipient, an address, a path, a fact): the owner's words (said or typed),
   an approved card, or a worker's reading (the agent's text, a page, a tool's output, an option the agent wrote).

### The levels

| Level | When (reversibility × reach) | What Swift does | Which channels approve |
|---|---|---|---|
| **0. Do it** | read, or reversible and only the owner's PC, and the owner's words asked for it | acts; "undo that" works | none needed |
| **1. Ask once** | disruptive and only the owner's PC; or a level-0 action whose words don't clearly ask (an address the owner gave earlier, writing into an app); or Swift's own question about the owner's request | one short question on screen, Yes/No | gesture, named voice, **plain voice if on screen**; restating the request (A+B) by voice counts as yes |
| **2. Card** | anything a worker chose to do on the owner's PC (commands, file edits, reads outside the read folders); a Recycle Bin move | a card that says what and why; a step or plan card may cover several (B2) | gesture, named voice |
| **3. Its own card** | irreversible, or reaches someone else, or the owner's accounts | its own card, never covered by a step card, a plan, a learned trust or a setting | gesture, named voice; **money: gesture only** (decision 9) |

Four rules sit across every level:

- **Typed words never approve**, at any level. A keyboard user presses the card's own button (Tab, Enter): that's a
  gesture aimed at the card, not words routed by a guess (decision 2).
- **Nothing approves unless the owner is present and the thing is on screen**, except a click, which was on it.
- **Origin is a hard line.** What a worker read never chooses a recipient, an address, a path to delete, a memory or
  a trust by itself. It can be *shown* to the owner on a card, marked as the worker's; only the owner's approval of
  that card makes it usable.
- **Learned trust and "ask me about everything" move one level.** A trust lowers a kind from 1 to 0 (only kinds on
  the table, never level 3, the modes study's decisions). "Ask me about everything" raises every 0 to 1 except
  reads in the read folders and volume.

### Every current rule on the model

| Current rule or case | On the model | Special case that goes |
|---|---|---|
| Hands-free approval needs the name | Levels 2 and 3 accept named voice, not plain voice | — |
| A bare "yes" never approves, except Swift's own reversible question on screen | Plain voice approves level 1 only, on screen | the exception sentence; `target="reversible"` stays as "level 1" |
| Push-to-talk "yes" on a card (D2) | Gesture | becomes stated instead of contradicting the rule |
| Typing never approves; typed "Swift, yes" to the Wi-Fi question; typed "Swift, yes" to the correction offer | Typed words never approve | the typed/name row in `intake.approves`; `_fix_refused`'s typed branch; `restated`'s `source != "typed"`; `SYSTEM_YES_NAME_HINT`'s two wordings |
| A+B: restating the request | Level 1, by voice | `restated.restated`'s own typed check (it calls the table) |
| A click on an agent-written option isn't the owner's words | Origin | — |
| Recipients only from contacts | Origin: the owner's words or contacts; never a worker's reading; send is level 3 | the "add a contact first" dead end |
| Recent address only when the request points at it | Owner-origin address not in this request's words → level 1 "Open usiu.ac.ke?" | `_POINTS_BACK` and its successors (`_CLAUSES`, `_LEAD`, `_TRAIL`, `_POINTING_CLAUSE`) |
| A description ("my university's website") only through a memory | Origin: memory written from the owner's words is owner-origin → level 0; otherwise level 1 listing the owner's recent addresses, or "say the address" | `remembered`'s subject matching can stay as a ranking, no longer a gate |
| Writes into apps only when the owner's words asked | Clearly asked → level 0; not clearly → level 1 with a preview; into a terminal → level 3 (runs code) | `_WRITE_WORDS` as a gate (it can stay as a hint for which level) |
| Deleting a file always asks | Recycle Bin move → level 2; permanent, or recycle not confirmed → level 3 | the open "is the Recycle Bin reversible" question |
| B2: one grant per step, deletes/sends/unknown ask | Level 2 grouped; level 3 never grouped | — |
| Memory only from the owner's words or a card | Origin | — |
| Learned trust, plan card, "ask me about everything" | Move one level, within the limits above | — |
| No hands-free listening while locked | Presence | — |
| Logs, status labels, audio | Not approval rules; kept as they are, reworded (R5 to R7) | — |

### Where the model is stricter, looser, and why

**Stricter than today:**
- A typed "Swift, yes" no longer answers Swift's own question or takes the correction offer (reverses the 2026-11-07
  ruling for the offer). Why: the name proves nothing for typing, and one rule beats two rulings. The keyboard keeps
  a way: the card's button.
- Money (not built yet) approves by gesture only, not "Swift, approve". Why: a misheard named phrase from a video or a
  call should never pay.
- Typing into a terminal or console is level 3 (today it's "writing into an app" if the owner's words matched). Why:
  in a terminal, text runs code.
- A delete Windows would make permanent (too large for the bin, a network drive) gets its own card even if a plan
  covered "move to the Recycle Bin".

**Looser than today:**
- A recipient the owner reads out or types can be used, marked on the send card. Why: the owner adapting to Swift
  ("add a contact first") is exactly what the principle forbids, and the send card is already level 3.
- An address the owner gave earlier, or a description, gets one question instead of a refusal or a regex guess.
- Writing into an app when the words didn't match gets a question with a preview, not a refusal.
- The keyboard can approve by pressing the card's button.
- `swift.log` carries reason codes and structure, and the local interaction log keeps the owner's answers.

**Unchanged:** paying, sending to others, deleting permanently and anything a worker read never act on their own;
no listening while locked; audio stays on the PC; Swift speaks as itself.

## 5. The other tensions the task named

- **Word matching vs a card.** The pattern to keep: a regex may *choose the level* (clearly asked → do it), never be
  the *only gate* between the owner and a refusal or an unsafe action. Where the worst case is small and reversible
  (opening the owner's own address, writing a draft the owner can undo), the safe default when the regex is unsure is
  a question, not a refusal. Where the worst case is large (a terminal, a send), the level is set by the action, not
  the words, so a regex miss can't lower it.
- **Logs vs proving causes.** The rule isn't what blocked proof. What blocked it was that structure (why a
  connector failed, what UIA element was found, the owner's answer) was dropped along with content. Content = the
  owner's words, names, addresses, file contents. Structure = reason codes, exception classes, element roles and
  Swift's own field names, counts, timings. Structure belongs in `swift.log`; the owner's answers belong in the
  local interaction log, which the rule already allows.
- **Memory vs learned trust and B4's map.** No tension once origin is the rule: trust comes from the offer card
  (approved), the map from the owner's words; anything inferred waits for a card. Keep the asymmetry that a typed
  "remember X" writes memory but a typed "always do X" doesn't make a trust: memory is the owner's words, a trust is
  a standing approval, and typed words never approve.
- **No listening while locked; status labels; audio.** Sound; reword only (R4, R6, R7).
- **Credentials vault** (C2, C4; workstreams "needs a decision"): on the model, anything touching the owner's
  accounts is level 3 and the sign-in itself stays the owner's. The model doesn't decide the vault; it says where it
  would sit.

## 6. The working rules

| Rule | What happens in practice | Proposal |
|---|---|---|
| Take a new check's number from "Next free check number" | Branches can't see each other: 305 was claimed by four branches at once on 2026-11-14 and renumbered to 310, 320 and 330 (`a18e1fe`, `794ceac`, `d736d59`); `main` says next free is 354 while `claude/qa-e2e-proof-*` uses 380-389; the orchestrator now hands out ranges by hand (`check-numbers-claimed.md`) | A branch writes **provisional ids** (`a9-1`, `qa3-7`); `plan.py --renumber` gives them numbers when merging into `main` and fixes the ledger and report lines in the same commit. No ranges to hand out (decision 11) |
| `plan.py --write` sections between markers; "don't edit between its markers" | Every merge conflicts in the generated block and someone resolves it by hand | Move the generated run list and status into their own file (`owner-checks-status.md`), mark it `merge=ours` in `.gitattributes`, and regenerate with `--write` after every merge (decision 12) |
| Never push | The owner moves between PCs; work in worktrees can only travel by merging to `main` | Keep "never push `main`". When the owner asks, Claude makes a `git bundle` of named branches into a folder the owner chooses; the owner carries it (decision 13) |
| The commands in `CLAUDE.md` (`uv run ...`) | `uv run` hangs in worktrees on this PC; sessions are told to use the main checkout's `.venv` with `PYTHONPATH=src`. Git has no identity, so each session is told the `-c user.name -c user.email` form | Put the forms that work on this PC in `CLAUDE.md`, and let the owner set a git identity once in the repo's config (their machine setting) (decision 14) |
| Product-rule fixes reviewed by someone else | Works: X-05 and X-17 reviews each caught real faults | Keep |
| Copies of rule wording | `CLAUDE.md`, ADR-015, SPEC.md, `dialogue.py`, the README and hints disagree (D1) | `CLAUDE.md` holds the model's table once; a unit test reads that table and checks it against `intake.approves` for every channel × level, so wording and code can't drift apart (decision 10) |

## 7. Decisions for the owner

Each has a recommendation and what changes in code if agreed. 1–3 settle check 387 and HA-HEAR-01.

1. **Does a typed "Swift, yes" approve anything?** Recommended: **no, anywhere**: not Swift's own question, not the
   correction offer. Code: `intake.approves` returns `typed` for every target; `_fix_refused` calls `approves` (its
   typed branch and `FIX_TYPED_HINT` go); `restated.py:49` drops its own `source != "typed"`; one hint, "Typing can't
   approve: click Yes, press Enter on Yes, or say yes"; HA-HEAR-01's xfail becomes a passing test; check 387's step 2
   gets an expected result. Alternative: typed words approve level 1 (with or without the name, since the name adds
   nothing), which loosens R3 and needs `CLAUDE.md` reworded.
2. **A keyboard way to approve.** Recommended: **yes**: while the text box is open on a card or Swift's question, Tab
   reaches the card's own Yes/Approve and Enter presses it, counted as a click. Code: overlay focus order on
   `ask.ts`/the confirm card in the typing pane; `confirm.reply` source `click`. Owner check for it.
3. **State the push-to-talk rule.** Recommended: **yes**: "a yes with the hotkey held is a gesture, like a click"
   (D2). Code: none; `CLAUDE.md` wording.
4. **Recent and described web addresses by asking.** Recommended: when the owner's address isn't in this request's
   words, Swift asks "Open usiu.ac.ke?" with the owner's own address (from Swift's record of their words, last 10
   minutes, or a memory), and a plain yes on screen opens it; several → it lists them; none → "say the address".
   Code: `owner_address.points_back` stops being a gate (deleted, or kept only to skip the question for "open it
   again"); `desktop_open` asks through Swift's question path. The `claude/qa1-pstack-*` regex rewrite isn't needed
   for safety (QA-02/QA-04 close as superseded). Owner check rewritten (330).
5. **A recipient from the owner's own words.** Recommended: **yes**: an email address the owner said or typed in this
   request can be a recipient; the send card marks it "not in your contacts" and offers to save it. Never from a
   worker's text, a page or a reply. Code: `draft_email` accepts an address found in `scope.said`/answers
   (normalised, "dot", "at"); `find_contact` unchanged; the card's marked row. Owner check.
6. **Writing into apps when the words aren't clear.** Recommended: ask with a preview instead of refusing; typing
   into a terminal or console is always its own card. Code: `desktop_write`/`fill_in_email` return a question instead
   of `NOT_ASKED`; a terminal target (including VS Code's, OCT-01) maps to level 3. Owner check.
7. **The Recycle Bin.** Recommended: a move to the Recycle Bin asks on a card but may be listed on a plan or step
   card; a permanent delete, emptying the bin, or a recycle Swift can't confirm landed in the bin, has its own card;
   no learned trust for any delete. Code: the W2 file tools (not built) follow this; `step_grant` unchanged.
8. **Logs: content out, structure in.** Recommended: `swift.log` gains reason codes and error classes for connector
   and desktop failures (never text); the local interaction log keeps the owner's answers to questions. Code:
   `runlog.SUMMARY_FIELDS` additions, `connector_failed` gains a `reason` code, the interaction record keeps
   `answers`. Second reviewer (product rule).
9. **Money by gesture only.** Recommended: **yes**, when paying is built: only a click or push-to-talk approves a
   payment, never the open microphone, even with the name. Code: none today; a level-3 "money" flag in the gateway
   when C2 is built.
10. **One table, tested.** Recommended: `CLAUDE.md` holds the model's table; `intake.approves` takes `(channel,
    level)`; a test checks the two agree, and every door calls `approves` (the three outside deciders in D3 go).
    Code: `intake.approves` signature; `session.py` call sites; a new test reading `CLAUDE.md`. Net deletion expected.
11. **Provisional check ids.** Recommended: branches use `<branch>-<n>` ids; `plan.py --renumber` numbers them at
    merge. Code: `plan.py`, `report.py`, `test_owner_plan.py` accept provisional ids; `CLAUDE.md`'s check rule.
12. **Generated status in its own file.** Recommended: yes, `merge=ours` and regenerate after merging. Code: `plan.py`
    output path, `.gitattributes`, the markers removed from `owner-checks.md`.
13. **Moving work between PCs.** Recommended: a `git bundle` on request; still never push. Code: none; `CLAUDE.md`.
14. **Commands that work on this PC, and a git identity.** Recommended: `CLAUDE.md` lists the `.venv` +
    `PYTHONPATH=src` forms as the worktree way, and the owner sets `user.name`/`user.email` once in the repository's
    config. Code: none; `CLAUDE.md`.

The proposed rewrite of `CLAUDE.md`'s rules is in [`claude-md-proposed.md`](claude-md-proposed.md). It assumes the
recommendations above; each line that depends on a decision names it.

## Appendix: the proof script

Run from the worktree with `PYTHONPATH=src /c/Users/frchi/Documents/Swift/.venv/Scripts/python.exe proof.py`.

```python
from types import SimpleNamespace as NS
from swift import intake
from swift.workflows.desktop_tools import owner_asked_to_write, owner_asked_for_email
from swift.workflows.owner_address import points_back
from swift.restated import restated
from swift.system import intents
print("P1 typed 'Swift, yes' to reversible:", intake.approves("typed", named=True, target="reversible"))
print("P2 typed 'yes' to reversible:", intake.approves("typed", named=False, target="reversible"))
print("P3 hotkey bare 'yes' on a card:", intake.approves("voice", named=False, target="card"))
payload = intents.parse("turn off the wifi")
q = NS(own=True, kind="yes_no", payload=list(payload), request="turn off the wifi")
print("P4 typed 'Swift, turn off the wifi' restated:", restated("Swift, turn off the wifi", q, "typed", True, None))
print("P4b spoken same:", restated("turn off the wifi", q, "answer", False, None))
for s in ["what's here on my screen?", "correct me if I'm wrong, is it raining?", "reply to Ada saying thanks",
          "answer Ada: see you at 3"]:
    print("P5 write?", repr(s), owner_asked_to_write(s), "email?", owner_asked_for_email(s))
for s in ["show this week's timetable", "find my university's website and open it", "open that one drive folder",
          "what was that site again"]:
    print("P6 points_back", repr(s), points_back(s))
```

Output on `e18af1b`:

```
P1 typed 'Swift, yes' to reversible: Verdict(allowed=True, reason=None)
P2 typed 'yes' to reversible: Verdict(allowed=False, reason='name')
P3 hotkey bare 'yes' on a card: Verdict(allowed=True, reason=None)
P4 typed 'Swift, turn off the wifi' restated: again
P4b spoken same: yes
P5 write? "what's here on my screen?" True email? False
P5 write? "correct me if I'm wrong, is it raining?" True email? False
P5 write? 'reply to Ada saying thanks' False email? False
P5 write? 'answer Ada: see you at 3' False email? False
P6 points_back "show this week's timetable" True
P6 points_back "find my university's website and open it" True
P6 points_back 'open that one drive folder' True
P6 points_back 'what was that site again' True
```

Plus the repository's own: `tests/unit/test_health_HEAR.py::test_a_typed_swift_yes_doesnt_turn_the_wifi_off`
(strict xfail, HA-HEAR-01).
