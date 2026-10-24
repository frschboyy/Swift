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

**Caveat:** synthetic voices are far easier to tell apart than real people.
"Other accepted 0%" is optimistic, and the threshold must be set on recordings of
real other people before this ships.

## Not done / next

* Real room recordings. Synthetic noise is a proxy, and real reverb and distance
  hurt more. Recording a few noisy clips with `corpus.py read` and re-running both
  benches would confirm the thresholds.
* Larger models are the main reason cloud transcription holds up better in
  noise. Running one locally costs memory Swift doesn't have (see PLAN.md M2).
* Windows "Voice clarity" processing applies to the communications capture
  path. Swift opens the mic in default mode through PortAudio, which can't
  request it.
