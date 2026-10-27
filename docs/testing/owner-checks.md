# Owner checks: the overlay, conversations, corrections, stepping away, several requests, the calendar, emails written as you (ADR-012, ADR-013, ADR-014, ADR-011 §13 #5)

About 45 minutes, in your real Swift with your real microphone. Run them in order.

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
| 2b | "Hey Swift, what day will it be one week from today?", then within 8 s: "and the date?" | The date **a week from today**, not today's (failed on 2026-10-27). Then "what time is it in Tokyo?" and "and the date there?" gives Tokyo's date | (seen on screen) |
| 3 | Within 8 s again: "what day is it tomorrow?" | A third answer; the two before it as dim lines (at most two) | Three requests in one thread |
| 4 | "Hey Swift, set up a meeting with Test Me on Thursday at three" | **No** "I have a workflow for that"; it goes straight to a calendar card for Thursday 15:00. The working card says "Working on it" / "Thinking", never "Claude Code is…" | The calendar workflow ran directly |
| 5 | On that card, hold the hotkey and say "make it Friday at three instead" | "Changing it: …" on the working card, then a **new card** for Friday 15:00. Click **Reject**. | A change on the card (revise), then a rejection |
| 6 | Hands-free: "hey Swift, set up a meeting with Test Me on Monday at ten". On the card, say just "approve" | A hint: say "Swift, approve". The card stays. | (seen on screen only) |
| 7 | On the same card, say "no" | "Not approved", then "Listening for a reply…" | A rejection by voice |
| 8 | Within 8 s: "make it Tuesday at ten instead" | A **new card** for Tuesday 10:00, with "Not approved: …" above it. It **stays** until you answer. Say "Swift, approve". | A correction in the same thread, answered; **no timed-out card** |
| 9 | Check Google Calendar | Exactly one new event: Tuesday 10:00. Nothing for Thursday, Friday or Monday. Delete it afterwards. | (Google Calendar) |
| 10 | Hold the hotkey: "research the history of tea into Word", with Word open. While it writes, say "show me" briskly, **without** "hey Swift". Then say "stop" | "show me" brings Word to the front with "Here it is in Word." on the card (before the writing starts, it opens the steps instead). "stop" stops the run, "Cancelled" briefly, and nothing stays stuck on screen. (Failed on 2026-10-27 at 12:50 and again at 17:00: every short clip was dropped. Brisk clips are now taken as they sounded, "so me" as "show me".) Optional: start another research run and say "pause": "Paused. Say “go on” to pick it up."; then "go on" picks it up | A mid-run "show me" and "stop"; "show me" brought the app forward; how many short clips were kept, heard as close, or empty |
| 11 | Put the laptop to sleep for a minute, or plug headphones in or out. Then, without the hotkey: "hey Swift, what time is it" | It answers. If it doesn't within a few seconds, wait 5 s and try once more, then note the time. | A wake request after the pause; microphone reopen events, if any |
| 12 | Lock the screen (Win + L). Hover the tray icon? You can't while locked, so: wait 10 s, unlock, then hover Swift's tray icon right away | While locked, Windows' microphone indicator goes off. After unlocking, the tooltip says "listening for 'hey Swift'" within a few seconds. | Presence: away (locked), then here (unlocked); microphone paused, then reopened |
| 13 | Right after unlocking, without the hotkey: "hey Swift, what time is it" | It answers within about a second, with no long first-time delay. (On 2026-10-27 it took 7–10 s.) | Unlock to listening again (microphone open and speech model ready, "listening again ms=") under 2 s (4.7 s at 17:29 on 2026-10-27: the device list was refreshed first; now only if the microphone won't open); the first wake after unlocking transcribed in under 3 s, and how long after the unlock you finished saying it; no "microphone paused" while you were back |
| 14 | Hold the hotkey: "set up a meeting with Test Me on Friday at four". When the card appears, lock the screen (Win + L) and wait **3 minutes** (longer than the card's 2-minute countdown). Unlock | The card is back **on screen, in front of other windows**, with "1 card waiting, since …" at the top and a fresh countdown. Click **Reject**. (Failed on 2026-10-27: no card; fixed since.) | A card held while away, answered after |
| 15 | **The waiting stack** (ADR-015 §9). Hold the hotkey: "add a calendar event for lunch with Test Me on Friday at noon". While it works, press Esc. Then hold the hotkey: "draft an email to Test Me about lunch", and press Esc again | A **stack of cards in a bottom corner**, compressed: "2 cards need you" and the newest title, **in your own words** (never "[Swift workflow: …"). It glows briefly when a card joins. **Double-click** it: it expands upwards with both, each with **Resume**, **Skip** and **×**. Click **Skip** on the top one: it moves to the bottom. Click **×** on the email one: it's gone. Click anywhere outside the stack: it folds back up | Two stopped requests parked; one skipped, one ended from the stack |
| 16 | Double-click the stack and click **Resume** on the lunch one (or click the card itself). Then hold the hotkey: "set up a meeting with Test Me on Saturday at ten" and, on its card, click **Later** | Lunch picks up on the main card where it stopped (the stack folds up); Reject its card. The Saturday card goes into the stack ("Put off for later"), off screen, and doesn't count down. Open it from the stack: it's back with its time. Click **Reject**. Saying "continue" still works as a shortcut | A conversation resumed from the stack; a card put off and answered |
| 16b | **Typing** (ADR-015 §10). Press **Ctrl+Alt+Space** (or tray → **Type to Swift…**). Type "what time is it", Enter. Within a few seconds, open it again: it says "Following up: …"; type "and the date?", Enter. Then hold the hotkey: "set up a meeting with Test Me on Sunday at ten"; on its card, type "approve", Enter | A text box where the cards appear, with the cursor in it, and Esc closes it (keeping what you typed). The time, then the date **on the same card** (one thread). On the meeting card: "Typing can't approve. Click Approve, or say “Swift, approve”." The card stays. Type "reject": it's rejected | A typed request; a typed follow-up in the same thread; typing didn't approve |

### Windows for each request, cards that wait their turn (ADR-015)

Swift now uses more of the screen: each other request gets a small window of its own, a long answer can open in a larger reader, and you can drag any of them anywhere. Nothing stays big for long. A card only counts down while it's on screen and you're there.

| # | Do | You should see | Report checks |
|---|---|---|---|
| 17 | Hold the hotkey: "research the history of tea and summarise it in detail". While it works: "hey Swift, what time is it" | The time on the main card. The research is **a small window of its own** (a chip with its title, what it's doing and the time so far), away from the card, not a line squeezed under it. **No chip is left behind for "what time is it"** once its answer shows (failed on 2026-10-27: "What time is it? Working on it 2:44", still counting). | Two requests running at the same time |
| 18 | Let the time answer fade. Wait for the research to finish | The research comes back to the main card **by itself**. When it finishes, the answer **scrolls** inside the card (nothing cut off at the bottom). Click **Read all**: a larger reader window opens with the whole answer. Scroll it to the end. | (seen on screen) |
| 19 | Leave the reader alone for a minute, without the mouse on it. Then click it | It shrinks to a small chip ("… · Open"). Clicking the chip opens it again. Drag the reader somewhere else by its top and let go: it **stays where you dropped it** (failed on 2026-10-27: it vanished on release). Drag a request chip too. Then close the reader with **×**. | (seen on screen) |
| 20 | Hold the hotkey: "research green tea", then **right after you let go**, "hey Swift, what time is it" (on 2026-10-27 it was dropped while the first was transcribed). Drag the research chip to another corner. When both are done, do the same again | The second time, the research chip appears **where you dragged it** the first time. Clicking a chip brings that request to the main card. | (seen on screen) |
| 21 | Hold the hotkey: "set up a meeting with Test Me on Friday at four", and **right away, before its card shows**: "hey Swift, add lunch with Test Me on Friday at noon". Wait about a minute without answering, then click **Reject** | One card on screen with "1 more card waiting"; the other stays out of sight and **doesn't count down**. The moment you say the second one, the main card says **"Got it: “add lunch with Test Me on Friday at noon”"** (failed on 2026-10-27: nothing showed it). The waiting card is also in the stack. After Reject, the second card **comes forward by itself** with its full two minutes (it never vanishes unfinished). Click **Reject**. | A card waited behind another, then answered; no card timed out while waiting |
| 22 | Hold the hotkey: "set up a meeting with Test Me on Saturday at ten". When the card shows, lock the screen (Win + L) for 3 minutes. Unlock and don't touch anything | The card **comes back by itself**, in front, with "1 card waiting, since …" and at least a minute left. Click **Reject**. | A held card redrawn on return, then answered |
| 23 | Hold the hotkey: "research the history of coffee and summarise it". Don't touch the card | After about 30 s without news, the working card **shrinks to one line**. Move the mouse over it: it opens again. Press Esc. | (seen on screen) |
| 24 | Start a research request, then "hey Swift, what time is it". Say "show me the research one", then "stop the research one" | The research comes to the main card; then it ends ("Stopped …") and nothing else stops. If the research finished before you said "stop", Swift says it had already finished and does nothing else (on 2026-10-27 it went to Claude Code, which offered to delete a calendar event) | A request brought forward and stopped by name |
| 25 | Start three long requests one after another ("research …"), then a fourth | One on the main card and **two chips**; each request says "Got it: …" as you say it, and the fourth gets a chip of its own at once ("Waiting to start"), so there's no need to say it again. It starts when one finishes | The fourth waited for a slot |

### Answering Swift's questions, and model errors (owner checks of 2026-10-27, fixed)

| # | Do | You should see | Report checks |
|---|---|---|---|
| 26 | "Hey Swift, add lunch with Test Me to my calendar" (no day or time) | Swift asks which day and time, with "Listening for your answer… 25 s" under it, and the card **stays** for those 25 s, even if another request ran beside it. Move the mouse over the card and away again: it still stays. Say nothing for 30 s: the question goes into the waiting stack ("Swift asked you something"). (Failed on 2026-10-27: the card went after about 7 s.) | The question listened at least 20 s ("question window"), then was parked unanswered |
| 27 | A minute later: **Resume** it from the stack, or with the hotkey: "Friday at one" (or "continue") | It goes on with lunch, on the same card, and shows the calendar card. Click **Reject**. | The question picked up later |
| 28 | Only if Claude Code ever says it couldn't confirm its model | One card: "Claude Code couldn't reach its models; check your connection or sign-in", after Swift tried once more with the default model | Retries with the default model, if any |
### Your calendar: look, change, cancel, Meet links, undo (2026-10-27)

About 10 minutes. Uses your real Google Calendar: every change waits for a card, and you clean up with Swift itself. Before check 29, add one event yourself in Google Calendar: "Swift check", tomorrow 11:00–11:30.

| # | Do | You should see | Report checks |
|---|---|---|---|
| 29 | "Hey Swift, what's on my calendar tomorrow?" | **No card.** A table "Your calendar: <tomorrow>" with "Swift check" at 11:00, and a one-sentence answer. Not "I can't read your calendar". | The calendar workflow ran on a question |
| 30 | "Hey Swift, when is my next meeting?" | The next event in the coming week, by name and time | The calendar workflow ran |
| 31 | Hold the hotkey: "move Swift check to 2 pm" | Within about 15 s (the calendar workflow, on the light model; on 2026-10-27 it went to the general agent), a card "Change in your calendar: Swift check" with "When: … 11:00–11:30 → … 14:00–14:30". **Approve.** If it was heard as "swift deck", the card still names Swift check. | An approved update; calendar changes ran the calendar workflow on the light model |
| 32 | Hold the hotkey: "add a Google Meet link to Swift check" | A card listing "Adds a Google Meet link". Approve. In Google Calendar the event now has a Meet link. | An approved update |
| 33 | Hold the hotkey: "set up a meeting with Test Me on Thursday at three with a Meet link" | A card "Add to your calendar: …" whose line ends "invites Test Me (Google emails them) · with a Google Meet link". **Approve.** | An approved add |
| 34 | Right away: "hey Swift, undo that" | A new card "Undo: remove from your calendar: …" for the Thursday meeting. Approve. It's gone from Google Calendar, and Test Me gets a cancellation. | An undo, approved |
| 35 | Hold the hotkey: "change Swift check to 3 pm", **approve**, then hold the hotkey: "I didn't approve that" | A card "Undo: change back: Swift check" with "When: … 15:00 → … 14:00". Approve; it's back at 14:00. | An undo of an update |
| 36 | Hold the hotkey: "cancel Swift check" | Within about 15 s (on 2026-10-27 it took over two minutes), a card "Remove from your calendar: Swift check". Click **Reject** first: it's still there. Then ask again and **approve**: it's gone. Plain "cancel" while something runs still stops it. | A rejected and an approved removal |
| 37 | "Hey Swift, email Test Me that the meeting is off", approve, then "hey Swift, undo that" | "…can't be undone (a sent email can't be unsent)", and **no** card that removes a calendar event instead | An undo refused for an email |

If Swift says the calendar "isn't allowed yet" or the sign-in "has expired", sign in again yourself (`uv run --group spikes python -m swift.connectors.gmail signin`).

### Changing your mind (ADR-014 §7; moved here from checks 22–24)

| # | Do | You should see | Report checks |
|---|---|---|---|
| 38 | Hold the hotkey: "write a short paragraph about lunch". While it works, hold the hotkey: "actually, make it about dinner instead" | "Changing course: actually, make it about dinner…" on the card; the answer is about dinner, on the **same card** | A change of mind passed on (same session for Claude Code) |
| 39 | Hands-free during a run: "hey Swift, write a haiku about rain", then, **without** "Swift": "actually make it about snow" | A hint: say "Swift, actually …". Then say "Swift, actually make it about snow" and it changes course | A hands-free change of mind needed the name |
| 40 | "Hey Swift, email Test Me that I'm running late". Approve the card. While it finishes, say "Swift, actually say I'm not coming" | "The email was already sent, so I can't take it back. Say “yes” and I'll send a correction." Say "Swift, yes" and **Reject** the new card | Told it was already sent; the correction offered |

### Emails written as you, and people you've emailed (owner checks of 2026-10-27, fixed)

About 5 minutes. **Sign in to Google again first**, yourself: Swift now asks for two more read-only permissions, "other contacts" (the people you've emailed) and your basic profile (your name, to sign emails). Run `uv run --group spikes python -m swift.connectors.gmail signin`; each permission should print `granted`. Until you do, Swift still finds your saved contacts, but not people you've only emailed, and signs with `owner_name` from `config.yaml` if you set it.

| # | Do | You should see | Report checks |
|---|---|---|---|
| 41 | "Hey Swift, email Test Me that the meeting is off" | Gmail's compose window with a **short subject** (e.g. "Meeting cancelled", never the whole message) and a body that starts "Hello …," says it in plain words as you, and ends "Regards," and **your name** (from your Google account, or `owner_name`). Close it without sending. | A draft greeted and signed with your name |
| 42 | "Hey Swift, email Janet saying I'll send the chapter tomorrow" (someone you've emailed but never saved as a contact) | Swift finds her: the recipient card shows her email address. If several match, each line shows the email and a second detail (her organization, or "you've emailed them"), and Swift asks which one. Close the draft without sending. | A contact found from Gmail correspondence |
| 49 | "Hey Swift, email Test Me that I'm running late". When the compose window shows, close it, then in the reply window: "actually say that I am not coming". Then: "can you send it for me?" | The compose window again with the **same short subject** ("Running late") and a body "Hello …, … not coming … Regards, <your name>". Then a send card whose subject is still "Running late": **Reject**. Also "email myself", then "the email should ask me how I'm doing today": the question is in the body, never the subject. | An email's follow-ups stayed in the email workflow |

### Hearing you (owner checks of 2026-10-27 17:00, fixed)

About 10 minutes. Speak at your **normal** volume, from where you usually sit; don't shout. Have a TV, video or music playing at a normal level for checks 45 and 46.

| # | Do | You should see | Report checks |
|---|---|---|---|
| 43 | "Hey Swift, research the history of tea and summarise it in detail", at normal volume | A soft two-note chime and a small "Listening…" pill **while you are still saying the request**, before any card. (To turn the chime off: `audio: chime: false`.) | Wake phrases seen early (`peek_wake`) |
| 44 | Hold the hotkey and say "what time is it" | The chime and "Listening" as the key goes down | (heard; seen on screen) |
| 45 | "Hey Swift, what time is it". In the 8 s after the answer, say nothing; let the TV talk | Nothing happens: the TV is **not** taken as a reply | Replies set aside as the room (`followup_quiet`) |
| 46 | "Hey Swift, what time is it", then within 8 s: "and the date?" at normal volume, TV still on | The date. If Swift wasn't sure what you said: "I didn't catch that. Try saying it again." instead of a wrong action | A reply taken; any "try saying it again" |
| 47 | Hold the hotkey: "set up a meeting with Test Me on Friday at four". Let go and **at once** hold it again: "what time is it" | "Got it. Listening for the next one…", then both: the time, and the calendar card. Nothing dropped. Reject the card | A request recorded while the last one started (`queued_behind`) |
| 48 | Start "hey Swift, research the history of coffee". While it works, say a brisk "show me", then a brisk "stop" | "show me" opens it, "stop" stops it | Short clips kept (or heard as close) during a run |

## After the checks: the report

From the repository root, with the time you noted in step 3 of "Before you start":

```powershell
uv run python spikes/owner_checks/report.py --since 20:00
```

It reads your local Swift logs, prints what happened request by request, and marks each check `PASS` or `NOT SEEN`. It only reads, and it prints only to your terminal. Paste its output into the chat. It includes your request transcripts, which are your own data, so skim them first if you like.

## If something goes wrong

Note the check number and the time. That's enough: the logs have the rest.
