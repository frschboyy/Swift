# Why voice, requests and cards still fight: owner checks 191–197 (2026-11-08)

The owner ran checks 191–199 on `main` at `e3cfdad` and asked whether the failures are separate bugs or one problem, and for the architecture rather than more isolated fixes. This answers from tonight's evidence: `swift.log` and `interactions.jsonl` from 01:35 to 02:07, and **all 33 saved recordings replayed through the speech model**. Each finding says whether it is proven.

## In short

Most of it is one problem. **Swift has no single owner of the conversation's state.** Three things each decide on their own what speech means and what is in front:

- the open microphone, whose meaning depends on the mode it finds itself in (at rest, a run in front, a question waiting, a capture going, Swift talking);
- the request launcher, which gives the front to whatever started last;
- the overlay's presenter, which only shows an answer whose request is still in front.

Each is consistent by itself, and they disagree at the edges. Tonight, the edges were where the owner spent most of the session: saying "Hey Swift" while something else was going on.

## 1. What happened, finding by finding

| Check | What the owner saw | Cause | Evidence | Proven? |
|---|---|---|---|---|
| 191 | 5 of 9, then 8 of 10, "Hey Swift"s registered | The wake phrase is found by transcribing everything and matching the text. Tonight's misses were written as "Hate Swift.", "Take rift.", "He flipped.", "Please lift.", "He proved". No text rule can recover those without matching ordinary speech | The 7 saved misses, replayed | **Yes** |
| 191 | The TV started a request | The TV said something the model wrote as "Hey Swift Box has some great." A text match can't tell a voice on TV from the owner's | The 01:38:34 recording | **Yes** |
| 196 | "Hey Swift" did nothing; the card stayed on "Research the history of T" | Swift had asked "your request cut off, what did you mean?" and was listening for the answer. A bare "Hey Swift" was taken **as the answer**: empty, so it asked again, then shelved the question | 02:01:52 `turn='reask'`, 02:01:56 `turn='shelve'` | **Yes** |
| 197, 196 | "Research the history of T" | Not a cut-off: the speech model writes "tea" as the letter "T". The whole saved recording says "T", followed by silence | 4 recordings | **Yes** |
| 194 | The first request's card left before it could be read | Saying "Hey Swift" during a request starts a new one that **takes the front**. The first one's answer then arrives behind, and the overlay deliberately doesn't show an answer that isn't in front: it only becomes a "Ready to read" edge | `_launch` gives a new request the front; `presenter.onAnswer` refuses an answer not in front; at 01:41:42 the second request's "I didn't catch that" was in front 0.8 s before the tea answer came | **Likely, not proven on screen**: the overlay doesn't log what it draws |
| 195 | "I only manage calendar events here" | "Delete the word test from a file" matched the **calendar** workflow because it says "delete". The run was given calendar tools only, on the small model, and had no way to hand the request on | `workflow='calendar-event'`, `demand='light'`, `claude-haiku` | **Yes** |
| 197 | A long and a short version of the same request ran separately | Duplicates are matched on exact words only. "…in great detail, include sources" was stopped at 02:01:14; "Research the History of T" came 18 s later | The records | **Yes**, and partly by design (below) |
| 193 | No source given for the weather | The weather tool returns data with no source, and nothing asks for one to be shown | The tool | **Yes** |
| 193 | An ellipsis in the answer | **Unproven.** Step lines in the working card and live view are cut with "…" (`_short`), and the answer itself isn't kept in the logs. A screenshot would settle it | — | **No** |

**Not the cause:** Swift's "Hello" never shows up in any recording, so it isn't hurting recognition. The recordings after a bare "Hey Swift" transcribe well, at 0.8 to 0.9 average confidence. Lower figures in the log are the least sure word, not the whole.

## 2. The owner's questions, answered

**Does wake-word detection behave differently when a card is visible?** Detecting the phrase is the same: the microphone is always transcribing. **What Swift does with it** depends on the state, and that's where it differs:

| State | A bare "Hey Swift" | Proven tonight |
|---|---|---|
| At rest | Starts a request | — |
| A request in front, working or on a card | Starts a new one, which takes the front | 194 |
| Swift's question waiting for an answer | **Taken as the answer** | 196 |
| A capture recording | Ignored: those are that request's words | — |
| Swift talking | Ignored, unless it's a short "no" or "stop" | — |
| Transcribing something else | Waits, and only the latest waiting one is kept | — |

