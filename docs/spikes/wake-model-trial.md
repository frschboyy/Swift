# Wake-word model trial (2026-11-10)

ADR-020, the owner's decision 2: try a dedicated wake-word model and score it on the owner's saved clips
(misses and false wakes) before it replaces anything. This page is that trial, in two rounds. Round 2
(below) scores a two-stage wake, the way phone assistants do it. Round 1 (further down) is the morning's
openWakeWord head.

**Result of round 2: don't switch yet.** As labelled, no path beats today's on both misses and false wakes.
The closest is ViolaWake (threshold 0.5) followed by a Parakeet check of the window it fired on: 16.7%
misses against today's 19.0%, and 20 of the 27 live misses caught against 8. But it makes 2 false wakes
in 31 minutes (3.9 an hour) where today's path makes none. In both of those clips Parakeet hears "Hey
Swift" inside a clip labelled negative, so they may be labelling errors. If the owner's ear says they are,
this path beats today's on both counts. None of the two-stage paths catches the 5 calm office takes:
stage 1 hears them, stage 2 throws them out. Nothing is wired into `src/swift`.

## Round 2: a two-stage wake (afternoon)

### What was tried, and what was dropped

| Engine | Licence | Upkeep | Verdict |
|---|---|---|---|
| Picovoice Porcupine, current | Paid. The free tier ended 2026-06-30, replaced by a 7-day trial "for product teams"; third-party listings put the cheapest plan at about $6,000 a year. The AccessKey is checked online. | Active | Dropped: no free personal use |
| Porcupine 1.9.5 (2021, legacy) | Apache-2.0 (its package LICENSE). No AccessKey, nothing online. | Unmaintained since 2021 | Scored with its built-in "jarvis" only. It can't be given "Hey Swift": custom keywords come from the Console, which as far as I could tell makes keywords for current versions only (not tested: it needs an account). |
| openWakeWord 0.6.0 | Code Apache-2.0. Its own ready-made models are CC BY-NC-SA 4.0 (non-commercial, fine for personal use). A model trained here is the owner's. | Last commit 2025-12-30 | Trained with its full recipe |
| ViolaWake 0.2.10 | Apache-2.0 | Active but young: created 2026-03, one maintainer, 9 stars | Trained, with its online TTS switched off (see below) |
| LiveKit WakeWord 2.x | Apache-2.0 | Active (last commit 2026-11-06) | Skipped at the owner's request: training needs a LiveKit Cloud account for its TTS |
| Mycroft Precise | Apache-2.0 | Last commit 2023-11; Mycroft AI wound down | Dropped as dead |

### How the two models were trained (all on this PC)

- **Positives:** 5,000 + 1,000 synthetic "Hey Swift" clips from Piper's `en_US-libritts_r-medium` voice
  (904 speakers, CC BY 4.0), with varied speed and noise. `spikes/wake/piper_samples.py` stands in for
  openWakeWord's Linux-only generator.
- **openWakeWord, full recipe** (`train.py` as published, run through `spikes/wake/oww_train_windows.py`
  for two Windows-only fixes):
  - Near-misses: 5,000 + 1,000 Piper clips of phoneme-overlap phrases, plus "hey steve", "hey shift",
    "they sift", "Taylor Swift" and others.
  - Negatives: its usual 2,000 hours of precomputed ACAV100M features (17 GB).
  - Augmentation: the MIT room echoes (270), 1,000 AudioSet clips (2.8 h) and 300 clips of Piper office
    babble.
  - False-wake validation: its 11-hour set.
  - Training: 20,000 steps, about 45 minutes on the CPU.
  - Left out of the recipe: the 1 h of FMA music (AudioSet already has music).
- **ViolaWake** (`--no-auto-corpus`, run through `spikes/wake/viola_train_offline.py`):
  - Same positives.
  - Negatives: the 5,000 near-misses, 1,500 Piper speech clips, the 300 babble clips and the AudioSet clips.
  - Training: about 21 minutes.
  - It has no large negative set like openWakeWord's 2,000 hours, and it found no shared corpus of its own.
  - By default its trainer makes speech with Edge TTS, an online service. Even with `--no-auto-corpus`,
    its quality gate still does, and it won't save a model without passing the gate. The runner skips the
    gate and blocks the online call. The first run reached the gate and was stopped. It may have sent its
    stock check phrases (text only, never audio) before that.

