# Review of dcac4c8 (Modes §2 plan card), 2026-11-18

Reviewer: separate session (not the author). Code not changed. Findings are recorded in `docs/audit/findings.yaml`
on branch `claude/keen-meninsky-750aba` (one commit on top of dcac4c8).

- PLAN-01 (medium, product rule): a "Change" on a plan or step card (and the early returns of `_propose_plan`)
  keeps the previous grant, so its covered commands still run without a card. Only `redirect()` and a yes replace
  it. This was already the case in `_propose_step`.
- PLAN-02 (low): the plan card leaves out "Runs in" (`confirmFacts` returns `planRows` before `runsIn`).
- PLAN-03 (low): a long plan has no "more below" marker. The step count is capped, the commands per step are not.
- PLAN-04 (low, design): after "Ask me about everything" is turned off, the old grants cover again.

Held: rules 1-7 (all-or-nothing reversible steps, one-time per-listing bindings, ask-everything checked at use,
commands only, Swift-computed covered/asks, content-free logs, overlay rows and button match).
Tests: test_plan_card, test_b2_step_grant, test_own05_worker_approval: 88 passed.
Not checked: the card on screen or how it overflows, what Swift says aloud for a plan card.
