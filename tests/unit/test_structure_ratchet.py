"""Ratchets from the 2026-11-12 health audit: the structure may get better, never worse.
Lower a number here when a change improves it."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"

# Two-way package imports that exist today (HA-INT-01). Remove a pair once it's broken.
KNOWN_CYCLES = {("swift.executors", "swift.routing"), ("swift.routing", "swift.system"), ("swift.security", "swift.workflows")}
SESSION_MAX_LINES = 5057  # session.py at bb5cb89; the split should only lower this.


def _package(module: str) -> str:
    return ".".join(module.split(".")[:2])


def _package_edges() -> set[tuple[str, str]]:
    modules = {".".join(p.relative_to(SRC).with_suffix("").parts).removesuffix(".__init__"): p for p in (SRC / "swift").rglob("*.py")}
    edges = set()
    for name, path in modules.items():
        pkg = name if path.name == "__init__.py" else name.rsplit(".", 1)[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = pkg.split(".")[: len(pkg.split(".")) - node.level + 1]
                    base = ".".join(parts + ([base] if base else []))
                targets = [base, *(f"{base}.{a.name}" for a in node.names)]
            elif isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            else:
                continue
            for target in targets:
                if target in modules and _package(target) != _package(name):
                    edges.add((_package(name), _package(target)))
    return edges


def test_no_new_two_way_package_imports():
    edges = _package_edges()
    cycles = {tuple(sorted(e)) for e in edges if (e[1], e[0]) in edges}
    assert cycles <= KNOWN_CYCLES, f"new: {cycles - KNOWN_CYCLES}"


def test_session_py_does_not_grow():
    lines = len((SRC / "swift" / "session.py").read_text(encoding="utf-8").splitlines())
    assert lines <= SESSION_MAX_LINES, f"session.py is {lines} lines; add a small module instead (CLAUDE.md)"
