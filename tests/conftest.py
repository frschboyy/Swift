from __future__ import annotations

from pathlib import Path

import pytest

from swift.config.paths import AppPaths, app_paths


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """AppPaths rooted in a temp directory; never touches the real profile."""
    return app_paths({"SWIFT_CONFIG_DIR": str(tmp_path / "config"), "SWIFT_DATA_DIR": str(tmp_path / "data")})
