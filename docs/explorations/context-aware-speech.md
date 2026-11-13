# Context-aware speech evaluation (2026-11-13)

- **Status:** investigation, not decided. No ADR. No production code changed.
- **Asked by the owner:** can Swift judge how likely and how fitting each recognised word is, instead of only comparing transcripts with known words? Which techniques from language modelling fit Swift, on this PC, local-first?
- **Builds on:** seams audit §7 (speech adapted by context), [`stt-noise.md`](../stt-noise.md), [`stt-vocab.md`](../stt-vocab.md), W-03 (merged 2026-11-13).
- **Spikes:** `spikes/stt/error_signals.py` (measures), `spikes/stt/error_signals_score.py` (scores). Read-only on the corpora.

## In short

1. **Swift's engine is Parakeet, not Whisper.** Whisper is installed as a second engine and three Whisper models are on disk. That makes Whisper available as a second opinion at no download cost.
2. **Parakeet's own word probability already ranks errors well** (AUC 0.87 on 681 labelled words). Swift uses it at one strict threshold (0.4), which catches 23% of wrong words. Used for *flagging only*, a looser threshold catches 38% at 5% false flags.
3. **A second engine finds more, but not precisely.** Where Whisper base.en disagrees with Parakeet, 64% of wrong words are caught, and so are 18% of right ones. Good for monitoring, unsafe for correcting.
4. **Rescoring has a low ceiling today.** Picking perfectly between Parakeet's and Whisper's sentence would lift exactly-right sentences from 37 to 41 of 86. Parakeet decodes greedily and has no alternatives to rescore; the gap between its top two tokens adds nothing over the probability Swift already has.
5. **The hard class is untouched by every acoustic signal:** 32 of 118 wrong words were heard with probability 0.9 or more ("bean size", "distal"). Only context can catch those, and that is the one place a language model might earn its cost. It is unmeasured: it needs a model download.
6. **On the owner's own kept clips, every signal is near chance** (AUC 0.59 to 0.63). Those are the clips Swift got most wrong. More labelled data from real use matters more than any model.

**Recommendation:** build contextual evaluation first as an independent monitor that never changes a transcript. Let it act only inside closed sets (contacts, expected answers), each step gated by W-03. Decide on a language model by a spike with a kill criterion, not by assumption.

## 1. What exists

| Part | What it is | Where |
|---|---|---|
| Engine | Parakeet-TDT 0.6B v2, int8 ONNX, through `onnx-asr`; greedy decoding only: no beam, no n-best, no language model, no prompt | `stt/transcriber.py` `ParakeetTranscriber` |
| Second engine | `faster-whisper` 1.2.1 on CTranslate2; `base.en`, `small.en` and `distil-small.en` on disk (2.8 GB). Reports no word probabilities to Swift today | `WhisperTranscriber` |
| Confidence | Per word: the probability of its least likely token. `assess()` refuses a sentence averaging under 0.7 and marks words under 0.4 as unclear | `Word.p`, `UNCLEAR_P`, `REJECT_P` |
| After recognition | Silence gate, trim, word fixes (whole-word replacement), then intake and routing | `_transcribe_sync`, `stt/fixes.py` |
| Outcome signals | A clip is kept when Swift was unsure, the owner said it again, corrected it, or the request failed; 7 days | `stt/recordings.py` |
| Evaluation | The improvement pass: word error rate clean and with noise, the aggregate gate, and W-03's per-sentence gate, on the owner's test set | `stt/improve.py` |
| Corpora | `stt_corpus` 51 read clips, `stt_noisy` 30 (TV, music, far), `stt_testset` 15 kept clips with known words, 296 unlabelled clips in `audio` | `%LOCALAPPDATA%\Swift` |
| Runtimes installed | `onnxruntime` 1.31, `ctranslate2` 4.8, `tokenizers` 0.23, `numpy`. **Not installed:** torch, transformers, kenlm, sherpa-onnx, any local LLM | `.venv` |
| Hardware | i7-10610U, 16 GB (seams audit §7.2) | — |

