# Wake-word model trial (2026-11-10)

ADR-020, the owner's decision 2: try a dedicated wake-word model and score it on the owner's saved clips
(misses and false wakes) before it replaces anything. This page is that trial.

**Result: don't switch.** The candidate, openWakeWord with a "hey swift" head trained on this PC,
catches most misses but false-wakes 70 to 500 times an hour. Today's matching false-woke 0 times in the
same 31 minutes. Nothing is wired into `src/swift`.

## Method

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
The numbers are given for all 30 and for the 24 sure ones. Owner check: listen to the 30 and correct the
labels (`--labels`).

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

## Numbers

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

## Why the head fails, and what a real model would need

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

## Recommendation

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

## Reproduce

```bash
uv run --frozen --group spikes python spikes/wake/wake_bench.py build --out <scratch>
uv run --frozen --group spikes python spikes/wake/wake_bench.py stt --out <scratch> --whisper
uv run --frozen --group spikes --with openwakeword==0.6.0 python spikes/wake/wake_bench.py oww --out <scratch> --model hey_jarvis
uv run --frozen --group spikes --with openwakeword==0.6.0 python spikes/wake/train_head.py --out <scratch> --labels <labels.json> --positives owner --tag head_owner
uv run --frozen --group spikes python spikes/wake/wake_bench.py report --out <scratch> --labels <labels.json> --oww hey_jarvis head_owner
```

The hand labels (clip id → pos/neg/skip, no text) are in the session's notes folder, not in git.
