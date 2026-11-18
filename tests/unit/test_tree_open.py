"""B13: a file tree's Open / Show in folder act only on what the file system has under a folder Swift verified
(files.py), never on the worker's words. Nothing real is opened: the openers are fakes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swift import files, frames, shapes


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Path]]:
    done: list[tuple[str, Path]] = []
    monkeypatch.setattr(files, "OPENERS", {"open": lambda p: done.append(("open", p)), "reveal": lambda p: done.append(("reveal", p))})
    monkeypatch.setattr(files, "_VERIFIED", [])
    return done


def _tree(tmp_path: Path) -> dict[str, Any]:
    (tmp_path / "2026").mkdir(exist_ok=True)
    (tmp_path / "2026" / "beach.jpg").write_bytes(b"x")
    (tmp_path / "setup.exe").write_bytes(b"x")
    shape, problems = shapes.check({"shape": "tree", "root": str(tmp_path), "entries": [
        {"name": "2026", "folder": True, "entries": [{"name": "beach.jpg"}, {"name": "made-up.jpg"}]},
        {"name": "setup.exe"}, {"name": "..\\..\\outside.txt"}]})
    assert not problems and shape is not None
    return shape


def test_rows_are_found_only_where_the_file_system_has_them(tmp_path: Path, opened: list[Any]) -> None:
    tree = files.verify_tree(_tree(tmp_path), lambda _: "read")
    assert tree["root"] == str(tmp_path.resolve())
    year, exe, outside = tree["entries"]
    assert year["found"] and [e["found"] for e in year["entries"]] == [True, False]  # the worker's made-up name: no
    assert exe["found"] and outside["found"] is False


def test_a_root_outside_the_read_folders_or_not_there_gives_no_actions(tmp_path: Path, opened: list[Any]) -> None:
    assert "root" not in files.verify_tree(_tree(tmp_path), lambda _: "ask")
    assert "root" not in files.verify_tree({**_tree(tmp_path), "root": str(tmp_path / "nope")}, lambda _: "read")
    assert "root" not in files.verify_tree({**_tree(tmp_path), "root": "relative\\folder"}, lambda _: "read")


async def test_open_acts_only_under_a_verified_folder_and_never_runs_code(tmp_path: Path, opened: list[Any]) -> None:
    files.verify_tree(_tree(tmp_path), lambda _: "read")
    handle = frames.HANDLERS["tree.open"]
    await handle(None, {"path": str(tmp_path / "2026" / "beach.jpg"), "how": "open"})
    await handle(None, {"path": str(tmp_path / "setup.exe"), "how": "open"})  # code: shown in its folder instead
    await handle(None, {"path": str(tmp_path / "2026"), "how": "reveal"})
    await handle(None, {"path": str(tmp_path.parent), "how": "open"})  # above the verified folder: refused
    await handle(None, {"path": str(tmp_path / "gone.txt"), "how": "open"})  # not there: refused
    await handle(None, {"path": str(tmp_path / "2026" / ".." / ".." / "x"), "how": "open"})
    assert [(how, p.name) for how, p in opened] == [("open", "beach.jpg"), ("reveal", "setup.exe"), ("reveal", "2026")]


async def test_nothing_is_opened_before_swift_has_verified_a_folder(tmp_path: Path, opened: list[Any]) -> None:
    (tmp_path / "a.txt").write_text("x")
    await frames.HANDLERS["tree.open"](None, {"path": str(tmp_path / "a.txt"), "how": "open"})
    assert opened == []