**Does a card disappearing, a failed transcription or an incomplete request affect the listener?** No evidence of that. After every failure tonight, the next "Hey Swift" was transcribed normally. What changed was the state it landed in.

**Is the listener continuously active?** Yes. It hears everything above the room's level, except while the screen is locked or listening is paused. It drops utterances under 0.4 s and over 10 s.

**Could TV audio interfere?** Yes, both ways: it started one request tonight, and while the TV speech is being transcribed, a real "Hey Swift" waits behind it.

## 3. The architecture: one owner for the conversation

These are the changes that address the causes rather than the cases. They're in the order I'd do them, each a step of its own.

### 3.1 A turn manager: one place decides what speech means (fixes 194, 196, and most of 5)

A small module (not more `session.py`) owns one explicit state: **at rest · capturing · a run in front · Swift asking · Swift talking**, with each transition named and logged (content-free). Every way speech comes in (the open microphone, the hotkey, typing) asks it what the words mean. The rules it enforces:

1. **Swift's name always opens a new turn,** in every state. A bare "Hey Swift" is never an answer. "Swift, Tuesday" still answers, because it has words.
2. **A new turn doesn't take the front from something the owner is reading or answering.** It lands as an edge ("Got it: …") and comes forward when the one in front is done or dismissed. This is the Deck's own rule (ADR-018), applied to voice.
3. **An answer finishing behind stays as an edge until it's read.** It doesn't fade while out of sight.
4. **The overlay logs each card's arrival and why it left** (faded, replaced, dismissed, went behind), content-free, so the next "it disappeared" can be proven rather than inferred. This should come first, since 194 is unproven.

The test for "one owner": a seam scenario (`test_seam_replay.py`) replays tonight's 01:41 sequence (a request working, "Hey Swift", an unclear capture, the first answer arriving) and fails if the first answer is ever off screen without an edge.

### 3.2 A dedicated wake detector (fixes 191)

The evidence is now enough to decide. Text matching tops out around 5–8 in 10 for this voice and room, and nothing can learn "Hate Swift." without also matching ordinary speech. As in Apple's design ([Hey Siri](https://machinelearning.apple.com/research/hey-siri)):

- **Stage 1:** a small keyword-spotting model listening to sounds, not words, cheap enough to run on every 10–20 ms frame. Candidate: [sherpa-onnx keyword spotting](https://huggingface.co/openEuler/sherpa-kws), which appears to take a new phrase without retraining (unverified).
- **Stage 2:** the speech model Swift already has, run only on what stage 1 flagged, as a check.
- **The owner's voice:** comparing against a few samples of the owner saying "Hey Swift" (on the PC, never sent anywhere) would turn away the TV.

This needs a new dependency and a model download, so it's the owner's decision. A spike would score it on the 74 saved wake clips and the misses before any wiring.

### 3.3 Requests know what they are (fixes 197 and 195)

- **Same, similar or new:** exact words stay the automatic rule. When a new request is **close** to one running or just stopped (same verb and subject, different detail), Swift doesn't guess either way: the new one runs, and the edge says "Like the one you stopped: carry on with that instead?" with a click. Merging requests silently is how the owner's real second requests would get lost.
- **Workflows are hints, not walls:** a workflow that can't do what was asked hands the request back to the general agent instead of answering "I can't". The match on "delete" should also need the workflow's own subject (an event, a meeting) in the words.
- **Misheard words:** "of T" to "of tea" is one more case for the learned word fixes (`stt_corpus`), not a rule in code.

### 3.4 Answers show where they came from (fixes 193)

Every tool that reads the outside world returns its source (a name and an address). Swift, not the agent, draws them as the **Sources** block from the Halo spec, with links. The web tools already track every address a run was given (`web_scope.py`), so this is mostly plumbing. Long research answers then use Halo's expanded card: headings, the source list and a "Read more", rather than one long paragraph.

### 3.5 Flexibility (fixes 195's tone)

The agent's instructions should say: when a tool can't do something, find another way or say what you can do instead, and never answer by naming a tool's limits. That is a prompt change, and it only helps once 3.3 stops sending general requests to narrow workflows.

## 4. What this doesn't cover

- The ellipsis in 193 needs a screenshot.
- 194 is the likeliest explanation, but it rests on the code and the timeline; 3.1's logging comes first so it can be proven.
- Nothing here has been built. This is the investigation the owner asked for, before any change.
