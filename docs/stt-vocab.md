# Vocabulary boosting for Parakeet (2026-10-24)

The question: Parakeet takes no prompt, and most of its real mistakes are project
jargon ("deadlock" or "good luck" for "git log", "bean size", "distal", "Tori").
Can the decoder be nudged toward a list of known words and phrases, and does that
make it invent those words when they weren't said?

Short answer: a small bonus (2) fixes a few jargon errors and invented nothing
in real speech, but the gain is small and it comes from a list built from the
test sentences. Larger bonuses fix more and start inventing words, including
after a lone "Stop.". Not wired in; see "If it goes in" below.

## Method

`spikes/stt/boost_bench.py` copies onnx-asr's greedy TDT loop
(`_AsrWithTransducerDecoding._decoding`) and adds phrase boosting. It works
outside site-packages: it calls the model's own `_decode` and `_encode`. Each
clip is encoded once and decoded once per setting. With no boosting, the copy
gives the library's output exactly (the script checks this).

* **Matching.** A prefix trie over the phrases' *text*, walked one token at a
  time. Any token whose text keeps the match on a phrase counts. Piece
  sequences don't work: vocab.txt has 1024 short pieces and no scores, and the
  model's own spelling isn't the shortest one ("overlay" comes out as " over" "l"
  "ay", "config" as " con" "f" "ig"). Each phrase is matched as written, in
  lower case, with a capital first letter, and with every word capitalized.
* **Bonus.** At a word start, tokens that begin a phrase get `bonus` added to
  their logits. Inside a phrase, only the tokens that continue it get the bonus,
  so the model decides on its own where the word ends. A phrase counts as said
  only when a word boundary or the end of the clip follows it, so "overlay" plus
  "s" doesn't count.
* **Take-back.** NeMo's phrase boosting subtracts the bonus from beam hypotheses
  that don't finish a phrase. Greedy decoding has no hypotheses to fix up after
  the fact, so this goes back instead: if a phrase isn't finished and the bonus
  changed any token since the phrase began, decoding returns to that point and
  runs without bonuses until that attempt is over. Shorter phrases inside longer
  ones ("git" in "git log") get their own return point.
* **Confidence.** Swift's per-word probabilities (`words_from_tokens`, then
  `assess` with unclear_p 0.4 and reject_p 0.7) come from the *unboosted*
  distribution, so they report what the model itself thought.

Vocabularies:

* **hand**: 23 phrases in `spikes/stt/vocab_hand.txt` (git log, beam size,
  distil, executors, overlay, Tauri, README, PLAN.md, config.yaml, ...). **Taken
  from the test sentences, so it flatters the result**: every phrase on it is
  known to occur in the test set.
* **auto**: 312 names gathered from git: tracked file and folder names, their
  stems, and branch names, with `_` and `-` read as spaces ("test voice.py",
  "noise conditions"). It covers about half of the jargon in the sentences and
  many common words ("tests", "main", "docs", "audio", "swift").

Test sets: the clean corpus (`stt_corpus`; 51 clips now, including 11 labelled
real requests), the real noisy corpus (`stt_noisy`: tv, music, far, 8 sentences
each, plus 2 quiet takes per condition), babble mixes at 5 and 0 dB SNR (as in
`noise_bench.py`), and 50 noise-only clips (white, pink, hum, static and babble,
10 each, at -35 dBFS). For WER, "x.y" in a transcript counts as "x dot y", the
way the reference sentences are written. So the clean baseline is 0.116 here,
not the 0.15 reported earlier.

## Results

WER by setting (spikes/stt/results/boost-20261024-180102.json):

| Setting | clean | tv | music | far | babble 5 dB | babble 0 dB | new boosted words in speech / babble / noise-only |
|---|---|---|---|---|---|---|---|
| none | 0.116 | 0.475 | 0.068 | 0.085 | 0.600 | 0.996 | — |
| hand, bonus 2 | **0.105** | 0.458 | 0.051 | 0.051 | 0.600 | 0.996 | 0 / 1 / 0 |
| hand, 4 | 0.103 | 0.458 | 0.051 | 0.051 | 0.593 | 0.996 | 0 / 3 / 0 |
| hand, 6 | 0.096 | 0.458 | 0.051 | 0.051 | 0.578 | 0.983 | 1 / 18 / 1 |
| hand, 8 | 0.109 | 0.424 | 0.051 | 0.051 | 0.593 | 1.013 | 5 / 34 / 2 |
| hand, 10 | 0.158 | 0.441 | 0.085 | 0.051 | 0.672 | 1.033 | 16 / 71 / 3 |
| auto, 2 | 0.109 | 0.441 | 0.068 | 0.085 | 0.595 | 0.991 | 0 / 9 / 0 |
| auto, 4 | 0.109 | 0.441 | 0.068 | 0.186 | 0.611 | 1.007 | 3 / 29 / 0 |
| auto, 6 | 0.116 | 0.407 | 0.068 | 0.119 | 0.613 | 1.002 | 9 / 60 / 4 |
| auto, 8 | 0.151 | 0.424 | 0.119 | 0.119 | 0.624 | 0.993 | 25 / 77 / 9 |

"New boosted words" counts clips where a boosted word appears that is in neither
the reference nor the unboosted transcript. Each noisy condition has only 8
sentences, so one fixed word moves its WER by about 0.02 to 0.03.

