"""T0-02 (P0-2): ``python -m swift --version``."""

from __future__ import annotations

import subprocess
import sys

from swift.__main__ import main


def test_version_flag(capsys) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "Swift 0.1.0"


def test_version_module_invocation() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "swift", "--version"], capture_output=True, text=True, check=True, timeout=60
    )
    assert out.stdout.strip() == "Swift 0.1.0"


def test_no_args_is_usage_error() -> None:
    assert main([]) == 2
