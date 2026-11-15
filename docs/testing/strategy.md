# Testing strategy: the layers, and which a change needs

**Status:** adopted 2026-11-15 (the owner accepted the split); `CLAUDE.md` links here.

Green tests have coexisted with bad days on the real PC (handoff §1, "Limit of these tests"). Each layer below
proves something the one before can't; none proves the next.

## 1. The layers

| Layer | What it proves | What it can't | Where |
|---|---|---|---|
| **Unit** | one module's rule, alone, fast | that the module is called, or called in the right order | `tests/unit/test_<module>.py` (e.g. `test_intake.py`, `test_memory.py`, `test_redaction.py`) |
| **Integration** | the session with fakes: a request through routing, the gateway, cards and the journal, on a virtual clock | the real overlay, the real devices, real services | `tests/unit/test_session.py`, `test_attention.py`, `test_calendar_lifecycle.py`, `test_worker_task.py` (the executor contract), `tests/protocol_contract.py`, `tests/virtual_clock.py`; fakes in `connectors/fake.py`, `desktop/fake.py`, `system/control.FakeSystem`, `executors/mock.py` |
| **Seam** | real backend frames through the real overlay presenter, and what the overlay acknowledges back | the DOM, Tauri, pane windows; replays one way only | `tests/unit/test_seam_replay.py`, `test_screen_state.py`; the dev harness for frames by hand |
| **Overlay and Rust** | the presenter, deck and drawing logic; placement and prefs | the backend | `overlay/` `npm test`, `npx --no-install tsc --noEmit`; `overlay/src-tauri` `cargo test` |
| **Evaluation gates** | routing and speech recognition don't get worse on recorded data | behaviour after routing or hearing | `eval/parity/score.py` (must not drop), `eval/stt/gate.py` (no sentence that was right may go wrong) |
| **Owner acceptance** | it works on the real PC, with the owner | anything not run | `docs/testing/owner-checks.md`, `spikes/owner_checks/report.py`, the ledger and `plan.py` |
| **Structure** | the register is honest; `session.py` doesn't grow; no new package cycles; every owner check names its code | behaviour | `test_findings_register.py`, `test_structure_ratchet.py`, `test_owner_plan.py`, `test_architecture.py` |

## 2. Which layers each change needs

| Change | Needs |
|---|---|
| Any Python change | unit tests for the rule; the full Python suite |
| A rule in one module (intake, read scope, memory, step grant) | unit test of the rule, and an integration test that the door reaches it |
| **What's on screen** (cards, questions, countdowns, the stack) | a scenario in `tests/unit/test_seam_replay.py` that fails with the fix undone; overlay tests if the overlay changed |
| **Speech recognition** (transcriber, fixes, endpointing, the noise gate, wake words) | `eval/stt/gate.py` before and after; any confidence bar scored on the owner's saved clips |
| **Routing** (rules, fast lane, classifier, light lane) | `eval/parity/score.py`: must not drop |
| **A product rule** (action authority, presence, logs, audio) | a test against the rule's statement (for approval: `intake.approves`' test against the table); a review by someone other than the author; an owner check |
| Overlay (TypeScript) | `npm test`, `tsc --noEmit`; the seam scenario if the backend's frames are involved |
| Overlay (Rust) | `cargo test` with the worktree's own `target` |
| A claim of "one owner of X" | the test that would fail if there were two |
| New behaviour the owner will see | an owner check (§4) |
| Documents only | `test_findings_register.py` if the register changed; `test_owner_plan.py` if checks changed |

## 3. Commands (Windows; from a worktree)

- **Python tests:** from a worktree on this PC (`uv run` hangs building a worktree venv), use the main checkout's
  interpreter; where `uv` works, `uv run --frozen pytest -q -p no:cacheprovider` is the same:
  ```bash
  PYTHONPATH=src /c/Users/frchi/Documents/Swift/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
  ```
  Use the same interpreter (`PYTHONPATH=src … python.exe`) for `eval/parity/score.py` and `eval/stt/gate.py` below.
- **Routing parity** (must not drop):
  ```bash
  uv run python eval/parity/score.py
  ```
- **Speech gate** (before and after any change to speech recognition; no sentence that was right may go wrong):
  ```bash
  uv run python eval/stt/gate.py --data //localhost/c$/Users/frchi/AppData/Local/Swift
  ```
- **Overlay:** in `overlay/`, run `npx --no-install tsc --noEmit` and `npm test`. A worktree has no `node_modules`;
  link it temporarily and remove the link afterwards:
  ```powershell
  New-Item -ItemType Junction -Path <worktree>\overlay\node_modules -Target C:\Users\frchi\Documents\Swift\overlay\node_modules
  ```
- **Rust:** `cargo test` in `overlay/src-tauri`, using the worktree's own `target` (a long target path breaks Windows
  linking).
- **Dev harness:**
  - Add a temporary `.claude/launch.json` entry running `npm --prefix overlay exec -- vite overlay --port 1431
    --strictPort`, plus the existing `backend-harness` entry (debug backend on 8765).
  - Open `http://localhost:1431/dev/harness.html?port=8765&token=devharness-token-0123456789abcdef`.
  - Drive states with `window.__shim.inject(type, data)`; the `Agent` shape is `{id, name}`.
  - Revert `launch.json` afterwards.
- **Owner's logs:** `C:\Users\frchi\AppData\Local\Swift\logs\swift.log`. From a worktree, read them at
  `//localhost/c$/Users/frchi/AppData/Local/Swift/logs/swift.log`.

Port 1420 is the owner's running Swift: never start a dev server on it; the harness uses 1431. No real-world actions
to test (emails, calendar, Wi-Fi, locking, deleting): use the fakes, debug mode and the dev harness.

## 4. Owner checks

New behaviour gets checks in `docs/testing/owner-checks.md`, report lines in `spikes/owner_checks/report.py`, and the
code each check proves in `docs/testing/owner-checks-ledger.yaml` (`test_owner_plan.py` fails without it).
`spikes/owner_checks/plan.py` keeps the run list and status in `owner-checks-status.md`:

- on a branch, give a new check a provisional id, `<branch>-<n>`; `plan.py --renumber` numbers it when it merges into
  `main` *(foundation decision 11)*;
- when the owner pastes a report, save it to a file and record it with `--record FILE`; what they tell you they saw
  goes in with `--set 216=pass 217=fail --note "…"`;
- after recording, and after every merge, run it with `--write`. The status file is generated and never merged by
  hand (`merge=ours`) *(foundation decision 12)*.

A new check's id comes from `plan.py --next-id`. At merge, on the branch's worktree:

1. `git merge main` (the status file keeps this side; a conflict there is fixed by step 3);
2. `plan.py --renumber`, then commit ("Owner checks: renumbered at merge");
3. `plan.py --write`, then commit; then fast-forward `main`.

Once per clone, so `merge=ours` takes effect: `git config merge.ours.driver true`.

A pasted report carries the first 60 characters of each request ([`docs/security/privacy.md`](../security/privacy.md)
§8).

The live roadmap: `docs/handoff/roadmap.md`, written to `ROADMAP.md` by `spikes/owner_checks/roadmap.py`.
