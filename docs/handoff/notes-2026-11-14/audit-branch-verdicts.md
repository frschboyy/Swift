# Verdicts on three old branches (2026-11-14)

Branch with the result: `claude/merge-audit-branches-b460f7`, from `main` at `a8f12ce`. Nothing pushed or merged into `main`.

| Branch | Verdict |
|---|---|
| `backup/wake-porcupine-trial-pre-rebase` | **Superseded: all of it is in `main`.** Delete the branch. |
| `claude/audit-fixes-recipients` | **Superseded/ported.** Its 3 commits are the first 3 of `audit-fixes-google-calendar`. One fix is ported, one is superseded, one is a handoff edit. Delete the branch. |
| `claude/audit-fixes-google-calendar` | **Partly still wanted.** 8 fixes ported (11 commits) plus their owner checks, renumbered to 350–353. 4 commits superseded by `main`, 4 are handoff edits that no longer apply. Delete it once this branch is merged. |

Method: `git cherry -v main <branch>` (patch ids), then a content check of each change against `main`'s current code, since several fixes landed again under other names (HA-FAKE-01, X-02).

## 1. `backup/wake-porcupine-trial-pre-rebase` (25 commits)

- `git cherry`: 22 of 25 are already in `main` by patch id (`17d7579` … `97ff387`, ADR-021 steps 1–6).
- The other 3 (`2e463a9` step 4, wiring; `427b198` step 5, checks; `712c514` renumbering to 228–232) are in `main` as `1553cf8`, `5d65666` and `337ab0b`. Their patches differ only because conflicts were resolved during the rebase.
- Content check: every one of the branch's 23 files exists in `main`. The ones that differ have `main` *ahead*: `wake_acoustic.py` (a docstring), the ADR-021 status line (lock-rule review done, merged 2026-11-12), `settings.py` / `config.example.yaml` (`runs`, `memory_dir` added later), and `session.py`, the owner checks and the seam tests (later work).
- ADR-021 was **not dropped**. It is merged into `main` and off by default (`wake.acoustic`), waiting on owner checks 228–232 (`roadmap.md:70`). The backup branch adds nothing to it. No new dependency.

## 2. `claude/audit-fixes-recipients` (3 commits)

These are the same commits as the first three of `audit-fixes-google-calendar` (same hashes):

| Commit | What | Verdict |
|---|---|---|
| `ceadea4` find_contact: only the contact the owner picked is a recipient | Of several matches, only the picked one goes in `scope.resolved` | **Superseded** by `ccfcae7` X-02 on `main`. `main` is stricter: with several matches it resolves none, with or without an ask (the branch still resolved all of them when no ask was possible). Test: `test_seams_audit_privacy.py::test_of_several_francises_none_is_a_recipient_until_the_owner_picks`. |
| `eac4417` Gmail: a contact named "Last, First" is one recipient | `mime()` builds the To header with `email.utils.formataddr` | **Ported** (`ef4689e`). |
| `71c8b8a` Handoff row | — | Dropped (stale). |

### What this branch changes about recipients, for the second review

The only recipient-related code now on my branch from these old branches:

1. **`src/swift/connectors/gmail.py` `mime()`** (`ef4689e`): the To header was `f"{name} <{email}>"`, now it is `formataddr((name, email))`. For a name with a comma ("Smith, John") the old header read as **two** addresses ("Smith" and "John <…>"), so Gmail could treat it as two recipients. Now the name is quoted. **Which** contacts are recipients is unchanged: the list still comes only from `email.to`, which the gateway has already checked against `scope.resolved` (contacts / `find_contact`). Test: `test_google_contacts.py` (the new "Last, First" case).
2. **Test-only commit** `6eb3f52`: two dialogue tests from the old branch that check `main`'s X-02 behaviour through the spoken "Which Sam?" question: a pick resolves only that one contact, and "never mind" resolves none. No code changes.

`find_contact` (`src/swift/workflows/tools.py`) is **not** touched: `main`'s X-02 version stays as it is.

## 3. `claude/audit-fixes-google-calendar` (20 commits)

