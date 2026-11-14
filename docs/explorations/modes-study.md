# Modes: asking less without a mode switch, a study

The owner asked on 2026-11-14 whether Swift should have modes like Claude Code's (auto, manual, accept edits, plan,
bypass permissions). The orchestrator proposed something else, and the owner asked for it as a study first, like B4
and B6. This is that study. It changes no product code and adds no owner checks; each part gets checks when it's built.

No prototype: the three cards below are small, and the decisions are about rules, not looks. If the owner wants to
see them, a dev page on the harness (port 1431) is a short job.

## In short

Not Claude Code's modes:

- **No bypass.** The product rules in `CLAUDE.md` are a floor no setting can lower. Deleting, sending, paying and
  pushing always ask; recipients come only from contacts; typing never approves.
- **No "accept edits".** Swift's actions are far more varied than file edits, so one switch for "edits" means nothing.
- **No global modes.** A mode the owner has to remember to switch makes the owner adapt to Swift.

Three smaller things instead:

1. **Learned trust, one kind of action at a time.** After the owner has approved the same reversible kind a few times,
   Swift asks once: "Always do this without asking?" A yes is kept in the memory store and can be taken back.
2. **A plan card for longer tasks.** One card shows the whole plan, says up front which steps will still ask, and one
   approval covers the rest. Built on B2's step grant.
3. **"Ask me about everything."** One switch that brings every card back, for when the owner wants to watch closely.

Recommended order: 3, then 1 (Wi-Fi and the other radio switches only), then 2.

## What asks today

From `src/swift/security/gateway.py` (`POLICY`), `src/swift/executors/claude_code.py` (`_ask`) and
`src/swift/executors/read_scope.py`:

| What | Asks today? | Why |
|---|---|---|
| Send an email, add/change/delete a calendar event, run a program | always (gateway `confirm`) | others see it, or it runs code |
| Wi-Fi or Bluetooth off, airplane mode on | yes (`system_action_disruptive`): "Turn off Wi-Fi?" | the owner loses something until they put it back |
| Volume, brightness, a timer, opening a site or file the owner named | no (`system_action`, `desktop_open`) | reversible, the owner's own words asked |
| Filling in a Gmail draft, writing into Word | no (`fill_in_email`, `desktop_write`) | reversible in the app, the owner's words asked |
| A worker's command (Bash, PowerShell) | yes, unless a B2 step card covered it | the agent chose it |
| A worker's file write or edit | yes | the agent chose it |
| A worker reading outside the read folders | yes; Swift's own folders, keys and secrets never | what's read goes to the model |

So the cards that repeat for a reversible thing the owner asked for are few: the radio switches, and reads of a folder
the owner keeps allowing. Most repeated cards come from workers' commands, which is B2's and the plan card's job, not
learned trust's.

## 1. Learned trust

### What "the same kind" is, and who decides

A **kind** is a key from a closed table in Swift, next to `POLICY`, never the agent's words:

```
TRUSTABLE = {
    "wifi_off":      system_action_disruptive, radio Wi-Fi off,
    "bluetooth_off": system_action_disruptive, radio Bluetooth off,
    "airplane_on":   system_action_disruptive, airplane mode on,
    "read:<folder>": a worker reading in one folder outside the read folders (decision 4),
}
```

The gateway's `Action` gets one field, `kind: str = ""`, set by the tool that builds it (`system_tools.py` sets it
from `it.disruptive`'s intent, the same place it chooses the tool today). An action whose kind isn't on the table is
never counted and never offered. Adding a kind is a code change with a test, the way B2's `REVERSIBLE` widens (one
shape at a time, owner's say-so).

A kind goes on the table only if all of these hold. Swift decides them when the table is written, not at run time:

- **Swift can undo it**: it has an `undo`, or the owner can put it back in one step and Swift says how.
- **Nobody else sees it**: no recipient, no invite, no post, no payment, nothing sent or published.
- **It deletes nothing** (ADR-019) and runs no code.
- **The owner's own words asked for it**: the tool already checks this (`owner_intents` in `system_tools.py`). A trust
  removes the card, never that check. A page or the agent can't make Swift switch Wi-Fi off, trusted or not.

Never on the table: send, calendar, delete, pay, push, run a program, write a file, a worker's command. So
"Always do this without asking?" can never be shown for something irreversible, because the code that shows it only
looks up keys on the table.

### When Swift offers

The gateway journal already records each approved action (`security/journal.py`, metadata only). It gets the kind as
one more field. Swift offers when, for one kind:

- the owner approved it **3 times**, in **3 different runs**, within **14 days**;
- and rejected it **0 times** in that window.

The offer comes **after** the third one is done, on its own small card, never in the way of the work:

```
 You've turned Wi-Fi off 3 times this week.
 Do it without asking from now on?
 You can say "ask me again about Wi-Fi".
                         [ Always ]   [ Keep asking ]
```

The card is an approval like any other: hands-free it needs Swift's name ("Swift, always"), a bare "yes" doesn't count
(it isn't the open-question exception: the owner didn't just ask for this change), and typing never approves it.
**Keep asking** is remembered too, so the same kind is offered at most once, ever, unless the owner asks for it
("stop asking me about Wi-Fi").

### Where it's kept

In the memory store (`src/swift/memory.py`, `423dd92`), as a setting, so it's a plain file the owner can read, with
every version kept:

```
memory/settings/trust.wifi_off.md      source: approved · card: <the offer card's id> · run · when
```

`Store.write("setting", ..., source="approved", card=...)` already requires a card for `approved`; a worker can't
reach the store (one writer, `test_one_writer_only_swifts_backend_imports_the_store`), and Swift's data folder is
never read or written by a worker (`read_scope._HOME_NEVER`). The owner can also say it in words ("always turn Wi-Fi
off without asking"): that's `source="said"`, as for any setting.

One change to how it's read: `Store.setting` lets `config.yaml` win. A trust should come **only** from the store, so a
file edit, by anyone, can't add one. Decision 3.

### Where it takes effect

One place: gateway step 3 (policy). If the policy is `confirm`, the kind is on the table, the store has its trust, and
"ask me about everything" is off, the card is skipped. Everything else runs as today: validate, resolve, journal
(with `trusted: wifi_off`), the digest check, the receipt, and the `approved` list, so "undo that" still works.

### How it's shown, listed and undone

- **When it's used:** the working card says what was done and why there was no question: "Wi-Fi is off. (You said
  not to ask.) **Undo**". Spoken: "Wi-Fi's off." Nothing else changes.
- **Listed:** "what do you do without asking?" lists each trust with its date, from the store. "What do you know about
  me" gets one line at the end: "And 2 things I do without asking."
- **Undone:** "ask me again about Wi-Fi", "stop doing that without asking" (the last trust used), or **Ask me again**
  on the list. That's `Store.forget`, which keeps the versions. Typing it works: taking a trust back only makes Swift
  ask more.

## 2. The plan card

### How it differs from B2's step card

B2's step card (`_propose_step`): the agent lists one step's commands; Swift keeps only those it classes as reversible
(`step_grant.reversible`), shows them, and on a yes makes a `Grant(step, commands)`. Each listed command is covered
once; the next step needs a new card.

The plan card is the same mechanism stretched over the task, with one thing B2 doesn't have: **it says up front where
the owner will still be asked.**

```
 Make a GitHub repository for "tea-timer" and pull it down
 1  Create the folder and start a repository      mkdir tea-timer · git init
 2  Write the README and first commit             2 file changes · git add · git commit
 3  Create the repository on GitHub              will ask you (it publishes)
 4  Push the first commit                         will ask you (it sends)
                    [ Go ahead with 1 and 2 ]   [ Change ]   [ Stop ]
```

| | B2 step card | Plan card |
|---|---|---|
| Covers | one step | every step of the task listed on it |
| Shows | the commands it covers | each step in words, its commands, and which steps will ask |
| Grant | `Grant(step, commands)` | a list of `Grant`s, used in order |
| Who decides what's covered | Swift (`reversible`) | Swift, the same way, per command |
| Off the plan | asks | asks; a changed plan is a new plan card |

What changes underneath: `WorkerTask.grant` becomes a short tuple of steps (`Grant` unchanged), and `_ask` looks in
the current step and the ones after it. The agent gets a `propose_plan` tool next to `propose_step`, shown only for
tasks with more than one step; a one-step task keeps the step card.

Two honest limits:

- **Later commands often aren't known yet** (a file name the agent picks in step 2). Those show "will ask" on the plan
  card, and get their own card or a step card when they come. The plan card never approves "whatever step 2 needs".
- **File writes and edits stay outside the grant** unless decision 5 says otherwise, because `reversible` only knows
  commands today. If they're included, it's only inside the run's working folder, never Swift's own folders, never a
  delete.

## 3. "Ask me about everything"

