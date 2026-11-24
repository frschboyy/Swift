# "Hey Swift" missed at 22:15 and 22:25 on 2026-11-18 (owner item 1)

Diagnosed 2026-11-24 on `claude/listening-feedback-3bb7ab`, from the owner's `swift.log` and saved clips. The
owner thought the microphone wasn't hearing him. **It was.** The mic was open and its levels were normal. Each
phrase was lost after Swift heard it, in one of two ways.

## 22:25:05–22:26:42: the speech check turned the name down (proven for the rejection)

- Six detector misses were kept (`recordings: missed wake phrase kept | source='detector'`) at 22:25:05, :11, :16, :22,
  :40 and 22:26:42, about 6 s apart. Each clip is 1.7–2.8 s long: the length of a bare "Hey Swift". The next try
  (22:26:47) woke Swift.
- **Levels:** the loudest 32 ms of each clip is −10 to −16 dBFS, with peaks of −2 to −9 dBFS. That's the same as
  the four wakes that worked at 22:20–22:22 (−9.5 to −12 dBFS). The room floor was −59 to −73 dBFS. Nothing was
  clipped.
- **Stage 1 (acoustic):** replayed offline, the detector scores 0.68–0.96 on these clips (threshold 0.5). Live, each
  one was a hit, which is why the clip was kept (`session._second_way`).
- **Stage 2 (Parakeet on the windows around the hit), replayed:** none of the windows passes
  `match_wake_window`. The transcripts are far from the name: a greeting-like word followed by a word with no
  "wift" in it, or a short unrelated phrase. Two whole-clip transcripts are a near miss ("He …wifted"), and
  `near_wake` primes for them. The next takes were no closer, so priming didn't help.
- **The cause:** the speech model mis-transcribed a bare "Hey Swift" said repeatedly. It was the same voice, mic and
  level as the takes that worked. Why these takes and not those is **unproven**. Possibly the owner said it faster or
  more forcefully after the first miss: these takes are louder than the ones that worked. **Unverified:** that every
  clip is "Hey Swift". The owner hasn't labelled them yet (`spikes/wake/label_misses.py`).
- **A narrower bar, scored and rejected:** letting stage 2 accept "-wifted" ("He twifted") would gain nothing.
  Replayed on all 45 detector-miss clips still saved, it accepts exactly the clips today's check accepts. No bar
  change is proposed: a fix would have to make stage 2 accept text this far from the name, which `match_wake_window`
  was scored against (0 false wakes in 2 h of the office, ADR-021). The offline replay starts the scorer at the
  clip's start rather than mid-stream, so its hit times differ a little from live.

## 22:11:38–22:16:38: segmentation was deaf for most of the window (proven from counters; source unproven)

- The 22:16:38 `wake listening` line has `too_long=10 forced_resets=5`. `speech_blocks=3539` of `blocks=9324` is
  about 113 s of "speech" in 5 min.
- `WakeListener.feed` drops an utterance once it has more than `max_s` (10 s) of speech without a 0.8 s pause. It then
  stays deaf until a 0.8 s pause comes, or for 30 s (a forced reset). So five 30-second resets add up to at least
  150 s deaf, plus up to 10 s per dropped utterance. Most of those five minutes, a "Hey Swift" would have been
  swallowed whole, and nothing is saved from a too-long stretch.
- What kept the gate open is **unproven**. The bar was about −40 dBFS (the owner's voice bar). Something above it
  kept going with gaps under 0.8 s: talk, a video, music. The two clips that did get through are detector misses.
  One is very quiet (−29 dBFS loudest, below the detector's threshold when replayed). The other is a near miss.
- Not changed: no bar was scored on this, and the 30 s cap is a deliberate trade (`wake.py`). Item 14's at-rest orb
  now shows this case: the orb only reacts while an utterance is being collected, so it stays still while the
  listener is deaf after a too-long stretch.

## Not covered

- The 22:18:38 and 22:19:56 restarts (engine crashes, another session) don't explain either miss. The mic reopened
  at once each time.
- Nothing was run on the real PC for this diagnosis. The clips were read and replayed from
  `%LOCALAPPDATA%\Swift\audio`, and no transcript was copied into git.
