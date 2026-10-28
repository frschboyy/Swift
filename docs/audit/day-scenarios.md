# A simulated day with Swift

Each row says how it was examined:
- **test:** a unit test with the fakes;
- **log:** the owner's real log or interaction log, 2026-10-27/28;
- **code:** reasoning over the code path;
- **unverified:** needs the real PC.

"Gap" means the actual behaviour falls short of what the owner would expect.

## Lifecycle

| Scenario | Expected | Actual | How | Gap |
|---|---|---|---|---|
| Wake, ask, walk away; back hours later | The first "hey Swift" answers within about a second | Back is detected on input; the speech model is primed (183–875 ms median, 12.8 s worst); the spare starts 5–6 s later. Listening again 1.25 s median, 4.7 s max | log | The first agent request after a long absence pays a cold CLI start (8 s at 05:38:40) if it comes before the spare is ready (B-05) |
| The spare Claude CLI exited while idle | Replaced quietly | `ensure_spare` replaces it; "spare claude exited while idle" 4 times; the run starts cold once | log, code | none |
| The Google token expired or was revoked | A card that says "sign in again", with the command | `GoogleSession._failure`: "sign-in has expired", with `SIGNIN_HINT` | code | none |
| Lock and unlock mid-run | The run goes on; its card is held while away and comes back | `hold_cards`, attention held; the card is replayed on return | test (`test_held_cards`) | Check 14/22 not re-run since the fix |
| Lock while "hey Swift, …" is still being transcribed | Nothing acts | **Acted before A-09**; now dropped (`paused_drop`) | test | fixed |
| Sleep and resume | The microphone reopens; listening within about a second | `Lifecycle.handle` reopens the mic after resume; the stale pause from before is ignored | log, test | none seen |
| The microphone is unplugged and plugged back in | Swift notices and reopens | The watchdog `_check_stream` reopens ("stopped delivering audio; reopening" at 22:51 and 22:54 on 10-26) | log | No card tells the owner the microphone is gone; only the tray |
| Restart with a timer pending | It still fires; if it was due while Swift was down, "this was due at …" | Loaded from `schedule.json`; marked missed if over 45 s late | code | A due item is dropped from the file before it is shown: a restart while it waits loses it (B-03) |
| Restart with a card open | The action isn't done, and Swift says so after the restart | The run ends with Swift; the journal has no `PENDING` (the card comes before the journal). Nothing is said after the restart | code | The owner may think it's still waiting; low risk (nothing done) |
| Long idle, then an immediate request | Answers | A wake transcription timed out twice after about 30 min quiet (20 s timeout, 10-27 04:48 and 05:02); priming on return addresses the locked case, not plain idle | log | Possible on long unlocked idle; logged with `idle_s` to tell |

## Speech

| Scenario | Expected | Actual | How | Gap |
|---|---|---|---|---|
| "Hey Swift" while Swift is talking | Ignored (half-duplex); the hotkey, Esc or typing stops the voice | `own_voice` drops it while speaking and 0.6 s after | code, test (`test_speech`) | No voice barge-in (by design, not built) |
| "Hey Swift" while a run works | A new request beside it, or mid-run phrases | `_hear_busy` → `_new_request(strict)` → `_start_beside` | test | none |
| "Hey Swift" on a card | A change to the card, a new request beside it, or "Swift, approve" | As expected | test | none |
| Mumbling, someone else, a TV | Set aside, or "say it again" | 9 set aside as the room, 1 as long talk, 7 "say it again" in one night; `followup_min_p` and the SNR filters | log | 15 `unclear_speech` since 10-27: the owner repeats sometimes |
| Accidental or repeated wake | No duplicate work | The same words again while running → "Still on it" (A-11); a reworded repeat is a second request | test | Partly |
| A brisk "stop" or "show me" mid-run | Acted on at once | Short clips kept; `close_control` matches "so me" → show | test | Check 10 not seen live since the fix |
| A second request right after the first | Both run | The queued capture (`queued`), then beside | test | Check 47 not run live |

## Conversation

