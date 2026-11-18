# The owner's runs of 2026-11-13, as first diagnosed

Moved from `docs/handoff/README.md` §2 on 2026-11-18. This is the diagnosis written on the day; "none is fixed yet" was true then. Where each item stands now is in [`docs/handoff/workstreams.md`](../handoff/workstreams.md) (A1–A12, B1–B14, C1–C9) and [`docs/audit/findings.yaml`](../audit/findings.yaml) (X-20 for check 213).

## The owner's run of 2026-11-13 (10:05 to 11:05)

Recorded with `plan.py`. Passed by the owner: 191 (8 of 10), 193–196, 214, 233, 234, 237, 240, 241. What it found, most serious first; none is fixed yet:

- **Check 213 failed, cause proven: the never-read rule covers Read, Glob and Grep only.** The agent used Bash (`cd "$LOCALAPPDATA/Swift" && grep … interactions.jsonl`), each command came on an approval card, the owner clicked Approve six times, and yesterday's requests were read back. `claude_code.py` sends Bash straight to `confirm_card`; `ReadScope.verdict` is only called from `_ask_read`. The same path reaches `.ssh`, `.env` and the other never-read places. **Safeguard merged 2026-11-13 (X-20):** a Bash or PowerShell command that names a never-read place is refused with no card (`ReadScope.in_command`). Of the 15 commands in the owner's log, it refuses the three that read the log and no other. It reads the command's text, so a path built in pieces, by a wildcard or inside a script still gets a card; the root fix is a shell that can't open those folders. Check 213 needs running again.
- **A card stayed "working" for a request that had ended (10:48 to 10:52).** The backend stopped `cc-6` at 10:49:50 and parked it; at 10:51 the owner opened its live view and pressed Stop four times ("stop from the live view ignored | known=True"). So the backend knew it was over and the overlay still showed it. Why the overlay kept it is unproven (two stops 220 ms apart, then a `ProcessError`, came just before). **Cause proven and fixed (merged 2026-11-13):** the second Stop cancelled the request's task again while it was still telling the agent to stop, inside its own clean-up, so "Cancelled" was never sent (the log shows "parked" 3 ms after the second stop). `swift/cleanup.py` runs that clean-up to its end; the seam scenario `test_a_second_stop_while_the_first_cleans_up_still_ends_the_card` fails without it. Owner check 242. Not done: when the overlay asks about a request that is over for any other reason, the backend still only logs it.
- **Check 197 failed, cause proven for the duplicate cards:** `_same_request` compares the words exactly, so "…history of T" and "…history of tea" are two requests. "Yes, tea the drink" answered with "Still on it" is not reproduced yet.
- **Check 215 wasn't reached the normal way:** `fill_in_email` failed 3 times of 4 (`connector_failed`; the log doesn't say why, as before). The one send that reached the 5-second window was stopped about 8 s after it went, so the window itself is still untested.
- **Two emails were really sent during the run,** both approved by a click: 10:36:27 and 10:45:11.
- **The report's FAILs:** 31–36 (a calendar request at 10:08 went to the agent, not the workflow), 49 (an email thread's follow-ups left the workflow after the fill failed), 239 (the daily reminder: Swift said it only does one-off reminders).
- **Asked for by the owner:** cards behind the main card shouldn't leave before they've been read; "remember that…" isn't built (the memory store, §4 groundwork); a repeating reminder (a small leftover in §4).

## The owner's run of 2026-11-13 (13:37 to 15:20)

Recorded with `plan.py`. Passed by the owner: 202, 207, 209, 210, 213 (refused as designed), 216, 217, 219, 220, 236, 242.
Failed: 201, 203, 204, 205, 206, 208, 218, 235, 239; 211 couldn't be done. Sorted by what they are; none is fixed yet.

**Defects, cause proven:**

