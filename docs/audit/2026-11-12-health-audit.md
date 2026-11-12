# Swift health audit (2026-11-12)

The owner asked for one end-to-end picture instead of finding bugs one task at a time. This audit did two things:

1. **Phase 0:** every finding from the 12 earlier audit documents went into one register, [`findings.yaml`](findings.yaml), and each was rechecked against the code at `bb5cb89`, not taken from what its document said.
2. **Phase 1:** five fresh reviewers, none of whom wrote the code, read in full the modules no audit had covered, plus an integration pass over how the packages depend on each other.

No product code was changed. Branch `claude/health-audit`.

## How to use the register

- **`docs/audit/findings.yaml` is the one list.** The older documents stay as the reasoning behind each entry; the register is where status lives.
- **A fix updates its entry** in the same commit: `status: fixed`, `evidence` (where), `test` (the test that now passes).
- **`tests/unit/test_findings_register.py` keeps it honest:** known fields and values, unique ids, every named test exists, and an open critical finding has a test or a note saying `untested:` and why.
- **Repro tests are strict expected failures** (`tests/unit/test_health_*.py`, `overlay/tests/health-UI.test.ts`). When a fix lands, its test flips and fails the suite until the marker is removed, so no fix goes unrecorded.
- **`tests/unit/test_structure_ratchet.py`:** no new two-way imports between packages, and `session.py` never grows past 5,057 lines. Lower the numbers as things improve.

## The picture

241 findings. 78 are fixed, 4 are closed (3 won't fix, 1 duplicate).

| | critical | high | medium | low |
|---|---|---|---|---|
| open | 6 | 10 | 46 | 53 |
| partial | 6 | 9 | 6 | 2 |
| unproven | – | 1 | 8 | 12 |

**Product-rule breaks count as critical** (CLAUDE.md), so the merge raised every open one the reviewers had rated lower. The note on each says so. Two were lowered by hand because no path can break a rule today: HA-CFG-06 is dead code, and WL-07 waits for a deleting tool that doesn't exist yet.

**The October critical findings, and the critical ones from November's reliability work, are fixed.** What's left in critical is new or partial:

| Id | What | Size of fix |
|---|---|---|
| HA-CFG-01 | Bash, Write or Edit in `executor.allowed_tools` would be pre-approved, so a file could be deleted without a card. Not set on the owner's PC today | Small: refuse non-read tools in settings |
| HA-HEAR-01 | Typing "Swift, yes" answers "Turn off Wi-Fi?". The intake table allows it on purpose, against "typing never approves" | **Owner decides** which is right |
| HA-HEAR-02 | "Hey Swift" in the first 2 s after locking still chimes | Small: check the lock in `peek_wake` |
| X-02 | Several `find_contact` candidates all count as recipients | Small, same place as X-01 |
| B-10 | Owner-facing texts name the provider ("Claude Code stopped there") | Small: a test that scans the texts, then reword |
| OCT-01 | VS Code's terminal isn't on the list of terminals Swift won't type into | Small |
| RV-15 | The lock rule is checked in four places; one place would end the misses | Structural |
| X-01, X-05, X-07, RA-07, D-01 | Partly fixed; the leftovers are in each entry | Mixed |

**New high findings worth fixing soon**, each small and with a repro:

- **HA-FAKE-01:** Google errors are matched by searching their text for "404" or "401", and that text includes the request address. Swift can say an email was sent, or an event removed, when it wasn't. The fakes' errors have no address, so two tests pass falsely.
- **HA-UI-01:** while a request works, Esc pressed in any app never reaches it and cancels Swift's request instead.
- **HA-FAKE-03:** Esc while the agent is still connecting is swallowed, and the request runs anyway.
- **HA-SYS-01:** "airplane mode on" can leave Wi-Fi off with only a Bluetooth error, and "undo that" can't restore it.

## Why fixes keep finding new bugs

The register supports the earlier diagnosis, and adds one cause:

1. **Two hot spots, still open:** what's on screen (RA-01, RA-02, II-01, review item 9) and what was heard (RV-10, RA-18). Most repeat fixes land there.
2. **Fakes kinder than reality (new).** The Google fakes' errors, the instant-starting CLI fake and the all-or-nothing Gmail fill each let tests pass on paths that fail on the real PC. HA-FAKE-01 to 05 name the tests affected.
3. **Structure:** three package pairs import each other (HA-INT-01), nine imports reach into private helpers (HA-INT-02), `session.py` is 5,057 lines, and tests hold 304 sleeps (140 on 2026-11-05).

## Suggested order

1. **Owner decision:** HA-HEAR-01. Should typing "Swift, yes" answer Swift's own reversible question?
2. **Small critical and high fixes**, one finding per commit, each flipping its repro: HA-CFG-01, HA-HEAR-02, X-02, HA-FAKE-01, HA-UI-01, HA-FAKE-03, HA-SYS-01, OCT-01, B-10. Product-rule fixes go to a reviewer who didn't write them.
3. **Make the fakes faithful** where HA-FAKE names a false pass, so the next bug of that kind is caught by the suite.
4. **Then the agreed structural order** in the handoff (§4 g and the groundwork). The ratchets keep it from sliding back meanwhile.
5. **The rest** in severity order. Low items only when their area is being changed anyway.

## Measured on this branch

- Python: 1,853 passed, 1 skipped, 43 expected failures.
- Overlay: `tsc` clean; 127 passed, 2 todo (O-03, HA-UI-05).
- Rust: 31 passed (the UI reviewer's run).
- Routing parity: 413/423, 0 harmful (the config reviewer's run).

## Limits

- **Nothing was run on the real PC:** display scale changes, real Esc presses, the Windows calls behind the system lane, live Google errors.
- **Not read by any reviewer:**
  - `main.ts` (2,249 lines), beyond what the overlay files call in it;
  - `routing/fast.py` and `rules.py` in full;
  - the Gmail focus failure.
- **Statuses of older entries come from today's code and tests.** Entries with `test: null` and `status: fixed` (X-17, X-18, O-05, D-07, D-09) have a fix commit but no test named yet.
- **The flaky test** (`test_parked.py::test_finish_the_named_task`, HA-INT-03) was not reproduced.