Two consequences:

- A small language model or an embedding model in ONNX form would run on what is installed. It needs a model file, not a new dependency.
- Anything in torch (fine-tuning, most research code) needs gigabytes of downloads. It stays out, as the audit already concluded.

## 2. What the existing signals can detect (measured)

**Method.** 90 labelled clips, 86 with speech recognised, 681 recognised words. Each word is marked wrong when the alignment with the known sentence calls it a substitution or an insertion (118 wrong, 17%). Four signals per word:

- **Parakeet p:** the probability Swift already keeps.
- **Top-2 margin:** how far the chosen token was ahead of the runner-up, read from the decoder.
- **Whisper forced score:** Whisper base.en is made to read Parakeet's sentence against the audio (`find_alignment`), giving its probability for each of Parakeet's words. This is an audio-conditioned language model score, with no new download.
- **Whisper disagrees:** Whisper's own transcript doesn't have this word here.

| Signal | AUC, all | AUC, kept clips | Wrong words caught | Right words flagged |
|---|---|---|---|---|
| Parakeet p under 0.4 (today's rule) | — | — | 23% | 0.7% |
| Parakeet p, threshold moved to 5% false flags (about 0.59) | 0.87 | 0.62 | 38% | 5% |
| Top-2 margin | 0.85 | 0.59 | 34% | 5% |
| Whisper forced score | 0.84 | 0.63 | 42% | 5% |
| Whisper disagrees | — | — | 64% | 17.9% |
| p under 0.4 **and** Whisper disagrees | — | — | 23% | 0.5% |
| The three combined by rank | 0.87 | — | 53% | 5% |

By sentence: of 49 wrong sentences, 19 had a word under 0.4 and 46 had a Whisper disagreement. Of 37 right sentences, none had a word under 0.4 and 20 had a disagreement.

Engines compared: Parakeet got 37 of 86 sentences exactly right, Whisper base.en 21, either one 41.

**Whisper small.en as the second opinion:** a more precise judge at about three times the cost.

| | base.en | small.en |
|---|---|---|
| Wrong words it disputes | 64% | 66% |
| Right words it disputes | 17.9% | 10.3% |
| Right sentences with a dispute | 20 of 37 | 8 of 37 |
| p under 0.4 and a dispute: right words flagged | 0.5% | 0.2% |
| Three signals combined, wrong words caught at 5% false flags | 53% | 61% |
| Sentences it got exactly right alone / either engine | 21 / 41 | 34 / 42 |
| Confidently wrong words (32) it disputes | 7 | 6 |
| Added time per clip, p50 (forced score / own transcript) | 1.21 s / 1.33 s | 3.32 s / 3.63 s |

Small.en halves the false disputes, so it is the better second opinion for an idle-time monitor. It doesn't raise the rescoring ceiling (42 against 41) and doesn't see the confident errors either.

**Cost measured in the same run** (4 threads, Swift's backend also running): Parakeet p50 0.70 s per clip; the Whisper forced score p50 1.21 s more; Whisper's own transcript p50 1.33 s more. Clips p50 4.6 s long.

**What this shows:**

- The probability Swift already has is the best single signal. Swift throws most of it away by using one strict threshold for both "refuse to act" and "notice".
- The margin is redundant with it.
- A second engine sees a different half of the errors. Combined by rank it lifts detection from 38% to 53% at the same false-flag rate, at +1.2 s per clip. That is too slow for the live path and fine at idle.
- 32 of 118 wrong words were confidently wrong (p ≥ 0.9). Whisper disputed 7 of them. Nothing acoustic sees the rest.
- On the kept clips nothing works. They are 68% wrong words: once a sentence is mostly wrong, "which word" has no answer, and the right response is to ask again, which `assess()` already does.

**Limits of this measurement:**

- 118 wrong words is small; differences of a few points between signals are noise. The ranking of p, margin and forced score is a tie.
- Some "wrong" labels are spelling, not hearing ("Summarise", "pm", "README" split as "Read Me"). The scoring normaliser needs those cases before any bar is set.
- Deleted words (24) have no recognised word to flag, so no per-word signal can see them.
- The read corpus is developer prompts, not daily requests. Daily use hasn't happened yet.
- Timings were taken with Swift running; they are upper estimates.

## 3. The techniques, assessed

| Technique | Fits today's architecture? | What it can do | What it can't | Model | Overhead | Effort |
|---|---|---|---|---|---|---|
| **Acoustic confidence** (have it) | Yes, in place | Rank words by risk; 38% of errors at 5% false flags | Confident errors (27% of all) | none | 0 | Hours: a second, looser threshold for flagging |
| **Alternative candidates from Parakeet** | Partly: greedy only; alternatives need the custom decode loop of `boost_bench.py` | Closed-set scoring where the answer set is known (yes/no, contacts) | General rescoring: no n-best exists, and the margin carries no new information | none | tens of ms | Medium |
| **Second engine as candidate and judge** | Yes: Whisper and its models are installed | Catches 64% of wrong words as disagreement; an audio-conditioned score for each word | Precision: flags 18% of right words. Base.en is the weaker engine | Whisper base.en (on disk) | +1.2–1.3 s per clip, about +300 MB while loaded | Low for offline use |
| **Text language model: next-token probability, sentence plausibility** | Runs on `onnxruntime` + `tokenizers` with no new dependency | In principle the only signal for confident, wrong-in-context words ("bean size") | Tells unusual from wrong only weakly. Flags names, jargon and terse commands as unlikely. Knows nothing about the audio | A small causal model in ONNX int8, about 135 MB (SmolLM2-135M class, Apache-2.0). Size and licence of the exact file to be confirmed before any download | **Unmeasured.** Estimate: 30–100 ms per sentence, 250–400 MB | Medium, after a spike |
| **LM rescoring of candidates** | Only between Parakeet's and Whisper's sentences | At most +4 sentences of 86 with a perfect chooser | Anything neither engine heard | as above | LM cost plus the second engine's 1.3 s | Medium–high |
| **Word and sentence embeddings** | Runs on `onnxruntime` | Sentence level: spotting a repeat of the same request (an implicit "that was wrong" label); meaning-level scoring | Word-level error detection: "bean" and "beam" sit in sensible sentences either way, and a misheard sentence is usually still fluent | MiniLM class, 23–90 MB | Estimate 10–20 ms per sentence | Low–medium |
| **The owner's own lexicon** (contacts, app names, approved fixes, words from requests that went fine) | Yes: plain data Swift already holds | Protects names and jargon from being flagged; marks a word as never seen before | Doesn't detect errors alone | none | negligible | Low |
| **Meaning-level comparison:** does the heard sentence route and fill slots like the known one? | Yes: the router is deterministic and `eval/parity` already scores lanes | Separates errors that change what Swift does from errors that don't. Needs no labels beyond the known words | Agent requests, where meaning isn't a lane | none | milliseconds | Low |
| **The agent as reader** (seams audit method D) | Yes for agent requests | Passing "T / tea, may be misheard" lets the model that already reads the request use context | Local lanes (38% of requests), decided before any model reads them | Claude, already in the path | a few tokens | Low |

Not recommended now, as in the audit: fine-tuning or speaker adaptation (torch, hours of labelled audio), an n-gram model of the owner's text (a few thousand words is too little), a new main engine.

## 4. The six questions

**1. Which techniques can be built on the existing architecture?**
All of acoustic confidence, the second engine, the lexicon, the meaning-level comparison and the agent hint, with nothing new installed. A text language model and embeddings run on the installed runtimes but need a model file each. General rescoring is the poorest fit: Parakeet gives one hypothesis.

**2. Which lightweight local models?**
- **Second opinion:** Whisper small.en, already on disk: it disputes 10% of right words where base.en disputes 18%. At 3.3 s per clip it is for idle time only.
- **Text model, if the spike justifies one:** a causal model of about 135 M parameters in int8 ONNX. It is the smallest class that models sentences at all; anything larger competes with Parakeet for memory on a 16 GB laptop.
- **Embeddings:** none yet. The router-based comparison covers the same need for local lanes at no cost.

**3. Can acoustic errors be told from unusual but legitimate sentences?**
Only with two independent axes, and only partly.

| | Fits the context | Odd in context |
|---|---|---|
| **Heard clearly** | fine | Either a legitimate unusual phrase or name, or a confident mishearing. Acoustics can't tell; the lexicon and the language model are the only evidence |
| **Heard unclearly** | A sound-alike risk ("four"/"for") | Most likely an error |

Swift has the vertical axis today. The horizontal one needs the lexicon (cheap, personal) and possibly a language model (unmeasured). The top-right cell is where the owner's names and jargon live, so nothing in it may ever be corrected automatically.

**4. How to flag suspicious words without correcting names and unusual vocabulary?**
- Flagging and correcting are separate powers. The monitor flags; it never rewrites.
- A word in the owner's lexicon is never flagged for being unusual, only for being unclear.
- A flag needs two independent signals. Measured: p under 0.4 and a Whisper disagreement flags 0.5% of right words.
- Correction happens only inside a closed set that Swift already knows (the contacts in a name slot, the answers to an open question), and only when the candidate wins by a margin. A bonus is never added (W-07).
- Report false flags on protected words (names, jargon) as their own number, never folded into an average.

**5. Rescoring, or monitoring first?**
Monitoring first. The evidence: no n-best, a redundant margin, a ceiling of +4 sentences in 86 for two-engine rescoring, and a general language model that is unmeasured and biased against exactly the words the owner cares about. A monitor can be wrong without harm, produces the labelled data Swift lacks (W-04), and builds the test set that any later rescoring must pass.

**6. Overhead.**

| Approach | Latency | Memory | Disk |
|---|---|---|---|
| Looser flagging threshold on p | 0 | 0 | 0 |
| Lexicon check | under 1 ms | negligible | kilobytes |
| Router comparison (evaluation only) | milliseconds per pair | 0 | 0 |
| Whisper second pass | base.en +1.2–1.3 s per clip, small.en +3.3–3.6 s (measured) | about +300 MB for base.en while loaded (audit); small.en not measured | 0, on disk |
| Small text model | 30–100 ms per sentence (estimate) | 250–400 MB (estimate) | about 135 MB |
| Sentence embeddings | 10–20 ms (estimate) | under 200 MB (estimate) | 23–90 MB |

Estimates are marked as such; the spike in step 3 replaces them with measurements.

## 5. Proposed architecture

Three layers. Only the first exists.

```
audio ──► Parakeet ──► words + p ──► assess ──► intake / routing        (live path, unchanged)
              │
              ▼  (saved clips only, at idle, never while locked)
        ┌─ Evidence ─────────────────────────────────────────────┐
        │ per word: p · second opinion · in the owner's lexicon? │
        │ per sentence: outcome (said again, corrected, failed)  │
        └───────────────┬────────────────────────────────────────┘
                        ▼
                  Suspicion score ──► the labelling card, the improvement
                  (flags, never       pass's report, content-free counts
                   rewrites)          in the log
                        │
                        ▼  (later, each gated by W-03)
                  Closed-set actions: contacts in a name slot,
                  expected answers, a hint to the agent
```

- **Evidence** is a small module beside `stt/improve.py`, fed by the improvement pass. It runs on clips Swift already keeps, when the owner is idle, so the second engine's 1.3 s costs nothing the owner feels.
- **The suspicion score** starts as a rule (two signals agree), not a trained model: 118 wrong words can't train one honestly.
- **The lexicon** is built from contacts, app names, approved word fixes and the words of requests that finished cleanly. That is the owner's own words, so it respects the memory rule. Nothing a worker read goes in.
- **W-03 stays independent.** It compares outcomes on known sentences and knows nothing of these signals. Every later step that can change a transcript must pass it with no sentence going from right to wrong. The monitor is never used to excuse a W-03 failure.

Product rules it must keep: audio never leaves the PC; the log gets scores and counts, never words; nothing runs on speech while locked; a suspicion flag never approves, answers or blocks anything.

## 6. Evaluation methodology

**Data.** The three labelled sets, frozen as a baseline, plus what the labelling card adds. Fix the normaliser's spelling cases first. Report the read, noisy and kept sets separately: they behave differently.

**Detection** (is the flag right?):
- per word: AUC, and wrong words caught at 1% and at 5% right words flagged;
- per sentence: wrong sentences with a flag, right sentences with a flag;
- false flags on protected words, as a separate line;
- a bootstrap interval on every number, since the sets are small.

**Meaning** (did the error matter?): route the known sentence and the heard sentence, and count the pairs that land in a different lane or fill a slot differently. This is the "more than exact comparison" measure, and it needs no model.

**Correction** (when something may change text): exactly-right sentences, word error rate, and W-03's rule on all sets: no sentence that was right goes wrong.

**Cost:** p50 and p90 milliseconds and peak memory, measured with Swift idle.

**Bars:**
- A signal joins the monitor only if it adds detection at 1% false flags over Parakeet's p alone, outside its bootstrap interval.
- Anything that changes a transcript needs zero W-03 regressions, and its confidence bar scored on the owner's saved clips (`CLAUDE.md`).
- A model that costs a download is dropped if its spike doesn't meet the first bar.

## 7. Roadmap, in priority order

| # | Step | Needs | Why this order |
|---|---|---|---|
| 1 | **Make the measurement solid.** Fix the normaliser's spelling cases; add the meaning-level comparison; extend W-03's per-sentence gate to the read and noisy corpora (seams audit G) | nothing new | Every later decision reads these numbers. It also finishes W-03's coverage |
| 2 | **Monitor v0, no downloads.** A looser flagging threshold on p; the lexicon; Whisper small.en as a second opinion at idle on kept clips; flags feed the labelling card (seams decision 7, still the owner's to confirm) | the owner's yes on the labelling card | Produces labelled real-use data, which is the bottleneck (W-04) |
| 3 | **Spike: does a small text model see the confident errors?** Score the 32 confidently wrong words and the protected words. Kill it if it doesn't add detection at 1% false flags | the owner's OK for one model download (about 135 MB; file, source and licence confirmed first) | The only untested idea with a plausible payoff; cheap to disprove |
| 4 | **Act inside closed sets.** Contacts in a name slot (audit method A), expected answers while a question is open (C), the hint to the agent (D) | step 1's gate | Where accuracy gains were actually observed (audit §7.2) |
| 5 | **General rescoring or embeddings,** only if step 3 passes its bar or step 1's meaning measure proves too coarse | evidence from 1–3 | Low measured ceiling today |

Steps 1 and 2 need no decision about models. Step 2 touches what the owner sees (a card), so it gets owner checks when built.

## 8. Not verified

- Every figure for a text model or an embedding model is an estimate. Nothing was downloaded.
- Whether the exact ONNX file of a 135 M model exists at the size and licence assumed.
- Timings with Swift idle.
- Whether daily-use speech behaves like these corpora. The kept set suggests it is harder.

## Sources

- [ASR Rescoring and Confidence Estimation with ELECTRA](https://arxiv.org/pdf/2110.01857): a rescorer trained to detect errors doubles as word-level confidence.
- [Towards interfacing large language models with ASR systems using confidence measures and prompting](https://arxiv.org/pdf/2407.21414): use ASR confidence to limit which words a language model may touch.
- [ProGRes: Prompted Generative Rescoring on ASR n-Best](https://arxiv.org/pdf/2409.00217): language-model scores interpolated with ASR confidence over an n-best list.
- [SmolLM2-135M-Instruct](https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct/tree/ee72e5415c002e8fc0566a191a07c0b2b708875a): Apache-2.0; an int8 ONNX file of about 137 MB is listed.
