from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from swift.config.paths import AppPaths, app_paths


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """AppPaths rooted in a temp directory; never touches the real profile."""
    return app_paths({"SWIFT_CONFIG_DIR": str(tmp_path / "config"), "SWIFT_DATA_DIR": str(tmp_path / "data")})


@pytest.fixture(autouse=True)
def _frames_fit_the_contract(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every frame a ``Session`` sends in any test fits the protocol examples (seams audit layer A):
    a field the backend adds without an example (and so without a type in protocol.ts) fails here."""
    from protocol_contract import check_frame

    from swift import session as session_module

    problems: list[str] = []
    init = session_module.Session.__init__

    def checked(self: Any, send: Any, *args: Any, **kwargs: Any) -> None:
        async def send_checked(msg: Any) -> Any:
            problems.extend(check_frame(msg.type, msg.data))
            return await send(msg)

        init(self, send_checked, *args, **kwargs)

    monkeypatch.setattr(session_module.Session, "__init__", checked)
    yield
    assert not problems, "frames that don't fit tests/fixtures/protocol/frames.json:\n  " + "\n  ".join(
        sorted(set(problems)))


@pytest.fixture(autouse=True)
def _interaction_fields_are_classified(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every record a ``Session`` finishes in any test has only fields someone has decided on (X-03),
    however it was written. A new one stays out of swift.log, and fails here until it's in
    ``SUMMARY_FIELDS`` or ``LOCAL_ONLY_FIELDS``."""
    from swift import session as session_module
    from swift.runlog import unclassified

    found: set[str] = set()
    init = session_module.Session.__init__

    def checked(self: Any, *args: Any, **kwargs: Any) -> None:
        init(self, *args, **kwargs)
        inner = self.on_finish

        def finish(record: dict[str, Any]) -> None:
            found.update(unclassified(record))
            if inner is not None:
                inner(record)

        self.on_finish = finish

    monkeypatch.setattr(session_module.Session, "__init__", checked)
    yield
    assert not found, f"interaction fields nobody has classified (swift/runlog.py): {sorted(found)}"