One setting, `asking.everything`, in the memory store, set by the owner's words ("ask me about everything", "ask me
before you do anything"). While it's on:

- the gateway treats `reversible` like `confirm` (writes into Word, filling a draft, volume, opening a site all ask);
- no grant covers anything: step and plan cards aren't offered, every command asks;
- learned trusts are kept but not used, and no new ones are offered;
- the orb's tooltip and the tray say "Asking about everything", so the owner can see why.

Turning it on or off only changes how often Swift asks, so typing works for both, and the plain-yes exception for
Swift's own question ("Turn off Wi-Fi?") still holds. Reads inside the read folders still don't ask: they aren't an
action (decision 6).

## The product rules, one by one

| Rule | The risk | How the design keeps it |
|---|---|---|
| Deleting, sending, paying, pushing always ask | a trust or a plan covers one | the trust table can't hold them; the plan uses `reversible`, which has none of them; the gateway's `confirm` for sends is untouched; a test tries each against both |
| Recipients only from contacts | a trusted action skips the resolve step | trust skips only step 4 (the card); step 2 (resolve) runs; nothing on the table has a recipient |
| Hands-free approval needs Swift's name; a bare "yes" never approves | the offer card is approved by a stray "yes" | the offer card is a normal card: "Swift, always" or a click; not the open-question exception |
| Typing never approves | a typed "always" makes a trust | the offer card ignores typing, like every card; typed "always do this" isn't a source that writes a trust (decision 2) |
| No hands-free listening while locked | none: nothing here listens | unchanged |
| Logs content-free | the kind or the plan in the logs | the log gets the kind key (`wifi_off`) and counts (`trusted`, `covered`, `asked_again`), as `step_grant` counts today; the plan's text goes to the card only |
| Status labels generic | — | the card says "You said not to ask", never names Claude Code |
| Audio never leaves the PC | — | unchanged |
| Swift writes into apps only when the owner's words asked | a trust or a plan widens what is written | trust removes a card, never the `owner_intents` check; the plan card doesn't cover `desktop_write` beyond what the owner asked; "ask me about everything" only adds cards |
| Memory only from the owner's words or an approved card | a worker or a page creates a trust | trusts are written with `source="approved"` and the offer card's id, or `said`; workers can't reach the store or its folder; `config.yaml` doesn't count for trusts (decision 3) |
| Deleting a file always asks on a card | a learned "edit files" trust, or a plan, covers a delete | no file kind on the table; `reversible` rejects every delete; ADR-019 untouched |

## Decisions for the owner

1. **Start with which kinds?** Recommended: only Wi-Fi off, Bluetooth off and airplane mode on. They're the only
   reversible things the owner asked for that ask today. More kinds only when the owner names one.
2. **Can the owner make a trust by saying it, without waiting for the offer?** ("Always turn Wi-Fi off without
   asking.") Recommended: yes, spoken only, for kinds on the table. A typed one is answered "say it, or wait for me to
   offer", because it removes a card.
3. **Should `config.yaml` be able to set a trust?** Recommended: no. Only the store, from a card or the owner's spoken
   words, so a file edit can't remove a question.
4. **Should reads outside the read folders be a trust kind?** ("You've let me read D:\Projects 3 times. Add it to the
   folders I can read?") Recommended: yes, but as adding the folder to `executor.read_dirs` through the same offer
   card, so there's one list of read folders; never-read places are never offered.
5. **Should the plan card also cover a worker's file edits in its working folder?** Recommended: not at first. Commands
   only, as B2. Add edits later, with a diff on the card, once the plan card has been used.
6. **What does "ask me about everything" include?** Recommended: every action and every command, but not reads inside
   the read folders and not turning the volume up or down (asking about volume would make the switch unusable).
   And: it stays on until the owner turns it off, not just for this session.
7. **Offer after how many?** Recommended: 3 approvals, in 3 runs, within 14 days, none rejected; offered once per kind.

## When it's built

Each part gets owner checks from the next free number in `docs/testing/owner-checks.md`, with report lines and ledger
entries, and the rule tests in the table above (one per rule, each failing with the guard removed). Size, roughly:

- **3, ask me about everything:** small. One setting, two checks in the gateway and `_ask`, a tray label.
- **1, learned trust:** medium. `Action.kind`, the table, a count over the journal, the offer card, the list and forget
  phrases in the memory lane.
- **2, plan card:** medium to large. `propose_plan`, a tuple of grants, the card in the overlay with a seam scenario in
  `tests/unit/test_seam_replay.py`.
