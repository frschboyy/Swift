# Cross-platform readiness: a note for a later decision

The owner saved this on 2026-11-15 to look at later (handoff §5, decision 29). It is outside advice the owner
pasted in, kept here in short form. **Nothing in it is decided, and none of it has been checked against the code.**
Before deciding, someone reads the code and says where Swift calls Windows directly today.

## The proposal

**Keep Windows 11 as Swift's main platform, and make the core not depend on Windows.** Be ready for another
platform without building for one yet.

- **Core, the same on every platform:** agent orchestration, context and memory, planning, the permission model,
  task state and run records, tool choice, model providers.
- **Behind an interface:** speech recognition and speech output.
- **One adapter per platform:** microphone and wake word, window management and desktop interaction, UI automation,
  Wi-Fi and Bluetooth, native UI and notifications. Windows uses Win32, UI Automation and Windows audio; Linux
  would use D-Bus, PipeWire and AT-SPI; macOS would use Accessibility and Core Audio.

The core says what Swift wants to do. The adapter says how this PC does it.

## The suggested order

1. **Stabilise Swift on Windows.** Finish the current architecture and the known orchestration, interaction and
   autonomy problems.
2. **Pull out the interfaces.** The core stops calling Windows APIs directly; those calls move behind Windows
   implementations. Done a piece at a time, this is not a rewrite.
3. **Build a second adapter** (Linux is the likely trial) only when there is a real reason to support it.

**The caution:** put interfaces only at real operating-system boundaries, not around every function, and not for
platforms nobody has asked for.

## The larger point

The advice rates **independence from any one AI provider** above independence from any one operating system:
being able to change between local models (Ollama), the OpenAI, Anthropic and Google APIs, speech-to-text engines,
text-to-speech engines and desktop automation implementations, so that prices, subscription limits and provider
changes hurt less.

Swift already has decisions that touch this, and a decision here should start from them:

- ADR-008: the provider interface (`executors/*` behind `Executor`).
- Handoff §5, decision 19: a local model for offline questions.
- Handoff §5, decision 27: other AI providers and which tasks they'd take.

## What the owner would decide

1. Is "ready for other platforms, not built for them" a stated requirement on the roadmap?
2. If yes, when does stage 2 start, and which boundaries come first?
3. Does provider independence come before it?