None of the owner's clips were used for training, so every score below is on unseen audio.

**Stage 2** (`wake_bench.py stage2`) runs only when stage 1 fires:
- Parakeet (with the owner's word fixes) transcribes three windows: 1.2 s and 1.6 s ending 0.3 s after
  the detection, and 2.0 s ending 1.0 s after it.
- A lenient check passes if any window has a greeting-like word followed by "swift"/"swiftly" ("He
  swift", "Eat swift", "Very swift"), or a word or prefix before a "…wift" word at the start ("Exwift",
  "He dwifts", "Pretty swift"), or today's loose match.
- The bare name ("Swift.", "Swift, yes") doesn't pass: it's a known hard negative.

Windowing matters. Over the whole 4 s calm takes, which include office voices, Parakeet writes nothing
like the name ("He drifted", "He's left in my chat"). On windows centred on the loudest point, 3 of the 5
come out as "He's swift", "Exwift" and "Pretty swift" / "Hey Swift". A cut 0.2 s off flips them back.

### The set

- **Positives:** the same clips as round 1, plus the owner's 5 calm office takes: 168 in all.
- **Live misses:** labelled by the owner's ear (`miss_labels.json`), giving 27 positives, not round 1's
  30.
- **Negatives:** 370 clips (31.1 min), skipping the same 10 clips that open with "Hey Swift".

### Numbers

Misses are over the 168 positives. "Live misses caught" is of the 27 the owner labelled; "calm takes" is
of the 5. False wakes are per hour of the 31.1 minutes of negatives. One false wake there is 1.9 an hour,
so this set can't tell 0.5 an hour from 1.9.

| Path | Misses | Live misses caught | Calm takes | False wakes / h |
|---|---|---|---|---|
| **Today: Parakeet + `match_wake` loose** | **32 (19.0%)** | **8 / 27** | **0 / 5** | **0** |
| Parakeet + `match_wake` strict | 43 (25.6%) | 0 / 27 | 0 / 5 | 0 |
| Parakeet + the lenient check alone (no stage 1) | 20 (11.9%) | 16 / 27 | 0 / 5 | 1.9 * |
| ViolaWake th 0.5, alone | 9 (5.4%) | 26 / 27 | 5 / 5 | 81 |
| **ViolaWake th 0.5 → Parakeet lenient** | **28 (16.7%)** | **20 / 27** | **0 / 5** | **3.9 \*** |
| ViolaWake th 0.8, alone | 39 (23.2%) | 19 / 27 | 2 / 5 | 11.6 |
| ViolaWake th 0.8 → Parakeet lenient | 49 (29.2%) | 13 / 27 | 0 / 5 | 3.9 * |
| ViolaWake th 0.95, alone | 102 (60.7%) | 9 / 27 | 0 / 5 | 1.9 |
| openWakeWord full recipe th 0.1, alone | 24 (14.3%) | 20 / 27 | 1 / 5 | 13.5 |
| **openWakeWord th 0.1 → Parakeet lenient** | **32 (19.0%)** | **16 / 27** | **0 / 5** | **3.9 \*** |
| openWakeWord th 0.5, alone | 36 (21.4%) | 18 / 27 | 0 / 5 | 7.7 |
| openWakeWord th 0.5 → Parakeet lenient | 43 (25.6%) | 13 / 27 | 0 / 5 | 3.9 * |
| openWakeWord th 0.9, alone | 124 (73.8%) | 5 / 27 | 0 / 5 | 0 |
| Porcupine 1.9 "jarvis", sensitivity 0.3–0.7 | not measurable † | — | — | 0 |
| Porcupine 1.9 "jarvis", sensitivity 0.9 | not measurable † | — | — | 1.9 |

\* The same 2 clips each time, both labelled negative, in which Parakeet hears "Hey Swift" on the window:
- a hotkey dictation (`54360854…`), 55 s in;
- the tail of a wake clip (`f45307e5…-tail`), 5 s after the first "Hey Swift" (a repeat).

The lenient check alone flags only the first. If the owner's ear says both contain "Hey Swift", every
starred row drops to 0 false wakes.

† Every positive says "Hey Swift", so "jarvis" can't be scored for misses. That needs a few recorded "Jarvis"
takes.

**Latency after the name:**
- **Today:** the utterance must end (0.8 s of silence), then Parakeet transcribes the whole clip (p50 1.1 s
  here). That's about 1.5–2 s after "Swift".
- **Two-stage:** stage 1 fires at about the end of the name. Stage 2 waits 0.3 s (or 1.0 s for its long
  window), then Parakeet takes p50 0.30 / 0.36 / 0.43 s on the 1.2 / 1.6 / 2.0 s windows. That's about
  0.6–1.4 s after "Swift".
- **Caveat on the bench's "fires after the name ends" column:** it reads −1 to −1.6 s because "the name
  ends" is taken from when Parakeet's next word starts, and a pause after "Hey Swift," pushes that later.
  Where the request follows straight on, both models fire 0.1–0.3 s before that point.

**CPU while listening** (this laptop):

| Engine | CPU | Memory |
|---|---|---|
| Porcupine 1.9 | 1.3% of one core | 43 MB process |
| openWakeWord | 10.7% of one core | +35 MB (process 210 MB) |
| ViolaWake | 83% of one core in CPU time, measured alone | about 46 MB |

ViolaWake's 83% is for 120 s of audio that took 16 s of wall time, so most of it is probably ONNX Runtime's
thread pool spinning on tiny per-frame inferences. One thread per session would likely cut it a lot; that
wasn't tried. Stage 2 adds Parakeet (already loaded for requests) only when stage 1 fires.

### What this says

1. **Stage 2 is the bottleneck for calm speech.** Both models hear the calm takes when they're sensitive
   (ViolaWake at 0.5 catches all 5), but Parakeet's transcript of the window passes none of them. So the
   two-stage design fixes misses where the name comes out roughly right ("Hey twift", "He swift"), not
   where Parakeet can't make out the name at all.
2. **openWakeWord's full recipe is far better than round 1's head:** 13.5 false wakes an hour at 14.3%
   misses, against 510 an hour at 3.7%. Alone, it's still not good enough. As stage 1 at th 0.1 it ties
   today's misses (19.0%), catches 16 live misses against 8, and adds the 2 starred clips.
3. **ViolaWake hears more but is noisier alone** (81 an hour at 0.5). Behind stage 2 it's the best row.
4. **The lenient text check alone** (no acoustic stage) does better than any two-stage row here: 11.9%
   misses, 16 live misses caught, and one false wake, the first starred clip. The owner called a looser
   text rule on its own superficial, and the risk is real. "A swift reply…" said to someone else would open
   the microphone, and 31 minutes of negatives can't measure how often that happens.

### Recommendation

1. **Owner: listen to the two starred clips** (`54360854…` at 52–56 s, and `f45307e5…` from 3 s on).
   - If both contain "Hey Swift": ViolaWake th 0.5 → Parakeet lenient beats today's path on both misses and
     false wakes, as the rule requires. The next step is scoring it on hours of the owner's real room
     (`record_negatives.py`), since 31 minutes can't measure false wakes below 2 an hour.
   - If not: keep today's path.
2. **Don't count on any of this for calm office speech.** That needs a stage 2 that isn't speech-to-text.
   Apple's second stage is a larger acoustic model trained on the owner's own voice, which needs the
   ~300-take positive corpus (`record_corpus.py`). Five takes is far too few to train or judge one.
3. **"Jarvis" (Porcupine 1.9)** is cheap (1.3% CPU) and quiet (0 false wakes up to sensitivity 0.7) on
   these clips. Its misses and responsiveness need about 30 recorded "Jarvis" takes. It's an unmaintained
   2021 binary with a fixed word, so it's a comparison point, not a candidate.

### Early read on option 3: a stage 2 that knows the owner's voice

`spikes/wake/verifier.py` follows openWakeWord's custom-verifier recipe: a logistic regression on the
embeddings at the detection, trained on the owner's own clips and scored out of fold by day. With only
the clips there are today (5 takes, about 160 positives):

| Path | Misses | Live misses caught | Calm takes | False wakes / h |
|---|---|---|---|---|
| Today | 19.0% | 8 / 27 | 0 / 5 | 0 |
| ViolaWake 0.5 → Parakeet lenient | 16.7% | 20 / 27 | 0 / 5 | 3.9 |
| ViolaWake 0.5 → own-voice verifier 0.7 | 13.7% | 24 / 27 | 4 / 5 | 17.4 |
| ViolaWake 0.5 → own-voice verifier 0.9 | 19.6% | 21 / 27 | 1 / 5 | 11.6 |
| openWakeWord 0.1 → own-voice verifier 0.7 | 17.3% | 19 / 27 | 1 / 5 | 7.7 |

The own-voice stage keeps the calm takes, which the Parakeet stage can't do. But it false-wakes far too
often to use yet. It needs the owner's ~300 takes.

### Next: what the owner records (options 1, 3 and 4)

**Before recording takes, quit Swift, or turn wake listening off.** The takes say "Hey Swift" plus
commands like "draft an email to my dean" and "remind me every Friday…", and a running Swift would act on
them. Room recordings are fine with Swift running.

1. **Option 1, the two disputed clips** (about 1 minute). Answer y if you hear "Hey Swift":
   ```bash
   uv run --group spikes python spikes/wake/label_misses.py --clips 54360854620b4c9d9e32c66d8030b1fc@50-58 f45307e541134c74b7ce27575be88a21-tail@0-6
   ```
2. **Option 1, your room** (at least 2 hours, more is better). Work, take calls, play TV as usual, and don't
   say "Hey Swift". It writes room audio to disk, so make sure anyone else there is fine with it, and
   delete the folder when the trial is done.
   ```bash
   uv run --group spikes python spikes/wake/record_negatives.py --hours 2 --label office
   ```
3. **Option 3, 300 "Hey Swift" takes**: 34 per cell, at 3 distances × 3 noise levels. `media` means a
   video or podcast playing; `babble` means people talking nearby. At 1.5 m and 3 m, add `--auto`: a beep
   starts each take.
   ```bash
   uv run --group spikes python spikes/wake/record_corpus.py --distance 0.5 --noise quiet --count 34
   uv run --group spikes python spikes/wake/record_corpus.py --distance 1.5 --noise media --count 34 --auto
   ```
   (and the same for the other cells: 0.5 media/babble, 1.5 quiet/babble, 3 quiet/media/babble)
4. **Option 4, 30 "Jarvis" takes**: 10 each at 0.5 m quiet, 1.5 m quiet and 1.5 m media.
   ```bash
   uv run --group spikes python spikes/wake/record_corpus.py --distance 0.5 --noise quiet --count 10 --phrase Jarvis
   ```

Then a fresh `build`, `stt`, `align`, the detectors, `stage2`, `verifier.py`, and `report`, plus
`report --phrase jarvis --porcupine jarvis` for option 4, score everything on the new audio. The room
appears as "room: N in H h".

### Reproduce (round 2)

All audio and models stay in a scratch folder outside git. `<oww>` holds the downloads, the generated
clips and `hey_swift.yaml`. The envs are throwaway `uv run --with` envs: torch 2.5.1+cpu, openwakeword
0.6.0, `violawake[training,oww]` 0.2.10, piper-tts 1.8.0, pvporcupine 1.9.5, and scipy 1.13.1 for
`acoustics`.

```bash
uv run --frozen --group spikes python spikes/wake/wake_bench.py build --out <bench>
uv run --frozen --group spikes python spikes/wake/wake_bench.py stt --out <bench>
uv run --frozen --group spikes python spikes/wake/wake_bench.py align --out <bench> --labels <labels.json>
# Detectors (each in its throwaway env)
python spikes/wake/wake_bench.py porcupine --out <bench> --keyword jarvis          # with pvporcupine==1.9.5
python spikes/wake/oww_train_windows.py --training_config <oww>/hey_swift.yaml --generate_clips --augment_clips --train_model
python spikes/wake/wake_bench.py oww --out <bench> --model <oww>/model/hey_swift.onnx --tag oww_full
python spikes/wake/viola_train_offline.py --word "hey swift" --positives <oww>/model/hey_swift/positive_train \
    --negatives <negatives> --no-auto-corpus --output <viola>/hey_swift.onnx
python spikes/wake/wake_bench.py viola --out <bench> --model <viola>/hey_swift.onnx --tag viola_hey_swift
# Stage 2 and the table
uv run --frozen --group spikes python spikes/wake/wake_bench.py stage2 --out <bench> --labels <labels.json> --oww viola_hey_swift oww_full --thresholds 0.1 0.3 0.5 0.7 0.8 0.9 0.95
uv run --frozen --group spikes python spikes/wake/wake_bench.py report --out <bench> --labels <labels.json> --oww viola_hey_swift oww_full --thresholds 0.1 0.3 0.5 0.7 0.8 0.9 0.95 --porcupine jarvis
```

`<labels.json>` is the owner's `miss_labels.json` plus round 1's 10 skips, which are in the notes folder.

**Other data licences:**
- LibriTTS-R (the Piper voice) and AudioSet's labels are CC BY 4.0.
- AudioSet's audio comes from YouTube, and ACAV100M's features come from web video.
- All of it was used only locally, for training. Check their terms before sharing a trained model.
- piper-tts is GPL-3.0. It ran only in the throwaway env and isn't part of Swift.

## Round 1: an openWakeWord head trained on the owner's clips (morning)

### Method

Scripts: `spikes/wake/wake_bench.py` (set, today's path, report) and `spikes/wake/train_head.py` (the head).
Audio was copied to a scratch folder outside git and never left the PC. No audio and no transcripts are
committed.

**The set** (the owner's recordings in `%LOCALAPPDATA%\Swift`):

| Kind | Clips | Audio | Label from |
|---|---|---|---|
| Wake clips: requests started by wake listening | 133 | 18.4 min | Today's path accepted them live (see the bias below) |
| Saved misses (`*-miss.wav`, 2026-11-04 to 11-09) | 83 | 4.1 min | Hand label: 30 pos (24 sure, 6 weak), 52 neg (room sound, fillers, other speech), 1 skipped |
| The "Hello Swift" read-aloud clip | 1 | — | Its reference text |
| Hotkey requests and answers (`voice`, `followup`) | 137 | 11.5 min | No wake phrase expected |
| Read-aloud corpus, quiet and with TV (`stt_corpus`, `stt_noisy`) | 74 | 6.5 min | Reference text |
| Wake clips from 3 s on: the request after the phrase | 116 | 11.4 min | Ordinary speech |

That's 164 positives and 369 negatives (30.9 min). Ten clips labelled negative really did open with "Hey
Swift": said into the hotkey, or said again after 3 s. They were skipped, not counted as false wakes. Clips
with the name and no greeting ("I think Swift is crazy", "Swift, yes") stayed in as hard negatives.

**Hand labels for the misses.** There's no ground truth, so each miss was transcribed locally twice, with
Parakeet and with Whisper small.en. It was labelled positive when either transcript had a greeting-like word
followed by a Swift-like word ("He swift", "Hey, Twif", "They're swift", "Hate Swift" / Whisper "Hey Swift").
It was labelled weak when the sound-alike was further off ("He flipped" / "He's moved", "Please lift").
The numbers are given for all 30 and for the 24 sure ones. To replace them with ground truth, label the misses by ear (below).

**Today's path:** `ParakeetTranscriber._transcribe_sync` (int16-scaled, with the owner's word fixes) and
`swift.wake.match_wake`, both strict and `loose=True` (what `_wake_match` uses). The live second chance after
a near miss (`near_wake`) isn't replayed: it needs the previous clip.

**The candidate:** openWakeWord 0.6.0 (onnx), installed only into a throwaway `uv run --with` env. It ships
no "hey swift" model, so:
- **Stock `hey_jarvis` model:** a check that the frontend runs, and a source for its cost.
- **A "hey swift" head trained here:** a logistic regression on 16 consecutive openWakeWord embeddings
  (about 2 s of audio). The positive frames are the end of the name, located with Parakeet's token times.
  The negatives are every frame of every negative clip, plus the frames of each positive clip well before
  or after the phrase. Clips are padded with room-level hiss, since zeros leaked. Scores are out of fold, by
  day: a clip is only ever scored by a model trained without that day's clips.
- Positives come in three variants: the owner's clips, the owner's clips plus 300 Piper clips (the
  `en_US-lessac-medium` voice, with varied speed and noise), and Piper alone.

### Numbers

Misses are false rejects over the 164 positives. False wakes are counted over the 369 negative clips, per
hour of negative audio. "Live misses caught" means of the 30 hand-labelled misses.

| Detector | Misses | Live misses caught | False wakes | False wakes / h |
|---|---|---|---|---|
| Parakeet + `match_wake` strict | 41 (25.0%) | 0 / 30 | 0 / 369 | 0 |
| **Parakeet + `match_wake` loose (today)** | **28 (17.1%)** | **10 / 30** | **0 / 369** | **0** |
| openWakeWord `hey_jarvis` (stock), any threshold | 164 (100%) | 0 / 30 | 0 / 369 | 0 |
| Head, owner's clips, th 0.5 | 6 (3.7%) | 27 / 30 | 263 / 369 | 510 |
| Head, owner's clips, th 0.9 | 21 (12.8%) | 22 / 30 | 170 / 369 | 330 |
| Head, owner's clips, th 0.98 | 61 (37.2%) | 16 / 30 | 92 / 369 | 178 |
| Head, owner's clips, th 0.995 | 82 (50.0%) | 13 / 30 | 49 / 369 | 95 |
| Head, owner's + 300 Piper clips, th 0.9 | 22 (13.4%) | 23 / 30 | 137 / 369 | 266 |
| Head, owner's + 300 Piper clips, th 0.995 | 96 (58.5%) | 14 / 30 | 35 / 369 | 68 |
| Head, Piper clips only, th 0.5 | 124 (75.6%) | 11 / 30 | 1 / 369 | 2 |
| Head, Piper clips only, th 0.9 | 155 (94.5%) | 1 / 30 | 1 / 369 | 2 |

No variant and threshold is at or below today's path on both columns. The head trained on Piper alone
makes few false wakes, but it hardly hears the owner: one TTS voice doesn't carry over to a real one.

**With the owner's labels (2026-11-10, by ear with `label_misses.py`).** Of the 83 misses, the owner heard
"Hey Swift" in 27, not in 51, and couldn't tell on 5. That agrees with the transcript labels on 76 clips: 5
that I had as positive are can't-tell, and 2 longer clips from 2026-11-08 are positive. The set is 161
positives and 368 negatives. The heads were retrained with these labels.

| Detector | Misses | Live misses caught | False wakes / h |
|---|---|---|---|
| Parakeet + `match_wake` strict | 38 (23.6%) | 0 / 27 | 0 |
| **Parakeet + `match_wake` loose (today)** | **27 (16.8%)** | **8 / 27** | **0** |
| Head, owner's clips, th 0.9 / 0.995 | 16.1% / 55.9% | 21 / 12 of 27 | 310 / 90 |
| Head, owner's + Piper, th 0.9 / 0.995 | 19.3% / 60.2% | 20 / 12 of 27 | 242 / 66 |
| Whisper small.en + `match_wake` loose, on the misses only | — | 12 / 27 | 0 on the 51 negative misses |
| Parakeet or Whisper, on the misses only | — | 14 / 27 | 0 on the 51 negative misses |

The conclusion doesn't change.

With only the 24 sure misses, today's loose path misses 22 of 158 (13.9%) and catches 10 of 24 on replay.

**Bias in today's numbers.** The 133 wake clips were accepted live, so they flatter today's path. On replay
it still misses 8 of them (the live run had the near-miss second chance, or a split clip). The fair test
of today's path is the 30 live misses, and on those it catches 10.

**Latency.** Today's path waits for the end of the utterance (`end_silence_s` 0.8 s), then transcribes it:
p50 0.7 s and p90 3.1 s on the short miss clips. Those times were measured with other jobs running, so
they're high. That puts it at about 1.5 s after "Swift" ends. A streaming detector scores every 80 ms and
could open the microphone about 0.1–0.3 s after the name. The trained heads fire before the name ends (a
median of −0.2 to −1.0 s), which is another sign they learned "someone starts talking" rather than the
phrase.

**CPU and memory** (this laptop):

| | CPU | Memory |
|---|---|---|
| Parakeet (today) | about 1.1 core-seconds per second of speech, only when someone speaks | +699 MB, already loaded for requests, so wake listening adds none |
| openWakeWord frontend + model | 14.9% of one core, all the time while listening | +37 MB (process 210 MB) |

### Why the head fails, and what a real model would need

About 160 positives from one voice, with a few hundred synthetic ones from one TTS voice, is far below
openWakeWord's own recipe. A linear head on 1,536 features learns the owner's voice starting to speak,
not "hey swift". openWakeWord's training notebook (`automatic_model_training`) uses:

1. **Positives:** tens of thousands of synthetic clips from `piper-sample-generator` with a multi-speaker
   LibriTTS Piper model (hundreds of voices), plus the owner's own recordings
   (`spikes/wake/record_corpus.py`, which has never been run: there is no `corpus\wake` folder).
2. **Negatives and augmentation:** about 2,000 h of precomputed ACAV100M features (about 17 GB), plus
   room impulse responses (MIT RIR), background noise and music (AudioSet, FMA). These are a few tens of GB
   of public downloads.
3. **Training:** PyTorch, a small DNN, hours on this CPU.
4. **Scoring:** many hours of the owner's real room (TV, calls, music). The useful bar is under 0.5 false
   wakes an hour, and 31 minutes of negatives can't measure that. `record_negatives.py` exists for this.

It's all feasible locally, with no cloud service: the downloads are public datasets, and the training and
audio stay on the PC. It costs about 30 GB of disk and a day of setup and CPU, and the result is unproven.
It needs the owner's approval for the downloads and the PyTorch dependency, which the approval for
openWakeWord didn't cover.

### Recommendation

1. **Keep today's matching.** On these clips it makes no false wakes. The candidate as trained here is far
   worse on false wakes, so the rule in the task, which requires a candidate to win on both misses and false
   wakes, isn't met.
2. **The misses are a transcription problem.** On replay with `match_wake` loose, Whisper small.en's
   transcript catches 12 of the 30 live misses and Parakeet's catches 10. Taking either catches 16, and
   Whisper made 0 false wakes on the 52 negative miss clips. That's flattering, because Whisper also helped
   make the labels. A second model's opinion on short bare clips is still cheaper to try than a wake model.
   It needs labels from the owner's own listening, and scoring on hours of negatives: Whisper also writes
   "Thank you" for silence.
3. **If the owner wants the full wake-model attempt**, do it in this order: record the positive corpus
   (`record_corpus.py`, about 300 takes), record a few hours of negatives (`record_negatives.py`), approve
   the downloads and PyTorch, train with openWakeWord's notebook locally, and rescore with
   `wake_bench.py report`.

### Reproduce

```bash
uv run --frozen --group spikes python spikes/wake/wake_bench.py build --out <scratch>
uv run --frozen --group spikes python spikes/wake/wake_bench.py stt --out <scratch> --whisper
uv run --frozen --group spikes --with openwakeword==0.6.0 python spikes/wake/wake_bench.py oww --out <scratch> --model hey_jarvis
uv run --frozen --group spikes --with openwakeword==0.6.0 python spikes/wake/train_head.py --out <scratch> --labels <labels.json> --positives owner --tag head_owner
uv run --frozen --group spikes python spikes/wake/wake_bench.py report --out <scratch> --labels <labels.json> --oww hey_jarvis head_owner
```

The trial's hand labels (clip id → pos/neg/skip, no text) are in the session's notes folder, not in git.

## Labelling the misses by ear (owner)

The trial's labels for the 83 saved misses are a reading of two transcripts. To make them ground truth,
listen to each one:

```bash
uv run --group spikes python spikes/wake/label_misses.py
```

It plays each `*-miss.wav` clip, oldest first, with its date and length but no transcript. For each one,
answer `y` (I said "Hey Swift"), `n` (room sound, another sentence) or `s` (can't tell). `r` plays it
again, `b` goes back one clip and `q` saves and quits. Every answer is saved at once to
`%LOCALAPPDATA%\Swift\corpus\wake\miss_labels.json`, so you can stop and come back. A second run only
plays the clips you haven't labelled; `--all` goes over every clip again. The 83 clips take about
10 minutes.

To rescore with those labels, use a fresh bench folder (the trial's was temporary): run `build`, `stt`
and `train_head.py` as above, then `report` with
`--labels %LOCALAPPDATA%\Swift\corpus\wake\miss_labels.json`.