- **"Turn off the wafer" can't succeed (201, 206, 239: 14:13:51, 14:14:37, 14:16:35, 14:25:35).** A chain of three, from
  the interaction log and `system_tools.py`. (1) The local lane doesn't parse "wafer", so it goes to the agent, which calls
  `system_action`; that refuses it as "not asked for". (2) The refusal (`NOT_ASKED`, `system_tools.py:104`) tells the agent
  to ask a choice and gives the literal example `'Did you mean the Wi-Fi or Bluetooth?', options ['Wi-Fi', 'Bluetooth']`;
  the agent copies it. That is where Bluetooth comes from. (3) The answer can't unlock it: a "yes" to the agent's own
  question never counts, a click on an option never counts (by design), and spoken "WiFi" in one word, as speech
  recognition often writes it, matches no option (`dialogue._choose` splits "Wi-Fi" into "wi" + "fi" and needs those exact;
  "WiFi", "the WiFi", "I meant WiFi" all resolve `unclear`, measured). So the flow the tool asks for ends in
  "I couldn't turn Wi-Fi off" whichever way the owner answers. Root fix: the local lane offers "Did you mean Wi-Fi?"
  itself (Swift's own question about a reversible change, where a plain yes works), and the matcher treats "wifi" and
  "wi fi" as one word. Whether the owner's two spoken answers at 14:14 were "WiFi" is likely, unproven (answers aren't saved).
  **Fixed, merged 2026-11-13 (reviewed by a session other than the author, pass with notes; its main note fixed in
  `541ea7c`):** in a switch-off command, a way speech recognition has
  written Wi-Fi (`HEARD_AS_WIFI`: wafer, Wofo, waffle, why fi and close spellings; a new one is added from a saved clip)
  is read as Wi-Fi off, so it gets "Turn off Wi-Fi?" and never the agent (`225ca9b`; a guessed "on" stays unparsed:
  it has no question); and an option said as one word ("WiFi") is that option (`106b6dd`). Owner check 243.
  Not changed: `NOT_ASKED`'s example still names "Wi-Fi or Bluetooth" for other misheard words; a click on an option
  still never counts.
- **"Play some music" says "Playing." and nothing plays (235).** The `media` intent presses the Play/Pause key and
  answers "Playing." without checking (`system/lane.py:385`). With no player open the key does nothing.

**Defects, cause unproven:**

- **A question shown as "Working on it" (206, 211, 218: lunch at 13:51:57).** The backend asked "Which day and time next
  week for lunch?" on screen (`waiting=False`, nothing else running) and sent the `ask` frame; the owner saw "Working on
  it" with no question, and it ran out. Nothing on the overlay side is logged, so whether the presenter refused or
  mis-drew it is unproven (see "the overlay can still refuse a frame silently" below). Next: replay it in the harness.
  The spinner beside "Working" not turning is the same screen and not looked at.
- **Cards behind the main one vanish before they're seen (208, 219), and one reopened from the stack seemed to restart
  or stay "Working on it".** Not investigated. The owner's rule: a card never seen doesn't run out; a card waiting for
  them pauses while out of sight.
- **Two requests for one ask (204, 205: 14:21:03 to 14:22:02), and an agent approval card for a radio (204 FAIL in the
  report; 14:44:20).** Not investigated.
- **Swift stayed behind an always-on-top Task Manager (203).** Not investigated.
- **Gmail: the email isn't written unless the cursor is already in the body (seen during 242).** Known since before,
  from the focus check in `desktop/windows.py`; not investigated.
- **Opening a website failed (15:07:03).** Not investigated.

**Design, for the owner to decide (Halo step B and the interaction layer):** approval cards lead with a plain sentence
of what the command does and why, with the command folded underneath; fewer approvals per task, grouped where one
grant could cover them; a distinct look for working, waiting for an answer, waiting for an OK, doing, and failed;
results laid out to fit them (tables, cards, diagrams) rather than one text card; cards that grow when the content needs
it and can be expanded by hand; each card's lifetime fitted to the request (210); the orb animation's timing (221,
unsure).

**Capabilities not built (the roadmap's later steps):** repeating reminders (239, 237), location (the distance to CBD
was guessed at 4 km with no location: it should ask; this one is a defect in the answer, not only a missing feature),
booking (Uber, flights) by working through the site with the owner watching and approving, finding and installing a
tool it needs (diagrams), choosing how to play music.

