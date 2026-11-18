"""B13: Open and Show in folder from a file tree on a Done card (Halo B8, 2026-11-18).

The worker may name the folder its tree lists (``root``). Swift believes it only after checking it itself: an
absolute folder inside the read folders that exists (``verify_tree``), and then each entry is marked ``found`` only
if the file system has it under that folder. Only those rows get Open / Show in folder in the overlay.

``open_from_tree`` takes the path the overlay sends back and acts only if it resolves under a folder Swift verified
this session and exists now: the path comes from the file system, never from the worker's words. A file that runs
code (an .exe, a script, a shortcut) is never opened: it is shown in its folder instead. Nothing here deletes.
Opening a file or folder the owner clicked is level 0 (reversible, on the owner's PC, asked by a click).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

# Folders Swift verified as a tree's root this session (resolved, case-folded): what Open may act under.
_VERIFIED: list[str] = []
_MAX_VERIFIED = 32
# Extensions that run code when opened: shown in their folder, never opened.
RUNS_CODE = frozenset({
    ".exe", ".com", ".bat", ".cmd", ".msi", ".msp", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
    ".scr", ".pif", ".lnk", ".url", ".jar", ".py", ".pyw", ".hta", ".cpl", ".reg", ".appref-ms", ".application",
})


def _key(path: Path) -> str:
    return str(path).casefold()


def verify_tree(shape: dict[str, Any], read_verdict: Callable[[str], str]) -> dict[str, Any]:
    """The tree as Swift will show it: ``root`` kept (resolved) only if it is an absolute folder in the read folders
    that exists; then each entry gets ``found`` from the file system. Otherwise no root and no actions."""
    root = shape.get("root")
    rest = {k: v for k, v in shape.items() if k != "root"}
    if not isinstance(root, str):
        return rest
    path = Path(root)
    try:
        if not path.is_absolute() or read_verdict(str(path)) != "read" or not path.is_dir():
            logger.info("tree root refused")
            return rest
        resolved = path.resolve(strict=True)
    except OSError:
        return rest
    if _key(resolved) not in _VERIFIED:
        _VERIFIED.append(_key(resolved))
        del _VERIFIED[:-_MAX_VERIFIED]
    return {**rest, "root": str(resolved), "entries": _mark(shape["entries"], resolved)}


def _mark(entries: list[dict[str, Any]], base: Path) -> list[dict[str, Any]]:
    out = []
    for entry in entries:
        here = base / entry["name"]
        found = _inside(here) is not None and (here.is_dir() if entry.get("folder") else here.is_file())
        kids = _mark(entry.get("entries", []), here) if entry.get("entries") else []
        out.append({**entry, "found": found, **({"entries": kids} if kids else {})})
    return out


def _inside(path: Path) -> Path | None:
    """``path`` resolved, when it exists under a verified root; else None."""
    try:
        real = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    key = _key(real)
    return real if any(key == r or key.startswith(r.rstrip("\\/") + os.sep) for r in _VERIFIED) else None


def _open(path: Path) -> None:
    os.startfile(str(path))  # type: ignore[attr-defined]  # Windows only, like Swift


def _reveal(path: Path) -> None:
    subprocess.Popen(["explorer", f"/select,{path}"])  # Explorer, one fixed argument shape (pyproject: S603/S607)


# Replaced in tests: nothing real is opened by a test (CLAUDE.md: no real-world actions to test).
OPENERS: dict[str, Callable[[Path], None]] = {"open": _open, "reveal": _reveal}


def target(path: Any, how: Any) -> tuple[Path, str] | None:
    """What a click on a tree row may do: the real path and "open" or "reveal", or None (refused)."""
    if not isinstance(path, str) or how not in OPENERS or not path or len(path) > 32767:
        return None
    real = _inside(Path(path))
    if real is None:
        return None
    return real, "reveal" if how == "open" and real.is_file() and real.suffix.casefold() in RUNS_CODE else how


async def open_from_tree(session: Any, data: dict[str, Any]) -> None:
    """The overlay's ``tree.open``: Open (or a double-click) or Show in folder on a tree row."""
    found = target(data.get("path"), data.get("how"))
    if found is None:
        logger.info("tree open refused", how=data.get("how"))  # no path in the log
        return
    real, how = found
    await asyncio.to_thread(OPENERS[how], real)
    logger.info("tree open", how=how, kind="folder" if real.is_dir() else "file")