What changed on real speech:

* **hand, 2**: "deadlock" → "git log" (clean), "good luck" → "git log" (far),
  "to do's" → "to-dos" (clean and music), "back test" → "backtest", "Fix
  Overlinger" → "Fix Overlay" (tv; "focus" is still missing). Nothing invented.
* **hand, 4 to 6**: also "sessions.py" → "session.py", "Tori" → "Tauri" and
  "bean size" → "beam size", which need 6. At 6 "Search the codebase" became
  "Spikes the codebase".
* **hand, 8**: "distal" → "distil" too, but "What's the difference" became "What
  spikes", and "tell me about your day" became "tell me about README".
* **auto, 2**: "test" → "tests", "wakeword" → "wake word", "test voice dot py" →
  "test voice.py". Not "git log" (the list has no "git log"; "deadlock" stays).
* **auto, 4**: "Stop." became "Stop audio, and the other one is" (far), and
  "hard key" became "hard key unit". This is the failure that matters most for
  a voice agent: a boosted word starts in the silence after the speech, and the
  model carries on from it.

**Inventing words.** Noise with nobody speaking stayed empty at every setting.
Take-back removes any unfinished phrase the bonus started, and on steady noise
the model doesn't start one. Babble, the case where the model already invents
sentences, is where boosted words show up: "In the jars" → "In the jarvis" at
hand 2, and from bonus 6 the boosted words appear constantly ("Overlay has a
meeting with the team next Thursday", "My name is Dan README"). Of the quiet takes in the real noisy corpus, one (tv) already had invented
text. Only auto at bonus 8 added a second.

**Confidence checks.** With unboosted probabilities, a word the bonus fixed
keeps the model's low probability for it. Most fixes moved a transcript from
"clear" to "partly" (Swift acts and names the uncertain word): "git log" in the
far take, "backtest", "Tauri", "beam size". At high bonuses some moved to
"unclear" (Swift refuses): "Show the git log" at hand 8. The thresholds still
work as calibrated: they say how sure the *model* was. A boosted
fix is often flagged, which is honest, and refusals on invented text still
work because invented text keeps its low probabilities. Using the boosted
distribution instead would change the outcome on 12 to 38 clips per setting,
which is how many boosted choices the checks would stop seeing.

**Latency.** Decoding with boosting took 35–49 ms per clean clip at the median,
against 31–33 ms without (p90 58–74 vs 52–56 ms; max 172 vs 118 ms). The
encoder takes about 1 s per clip on this machine while it is loaded (other
sessions were running benches, with 0.7 GB RAM free), so the decoder's extra
cost is around 1% of a request. At bonus 10 the
worst clip took 6 s in the full run, because of repeated take-backs.

## Verdict

* Bonus 2 with a curated list is a small, real win: clean WER 0.116 → 0.105,
  the two worst real-world errors ("deadlock", "good luck" for "git log") fixed,
  and nothing invented in real speech. The list came from the test sentences,
  though, so a list written without seeing them would do less.
* The auto-gathered list helps less (0.109) and is riskier. It is mostly common
  words that are also file names ("tests", "main", "audio"), and those get
  inserted into babble even at bonus 2. A useful automatic list would need
  filtering: drop dictionary words, keep only names with odd spellings.
* Bonus 4 and up isn't safe: the gains are a few more words, and the cost is
  invented words in real speech, including after "Stop.".
* Learned word fixes (`learn_fixes.py`) handle the same top errors ("deadlock"
  → "git log") deterministically, with no risk of insertion. Boosting adds value
  for mishearings that haven't been seen yet and for words that need context
  ("bean size"), but only at bonuses that already cause trouble.

Recommendation: don't turn it on yet. If it goes in, use bonus 2 and a short
hand-kept list of real jargon, off by default, and measure it on recordings made
after the list was written.

## If it goes in (sketch, not wired)

* Settings (`SttSettings`): `boost_phrases: list[str] = []` and
  `boost_bonus: float = Field(0.0, ge=0.0, le=4.0)`. 0 or an empty list means
  off, which is the default.
* `ParakeetTranscriber._load_model`: if boosting is on, build `Phrases` from the
  list and `model.asr._vocab`, then replace `model.asr._decoding` with a method
  that runs `decode()` for each clip in the batch and yields
  `(ids, steps, logprobs)`. `recognize()`, `words_from_tokens` and `assess`
  stay as they are, and the logprobs stay unboosted. This relies on private
  onnx-asr names (`_decode`, `_create_state`, `_blank_idx`, `_vocab`,
  `_max_tokens_per_step`), so pin onnx-asr to 0.12.x and add a unit test that
  compares unboosted output against the library.
* Move `Phrases`, `boundary` and `decode` from the spike into
  `src/swift/stt/boost.py` with tests: take-back, the word-boundary rule, and no
  bonus inside a quiet stretch.
* Log `raw_text` and the boosted words used, so `learn_fixes.py` and the owner
  can see what boosting changed.

## Not done

* A held-out check: sentences recorded after the list was written.
* Filtering the auto list (dictionary words out), which is the obvious next try
  for an automatic list.
* Beam search with real NeMo-style scoring. onnx-asr only does greedy decoding.
  A beam would make take-back exact, but it multiplies decoder calls.
