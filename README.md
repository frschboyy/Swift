# Swift

A passive, voice-activated desktop agent for Windows. The authoritative specification is [`SWIFT_BUILD_PROMPT.md`](SWIFT_BUILD_PROMPT.md).

**Status:** Phase 0 (scaffold and risk spikes). Nothing runs as an agent yet.

## Development setup

Requires `uv` and CPython 3.12 (64-bit).

```powershell
uv sync --frozen          # install exactly what uv.lock pins
uv run python -m swift --version
uv run pytest
```

## Layout

See §13 of the spec. Decisions are recorded in [`docs/decisions/`](docs/decisions/).
