# Recordings that earn their keep (audit B-06): status

Branch `claude/busy-wiles-de06e3`, fast-forwarded from main `50f8e0f`. Not pushed, not merged.

## Done

- **Retention.** `audio.keep_days` (default 7; 0 saves nothing). Clips are swept at start-up and daily. Unflagged clips are deleted 30 s after their request. Logs carry counts only. The code is `src/swift/stt/recordings.py`.
- **Flagging.** Each clip's flags go in `index.json` next to the clips: `unsure`, `say_again`, `repeated` (a repeat or correction, which gives the known words), `missed_wake` (held in RAM 6 s) and `failed`. The index holds no transcripts.
- **Test set.** Flagged clips with known words go to `stt.test_set_dir`, capped by `audio.test_set_max` (200), the oldest dropped first.
- **Clearing.** The tray's **Clear saved recordings** (pane and native menu) wipes the clips, both indexes and the test set.
- **Improvement pass.** It runs from the tray's **Improve speech recognition** and weekly while idle. The code is `src/swift/stt/improve.py` and `src/swift/executors/improve.py`.
  - Word fixes are proposed on one confirm card. Nothing is applied without approval. Rejected fixes are never proposed again.
  - WER is measured clean and with pink noise at 10 dB, compared with the last pass on the clips both passes saw.
  - `endpoint_feed.json` is written for end-of-speech tuning. It holds no words.
  - `spikes/stt/model_compare.py --sets kept` runs the test set as its own set.
- **Docs.** `docs/stt-models.md` §Recordings, threat model T14 plus a privacy section, the audit's B-06 row, README, `config.example.yaml`, and owner checks 110-116 with their report lines.
- **Tests.** `tests/unit/test_recordings.py` (30 tests) covers retention, flagging, the cap, wiping, the card, the report, and a run with no network. Overlay `tsc` is clean, `npm test` passes 73, and `cargo check` is clean. The full pytest run on the final tree passed 1161.

## Left, in order

1. The owner runs owner checks 110-116.
2. Phase C reads `endpoint_feed.json` (see the shared note `recordings-b06.md`).
3. Separately from this task: `logging_setup.CONTENT_KEYS` doesn't redact `transcript_heard`, `transcript_raw` or `unclear`. This is suspected from the code; the current log has 0 such lines.

## Decisions taken by default

- `stt.save_audio: true` now means `audio.keep_all`: every clip, but still only for `keep_days`. The owner's config has it on, so remove it to keep only the useful clips.
- **Clear saved recordings** asks for no confirmation. Deleting is the safe direction.
- Proposed word fixes need only one sighting, as in `learn_fixes.py`. The card is the safeguard.
- `failed` means status `error` and not a say-again error. Cancelled and rejected requests aren't flagged unless they were repeated.
- The word-fix card waits 5 minutes. Unanswered, it is asked again on the next pass.
