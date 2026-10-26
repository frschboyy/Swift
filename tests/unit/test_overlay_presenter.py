"""The overlay's presenter sequence tests (ADR-013 §6), run with Node so `uv run pytest` covers them.

They live in overlay/tests/ and need only Node (22.6 or later strips TypeScript itself); skipped without it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[2] / "overlay"


def test_presenter_sequences_pass() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node isn't installed")
    done = subprocess.run(
        [node, "--test", "tests/presenter.test.ts"], cwd=OVERLAY, capture_output=True, text=True, timeout=120,
    )
    if "ERR_UNKNOWN_FILE_EXTENSION" in done.stderr:
        pytest.skip("this Node can't run TypeScript directly (needs 22.6+)")
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
