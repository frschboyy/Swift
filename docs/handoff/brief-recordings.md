# Brief: recordings that improve hearing (7-day loop)

This is the task as given to the session on branch `claude/busy-wiles-de06e3` (2026-10-28). To resume it, check that branch and worktree first (see `README.md` §2).

The owner approved keeping voice recordings for **7 days**, but only if they serve a purpose. This is audit finding B-06 (`docs/audit/2026-10-audit.md`): `stt.save_audio` is on, with about 148 clips (27 MB) in `%LOCALAPPDATA%\Swift\audio`, growing, never deleted, and holding room and bystander audio.

Earlier spikes already used the owner's clips by hand:
- the model comparison (`docs/stt-models.md`, `spikes/stt/model_compare.py`);
- noise-gate tuning (`docs/stt-noise.md`, `noise_bench.py`);
- word-fix learning (`spikes/stt/learn_fixes.py`);
- a speaker check for future voice ID.

## Build

1. **Retention:** delete clips older than 7 days, at start-up and daily. The setting is `audio.keep_days: 7` (0 = don't save). Log counts only.
2. **Flagging:** when a clip is saved, mark it useful when any of these hold. Record why in a small local index (content-free metadata, plus the known words where the owner supplied them):
   - low STT confidence;
   - "say it again" was asked;
   - the owner repeated or corrected themselves within a few seconds (the repeat gives the intended words);
   - a missed wake phrase;
   - a failed request.
3. **A test set:** flagged clips with known words are copied into a permanent local test set, capped at about 200, oldest dropped first. Add a "Clear saved recordings" item in Settings or the tray that wipes both the clips and the test set.
4. **An improvement pass,** on demand and weekly, on the PC only:
   - word-fix learning on the test set, proposed as a card the owner approves (never applied silently);
   - model and noise regression checks, reporting if accuracy drops;
   - feed end-of-speech tuning.

   No model training.
5. **Document it:** in `docs/stt-models.md` / the audit doc, and the privacy statement in `docs/threat_model.md`. Audio and transcripts never leave the PC.

## Proof

- Tests for retention, flagging, the cap, wipe, and nothing leaving the machine.
- Run every suite, as in `CLAUDE.md`.
- Owner checks numbered from **110**.
- Never quote clip transcripts in logs or docs.
- Avoid `swift/dialogue.py`, which belongs to Phase C.
