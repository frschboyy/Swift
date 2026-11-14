# Reliability: how to change and fix Swift

**Status: draft, proposed in [`docs/explorations/claude-md-split.md`](../explorations/claude-md-split.md).** Until
the owner accepts the split, `CLAUDE.md` is the authority and this file repeats it.

Sources: the reliability audit and its review ([`2026-11-reliability-audit.md`](../audit/2026-11-reliability-audit.md),
[`2026-11-reliability-audit-review.md`](../audit/2026-11-reliability-audit-review.md)) and the foundation review §6.

## 1. Three claims, kept apart

- **Specified**: a rule in `CLAUDE.md`, an ADR or a product document says it.
- **Implemented**: the code does it, and a test shows it.
- **Verified**: its owner check has passed on the real PC.

Never describe behaviour from a document alone: read the code and its tests. Never change a rule to fit what the code
happens to do; say where they differ. A report says which of the three it is claiming.

## 2. Understand, then prove, then change

1. Read the handoff ([`docs/handoff/README.md`](../handoff/README.md)) and the code a change touches.
2. Reproduce the problem where it happens.
3. Name the cause, or say "unproven".
4. Make the smallest change that fixes it.
5. Verify the original case.
6. Report what was and wasn't verified.

## 3. Rules for a fix

- **Prove the cause first.** Reproduce it where it happens before naming a cause. Say "unproven" when it is.
- **One finding per commit.**
- **Label the fix in its commit message:** root, partial, safeguard, workaround or symptom. A workaround names what
  would replace it.
- **Screen fixes need the seam.** A fix to what's on screen isn't done until it has a scenario in
  `tests/unit/test_seam_replay.py`, which fails with the fix undone.
- **Product rules:** someone other than the author reviews a fix to one, unless the owner waives it.
- **Big claims need a test.** A commit that claims "one owner of X" names the test that would fail if there were two.
- **Structural steps delete code.** Prototype on a branch and keep it only if it removes more than it adds.
- **Confidence bars:** score any change to one on the owner's saved clips.

Why the review rule exists: on X-05 each of the first three review rounds caught a real fault, two added by the
follow-up under review; X-17's first two rounds each blocked it (README §2).

## 4. Scope and ownership

- **Stay in scope.** A problem found on the way is recorded (in `docs/audit/findings.yaml` or the report) and fixed
  separately, unless it blocks the task.
- **Respect the owners.** Before adding logic, find the code that already owns that responsibility and change it
  there; two owners of one thing is a bug. The map is [`docs/architecture/ownership.md`](../architecture/ownership.md);
  a second owner found is a finding.
- **`session.py` is large:** add small modules with narrow interfaces. `tests/unit/test_structure_ratchet.py` stops
  it growing and stops new package cycles.
- **No new dependencies without a clear need.**

## 5. The findings register

`docs/audit/findings.yaml`, one entry per finding from every audit. `tests/unit/test_findings_register.py` keeps it
checkable: known keys and values, unique ids, every named test exists, a fix says where it is, and an open critical
finding has a test or says `untested:` with why.
