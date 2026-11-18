# Review: A3 hold during calls, commit 7ab2b70 (claude/laughing-nightingale-968e04)

Reviewer did not write it. Read only. Tests: test_calls.py + held-cards/attention/dialogue/hardening/system_lane: 277 passed, 1 skipped.

**Verdict: reject as is (fine to merge once 1-3 are fixed; nothing approves wrongly).**

Product rules hold: the hold never approves, auto-denies or reorders anything. A held card freezes (12 h HOLD_S, then
no_answer as for away), and comes back with at least RETURN_S 60 s, counting down only once the overlay says it drew it.
Approval stays in intake/gateway, and the hold never touches it. The setting is off by default, and the watcher isn't created when it's off.

## Findings, worst first

1. **High: a card that arrives during a call is shown on the shared screen.** `hold_cards` only hides the card that is on screen
   when the hold *starts* (session.py:4331-4346). A new confirm card during a call is sent as a plain `confirm.request`
   (session.py:4236), and no `confirm.hold held=True` follows, so the overlay draws it. Its countdown is frozen and it isn't read aloud.
   Result and notice cards aren't held at all. Scenario: the owner on a Teams share, a worker asks to edit a file, and the card
   with its detail shows to everyone. The calls.py docstring ("holds what it would show") overclaims.
   Fix: in the card-show path, when `attention.held`, send `confirm.hold held=True` (and stack it) right after `confirm.request`.
   Add a session-level test where a card arrives after `set_call(True)`.
2. **High (detector): packaged apps are never detected, so new Teams, Store WhatsApp/Slack/Zoom don't count.** calls.py:43-47 compares the
   ConsentStore key (`MSTeams_8wekyb3d8bbwe`) with process names (`ms-teams.exe`), which never match. new Teams is the
   default Teams. That is a false "not in a call": showing, the unsafe direction. The spike flagged it, but the code drops these apps silently.
   Fix: for packaged keys (no `np:` prefix), match by package family to a running process (psutil exe path under
   `WindowsApps\<family>`), or treat a call-app packaged key with Stop==0 and a recent Start as a call. Add a test.
3. **Medium: a stale key can hold Swift for hours with no sign.** A browser key left at Stop==0 (a crash mid-stream; the spike saw
   the same with Zoom) plus Chrome running gives a permanent hold: cards hidden, due reminders silent (chime only), questions
   parked, and after 12 h confirms end as no_answer. `set_call` doesn't call `lifecycle.announce()`, so neither tray nor capsule says why.
   Fix: announce the call hold (tray "Holding: you're on a call"), and ignore a key whose LastUsedTimeStart is older
   than some cap (for example 4 h).
4. **Medium: the owner can't get a held card back during a call.** `_open_card` index 0 (session.py:1466) only calls `_owner_here()`. With
   `in_call` set, `handle` re-holds it (lifecycle.py:123), so clicking the held card in the stack does nothing until the
   call ends. Fix: an owner's open from the stack shows that card even during a call (the owner chose to). Or the call hold stays off
   for that card until the next call.
5. **Medium: a watcher error ends call detection silently and can leave the hold stuck.** `CallWatch.poll` catches only probe errors
   (calls.py:113-117). If `on_change` / `hold_cards` raises, the `run()` task dies unobserved (task stored as an F841 local).
   If that happens on start, `lifecycle.in_call` stays True, and every later presence change re-holds. Fix: try/except around
   `on_change` in `run()`, log the error class, keep polling.
6. **Low: the probe blocks the event loop every 2 s.** psutil.process_iter + registry walk + shell32 take about 20 ms (spike) on the loop that
   serves audio and IPC. Fix: `await asyncio.to_thread(self.probe.in_call)`.
7. **Low: `dialogue.forget()` / `_away_questions()` run again on every presence change during a call** (lifecycle.py:123 passes
   True for here/idle changes too). Questions are already parked while `_away`, so nothing is answered wrongly. But a
   "make it louder" carry from a hotkey request mid-call is wiped at the next idle/here flip. See Q2 below.
8. **Low: substring matching on app names.** `"msedge" in "msedgewebview2.exe"` matches any WebView2 app with the mic open,
   *including Swift's own overlay if it ever opens the mic* (it doesn't today: no getUserMedia in overlay/src). The same goes for
   `chromedriver`, `zoomit` (no mic). It errs toward holding. Fix: match exact exe names.
9. **Low: a failed probe logs a warning every 2 s forever** (calls.py:116). Log once per error class or on state change.
10. **Nit: logs and records say "away" for a call hold**: "confirm card held while away", `held_away` counter
    (session.py:4339-4340). Structure, not content, but it misleads log reading. Pass a reason.

## The questions asked

- **Q1 present/in front on release:** OK. Release goes through `set_held(False)` → redraw → `set_seen` before the countdown runs.
  Approval still needs presence + on screen. A held confirm when the call ends mid-approval: the answer future is still
  live, so an answer before or after counts (test_an_answer_while_held_still_counts). Nothing auto-denies.
- **Q2 `dialogue.forget()` on call start:** acceptable, and it's the safe direction. A pending question is settled to the stack
  (`_away_questions`), not answered, and its answer can't land on a different question afterwards. The cost: a question asked in
  the 2 s before the hold, which the owner was about to answer, goes to the stack, and an ellipsis carry is lost. I'd keep the
  forget but run it only on the hold's rising edge (fixes finding 7).
- **Q3 interplay:** away→back mid-call keeps the hold. A call ending while away doesn't release (tested). Hysteresis is fine and tested.
  A failed probe keeps the last state (tested). The stale-key check covers non-packaged apps only. Swift's own mic (python.exe) is excluded.
  Shutdown: the task is cancelled with the loop like presence_tasks. Off: no watcher, `in_call` stays False.
- **Q4 privacy:** swift.log gets "call hold" / "call hold ended" + seconds, and on failure the error class. No app names, no
  content. OK.
- **Q5 tests:** they fail without the code (import and lifecycle change). Missing: a session-level card arriving during a call
  (finding 1), `_mic_open` key parsing / packaged names (finding 2), on_change raising (finding 5). `live` in
  test_mic_call_ignores_swift_stale_and_non_call_apps is dead. The parametrize on test_example_config is pointless.
  The example-config test reads a relative path and depends on the cwd.
