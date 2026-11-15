"""QA15-01: the pre-commit hook and the ruff baseline it runs can't silently rot."""

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".githooks" / "pre-commit"
NOQA_MAX = 78  # noqa comments in src/swift on 2026-11-15; lower it when one goes, never raise it


def test_hook_is_a_posix_script_checked_in_as_executable():
    text = HOOK.read_bytes()
    assert text.startswith(b"#!/bin/sh\n") and b"\r" not in text
    mode = subprocess.run(["git", "ls-files", "-s", str(HOOK)], cwd=ROOT, capture_output=True, text=True, check=True)
    assert mode.stdout.startswith("100755"), mode.stdout
    assert b"ruff check" in text and b"test_findings_register.py" in text
    # Git's own variables are cleared before the tests run, or a scratch-repository test acts on this repository.
    assert text.index(b"unset $(git rev-parse --local-env-vars)") < text.index(b"-m pytest")


def test_ruff_config_parses_and_selects_the_cited_families():
    lint = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["lint"]
    assert {"ASYNC", "B", "BLE", "F", "RUF", "S"} <= set(lint["select"])


def test_ruff_passes_on_src_and_tests():
    out = subprocess.run([sys.executable, "-m", "ruff", "check", "--quiet", "src", "tests"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def test_noqa_count_does_not_grow():
    count = sum(p.read_text(encoding="utf-8").count("noqa") for p in (ROOT / "src" / "swift").rglob("*.py"))
    assert count <= NOQA_MAX, f"{count} noqa comments in src/swift; fix the code instead of silencing ruff"
