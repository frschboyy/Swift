"""Layering rules checked on the source (docs/architecture.md, ADR-005, ADR-010 §4.4)."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "swift"
# Connector methods that change the outside world.
SIDE_EFFECTS = {"send"}
# The only place allowed to call them (through Action.perform, which only the gateway runs).
ALLOWED = {SRC / "workflows" / "tools.py", SRC / "security" / "gateway.py"}


def _calls(tree: ast.AST) -> list[tuple[int, str, str]]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in SIDE_EFFECTS:
            owner = node.func.value
            name = owner.id if isinstance(owner, ast.Name) else getattr(owner, "attr", "")
            out.append((node.lineno, name, node.func.attr))
    return out


def test_only_the_gateway_path_calls_connector_side_effects() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        if path in ALLOWED or path.parent.name == "connectors":
            continue
        for line, owner, attr in _calls(ast.parse(path.read_text(encoding="utf-8"))):
            if "connector" in owner.lower() or owner in {"mail", "gmail"}:
                offenders.append(f"{path.relative_to(SRC)}:{line} {owner}.{attr}")
    assert offenders == []


def test_connector_send_in_tools_is_only_inside_perform() -> None:
    """In tools.py the one ``connector.send`` lives in the ``perform`` the gateway runs after approval."""
    tree = ast.parse((SRC / "workflows" / "tools.py").read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
            sends = [c for c in _calls(ast.Module(body=fn.body, type_ignores=[])) if "connector" in c[1]]
            if sends:
                assert fn.name in {"perform", "send_email"}, fn.name
    perform = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "perform")
    assert any(c[1] == "connector" for c in _calls(perform))


def test_connectors_do_not_import_tools_or_session() -> None:
    for path in (SRC / "connectors").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(("swift.workflows", "swift.session", "swift.security")), path
