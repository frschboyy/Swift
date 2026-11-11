# ADR-021: A second way in for "Hey Swift": an acoustic detector, checked by Parakeet

- **Status:** Accepted for building (2026-11-11): the owner said "start step 1". Steps 1 to 4 are done: it's wired into Swift behind `wake.acoustic`, which is off by default. Steps 5 (owner checks) and 6 (rescoring) are next.
- **Decided by:** Owner (pending)
- **Date:** 2026-11-11
- **From:** [`docs/spikes/wake-model-trial.md`](../spikes/wake-model-trial.md), round 3, and ADR-020 §6 decision 2 ("try a dedicated wake-word model, kept only if it beats speech-to-text matching on both").
- **Touches:** `swift/wake.py` (matching), wake listening in `backend/__main__.py`, `session.py` (one call site), settings `wake.*`. Product rules in `CLAUDE.md` are kept as they are.

## 1. Why

Today, wake detection is speech-to-text: `WakeListener` cuts an utterance, Parakeet transcribes it, and
`match_wake` looks for "hey swift" in the text. On the owner's recordings (417 positives: 247 takes at
0.5 m and 1.5 m, quiet, with media and with babble; 27 live misses; 140 wake clips) it misses 38.6%,
with 0 false wakes in 2 hours of the office and on 1,502 negative clips.

Accepting a wake when **either** today's path matches **or** an acoustic detector fires and Parakeet's
transcript of that moment passes a lenient check gives:

| | Misses | Live misses caught | Takes caught | False wakes (2 h office + other negatives) |
|---|---|---|---|---|
| Today | 38.6% | 8 / 27 | 115 / 247 | 0 |
| Today OR (ViolaWake 0.5 → Parakeet window check) | 28.1% | 20 / 27 | 139 / 247 | 0 |

It's the only path in the trial with fewer misses and no more false wakes. At 1.5 m with media or
babble, nothing that goes through speech-to-text works (0–12%). This ADR doesn't fix that case; §7 does.

## 2. Decision (proposed)

Keep today's path exactly as it is. Add a **second way in**, used only where today's path finds no wake
phrase and nothing else is waiting for the words (§4):

1. **Stage 1, always on:** a small acoustic "Hey Swift" detector scores the microphone stream every 80 ms
   on its own thread and remembers when it fired. It decides nothing by itself.
2. **Stage 2, only when an utterance with no match contains a detection:** Parakeet transcribes three
   short windows of that utterance around the detection. If one passes the window check, the utterance
   starts a request. The words after the detection are the request.

Approving is untouched. The second way in only starts a request, the way a loose `match_wake` does today.
`match_address` (approving hands-free) never uses it.

## 3. How it works

```
microphone ─▶ recorder.tap ─┬─▶ WakeListener.feed        (today: cuts utterances → session.hear_wake)
                            └─▶ AcousticWake.push         (new: a queue; scored on its own thread)

session._hear_transcribed(heard, audio, started_at, ended_at)
  match = _wake_match(heard.text)                          (today, unchanged)
  if match is None and second way in allowed (§4):
      t = acoustic.first_hit(started_at, ended_at)        (a time; no audio kept by the detector)
      if t: match = await second_way_in(t, audio, …)      (new module: 3 windows → check → remainder)
  … the rest of today's flow, unchanged
```

**`swift/wake_acoustic.py` (new, small, its own interface):**
- **`AcousticWake(models_dir, threshold=0.5, refractory_s=1.5)`:**
  - `push(block, at)` is called on the audio thread and only enqueues; the queue is bounded and drops the
    oldest block when full.
  - A worker thread computes the features and scores, and keeps the times it fired over the last 15 s.
  - `first_hit(t0, t1) -> float | None`, `reset()`, `pause()` / `resume()`.
