# QA 1 with pstack: regressions from the 2026-11-13 and 2026-11-14 merges (`cc19d71..main`)

Branch `claude/qa1-pstack-161dc6`, from `claude/qa-review-fix-1707cc` (QA-01, QA-02, QA-03). 2026-11-15.

## How pstack was used

pstack's skills are marked so that only the owner can invoke them (`disable-model-invocation`), so the Skill tool
refuses them here. They were **applied by hand**: each `SKILL.md` was read from
`~/.claude/plugins/marketplaces/cursor-plugins/` (and the installed pstack 0.15.36) and followed step by step, with
`CLAUDE.md` winning where they differ.

- **thermos**: not part of pstack. It is the separate `thermos` plugin in the same marketplace, which isn't installed.
  Both of its reviews ran in parallel as general-purpose subagents briefed with the rubric files:
  - the code-quality review finished;
  - the correctness review hit the usage limit before reporting. Its focus list was covered by hand: the owner-check
    files, `debug.ask`, `read_scope`, countdowns, `points_back` and `split_answer`.
- **interrogate**: three adversaries per fix, each in its own worktree. There is no `pstack-models` rule, so the
  arena defaults were used, mapped by the Claude Code adapter:
  - Opus at xhigh effort;
  - the session model (Opus), in place of the Grok seat;
  - Sonnet, a third model as the orchestrator asked.

  After 00:30 the Opus seats hit the 5-hour limit. QA-04's second round ran on Sonnet and Haiku, and its Opus seat
  is still to run.
- **blast-radius**: run by hand for each fix. The one fact each fix is safe because of is proven by a script that
  calls the real code. The scripts are in the session scratchpad, `br/`.
- **deslop**: not in pstack 0.15.36 (it has `unslop`), and not used: no cleanup in this pass.

## Findings

| id | what | status |
| --- | --- | --- |
| QA-01 | A long answer's 300+ character first sentence was said twice on its card | fixed (13405a5). interrogate found QA-05 in it |
| QA-02 | A recent address opened for "show this week's…" | **partial**: interrogate proved 22 more wrong phrasings → QA-04 |
| QA-03 | Gmail with two composes mixes fields | open. The mechanism is proven with a fake UIA tree; the real tree order needs the PC |
| QA-04 | After QA-02, still opened for "…again", "find my university's website and open it"; refused "open it in Edge" | fixed (965e9c0, plus round 2). Web-address rule; second review pending |
| QA-05 | QA-01's cut could fall inside `**bold**`, code or a link | fixed (277afd6) |
| QA-06 | A+B: a compound request restated in another order does nothing ("turn off bluetooth and turn off wifi" to "Turn off Wi-Fi?") | proven end to end. Fix waits for the orchestrator (`restated.py`) |

Checked, and **not regressions from this range** (kept for QA 2):

- **The reader pane renders text details as one plain paragraph.** It doesn't use `renderBlocks`, so `**` and
  `- item` show raw: `pane.ts` `details()`. It was the same before `cc19d71`.
- **`ToolHost.last_write` is one slot.** After request B writes, request A's "show me" or "undo" acts on B's app.
  It is older than `bcddb3f`, which only moved it behind `written_by`.
- **`recordings.py:81` judges "same request" by word-set overlap.** "turn on the wifi" then "turn off the wifi"
  counts as the same request there. Older than this range.

Cleared:

- **The owner-check files.** No duplicate YAML keys in the ledger or the register, no check anchor used twice, and no
  report line lost since `cc19d71`.
- **The working card's time bar.** `drawCard` always runs `showDeadline`, but an active card always has
  `fadeAt = null` (`presenter.ts:188`, invariant at `:319`).
- **Countdowns.** The question, ask and confirm countdowns are anchored to the backend; only fades are timed in the
  overlay.
- **The session.py split steps** (`073ad8a`, `0df4602`, `33c5b68`, `64b9a16`) and **the `debug.ask` guard**: no
  behaviour change.

## interrogate and blast-radius, per fix

### QA-01 (13405a5)

**interrogate.** The Sonnet adversary proved the cut splits a markup span: QA-05, rerun and fixed. The two Opus
seats stopped at the usage limit without findings.

**blast-radius.**
- The one fact: the old and new `split_answer` differ only where one first sentence is longer than the summary. On
  19,999 random answers the outputs were identical (`qa01_diff.py`).
- On 5,000 long first sentences, every word appears exactly once and no summary goes over 300 characters
  (`qa01_long.py`).

### QA-02 (d28e4bd)

**interrogate.** Three adversaries found 22 wrong phrasings through Session and `desktop_open`. I reran them:
- 7+ opened when not pointed at. They opened on `main` too.
- 5 were refused that opened before.
- Answers like "yes, again" unlocked the address.

All of them became QA-04 and its tests.

**blast-radius.** One caller, `desktop_tools._open_url`. The new rule only narrows the old one: on 16,335 phrasings,
1,152 no longer point and none newly do (`qa02_subset.py`).

### QA-04 (965e9c0 and round 2)

**interrogate, round 2** (Sonnet and Haiku; Opus pending):
- No wrong openings beyond "That one." and "Open the last one."
- Refused: "go ahead and open that site again", "the site I was on", "take me there", "bring that site up",
  "again and again".
- A backtracking `_TRAIL`: 14 s for `"open that site " + "again " * 8000 + "x"`.

All of these were fixed in round 2 and are now tests.

**blast-radius.**
- The one fact: a False only makes the agent ask for the address. A True allows only addresses the owner himself
  said in the last 10 minutes.
- Against `main` on 16,335 phrasings, 6,273 no longer point. 540 newly point, and all of them are
  "<verb> the same" or "pull up it/that" (`qa02_subset.py`).

### QA-05 (277afd6)

**blast-radius.** The one fact: QA-01's `split_answer` and this one differ only where QA-01 split a span. On 20,000
answers, 1,423 differ and none differ without a split span (`qa05_diff.py`).

## Decisions for the orchestrator

1. QA-04: the second review (web-address rule).
2. QA-06: the go-ahead to make `restated_as` compare intents as `same_request` does (sorted).
3. QA-03: the go-ahead to scope the Gmail fields to one compose dialog (it writes into apps). Check 372 asks the
   owner for the real tree order first.
