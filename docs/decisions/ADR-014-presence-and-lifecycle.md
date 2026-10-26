# ADR-014: Swift adapts to how people actually use it: presence, idle time, interruptions, resuming

- **Status:** Accepted (owner, 2026-10-27: approved as proposed, with the proposed answers in §9). L1 first.
- **Decided by:** Owner
- **Date:** 2026-10-27
- **Builds on:** ADR-007 (follow-up context), ADR-009 (overlay UX), ADR-010 (confirm cards), ADR-012 (desktop), ADR-013 (presenter, threads, several requests); threat model T7 (no action while locked)

## 1. Context

The owner's principle (2026-10-27): **Swift adapts to the user, not the user to Swift.**
- People use an assistant in bursts. They leave it for hours, get interrupted mid-task, change their minds, switch between hands-free and the hotkey, and come back later wanting to carry on.
- Swift should handle what happens before, during, between and after interactions. It should be reliable, unobtrusive, context-aware and resource-efficient, with no friction or surprises.

Today Swift assumes **continuous, attentive use**. The owner's own logs show the gaps:

| Seen | What it shows |
|---|---|
| "spare claude exited while idle; starting cold" (00:43 on 27 Oct) | After idle time, the first request pays the 5–13 s start-up again, without warning. |
| A corrected calendar card timed out unanswered (19:14–19:16 on 26 Oct) | A card left alone is silently abandoned after 120 s: the task is lost, not paused. |
| Wake listening stopped after sleep (22:54 onwards) | Swift didn't know the machine had slept. It found out only when audio stopped. |
| "hey Swift" stopped responding after a while unused | No way to see whether listening is healthy, from the tray or from the logs (counters added 2026-10-27). |

More gaps, from the code:

| Area | Today |
|---|---|
| Locked screen | Wake listening keeps going while the PC is locked (README: "does not yet pause"). T7 says nothing may run then. |
| Interrupted tasks | Esc, "stop", a timeout or a crash end a task for good. Drafts and context are dropped when the run ends. Nothing can be resumed later. |
| Changing your mind mid-task | Only "show me", "stop" and card answers work mid-run. "Actually, make it about the deadline instead" has nowhere to go. |
| Being busy elsewhere | No idea of a call, a meeting or a "leave me alone" hour: hands-free listening and notifications behave the same at all times. |
| Resources | The speech model (~720 MB) and a warm Claude Code (~300 MB) stay loaded for hours of idle time. The warm Claude Code still exits on its own. |
| Follow-up | A fixed 8-second window. Coming back after 10 minutes to say "and change the time" starts from scratch. |

## 2. Decision in short

1. **Presence:** Swift tracks whether the owner is here, idle, away or busy, from signals Windows already provides. Each state sets what listens, what waits, what stays loaded and what may interrupt.
2. **Nothing is lost by stepping away:** cards and tasks **pause** while the owner is away, instead of timing out. They're offered again on return ("1 card waiting: Meeting with Mr. Akande").
3. **Resumable conversations:** a thread that was stopped, interrupted or left unfinished is **parked** with its last draft and context. "Continue", "where were we" or "finish the email to Ada" picks it up, hours later.
4. **Changing your mind is part of the conversation:** mid-task "actually…" / "instead…" redirects the task, keeping what's useful.
5. **Quiet when it should be:** a call or meeting, a manual "be quiet for an hour", and quiet hours stop hands-free listening and interruptions. They resume by themselves.
6. **Resource-efficient between bursts:** heavy parts are released after long idle and warmed up again on the first sign the owner is back, before they speak.
7. **Visible health:** the tray shows whether Swift is listening, and why not. The log says which stage stopped.

## 3. Presence

### 3.1 States

| State | Means | Detected by (Windows, no new permissions) |
|---|---|---|
| **Here** | Using the PC, Swift used recently | Keyboard or mouse input (`GetLastInputInfo`); a Swift interaction in the last few minutes |
| **Idle** | Here, but nothing for a while | No input for `idle_min` (proposed 10 min) |
| **Away** | Not at the PC | Screen locked (`WTS_SESSION_LOCK`), asleep (`PBT_APMSUSPEND`), or no input for `away_min` (proposed 30 min) |
| **Busy** | Here, but shouldn't be disturbed | Another app using the microphone (Teams, Zoom, a call: Windows records microphone use per app), the owner's "be quiet for …", quiet hours |
| **Muted** | The owner turned hands-free off | "Stop listening", the tray, `mute` |

Returning is a signal too: unlock, resume from sleep, the first input after `away_min`. Swift reacts to it (§6) before the owner says anything.

### 3.2 What each state does

| | Here | Idle | Away | Busy | Muted |
|---|---|---|---|---|---|
| Wake phrase | on | on | **off** (T7) | **off** | off |
| Hotkey | on | on | on (unlocks first) | on | on |
| Follow-up window | on | — | — | — | — |
| A confirm card waiting | counts down | counts down (slower: §4) | **paused**, offered on return | paused while the call lasts | counts down |
| Running tasks | continue | continue | continue, but **no writing in apps** (ADR-012) and nothing external without the owner | continue quietly | continue |
| Notifications, digests | shown | shown | queued; one summary on return | queued | shown |
| Warm resources | kept | kept | released after a while (§6) | kept | kept |

