"""T0-06 (§11): importing swift forces model libraries offline."""

from __future__ import annotations

import os
import subprocess
import sys

import swift


def test_offline_env_set_in_process() -> None:
    for key, value in swift.OFFLINE_ENV.items():
        assert os.environ[key] == value


def test_offline_env_overrides_shell() -> None:
    env = dict(os.environ, HF_HUB_OFFLINE="0")
    code = "import os, swift; print(os.environ['HF_HUB_OFFLINE'])"
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True, timeout=60)
    assert out.stdout.strip() == "1"
