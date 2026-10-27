# Owner checks: the overlay, conversations, corrections, stepping away, several requests (ADR-012, ADR-013, ADR-014)

About 25 minutes, in your real Swift with your real microphone. Run them in order.

- Each check says **what to do**, **what you should see**, and what the log report checks afterwards.
- Note anything that looks wrong and roughly when, e.g. "check 3 at 20:15".

## Before you start

1. In `config.yaml`:
   - `debug: false`
   - `wake: enabled: true`
   - `connectors: calendar: google`
   - a contact for yourself, as in the email check before.
2. Restart Swift: Tray → Quit Swift, then in `overlay`:

   ```powershell
   npm run tauri dev
   ```

3. Wait for "Swift is ready". Note the time; the report uses it.

## The checks

| # | Do | You should see | Report checks |
|---|---|---|---|
| 1 | Say "hey Swift, what time is it" | An answer, then "Listening for a reply… 8 s" under it | A wake request; how many wake phrases the model was unsure of but still took (`unsure_wake`) |
| 2 | Within 8 s, without "hey Swift": "and what's the date?" | The date answer on the **same card**, with the time answer as a dim line above it | Same thread as check 1 |
| 3 | Within 8 s again: "what day is it tomorrow?" | A third answer; the two before it as dim lines (at most two) | Three requests in one thread |
| 4 | "Hey Swift, set up a meeting with Test Me on Thursday at three" | **No** "I have a workflow for that"; it goes straight to a calendar card for Thursday 15:00. The working card says "Working on it" / "Thinking", never "Claude Code is…" | The calendar workflow ran directly |
| 5 | On that card, hold the hotkey and say "make it Friday at three instead" | "Changing it: …" on the working card, then a **new card** for Friday 15:00. Click **Reject**. | A change on the card (revise), then a rejection |
| 6 | Hands-free: "hey Swift, set up a meeting with Test Me on Monday at ten". On the card, say just "approve" | A hint: say "Swift, approve". The card stays. | (seen on screen only) |
| 7 | On the same card, say "no" | "Not approved", then "Listening for a reply…" | A rejection by voice |
| 8 | Within 8 s: "make it Tuesday at ten instead" | A **new card** for Tuesday 10:00, with "Not approved: …" above it. It **stays** until you answer. Say "Swift, approve". | A correction in the same thread, answered; **no timed-out card** |
| 9 | Check Google Calendar | Exactly one new event: Tuesday 10:00. Nothing for Thursday, Friday or Monday. Delete it afterwards. | (Google Calendar) |
| 10 | Hold the hotkey: "research the history of tea into Word", with Word open. During the run, say "show me", then "stop" | The run stops, "Cancelled" briefly, and nothing stays stuck on screen | A mid-run "show me" and "stop" |
| 11 | Put the laptop to sleep for a minute, or plug headphones in or out. Then, without the hotkey: "hey Swift, what time is it" | It answers. If it doesn't within a few seconds, wait 5 s and try once more, then note the time. | A wake request after the pause; microphone reopen events, if any |
| 12 | Lock the screen (Win + L). Hover the tray icon? You can't while locked, so: wait 10 s, unlock, then hover Swift's tray icon right away | While locked, Windows' microphone indicator goes off. After unlocking, the tooltip says "listening for 'hey Swift'" within a few seconds. | Presence: away (locked), then here (unlocked); microphone paused, then reopened |
| 13 | Right after unlocking, without the hotkey: "hey Swift, what time is it" | It answers within about a second, with no long first-time delay | The first wake after unlocking transcribed in under 3 s; the warm Claude Code started after the speech model |
| 14 | Hold the hotkey: "set up a meeting with Test Me on Friday at four". When the card appears, lock the screen (Win + L) and wait **3 minutes** (longer than the card's 2-minute countdown). Unlock | The card is back **on screen, in front of other windows**, with "1 card waiting, since …" at the top and a fresh countdown. Click **Reject**. (Failed on 2026-10-27: no card; fixed since.) | A card held while away, answered after |
| 15 | Hold the hotkey: "add a calendar event for lunch with Test Me on Friday at noon". While it works, press Esc. Then hold the hotkey: "draft an email to Test Me about lunch", and press Esc again. Wait a minute, then hold the hotkey: "what time is it" | The time, with one more line, "Unfinished: …", in **your own words** (never "[Swift workflow: …"). Note which one it names. | A stopped request parked; the line offered |
| 16 | Within 8 s (or with the hotkey): "continue" | It picks up **the one the line named**, on the same card as before, even if another was stopped after it. Click **Reject**. | A parked request resumed: the one the line showed |

### Several requests at once, and changing your mind (ADR-013 phase B, ADR-014 §7)

| # | Do | You should see | Report checks |
|---|---|---|---|
| 17 | Hold the hotkey: "research the history of tea and summarise it". While it works: "hey Swift, what time is it" | The time on the card; under it **one line** for the research ("research the history of…", what it's doing, elapsed time). Nothing on the card jumps or flickers. | Two requests running at the same time |
| 18 | Let the time answer fade | The research card comes back by itself, with its steps | (seen on screen) |
| 19 | While the research still runs: "hey Swift, set up a meeting with Test Me on Friday at four". Then "hey Swift, what's the date" | The calendar card on screen; the date answer **does not cover it** (it's a line under it, or waits). | The calendar card was answered, never timed out |
| 20 | Click **Reject** on the calendar card. Then say "show me the research one" | The research card in front again | A request brought forward by name |
| 21 | Say "stop the research one" | The research row/card ends ("Stopped …"); nothing else stops | A request stopped by name |
| 22 | Hold the hotkey: "write a short paragraph about lunch". While it works, hold the hotkey: "actually, make it about dinner instead" | "Changing course: actually, make it about dinner…" on the card; the answer is about dinner, on the **same card** | A change of mind passed on (same session for Claude Code) |
| 23 | Hands-free during a run: "hey Swift, write a haiku about rain", then, **without** "Swift": "actually make it about snow" | A hint: say "Swift, actually …". Then say "Swift, actually make it about snow" and it changes course | A hands-free change of mind needed the name |
| 24 | "Hey Swift, email Test Me that I'm running late". Approve the card. While it finishes, say "Swift, actually say I'm not coming" | "The email was already sent, so I can't take it back. Say “yes” and I'll send a correction." Say "Swift, yes" and **Reject** the new card | Told it was already sent; the correction offered |
| 25 | Start three long requests one after another ("research …"), then a fourth | Three run (one card, two lines); the card says the fourth is waiting, and it starts when one finishes | The fourth waited for a slot |

### Answering Swift's questions, and model errors (owner checks of 2026-10-27, fixed)

| # | Do | You should see | Report checks |
|---|---|---|---|
| 26 | "Hey Swift, add lunch with Test Me to my calendar" (no day or time) | Swift asks which day and time, with "Listening for your answer… 25 s" under it. Say nothing for 30 s. | A question parked unanswered |
| 27 | A minute later, with the hotkey: "Friday at one" (or "continue") | It goes on with lunch, on the same card, and shows the calendar card. Click **Reject**. | The question picked up later |
| 28 | Only if Claude Code ever says it couldn't confirm its model | One card: "Claude Code couldn't reach its models; check your connection or sign-in", after Swift tried once more with the default model | Retries with the default model, if any |

## After the checks: the report

From the repository root, with the time you noted in step 3 of "Before you start":

```powershell
uv run python spikes/owner_checks/report.py --since 20:00
```

It reads your local Swift logs, prints what happened request by request, and marks each check `PASS` or `NOT SEEN`. It only reads, and it prints only to your terminal. Paste its output into the chat. It includes your request transcripts, which are your own data, so skim them first if you like.

## If something goes wrong

Note the check number and the time. That's enough: the logs have the rest.
