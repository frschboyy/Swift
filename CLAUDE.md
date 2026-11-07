# Swift: notes for Claude Code

Swift is a voice-first Windows assistant: a Python asyncio backend in `src/swift`, Claude Code through claude-agent-sdk, and a Tauri v2 overlay in `overlay/` (Rust in `src-tauri`, TypeScript in `src`). The owner is Francis.

**Start with [`docs/handoff/README.md`](docs/handoff/README.md).** It has the current state, work in progress, the owner checks to run, the agreed order, and the open decisions.

Owner's principle: **"Swift adapts to the user, not the user to Swift."**

## Rules

- **Git:**
  - Work on a branch in a worktree; commit there only.
  - **Never push.** Merge into `main` only when the owner says so.
  - End commit messages with a `Co-Authored-By:` line.
- **Never enter credentials or sign in for the owner.** Google sign-in is owner-run:
  ```bash
  uv run --group spikes python -m swift.connectors.gmail signin
  ```
- **No real-world actions to test** (emails, calendar, Wi-Fi, locking, deleting). Use the fakes, debug mode and the dev harness.
- **Port 1420 is the owner's running Swift.** Never start a dev server on it; the harness uses 1431.
- **Product rules** (a path that breaks one is a critical bug):
  - recipients only from contacts or `find_contact`;
  - approving hands-free needs Swift's name, and a bare "yes" never approves; the one exception is
    Swift's own question about a reversible change the owner just asked for ("Turn off Wi-Fi?"),
    where a plain spoken "yes" or a click on Yes does it while the question is open and on screen;
  - typing never approves;
  - no hands-free listening while locked;
  - logs content-free (transcripts redacted), except the owner's local interaction log;
  - status labels generic (never "Claude Code is…");
  - audio never leaves the PC;
  - Swift writes into apps only when the owner's own words asked;
  - memory is written only from the owner's words or an approved card, never from what a worker read;
  - deleting a file always asks on a card, whatever a setting or a run's permission says (ADR-019; whether
    a move to the Recycle Bin counts as reversible is decided when the W2 file tools are designed).
- **Code:**
  - `session.py` is large: add small modules with narrow interfaces.
  - No new dependencies without a clear need.
- **Owner checks:** new behaviour gets checks in `docs/testing/owner-checks.md`, plus report lines in `spikes/owner_checks/report.py`.

## Fixing things

Rules from the reliability audit and its review (`docs/audit/2026-11-reliability-audit.md`, `docs/audit/2026-11-reliability-audit-review.md`):

- **Prove the cause first.** Reproduce it where it happens before naming a cause. Say "unproven" when it is.
- **One finding per commit.**
- **Label the fix in its commit message:** root, partial, safeguard, workaround or symptom. A workaround names what would replace it.
- **Screen fixes need the seam.** A fix to what's on screen isn't done until it has a scenario in `tests/unit/test_seam_replay.py`, which fails with the fix undone.
- **Product rules:** someone other than the author reviews a fix to one, unless the owner waives it.
- **Big claims need a test.** A commit that claims "one owner of X" names the test that would fail if there were two.
- **Structural steps delete code.** Prototype on a branch and keep it only if it removes more than it adds.
- **Confidence bars:** score any change to one on the owner's saved clips.

## Commands (Windows; from a worktree)

- **Python tests:**
  ```bash
  /c/Users/frchi/AppData/Local/Microsoft/WinGet/Links/uv.exe run --frozen pytest -q -p no:cacheprovider
  ```
- **Routing parity** (must not drop):
  ```bash
  uv run python eval/parity/score.py
  ```
- **Overlay:** in `overlay/`, run `npx --no-install tsc --noEmit` and `npm test`. A worktree has no `node_modules`; link it temporarily and remove the link afterwards:
  ```powershell
  New-Item -ItemType Junction -Path <worktree>\overlay\node_modules -Target C:\Users\frchi\Documents\Swift\overlay\node_modules
  ```
- **Rust:** `cargo test` in `overlay/src-tauri`, using the worktree's own `target` (a long target path breaks Windows linking).
- **Dev harness:**
  - Add a temporary `.claude/launch.json` entry running `npm --prefix overlay exec -- vite overlay --port 1431 --strictPort`, plus the existing `backend-harness` entry (debug backend on 8765).
  - Open `http://localhost:1431/dev/harness.html?port=8765&token=devharness-token-0123456789abcdef`.
  - Drive states with `window.__shim.inject(type, data)`; the `Agent` shape is `{id, name}`.
  - Revert `launch.json` afterwards.
- **Owner's logs:** `C:\Users\frchi\AppData\Local\Swift\logs\swift.log`. From a worktree, read them at `//localhost/c$/Users/frchi/AppData/Local/Swift/logs/swift.log`.
- **Edits in the owner's main checkout:** an edit hook blocks the Edit tool there. Make changes in a worktree, then fast-forward `main` (`git merge --ff-only`) when the owner approves a merge.
