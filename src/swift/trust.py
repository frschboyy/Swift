"""Learned trust (modes study §1, decided 2026-11-14; CLAUDE.md: it lowers one kind from level 1 to 0, only kinds on its
table, never level 3).

A **kind** is a key of ``TABLE`` below, chosen by Swift from an intent it parsed, never from a worker's words. Only things
that are reversible, reach nobody else, delete nothing and run no code are on it: Wi-Fi off, Bluetooth off, airplane
mode on. A trust removes the question, never the check that the owner's own words asked for the change.

Kept in the memory store (``trust-<kind>``), made only from an approved offer card (``source="approved"`` with its card)
or from the owner's spoken words (``"said"``): never typed (it removes a question), never from ``config.yaml``, never by a
worker. Taking one back only adds a question, so typed words may do it. "Ask me about everything" wins over a trust.
Nothing here approves anything: ``intake.approves`` still decides every yes.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from swift.system import intents as it

# The store is Swift's backend's alone: this module never imports it (test_one_writer_only_swifts_backend_imports_the_store);
# the caller hands it in.
Store = Any

# Kind -> how Swift names it to the owner ("Wi-Fi off").
TABLE: dict[str, str] = {"wifi_off": "Wi-Fi off", "bluetooth_off": "Bluetooth off", "airplane_on": "airplane mode on"}
PREFIX = "trust-"
YOU_SAID = it.YOU_SAID
TYPED = "To make that a habit, say it with your voice, or wait for me to offer."
# Offered after this many approvals, in this many different runs, within this many days, none rejected.
APPROVALS, DAYS = 3, 14
# Only voice that is the owner's own words makes one (typed and a click on a worker's option never do).
SPOKEN = frozenset({"voice", "wake", "followup", "correction", "retry", "beside", "answer"})


def kind_of(intent: it.Intent) -> str | None:
    """The trust kind of ``intent``, or None when it isn't on the table."""
    return it.trust_kind(intent)


def _key(kind: str) -> str:
    return PREFIX + kind


def is_trusted(store: Store | None, kind: str) -> bool:
    """Whether ``kind`` is trusted: on the table, and its record was made by an approved card or the owner's voice. A
    record that can't be read counts as not trusted (Swift asks)."""
    if store is None or kind not in TABLE:
        return False
    try:
        record = store.get("memory", _key(kind))
    except (OSError, ValueError, KeyError):
        return False
    return record is not None and record.source in ("said", "approved")


def kinds(store: Store | None) -> list[str]:
    return [k for k in TABLE if is_trusted(store, k)]


def grant(store: Store, kind: str, *, source: str, run: str, words: str = "", card: str | None = None) -> bool:
    """Trust ``kind`` from an approved card (``source="approved"``) or the owner's spoken words (``"said"``). False for a
    kind off the table, typed words, or a source that isn't the owner's."""
    if kind not in TABLE:
        return False
    try:
        if source == "approved":
            store.write("memory", f"Do {TABLE[kind]} without asking", source="approved", run=run, card=card, key=_key(kind))
        elif source == "said" and parse(words) == ("trust_on", kind):  # the words must really name this kind
            store.write("memory", words, source="said", run=run, words=words, key=_key(kind))
        else:
            return False
    except ValueError:  # NotOwnerWords too
        return False
    return True


def revoke(store: Store, kind: str, run: str) -> bool:
    """Ask again about ``kind`` (``Store.forget`` keeps its versions)."""
    return kind in TABLE and store.forget("memory", _key(kind), run=run) is not None


_ALWAYS_LEAD = re.compile(r"always\b(?P<what>.+?)(?:,? without asking(?: me)?|,? and don'?t ask(?: me)?)", re.I)
_AGAIN = re.compile(r"ask me again (?:about|before) (?P<what>.+)", re.I)


def parse(text: str) -> tuple[str, str] | None:
    """("trust_on" | "trust_off", kind) for the owner's words, else None. "Always turn off Wi-Fi without asking" names a kind
    off the table as ("trust_on", "") so it is answered, not obeyed."""
    said = re.sub(r"^\s*(?:(?:hey|ok|okay)\s+)?(?:swift\b[\s,.:!-]*)?(?:please\s+)?", "", text, flags=re.I).strip().rstrip(".!?")
    if m := _AGAIN.fullmatch(said):
        what = it.parse_one(f"turn off {m.group('what')}")
        return ("trust_off", kind_of(what) or "") if what is not None else ("trust_off", "")
    m = _ALWAYS_LEAD.fullmatch(said)
    if m is None:
        return None
    what = m.group("what").strip()
    what = what if re.match(r"(?:do|turn|switch|put)\b", what, re.I) else f"turn {what}"
    found = it.parse_one(what)
    return "trust_on", (kind_of(found) or "") if found is not None else ""


def answer(store: Store, action: str, kind: str, words: str, source: str, run: str) -> str:
    """Carry out "always … without asking" / "ask me again about …" and say what was done."""
    if action == "trust_on":
        if source not in SPOKEN:
            return TYPED  # it would remove a question
        if not kind:
            return "I can only do that without asking for turning off Wi-Fi or Bluetooth, or turning on airplane mode."
        if not grant(store, kind, source="said", run=run, words=words):
            return "I couldn't keep that."
        return f"Okay. I'll turn {TABLE[kind]} without asking. Say “ask me again about it” to change that."
    if kind and revoke(store, kind, run):
        return f"Okay. I'll ask before I do {TABLE[kind]}."
    return "I wasn't doing that without asking."


def without_asking(store: Store | None) -> str:
    """The line at the end of "what do you know about me": "And 2 things I do without asking."""
    n = len(kinds(store))
    return f"And {n} thing{'s' * (n != 1)} I do without asking." if n else ""


# ---- when to offer: a count over the journal ------------------------------------------------------------------


def _ts(entry: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(entry["ts"])
    except (KeyError, ValueError):
        return None


def offer_due(journal: Any, kind: str, now: datetime) -> bool:
    """Whether to offer a trust for ``kind``: asked and approved ``APPROVALS`` times in as many different runs within
    ``DAYS``, rejected never in that window, and not offered before. Metadata only: the journal has no words."""
    if kind not in TABLE:
        return False
    runs: set[str] = set()
    for entry in journal._all():
        if entry.get("kind") != kind:
            continue
        if entry.get("state") == "OFFERED":
            return False
        when = _ts(entry)
        if when is None or now - when > timedelta(days=DAYS):
            continue
        if entry.get("state") == "CANCELLED" and entry.get("reason") == "rejected":
            return False
        if entry.get("state") == "PENDING" and entry.get("asked") and entry.get("run"):
            runs.add(str(entry["run"]))
    return len(runs) >= APPROVALS


def note_offered(journal: Any, kind: str) -> None:
    """Once per kind, ever (the journal remembers; "Not now" doesn't ask again either)."""
    journal.write(f"offer-{kind}", "OFFERED", kind=kind)
