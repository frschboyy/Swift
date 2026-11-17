# Correcting what Swift heard: a feedback loop for speech recognition

**Status:** first slice built on `claude/stt-corrections` (2026-11-17); owner decisions open (§5).

## 1. What the owner asked for

Wherever Swift shows the words it heard, a small flag opens a pane where the owner marks the part that's
wrong, says what kind of mistake it was, and types what they said. Each correction is kept with its clip and
feeds evaluation, a report of recurring failures, and later speech-pipeline work. A subtle hint says
corrections help; it never nags.

## 2. What already exists, and what this reuses (one owner each)

| Need | Owner today | This slice |
|---|---|---|
| Clips and their metadata | `stt/recordings.py`, `index.json` (id, source, flags, confidence, outcome, `known`) | A correction is one more write to the same entry: flag `corrected`, `known`, `heard`, `kind` |
| Known words → evaluation | `Recordings._to_test_set`; read by `stt/improve.py` (weekly pass) and `eval/stt/gate.py` | A corrected clip goes into the test set the same way a repeat does: both pick it up with no change |
| Typing on screen | the text box pane (`pane.ts drawType`, the one window that takes the keyboard) | The same pane in a *fix* mode: no second keyboard window, no Rust change |
| Heard words on a card | `main.ts headRow` (the owner's words on every card's head) | The flag sits there, after the words |
| Card hints | Halo SPEC §3 row 6 | One hint kind, `heard-fix`, counted in the overlay's prefs |
| Reports | `eval/stt` (gate), `spikes/owner_checks` | `eval/stt/corrections.py`, reading the test set and the index |

Seams decision 7 (a weekly labelling card) and ui-reach §5 gap 2 (repair by typing) are the same idea from two
ends. This slice is the "at the moment" end; the weekly card can later list unlabelled flagged clips through the
same `Recordings.correct`.

## 3. How it works

1. The final `transcript` frame carries `clip`: the interaction id, only when that request's audio was saved
   (recordings on, a spoken request). No clip, no flag: typed requests and recordings off show nothing.
2. The card's head row shows a flag after the heard words (tooltip: "Heard that wrong? Correct it: it helps
   Swift learn your voice"). **Not on a Needs your OK card** (§5 D2).
3. A click sends `recordings {action: "fix_open", clip}` (the clip is kept past its 30 s hold while the owner
   types) and opens the text box in fix mode: the heard words, all selected; a row of kinds; Enter saves,
   Esc closes. Selecting part of the words and typing over it is how the owner marks the wrong part: the
   saved correction is the whole sentence as meant, and the report aligns it with what was heard word by word.
4. Enter sends `recordings {action: "fix", clip, heard, said, kind}`. `Recordings.correct` checks the clip
   and the kind, writes the entry (now or, while the request still runs, when it finishes), and copies the
   clip into the test set with its metadata.
5. A card hint ("Heard something wrong? The flag corrects it, and helps Swift hear you better.") shows on
   at most 3 cards, stops once the flag is used, never on Needs your OK.

**Kinds:** `wrong_word`, `missed_word`, `extra_word` (heard words nobody said), `name`, `accent`
(accent or pronunciation), `background` (someone else's speech or noise), `cut_off`, `other`.

**Stored with each correction** (index and test set, local only): the heard words, the corrected words, the
kind, the time, confidence, peak and noise dB, source (wake, hotkey, follow-up…), and the speech model label
(`stt.model_label`: engine and model). Never in `swift.log`: the log line says a correction was saved, its kind
and nothing else.

## 4. Product rules

- **Typed words never approve.** The fix pane's Enter only saves a label. It never sends a request, never
  presses a card button (Tab doesn't reach the card in fix mode), and the flag isn't drawn on a confirm card.
  The backend's `fix` path writes a file and nothing else.
- **Audio never leaves the PC; `swift.log` holds no content.** Unchanged: corrections live in `index.json`
  and the test set, deleted by "Clear saved recordings".
- **No automatic rewrites.** A correction becomes test data, never a heard-to-meant replacement (word fixes
  were removed on 2026-11-17).
- **Change to a promise:** `recordings.py` said the index never holds a transcript. It now holds the heard words
  of a clip **the owner chose to correct**, next to the words they typed. `privacy.md` says so.

## 5. Open decisions for the owner

| # | Question | Recommendation |
|---|---|---|
| D1 | **Fine-tuning on corrections.** Today audio and words are never used to train a model. Training on corrections (locally, e.g. a Parakeet adapter or a wake-word refit on the `missed_wake` and "swift" clips) would change that promise and `privacy.md`. | Not yet. Collect for a few weeks, read the report, then decide with numbers |
| D2 | **The flag on Needs your OK cards.** Typing never approves, but a keyboard pane opening over a confirm card is the edge a second reviewer should look at. | Leave it off confirm cards (built that way) |
| D3 | **How long corrections are kept.** Corrected clips join the test set (kept past `keep_days`, `test_set_max` 200, oldest dropped). | As built; revisit if the set fills |
| D4 | **The weekly labelling card** (seams decision 7, "Yes"): list flagged clips without words and let the owner type them. | Next slice, through the same `Recordings.correct` |
| D5 | **Correct by voice** ("no, I said …") already gives known words for a repeat; should a spoken correction also ask the kind? | No: keep voice repair quiet |
| D6 | **The hint's words and count.** 3 cards, stops once used. | As built |

## 6. Not built in this slice

The flag on rows, the stack, the live view and question cards (only the card head row); the weekly labelling
card (D4); correcting a missed wake (a `missed_wake` clip has no heard words on screen); charts (the report is
text and JSON); any change to the speech pipeline itself.

A correction of a clip whose request isn't one the recordings note (a spoken answer to Swift's question, source
`answer`) is dropped when that request ends: such clips have no index entry to label yet.