| Scenario | Expected | Actual | How | Gap |
|---|---|---|---|---|
| "And what date is that?" | Same thread, answered with context | The fast lane keeps the thread's moment; check 2b passed | log | none |
| A topic change without a new thread | Not confused by the old one | The follow-up window carries context for 5 min; "new topic" clears it | code | The model sees the last exchange even when unrelated (cheap, rarely harmful) |
| A correction after a card | A new card with the change | `answer_text` with revise → "Changing it: …" | log (checks 5, 8) | none |
| The same request again because it seemed slow | One run | Fixed (A-11) | test | — |
| "Could you move…" vs "move…" | Both are instructions to the calendar workflow | Both reach calendar-event (probe) | test | none |
| "Cancel that", "repeat that", "stop talking" | Control, no model | `control` cancel, repeat, stop | probe | none |
| "What did I just ask?" | Answered from the thread | Goes to the agent on the light model with the last exchange | probe | 2–3 s for something Swift knows; candidate for the local lane |

## Lane choice

From the route probe and the real log (medians by lane are in [performance.md](performance.md)):
- Timers, volume, time in Tokyo, maths and "open Word" stay local.
- Calendar changes and questions reach the calendar workflow, mostly on Haiku.
- "Write … here" was swallowed by the light lane (A-10, fixed).
- "Could you tell Ada I'm running late" goes to the general agent, not email-draft. It still works, because the agent has the tools, but without the playbook.
- "Is it going to rain", news and "is it open now" go to the agent on Sonnet (Phase I's web lane is not built).
- No case was found where a lane swallowed a request that needs tools, other than A-10.

## Actions

| Scenario | Expected outcome | Actual | How |
|---|---|---|---|
| Missing details ("add lunch with Test Me") | Swift asks, listens 25 s, then parks it | The question window; check 26 | log |
| Ambiguous contact | The recipient card lists the candidates | `find_contact` candidates with detail | test |
| Misheard event title | Found by sound ("Flift Tech" 0.53) or asked | `sounds_like` fallback | test |
| Approve, then "undo that" / "I didn't approve that" | An undo card | `undo_last` with its own card | test, log (checks 34, 35) |
| Google accepts, the connection drops | done, or unknown; never "failed" | Fixed (A-05, A-06) | test |
| Errno 10053 on delete | Done on the retry | `tried` flag (13:40:40 on 10-27) | log, test |
| A refused token | "Sign in again" card | `not_connected` | code |
| The same action twice in one run | Done once | `scope.sent` digest | test |
| Partial success (system "volume up and Wi-Fi off") | Says what was done, asks for the rest | `system_action` returns what was done plus the reason | test |

## Desktop

| Scenario | Actual | How |
|---|---|---|
| The target app closed, focus stolen, a dialog pops up | `writer.changed()` between paragraphs → "Carry on writing in …?" card | test (`test_desktop`) |
| The owner types while Swift writes | Pauses and asks; push-to-talk keys don't count | test |
| Esc during a write | Stops between paragraphs; what was written can be undone | test |
| Writing into a chat app | Line breaks no longer send (A-01) | test; check 50 |
| Writing into a terminal | Refused (A-02) | test |
| Structured APIs first | Word object model → UIA Value (empty field only) → clipboard paste (text clipboard only, restored) → keystrokes. No coordinates are used | code |
| What leaves the machine | The context line ("Word (document), 69 characters selected") goes to the model; the selected text only when the request is about it and the app isn't private | code |

## Overlay

| Scenario | Actual | How | Gap |
|---|---|---|---|
| A card fading while the owner reads it | The countdown runs only while drawn, visible and the owner is present | test (`test_card_timing`) | The real "vanish" was A-08 (fixed) |
| Drag at 100% and 150% scaling | `drag_pane` / `placement.rs` in physical pixels | code | 150% not checked (check 58) |
| Stack: open, skip, end | Works | log (check 16 PASS; 10 ends) | — |
| Typing to Swift | Same router; never approves | test | — |
| A pane for a request that ended stays stuck | Rows are forgotten after 20 s (`FINISHED_ROW_S`) | code | not seen live |
| The backend restarts | The overlay reconnects with back-off (`ipc.ts`), but only the overlay can start the backend, and it never restarts it | code | B-04 |
