# Speech recognition in noise (2026-10-24)

The question: in noisy rooms, transcripts contain words that were never said.
Can noise suppression or voice isolation fix that, and can Swift admit when it
didn't hear clearly instead of guessing?

## Method

`spikes/stt/noise_bench.py` mixes noise into the owner's 40 recorded clips
(`stt_corpus`) and transcribes each mix with Parakeet, Swift's default engine.
It runs each mix raw and again after a spectral Wiener denoiser. Noise types are
white, pink, 60 Hz mains hum, static (crackle over hiss) and babble (four other
clips summed, standing in for people talking nearby), each at 10, 5 and 0 dB
SNR. Each noise type was also fed alone, with no speech, at -35 dBFS. That is
loud enough to pass the -50 dBFS silence gate.

WER is after light normalization. Some "errors" are formatting only ("3pm" vs
"three p m", "back end" vs "backend"), so absolute WERs are pessimistic. The
comparisons still hold.

## Findings

WER raw → after the Wiener denoiser (clean speech: 0.151 → 0.151):

| Noise | 10 dB SNR | 5 dB | 0 dB |
|---|---|---|---|
| white | 0.232 → 0.246 | 0.324 → 0.327 | 0.522 → 0.517 |
| pink | 0.201 → 0.201 | 0.271 → 0.282 | 0.377 → 0.372 |
| hum | 0.140 → 0.148 | 0.151 → 0.128 | 0.182 → 0.170 |
| static | 0.204 → 0.232 | 0.274 → 0.288 | 0.372 → 0.369 |
| babble | 0.291 → 0.299 | 0.628 → 0.601 | 1.017 → 1.006 |

1. **Denoising does not help recognition.** The Wiener filter moved WER by at
   most 0.03 either way, with no consistent direction; only hum improved slightly. This matches published results:
   modern ASR models (Parakeet, Whisper) are trained on noisy audio, and
   enhancement artifacts confuse them about as much as the noise. Voice
   isolation of the kind phones use on calls is tuned for human listeners. A
   neural enhancer (e.g. DeepFilterNet, GTCRN) can be tried with the same bench.
   On this evidence it is not worth the latency without a measured gain.
2. **Steady noise does not make the model invent words; other voices do.** With
   white, pink, hum or static and no speech, Parakeet returned nothing 40 out of
   40 times. With background voices and no speech, it returned a plausible
   sentence 10 out of 10 times ("Commit these one before the Mesa.").