## 4. Nothing is lost by stepping away

- **Confirm cards pause instead of expiring.** The countdown (ADR-009 §6) only runs while the owner is Here or Idle. On Away or Busy, the card is put aside: the provider waits, and the overlay shows nothing. On return: "You have 1 card waiting", with the card back where it was. After `hold_h` (proposed 12 h) a held card is dropped, the thread is parked (§5), and the task is reported as not done.
- **Why not keep the 120 s timeout:** it exists so a forgotten card doesn't block Swift. With several requests side by side (ADR-013 phase B), a held card no longer blocks anything else, and being away is the most common reason a card goes unanswered.
- **Running tasks keep going while away, within limits.** Reading and researching continue. Anything needing the owner (an approval, writing into an app) waits for them. External actions never happen while away, as today.

## 5. Resumable conversations

- **Parking.** A thread is parked, not discarded, when:
  - it's stopped ("stop", Esc);
  - a card is held past `hold_h`;
  - the owner starts something unrelated in the middle of it;
  - Swift restarts.

  A parked thread keeps its last request, the last proposed artifact (the draft or event), the provider's summary of where it got to, and when.
- **Resuming.** "Continue", "where were we", "go on", "finish the email to Ada", "what was I doing?". The rules match "continue / where were we" locally; naming a task matches parked threads by their titles (as ADR-013 §5.3). The resumed run gets the parked context, and the overlay continues the thread's card (ADR-013 §4.2).
- **Seen on return:** the next time Swift appears, a one-line chip offers what's open ("Resume: Email to Ada"), like the unread-digest hint (ADR-011 §13.4). Never more than one line. "Not now" or a few uses ignored and it goes away.
- **Kept for** `resume_h` (proposed 24 h), locally. "Forget that" drops one. Nothing about it leaves the machine.

## 6. Efficient between bursts, ready on return

| When | What happens |
|---|---|
| Idle for 30 min | Nothing visible. The warm Claude Code is replaced if it exited, so the next request isn't slow (fixing "exited while idle; starting cold"). |
| Away for 30 min | Release the speech model's memory (~720 MB) and the warm Claude Code (~300 MB). Wake listening is already off. |
| Return (unlock, resume, first input) | Warm up in the background: microphone, speech model, Claude Code. They're ready in the ~5–20 s before most people speak. The microphone is reopened on resume rather than waiting for the watchdog. |
| Low battery or battery saver | Warm Claude Code off, speech model kept. |

## 7. Changing your mind, and switching modes

- **Mid-task redirects.** During a run, "actually…", "instead…", "no, I meant…", "change it to…" (a short grammar, like ADR-010 §6):
  - **Before anything external happened:** the provider gets "the owner changed their mind: …". Claude Code takes it as a new turn in the same session; others get cancel plus a restart with the context, as ADR-008's change rule already does for cards.
  - **After something irreversible** (a sent email): Swift says so plainly and offers the follow-up action ("I can send a correction").
  - Hands-free, a redirect needs Swift's name first, like changes on cards.
- **Interruptions.** An unrelated request mid-task parks the first thread (§5) or runs beside it (ADR-013 phase B). It's never silently dropped.
- **Modes:**
  - "Stop listening for an hour" / "be quiet until 3" sets Muted or Busy with an end time.
  - "Start listening" ends it, and the hotkey always works.
  - Quiet hours (`quiet: "22:00-07:00"`) are optional.
  - A call or meeting (another app using the microphone) sets Busy automatically, and Swift releases the open microphone so it never competes with the call. Listening comes back when the call ends.

## 8. Visible health

- **Tray tooltip and icon** say the state in plain words: "Listening for 'hey Swift'", "Paused: screen locked", "Paused: you're in a call", "Muted until 15:00", "Microphone unavailable".
- **Log:** every presence change, and the 5-minute `wake listening` counters (added 2026-10-27).
- **The owner-check report** (`spikes/owner_checks/report.py`) shows presence changes alongside requests.

## 9. Owner's decisions (2026-10-27: the proposed answers, approved)

1. **Direction:** presence states, cards that pause instead of expiring, resumable conversations, mid-task redirects, automatic quiet, and resources released and re-warmed. Is this the behaviour you want?
2. **Away and locked:** hands-free off while locked or away (T7), and the hotkey still works after unlocking?
3. **Held cards and parked threads:** hold cards up to 12 h and keep parked conversations 24 h?
4. **Calls and meetings:** automatically quiet while another app uses the microphone?
5. **Resources:** release the speech model and the warm Claude Code after 30 min away, and re-warm on return?
6. **Order:**
   - **L1:** presence detection, lock and sleep handling, re-warm on return, tray status;
   - **L2:** held cards and resumable conversations;
   - **L3:** quiet modes and call detection;
   - mid-task redirects together with ADR-013 phase B.

   Each phase has the same kind of sequence tests and owner checks as ADR-013.
