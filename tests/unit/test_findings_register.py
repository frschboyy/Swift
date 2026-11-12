"""The findings register (docs/audit/findings.yaml) stays checkable: one entry per finding,
known values only, and every test it names exists."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "docs" / "audit" / "findings.yaml"

KEYS = {"id", "title", "source", "module", "area", "severity", "product_rule",
        "status", "confidence", "evidence", "test", "note"}
AREAS = {"screen", "speech", "actions", "privacy", "routing", "timers", "config", "tests", "process", "perf"}
SEVERITIES = {"critical", "high", "medium", "low"}
STATUSES = {"open", "fixed", "partial", "unproven", "stale", "wontfix"}
CONFIDENCE = {"confirmed", "suspected", "design-concern"}


def _entries():
    return yaml.safe_load(REGISTER.read_text(encoding="utf-8"))


def _test_exists(ref: str) -> bool:
    path, _, name = ref.partition("::")
    file = ROOT / path
    if not file.is_file():
        return False
    if not name:
        return True
    text = file.read_text(encoding="utf-8")
    if name[0] in "\"'`":  # a TypeScript test named by its title
        return name.strip("\"'`").rstrip(".") in text
    name = name.split("[")[0].split("::")[-1]
    return re.search(rf"(def|class) {re.escape(name)}\b|it(\.fails)?\(\s*['\"`][^'\"`]*{re.escape(name)}", text) is not None


def test_every_entry_has_the_known_shape():
    bad = []
    for e in _entries():
        if set(e) != KEYS:
            bad.append((e.get("id"), "keys", sorted(set(e) ^ KEYS)))
            continue
        for key, allowed in (("area", AREAS), ("severity", SEVERITIES), ("status", STATUSES), ("confidence", CONFIDENCE)):
            if e[key] not in allowed:
                bad.append((e["id"], key, e[key]))
        if not isinstance(e["product_rule"], bool):
            bad.append((e["id"], "product_rule", e["product_rule"]))
        if not str(e["title"] or "").strip() or not str(e["module"] or "").strip():
            bad.append((e["id"], "empty title or module", None))
    assert not bad


def test_ids_are_unique():
    ids = [e["id"] for e in _entries()]
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})


def test_named_tests_exist():
    missing = [(e["id"], e["test"]) for e in _entries() if e["test"] and not _test_exists(e["test"])]
    assert not missing


def test_a_fix_says_where_it_is():
    assert not [e["id"] for e in _entries() if e["status"] in {"fixed", "partial"} and not e["evidence"]]


def test_open_critical_findings_have_a_test_or_say_why_not():
    # A product-rule break with no repro is how a fix gets claimed without proof.
    bad = [e["id"] for e in _entries()
           if e["severity"] == "critical" and e["status"] in {"open", "partial", "unproven"}
           and not e["test"] and "untested:" not in str(e["note"] or "")]
    assert not bad