3. **The model knows when it is guessing.** Parakeet's token probabilities
   (onnx-asr `with_timestamps()`) separate good transcripts from bad ones:

   | Mean word probability | quantiles 10% / 50% / 90% |
   |---|---|
   | correct transcripts | 0.89 / 0.96 / 0.99 |
   | small errors (WER < 0.5) | 0.74 / 0.88 / 0.95 |
   | badly wrong (WER ≥ 0.5) | 0.41 / 0.60 / 0.76 |
   | invented from background voices | 0.41 / 0.50 / 0.62 |

   Words below 0.4 on *clean* speech were mostly real mistakes ("Kick the
   failing test", "deadlock" for "git log").

## What Swift does now

* Every Parakeet word carries a probability (`Transcription.words`, the least
  likely token of the word; punctuation doesn't count).
* **Mean below `stt.reject_p` (0.7), two or more words:** Swift does nothing and
  says "I couldn't make that out", quoting what it sounded like. On the bench
  this refused 90% of the invented sentences, 78% of badly wrong transcripts and
  3% of correct ones. A single word is never refused, because "Stop." scored 0.46.
* **Any word below `stt.unclear_p` (0.4):** the request still goes to the agent,
  with a note naming those words and asking it to check before guessing. This
  happened on 5% of clean requests.
* The interaction log records `stt_confidence` (the least likely word),
  `unclear` and, when refused, `transcript_heard`, so the thresholds can be
  re-tuned on real use.
* Whisper reports no probabilities and is trusted as before: the thresholds were
  calibrated on Parakeet only.

The check costs nothing noticeable: log-probabilities added 0–60 ms on clips
that take ~0.7 s.

## Speaker check prototype (spikes/stt/speaker_bench.py)

The idea: before transcribing, check that the voice belongs to the owner. The
model is WeSpeaker ResNet34-LM (26.5 MB, CC-BY-4.0, loaded through onnx-asr).
The owner is enrolled as the mean embedding of 10 corpus clips; 30 other clips
are held out for testing. With no recordings of other real people, Windows' two
TTS voices at five pitch/rate settings (80 clips) stand in for them.

Cosine similarity to the owner's profile (median, with the range in brackets):

| Audio | Score |
|---|---|
| owner, clean | 0.82 (0.43–0.91) |
| owner over 2 other voices, 10 dB | 0.69 (0.07–0.82) |
| owner over 2 other voices, 5 dB | 0.52 (−0.09–0.72) |
| owner over 2 other voices, 0 dB | 0.17 (0.00–0.45) |
| one other speaker | −0.05 (−0.13–0.10) |
| 2–4 other speakers, no owner | −0.03 (−0.12–0.16) |

At a threshold of 0.3, no clean owner clip was rejected, and 7% / 10% / 77% were
rejected at 10 / 5 / 0 dB. No other-speaker clip was accepted. At 0 dB the
transcript is wrong anyway (WER 1.0 under babble), so refusing there costs
nothing. Enrolling on 3 clips instead of 10 gave nearly the same numbers. The
lowest clean score (0.43) was the shortest clip (0.85 s). An embedding takes
about 120–200 ms on this laptop.

Synthetic voices are far easier to tell apart than real people, so the bench was
re-run with real ones: Mini LibriSpeech dev-clean-2 (OpenSLR 31, CC BY 4.0,
126 MB). That gave 208 clips of 2–5 s from 26 volunteer readers
(`spikes/stt/librispeech_others.py`). The background voices in "owner over other
voices" were drawn from the same set.

| Audio (real other voices) | Median (range) |
|---|---|
| owner, clean | 0.82 (0.43–0.91) |
| owner over 2 other voices, 10 dB | 0.72 (0.21–0.84) |
| owner over 2 other voices, 5 dB | 0.52 (0.11–0.76) |
| owner over 2 other voices, 0 dB | 0.30 (0.08–0.58) |
| one other speaker | 0.04 (−0.23–0.36) |
| 2–4 other speakers, no owner | 0.03 (−0.21–0.23) |

| Threshold | owner rejected | owner over voices rejected (10 / 5 / 0 dB) | other speaker accepted | voices accepted |
|---|---|---|---|---|
| 0.30 | 0% | 3% / 17% / 47% | 3% (2 speakers) | 0% |
| 0.35 | 0% | 7% / 30% / 50% | 0% | 0% |
| 0.40 | 0% | 10% / 30% / 60% | 0% | 0% |
| 0.45 | 3% | 13% / 30% / 70% | 0% | 0% |

The closest other speakers peaked at 0.36 and 0.30; the other 24 stayed below
0.20. A threshold of **0.35–0.40** rejected none of the 208 other-speaker clips and
none of the owner's clean clips. The margin is narrow, though: 0.36 against the
owner's lowest 0.43.

**Limits of this test:** 26 speakers is a small sample, and the LibriSpeech
readers used other microphones and rooms. Microphone and room differences push
scores apart, so someone talking in the owner's own room, into the same mic,
will score higher than these did. The owner's clips are all read prompts from
one session. Before shipping, record a few minutes of real use with other people
in the room and re-check the threshold. Short clips score lower, so very short
requests may need a lower threshold or no check.

## Real room recordings (2026-10-24)

`spikes/stt/real_noise.py` runs real noisy clips through Swift's own transcriber
and thresholds (`config.yaml`). The clips come from `corpus.py read --condition NAME`
with `prompts_noisy.txt`, which holds 8 sentences and 2 takes with nobody speaking.
The same sentences from the clean corpus are the baseline. So far there is one
condition: **tv**, a TV with people talking, in the owner's room, at normal
volume. Eight clips is a small sample, so read these numbers as a first check,
not a calibration.

| | WER | acted | noted | refused | mean p (p10 / p50) | speaker (p10 / p50) |
|---|---|---|---|---|---|---|
| clean (same sentences) | 0.136 | 88% | 12% | 0% | 0.46 / 0.89 | 0.43 / 0.82 |
| tv | 0.475 | 38% | 25% | 38% | 0.32 / 0.71 | 0.15 / 0.28 |

1. **`reject_p` 0.7 holds.**
   - It refused all 3 badly wrong transcripts. "Which files changed since the last
     commit?" was heard as "Which balance John suits the left?", with p 0.53.
   - It also refused the sentence invented from the TV with nobody speaking (p 0.57).
   - The other quiet take came back empty.
   - It refused no clean clip, and no nearly right noisy one: those scored p 0.81–0.98.
   - 0.65 would have refused the same clips. No noisy multi-word clip was fully
     correct, so how often 0.7 refuses a correct request in noise is still unmeasured.
2. **`unclear_p` 0.4 flagged real mistakes.** It named "Overlinger" (for "overlay
   focus") and "deadlock" (for "git log"). It missed a confident substitution:
   "**Remove** the variable … to assessment file" for "**Rename** … in the session
   file" was acted on at p 0.74, with no word below 0.4.
3. **Single words are the weak spot.** "Stop." over the TV was heard as "Sure."
   with p 0.71. "Sure" is an *approve* command, and single words are never
   refused. On an open confirm card, that would approve the action. Confidence
   doesn't separate these cases: the owner's clean "Stop." scored 0.46.
   *Fixed:* see "Approving by voice in noise" below.
4. **The speaker check would reject the owner in TV noise.** The owner's median
   score was 0.28, and 5 of 8 clips fell below 0.35. The TV-only clips scored 0.07
   and 0.12, but the lowest owner clip scored 0.15, so no threshold separates them.
   This is harsher than the synthetic 10 dB mix suggested. The check can't be a
   hard gate in this room.

## Approving by voice in noise

When the room is noisy, a voice "approve" on a confirm card no longer counts on its own.
The card says "Heard “Sure.”, but it's noisy here. Say “approve” again to go ahead, or
click." A second "approve" or a click goes ahead. "Reject", "stop" and Esc still
take effect at once. Anything else said in between starts the check over.

* **Noisy** means the room between words is louder than `stt.noisy_db` (−50 dBFS).
  This is measured as the 10th percentile of the 32 ms blocks in the recording,
  skipping the digital silence at the start of the stream (`Transcription.noise_db`).
  * The owner's clean clips measured −72 to −45: 2 of 40 counted as noisy.
  * The TV clips measured −49 to −31: all 8 spoken ones counted as noisy, including
    the "Stop." heard as "Sure.".
  * A false "noisy" costs one more word. A missed one could approve an action
    nobody asked for.
* **Word confidence is not used.** At 0.9 it would have held 35 of the owner's 40
  clean clips: "Stop." scored 0.46, lower than the misheard "Sure." at 0.71.
* The interaction log records `noise_db` for every voice request. A held approval
  records `held_for: "noise"` and, when it went through, `confirmed_twice`.
* Steady noise such as a fan counts too: the floor can't tell voices from other sound.

## More real conditions: music, 2 m (2026-10-24)

Same 8 sentences and 2 quiet takes, same room. **music** is music with vocals at
normal listening volume. **far** is a quiet room with the owner about 2 m from
the laptop mic, speaking normally. There was no fan to record.

| | WER | acted | noted | refused | mean p (p10 / p50) | room dB (min / p50 / max) | approve held |
|---|---|---|---|---|---|---|---|
| clean | 0.136 | 88% | 12% | 0% | 0.46 / 0.89 | −72 / −69 / −57 | 0% |
| tv | 0.475 | 38% | 25% | 38% | 0.32 / 0.71 | −46 / −39 / −32 | 100% |
| music | 0.068 | 88% | 0% | 12% | 0.62 / 0.92 | −51 / −45 / −37 | 88% |
| far | 0.085 | 100% | 0% | 0% | 0.83 / 0.89 | −67 / −62 / −56 | 0% |

1. **Music and distance are much easier than TV.** Music with vocals barely hurt
   recognition, and 2 m in a quiet room didn't either. A TV talking (speech
   *addressed* to the room) is still the hard case.
2. **`reject_p` 0.7 still holds.** Across all noisy multi-word clips it refused
   0 of 10 right transcripts and 3 of 3 badly wrong ones. The one music refusal
   was a real mistake ("Speaker Legal" for "fix overlay focus", p 0.62). No
   threshold from 0.65 to 0.8 changes this.
3. **Nothing was invented from music or a quiet room.** All four quiet takes came
   back empty. Only the TV produced invented text, and that was refused.
4. **`noisy_db` −50 separates quiet from noisy.** It held approvals on 100% of TV
   and 88% of music clips, and on none at 2 m or clean. "Stop." was heard
   correctly with music on. Moving to −54 would also catch the last music clip
   (−51), but across all 40 clean clips it would hold 9 (22%) instead of 2 (5%).
   −50 stays.
5. **`unclear_p` misses confident substitutions at a distance.** "Rename … to
   **2 seconds** in the session **phone**" and "**Showed the good luck** for the
   last two days" (for "show the git log") scored p 0.83 with no word below 0.4.
   These are acted on, with the agent left to notice. "good luck" → "git log" is
   a candidate for the learned word fixes (`learn_fixes.py`).

## Not done / next

* A fan or street-noise condition: none recorded yet. `noisy_db` will count
  steady noise as noisy, which is safe for approvals.
* No recordings yet of the owner saying "approve" or "yes" in noise: the threshold
  was checked on whole requests, whose pauses look the same to the floor measure.
* Larger models are the main reason cloud transcription holds up better in
  noise. Running one locally costs memory Swift doesn't have (see PLAN.md M2).
* Windows "Voice clarity" processing applies to the communications capture
  path. Swift opens the mic in default mode through PortAudio, which can't
  request it.