- **The detector's computation:**
  - openWakeWord's melspectrogram and embedding models (`melspectrogram.onnx`, `embedding_model.onnx`,
    Apache-2.0) give one 96-dim embedding every 80 ms.
  - The "Hey Swift" head (`hey_swift.onnx`, a TemporalCNN trained in the trial with ViolaWake's trainer on
    Piper voices; the weights are Swift's own) scores the last 9 embeddings.
  - Swift runs the three files with `onnxruntime`, which `onnx-asr[cpu]` already brings in. **No new
    dependency**: Swift doesn't import ViolaWake or openWakeWord, about 120 lines replace their runtime.
  - Every `InferenceSession` uses `intra_op_num_threads=1` and `inter_op_num_threads=1`: 6.9% of one core
    instead of 75%, with identical scores (trial, round 3).
- **Model files** go in `%LOCALAPPDATA%\Swift\models\wake\`, like Parakeet's: outside git, copied by the
  install step. Today they're saved in `%LOCALAPPDATA%\Swift\corpus\wake\models\`. If any file is missing,
  the second way in is off, and one content-free warning is logged.

**`second_way_in(t, audio, started_at, transcriber) -> WakeMatch | None` (same module):**
- **The windows:**
  - Taken from the utterance's own audio, so the detector keeps no audio.
  - Three windows: 1.2 s and 1.6 s ending 0.3 s after `t`, and 2.0 s ending 1.0 s after `t` (clipped to
    the utterance).
  - All three are needed: without the long one, misses go from 28.1% to 29.5%. Because stage 2 runs once
    the utterance has ended, the long one costs no waiting.
- **The window check** is `match_wake_window(text)`, moved into `swift/wake.py` from the bench
  (`lenient_wake`). It passes on:
  - a greeting-like word, then "swift" / "swiftly" ("He swift", "Eat swift", "Very swift");
  - something before a "…wift" word at the start ("Exwift", "He dwifts", "Pretty swift");
  - today's loose match.

  It never passes the bare name ("Swift.", "Swift, yes"). It's used **only on detection windows**, never
  on whole utterances: the owner judged a looser text rule on its own superficial.
- **The request:** Parakeet transcribes the audio from `t - 0.2 s` to the end of the utterance. A leading
  "…wift" word is dropped, and empty means a bare "Hey Swift", as today. The result is
  `WakeMatch(phrase="hey swift", remainder=…)`.
  - Measured in step 3 on 84 of the owner's "Hey Swift <command>" takes. The detector fires just after the
    name ends, so starting before the hit gets the request's first word right more often: 57 from −0.2 s,
    47 from the hit, 40 from +0.1 s. Today's match got 44 on the same takes.
  - From −0.3 s, a piece of the name starts to show up.
- **Cost:** up to 4 short transcriptions (0.3–0.4 s each), only on an utterance that today's path rejected
  and the detector fired in. At threshold 0.5 the detector fired about 2 times a minute in the office.
  Most of those utterances end at the window check, so roughly 2 minutes of Parakeet time per 2 hours.

**Settings (`WakeSettings`):**
- `acoustic: bool = False`. Off until the owner checks pass.
- `acoustic_threshold: float = 0.5`, the trial's value.

## 4. Where the second way in applies, and where it never does

- **Only at rest:** no run in front, no question waiting (`asked is None`), no follow-up window, not a
  short clip, not over Swift's voice. Everywhere else, words that don't match keep today's meaning.
- **Never for approving:** `match_address` and `_reply_doubt` don't see it. A bare "yes" still never
  approves.
- **Never while locked or paused:**
  - The detector is fed only through `recorder.tap`, and a locked screen closes the stream
    (`Lifecycle.handle` → `recorder.pause`), so it hears nothing.
  - `recorder.on_reopen` calls `reset()`, so nothing heard before the lock is remembered.
  - `_hear_transcribed` already returns when `_deaf()`, before the call site.
- **The confidence bars:** the utterance still passes the same `wake_phrase_min_p` bar as a loose match.
- **An utterance held mid-thought** (`_hold`, "set a timer for twenty … five minutes"): only utterances
  that already matched, or that answer something, are held, so the second way in isn't tried on them
  (`held=True`). Known limit: a request that only the second way in catches isn't held, so one that
  pauses mid-thought starts with its first half.

## 5. Product rules

- **Audio never leaves the PC:** all three models run locally, with no key and no network.
- **Logs stay content-free:** `wake_stats` gains three counters, `acoustic_hits`, `acoustic_wake` (accepted)
  and `acoustic_rejected`. No window text is logged.
- **No hands-free listening while locked:** see §4. This needs a review by someone other than the author
  (`CLAUDE.md`, "Fixing things").
- **Approving needs Swift's name, and a bare "yes" never approves:** unchanged, since the second way in
  only starts requests.
- **Status labels:** unchanged. When the second way in fires, it shows the same "heard" state as today.

## 6. Steps (one finding per commit)

1. **Parity:** Swift's own ONNX inference reproduces ViolaWake's scores on the trial's clips (max
   difference ≤ 0.01). It's a spike check, done before anything else. If it fails, stop.
   - **Done (2026-11-11):** `swift.wake_acoustic.HeySwiftScorer` against the round 3 ViolaWake run, through
     `spikes/wake/parity.py`, on all 1,968 clips (3.0 h of audio). Worst score difference 0.00005, and no
     clip fires differently at 0.5. One thread scored the 3.0 h in under 9 minutes, file reading included.
2. **`wake_acoustic.py`:** `AcousticWake`, with unit tests for timing, refractory, reset, pause and a full
   queue, on synthetic blocks and a saved "Hey Swift" take.
   - **Done (2026-11-11):** `AcousticWake`, with 10 tests in `tests/unit/test_wake_acoustic.py` that use a
     fake scorer, since the models aren't in git.
   - The tests cover: hit times, the refractory, forgetting old hits, reset, pause, a block mid-score when
     the screen locks (no hit), a full queue (dropped, scorer restarted), a failing scorer, and copying the
     tap's buffer.
   - **On real audio:** with the real models and 32 ms blocks, 180 of the owner's clips (60 takes, 60 office
     utterances, 60 wake clips) fire or not exactly as in the round 3 bench, with identical hit times. That
     check is run by hand: the takes aren't in git.
3. **`match_wake_window`** in `wake.py`, with the bench's examples as tests, plus `second_way_in` with a
   fake transcriber.
   - **Done (2026-11-11):** `match_wake_window` is the bench's check, moved unchanged. The bench now imports
     it, and the round 3 numbers are the same (28.1%, 0 false wakes).
   - `second_way_in` is in `wake_acoustic.py`: the shortest window first, stopping at the first that passes,
     windows clipped to the utterance, and the request from −0.2 s.
   - Tests in `tests/unit/test_wake_acoustic.py`: 17 for the window check, 5 for `second_way_in`.
4. **The call site** in `_hear_transcribed`, the settings, the wiring in `backend/__main__.py` (tap fan-out,
   reset on reopen), and the counters.
   - A scenario in `tests/unit/test_seam_replay.py`: "a 'He swift, what time is it' utterance with a
     detection starts the request 'what time is it'". It must fail with the change undone.
   - Also the negative cases: locked, a question waiting, a run in front.
   - **Done (2026-11-11):**
     - `Session._second_way` is called from `_hear_transcribed` at rest only. It rechecks lock, hotkey and
       cards after stage 2, and counts `acoustic_hits`, `acoustic_wake` and `acoustic_rejected`.
     - Settings `wake.acoustic` (off) and `wake.acoustic_threshold`. The backend feeds the detector from the
       recorder's tap and resets it when the stream reopens. If the models in `models/wake` don't load, it
       stays off with one warning.
     - Six scenarios in `tests/unit/test_seam_replay.py`. The first (a wake phrase only the detector heard
       starts the request on screen) fails with the call site undone. The rest: the detector alone starts
       nothing, a lock during stage 2, a question open, a run in front.
     - **Found on real takes, in real time** (real listener, models and Parakeet): the tail of a bare "Hey
       Swift" was transcribed as the request "Yeah." Now, if nothing from 0.3 s after the hit is within 10 dB
       of the utterance's loudest block, it's a bare phrase. Measured on the quiet takes: −14 dB or lower
       after a bare phrase, −6 dB or higher with a request. The cost: a quiet one-word "stop" right after
       the name can count as bare, and then Swift opens the microphone and waits.
     - On 24 takes that today's path missed in the bench and the two-stage path caught, 20 woke live. The
       live cut of an utterance differs from the 4 s take, so step 6 must rescore through the listener.
5. **Owner checks** in `docs/testing/owner-checks.md` with report lines in `spikes/owner_checks/report.py`:
   - calm "Hey Swift" at 0.5 m and 1.5 m, with today's path off and on;
   - an hour of normal office work with `acoustic_hits` and `acoustic_wake` read from the log;
   - locked: the counters don't move.
6. **Score on the owner's clips again** with the integrated code (confidence bars, `CLAUDE.md`), through the
   bench's `build`/`report` on the same 417/1,502 set. It must match round 3 (28.1%, 0 false wakes) within
   a point.
7. **Optional, later: an early "heard".** Run the two short windows 0.3 s after a detection, while the
   owner is still talking, and show "heard" as `peek_wake` does. That would make the second way in answer
   about 1 s sooner than today's path. It's a screen change, so it needs its own seam scenario.

The steps add a module of about 200 lines and about 15 lines in `session.py` and `backend/__main__.py`.
They delete nothing: this is a new capability, not a structural step.

## 7. Open questions for the owner

1. **Default:** keep `acoustic` off until the owner checks (step 5) pass, then on? (Recommended.)
2. **The far, noisy case** (1.5 m, media or babble) isn't fixed by this. The trial's own-voice verifier is
   the candidate: 29.0% misses, 24/27 live misses, but 4.4 false wakes an hour. Record more takes at 1.5 m
   in noise and a few more room hours (TV evening, calls) before deciding.
3. **Retrain the head with the owner's 247 takes?** It was trained on synthetic voices only. Retraining
   could help, but every number above would need re-scoring, out of fold. Not part of this ADR.
4. **"Jarvis":** Porcupine 1.9 did best at a distance (25/30, 0 false wakes, 0.2 s), but it's a fixed word
   on an unmaintained 2021 engine. Out of scope here. It stays a comparison point unless the owner wants a
   different name.
5. **Two hours of the office** can show that false wakes are rare, not how rare. Should step 5's hour of use
   be longer, or across conditions (TV evening, calls)?
