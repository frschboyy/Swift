"""The demo's listening (``debug.run``): a speech-like mic level and a growing partial transcript, no microphone."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable

from swift.ipc.protocol import Message, outbound


async def fake_listening(send: Callable[[Message], Awaitable[None]], transcript: str, demo_speed: float) -> None:
    """Synthesize a speech-like mic level and a growing partial transcript."""
    words = transcript.split()
    frames = max(1, int(1.8 * 30 * min(demo_speed, 1.0))) if demo_speed else 1
    for i in range(frames):
        phase = i / 30
        rms = 0.15 + 0.55 * abs(math.sin(phase * 7.0)) * (0.6 + 0.4 * math.sin(phase * 2.3))
        await send(outbound("level", rms=round(max(0.0, min(1.0, rms)), 3)))
        if i % 6 == 5:
            shown = words[: min(len(words), (i + 1) // 6 * max(1, len(words) // 8))]
            await send(outbound("transcript", text=" ".join(shown), final=False))
        await asyncio.sleep(demo_speed / 30)
