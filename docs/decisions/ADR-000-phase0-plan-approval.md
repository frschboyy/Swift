# ADR-000: Phase 0 plan approval and owner answers

- **Status:** Accepted
- **Date:** 2026-10-15
- **Decided by:** Owner

## Context

Per §19 of `SWIFT_BUILD_PROMPT.md`, the Phase 0 plan (scaffold + spikes S1–S4) was presented in §16 format together with open questions. The owner approved the plan. ADR-001…004 stay reserved for the spike outcomes listed in §17.

## Decisions

| Topic | Decision |
|---|---|
| Repository | `C:\Users\frchi\Documents\Swift`, git, Phase 0 work on branch `phase0/scaffold`. The OpenOdin reference stays outside, at `Documents\odin` (§0.1). |
| Runtime | uv-managed CPython 3.12.14; `uv` for the venv and the hashed lockfile. |
| Wake phrase | **"Hey Swift" only.** S1 trains no alternates. If S1 misses the targets, the §17 exit options apply (verifier on, Porcupine, pretrained phrase, or relaxed target). |
| Audience | **Personal use for now.** Non-commercial components (pretrained openWakeWord models, NC-licensed Piper voices) are acceptable as fallbacks. The §15 license review is still required before any distribution. |
| Google account | **Personal Gmail**, using the owner's own Cloud project (S4). |
| Integrations | Connector-ready. See ADR-005. |
| S2/S3 execution | Run by the agent on the owner's machine (the target), reported as `PASSED (agent-run)` on target. |
| Corpus storage | Outside git (path set in config; default `%LOCALAPPDATA%\Swift\corpus`). |

## Defaults taken (owner did not object)

- Config models cover all §12 files. Sections not used in Phase 0–1 are stubbed with defaults.
- S1 verifier: compare `tiny.en` vs `base.en` on FA reduction and added latency.
- S3 corpus: typed utterances only in Phase 0. STT-derived utterances are added in Phase 2.
- Wake annotation is semi-automatic (faster-whisper word timestamps), with a 10 % owner spot-check.
- Candidate LLMs: `qwen3:8b`, `qwen3:4b`, `qwen3:1.7b`.
