# Is a better local speech model worth it? (2026-10-27)

The owner checks at 17:00 needed shouting and careful pronunciation, and several hotkey requests
were refused as unclear. This note covers two questions. Would a different local model do better?
And what did the evidence say about the microphone?

## Method

`spikes/stt/model_compare.py` ran each model over the owner's own recordings, on this laptop (4 CPU
threads). Nothing was uploaded, and every clip went through Swift's own silence gate and trim first.

- **read**: 51 labelled read prompts from `stt_corpus` (a quiet room, 23 Oct).
- **noisy**: 24 labelled prompts from `stt_noisy` (a TV, music, two metres away).
- **checks**: 34 hotkey and wake recordings from the 17:00 checks (`spikes/stt/checks_1027.jsonl`).
  - The intended words come from the check script, or from the owner saying it again right away. Clips whose words aren't known were left out.
  - 8 of them are ones Swift got wrong or refused that day.

WER is measured after light normalization: case, punctuation, "3" vs "three", "p.m." vs "pm", "TestMe" vs "Test Me", and "um"/"uh".

## Results

| Model | WER read | WER noisy | WER checks | on the 8 failed | ms per clip (median) | load | memory |
|---|---|---|---|---|---|---|---|
| **parakeet-tdt-0.6b-v2 int8 (now)** | **0.123** | **0.209** | **0.050** | **0.22** | 820–950 | 12 s | 0.7 GB |
| parakeet-tdt-0.6b-v2 fp32 | 0.136 | 0.260 | 0.078 | 0.33 | 1,120–1,260 | 22 s | 2.2 GB |
| parakeet-tdt-0.6b-v3 int8 | 0.184 | 0.429 | 0.199 | 0.41 | 700–830 | 9 s | 0.7 GB |
| Whisper large-v3-turbo (int8, beam 5, VAD) | 0.127 | 0.271 | 0.117 | 0.26 | **27,000–29,500** | 11 s | 3.1 GB |

What the failed clips became:

| Said | v2 int8 (now) | v2 fp32 | v3 | Whisper turbo |
|---|---|---|---|---|
| Research green tea | Rinster's green tea | Richard Green Tea | Record green tea | Research green tea |
| Hey Swift, undo that | Hey thrift, undo that | Hey thrift, undo that | Hey first, I'll do that | Hateslift, undo that |
| Hey Swift, research about Mozart | Hey Crift, research about um Mozart | (same) | A research about um Mozart | Heathcliff research about Mozart |
| Cancel Swift check | Cancel Swift Stack | Cancel SwiftStec | Council with the same | Cancel SwiftStack |
| Hey Swift, write a haiku about rain | Hey Swift Ride a Haiku about Rain | (same) | Right a haiku a barrain | write a haiku about Reina |

## Decision: keep parakeet v2 int8

- **The fp32 build is not better.** It is slightly worse everywhere, 30% slower, and three times the memory. Quantization isn't what loses words.
- **Parakeet v3 is worse on this voice.** It is multilingual, and it lost words a v2 caught: WER 0.43 in noise against 0.21.
- **Whisper large-v3-turbo can't be used on this CPU.** It takes about 29 s per clip, against under 1 s now. Its accuracy is no better overall either. Only a GPU would change that, and this laptop has none for it.
- **What fails is the same in every model:** the name "Swift" after "hey", the names "Test Me" and "Swift check", and short words said hard ("write", "research"). No model fixes them. So the fixes are in Swift, not in the model:
  - **The name.** A misheard name at the start of a hotkey request ("Hey Crift", "Hey thrift") is now set aside before Swift judges how sure the model was. So are "um" and "uh". Two of the day's refusals, at 17:40 and 17:59, began that way.
  - **Say it again.** A request that is still mostly guesses gets "I didn't catch that. Try saying it again." instead of an action. This now covers wake requests and replies too, which used to act on any guess.
  - **Word fixes.** The owner can add these through `spikes/stt/learn_fixes.py`, which asks before saving each one. Candidates from today: "swift stack" / "swift deck" / "swiftstec" → "Swift check", and "hethme" / "testme" → "Test Me". Swift doesn't write fixes by itself.

## The microphone (Intel SST array): gain and AGC

| Recordings | Loudest moment | Speech (median) | Room between words | Clipped |
|---|---|---|---|---|
| Read prompts, 23 Oct | -13.5 dBFS | -23.9 | -56.8 | none |
| Checks, 27 Oct | -12.0 dBFS | -21.7 | **-70.2** | none |

- **Gain is fine.** Speech peaks around -12 dBFS and nothing clips. Software gain would only raise the noise as well.
- **The room measured 13 dB quieter on 27 Oct** with the same laptop. That points to the array's own noise suppression (Windows "Audio enhancements" / Intel's voice processing) cutting hard between words. That kind of processing also clips the starts and ends of words, which is what the model got wrong.
  - Swift doesn't change Windows settings.
  - It is worth one try by the owner: Settings → System → Sound → Microphone Array → Audio enhancements: Off. Then repeat checks 43–48 and compare `stt_confidence` in the report.

## Settings changed with this (wake listening)

| What | Before | Now | Why |
|---|---|---|---|
| Speech gate | level > 0.3 (about -46 dBFS), always | room + 0.2 (about 10 dB), at least 0.12 | In a quiet room, a normal voice was under the fixed bar. |
| Pause that ends an utterance | 0.6 s | 0.8 s | Words said one by one were split into two utterances. |
| Longest utterance | 6 s | 10 s | In one 5-minute window, 7 utterances were dropped as too long. |
| A reply without "hey Swift" | any speech, sureness ≥ 0.5 | sureness ≥ 0.7 (`wake.followup_min_p`), at least 18 dB over the room between its words, no more than 18 dB below the owner's own requests, at most 8 s | A TV became two requests (17:31:39, 17:32:05). |

The VAD choice stays as it was: level-based in Swift, no Silero VAD before Parakeet. The 24 Oct comparison found that Silero dropped short and quiet requests whole.