| Old commit | What | Verdict | On my branch |
|---|---|---|---|
| `ceadea4`, `2ba09cd` | find_contact: picked one only; no answer leaves none | Superseded by X-02 (`ccfcae7`) | — (tests only, see above) |
| `eac4417` | Gmail "Last, First" | Wanted (`main` still had the f-string) | `ef4689e` |
| `643efdf` | Google "not found" from the status, not the text | Superseded by HA-FAKE-01 (`http_status()` in `connectors/google.py`, used for 404/409/410/401) | — |
| `cdfcad4`, `00b57c3` | Google fakes raise a status error | Superseded (`main`'s fakes already use `Status(404)`) | — |
| `810c307` | Calendar: a list cut at its limit says "there may be more" | Wanted (`main` didn't say it, so "am I free Friday?" could be answered from a cut list) | `39d113f` |
| `e6d19f0` | Calendar: "until Friday" with no start includes Friday | Wanted (`main`'s `_range` still stopped at Friday 00:00 when there was no start) | `d9c6ddc` |
| `7f79723`, `8a9df77`, `bd0fb82` | Read rules: a Grep whose `glob` aims at secret-named files (`.env*`, `*.{pem,key}`) is refused | Wanted. `main`'s X-20 covers Bash commands and paths, but `_ask_read` never looked at Grep's `glob`, so a Grep in a read folder with `glob: ".env"` was allowed. One conflict (imports moved to `swift.security.web_scope`, `step_grant` added), resolved. | `9ebf342`, `5508cb4`, `8d1b6eb` |
| `29781c9` | Parked work: on the same clock tick, the one parked later is the newest | Wanted (`main` still uses `reverse=True`, which keeps insertion order for ties) | `e21bc50` |
| `f60b7ba`, `7ff6bb5` | `debug.ask` answers nothing outside debug mode | Wanted. In `main` the refusal is in `_start_text`, but `handle("debug.ask")` reaches `_take_answer` first, so outside debug mode a `debug.ask` message could answer an open question as if it were the hotkey. Nothing in the overlay sends it (only `protocol.ts` / examples and the dev harness), so this closes a side door and doesn't change normal use. One test conflict, resolved by keeping only the debug test. | `27aac46`, `1b3e651` |
| `3e20958` | "Open this": `.py .pyw .jar .msc .url .pif .wsh .msix .appx .appinstaller` count as programs (need a card) | Wanted (`main`'s `PROGRAMS` didn't have them) | `f1825e4` |
| `0692822` | pyproject: the spikes group's comment says `src/swift` imports the Google libraries from it | Wanted (`main`'s comment "Never imported by src/swift" is false: `connectors/google.py` imports `keyring` and `google-*`). Comment only, no dependency change. | `791cd9b` |
| `33d0d1a` | Owner checks 222–227 | Numbers taken in `main`. Ported as **350–353** (224–227); 222–223 not ported (X-02 owns that fix) | `2291fff` |
| `71c8b8a`, `2bea581`, `ca04c25` | Handoff edits | Dropped (stale) | — |

Nothing harmful found. No new dependencies.

**Product rules touched (they need a reviewer other than the author):**
- recipients: `ef4689e` (header formatting only, above);
- approval / "typing never approves": `27aac46` (`debug.ask` refused outside debug mode before it can answer);
- reads: `9ebf342`/`8d1b6eb` (stricter: more refusals, never fewer);
- programs need a card: `f1825e4` (stricter).

**Check numbers:** 350–353, not the next free 340, so they don't collide with sessions writing checks right now. Recorded in the shared `check-numbers-claimed.md`. `plan.py --write` was run.

**Follow-up spotted (not fixed here):** Glob with a secret-named pattern in a read folder (`pattern: "**/.env"`) is judged by the pattern's fixed start (the folder), so it can *list* such files. It can't read them, since Read is still refused by name.

## Test results

Run with the main checkout's venv (`PYTHONPATH=src …/.venv/Scripts/python.exe`), since `uv run` hangs on this PC.

- **Full Python suite** (on `6eb3f52`): 2151 passed, 1 skipped, 34 xfailed, **3 failed**:
  - `test_health_CFG.py::test_open_selected_script_is_refused`: XPASS(strict). The ported "open this" fix also fixes
    known finding **HA-CFG-04**. Marker removed and the finding marked fixed (partial) in `b728bdb`; that file and
    `test_findings_register.py` now pass.
  - `test_held_cards.py::test_a_countdown_that_runs_out_sets_the_card_aside_in_the_stack`: passes when run alone.
    A timing flake under load (four other sessions were running).
  - `test_seam_replay.py::test_a_card_counts_down_on_the_backend_s_clock_seen_away_and_back`: **fails the same way on
    `main` `a8f12ce`** (the two clocks 4 s apart under load). Pre-existing, not from this branch.
- **Routing parity:** the same as `main` `a8f12ce` (the same 10 misses, `web-330`…`web-339`, weather/news to agent). No drop.
- **Overlay:** not touched, so `tsc` and `npm test` were not run.
- Owner-check plan tests (`test_owner_plan.py`, `test_owner_report.py`): pass after `plan.py --write`.

## Commits on `claude/merge-audit-branches-b460f7` (oldest first)

`ef4689e` `39d113f` `d9c6ddc` `9ebf342` `5508cb4` `e21bc50` `27aac46` `f1825e4` `791cd9b` `8d1b6eb` `1b3e651` (cherry-picks
with `-x`), `2291fff` (checks 350–353), `6eb3f52` (X-02 tests), `b728bdb` (HA-CFG-04 closed), and this note.

## After merging

Delete all three old branches, local and on origin (owner's OK), and the worktree `C:\Users\frchi\Documents\Swift-audit-fixes`.
Remove the two audit-fixes rows from README §6.
