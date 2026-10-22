"""Swift: a passive, voice-activated desktop agent for Windows."""

from __future__ import annotations

import os

__version__ = "0.1.0"

# §11: model libraries must never fetch or phone home implicitly. These are
# forced (not setdefault) so a stray shell variable cannot re-enable them;
# the explicit `swift models fetch` command will lift them for its own run.
OFFLINE_ENV: dict[str, str] = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "DO_NOT_TRACK": "1",
}
os.environ.update(OFFLINE_ENV)

# numpy's OpenBLAS commits ~225 MB of per-thread buffers at import. Swift does no heavy
# numpy maths (CTranslate2 has its own threads), so one thread costs nothing. Must be
# set before numpy is first imported; setdefault leaves an explicit override alone.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
