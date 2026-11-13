"""What Swift knows about its owner, and Swift's own settings (product direction §5.5, §6.1; workstream C7).

A store owned by Swift, separate from ``config.yaml``, which still wins (``setting``). Plain files the owner
can read, one per record, under ``%LOCALAPPDATA%\\Swift\\memory``::

    memory/<key>.md                  what Swift knows now: a header (description, source, when, run, version), then the text
    memory/versions/<key>/<n>.md     every version, the forgotten ones too, so any change can be rolled back
    memory/settings/...              the same, for Swift's own settings

Product rules (``CLAUDE.md``; a path that breaks one is a critical bug):

- **Only the owner's words write memory.** ``write`` takes ``source="said"`` with the owner's own words, and the
  text must be found in them; or ``source="approved"`` with the card the owner approved. A worker's text (a tool
  result, a page, an email) is never the owner's words: the session passes only the transcript of a request the
  owner said or typed (``OWNER_WORDS``), never a click on a button a worker may have worded.
- **One writer.** Only Swift's backend imports this module; workers get no tool that reaches it.
- **Every change is versioned with its run.** Each version is created exclusively (``open(..., "x")``): two writes
  ending at once can't both take a version number, the second re-reads and applies again.
- **Logs content-free.** Only kinds, sources and version numbers are logged.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from loguru import logger

Kind = Literal["memory", "setting"]
Source = Literal["said", "approved", "inferred"]
ACTIONS = ("remember", "forget", "recall")
# Record sources whose transcript is the owner's own words, said or typed. Not "click": a button's words may be a worker's.
OWNER_WORDS = frozenset({"voice", "wake", "followup", "correction", "retry", "beside", "answer", "typed", "debug.ask"})
MAX_TEXT = 300
_RESERVED = {"con", "prn", "aux", "nul", *(f"{p}{i}" for p in ("com", "lpt") for i in range(1, 10))}


class NotOwnerWords(ValueError):
    """A write that doesn't come from the owner's words or an approved card."""


@dataclass(frozen=True)
class Record:
    key: str
    text: str
    source: Source
    when: str
    run: str
    version: int
    forgotten: bool = False


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s']", " ", text.lower()).split())


def key_of(text: str) -> str:
    """What a fact is about: "my manager is Ada" and "my manager is Janet" share "my-manager", so one replaces the other."""
    subject = re.split(r"\s+(?:is|are|was|=)\s+", _norm(text), maxsplit=1)[0]
    slug = re.sub(r"[^a-z0-9]+", "-", subject).strip("-")[:60].strip("-") or "note"
    return slug + "-" if slug in _RESERVED else slug


def _dump(r: Record) -> str:
    head = {"description": r.text.splitlines()[0][:120], "source": r.source, "when": r.when, "run": r.run,
            "version": r.version, **({"forgotten": "true"} if r.forgotten else {})}
    return "---\n" + "".join(f"{k}: {v}\n" for k, v in head.items()) + f"---\n{r.text}\n"


def _load(key: str, path: Path) -> Record:
    _, head, body = path.read_text(encoding="utf-8").split("---\n", 2)
    h = dict(line.split(": ", 1) for line in head.splitlines())
    return Record(key, body.rstrip("\n"), h["source"], h["when"], h["run"], int(h["version"]), h.get("forgotten") == "true")  # type: ignore[arg-type]


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _dir(self, kind: Kind) -> Path:
        return self.root if kind == "memory" else self.root / "settings"

    def get(self, kind: Kind, key: str) -> Record | None:
        path = self._dir(kind) / f"{key}.md"
        return _load(key, path) if path.is_file() else None

    def all(self, kind: Kind) -> list[Record]:
        folder = self._dir(kind)
        return sorted((_load(p.stem, p) for p in folder.glob("*.md")), key=lambda r: r.when) if folder.is_dir() else []

    def versions(self, kind: Kind, key: str) -> list[Record]:
        folder = self._dir(kind) / "versions" / key
        return sorted((_load(key, p) for p in folder.glob("*.md")), key=lambda r: r.version) if folder.is_dir() else []

    def write(self, kind: Kind, text: str, *, source: Source, run: str, words: str | None = None,
              card: str | None = None, key: str | None = None) -> Record:
        """Keep ``text`` as the newest version of its record. Raises NotOwnerWords unless it is the owner's."""
        text = text.strip()
        if not text or len(text) > MAX_TEXT:
            raise ValueError("empty or too long")
        if source == "said" and (words is None or (kind == "memory" and _norm(text) not in _norm(words))):
            raise NotOwnerWords("said, but not in the owner's words")
        if source == "approved" and not card:
            raise NotOwnerWords("approved, but no card")
        if source == "inferred":
            raise NotOwnerWords("nothing inferred is kept until the review job (§5.6) proposes it on a card")
        return self._commit(kind, Record(key or key_of(text), text, source, _now(), run, 0))

    def forget(self, kind: Kind, key: str, *, run: str) -> Record | None:
        """Forget it; its versions stay, so it can be brought back. Called only for the owner's "forget …"."""
        current = self.get(kind, key)
        if current is None:
            return None
        self._commit(kind, Record(key, current.text, current.source, _now(), run, 0, forgotten=True))
        return current

    def setting(self, section: Any, name: str) -> Any:
        """A setting's value: config.yaml when the owner set it there (it wins), else this store, else the default."""
        if name in section.model_fields_set:
            return getattr(section, name)
        kept = self.get("setting", f"{type(section).__name__}.{name}")
        return kept.text if kept is not None else getattr(section, name)

    def _commit(self, kind: Kind, record: Record) -> Record:
        folder = self._dir(kind) / "versions" / record.key
        folder.mkdir(parents=True, exist_ok=True)
        while True:  # compare-and-set on the version number: a version file is created once, by one writer
            n = max((int(p.stem) for p in folder.glob("*.md")), default=0) + 1
            record = Record(**{**record.__dict__, "version": n})
            try:
                with open(folder / f"{n}.md", "x", encoding="utf-8") as f:
                    f.write(_dump(record))
                break
            except FileExistsError:
                continue
        current = self._dir(kind) / f"{record.key}.md"
        if record.forgotten:
            current.unlink(missing_ok=True)
        else:
            tmp = current.with_suffix(".tmp")
            tmp.write_text(_dump(record), encoding="utf-8")
            os.replace(tmp, current)
        logger.info("memory changed", kind=kind, source=record.source, version=n, forgotten=record.forgotten)
        return record


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- The owner's words: "remember …", "forget …", "what do you know about me?" ---------------------------------

_LEAD = re.compile(r"^\s*(?:(?:hey|ok|okay)\s+)?(?:swift\b[\s,.:!-]*)?(?:(?:and|so|ok|okay|also|please|can you|could you)\s+)*", re.I)
_REMEMBER = re.compile(r"(?:please )?(?:remember|keep in mind)(?: that)? (?!to |when |what |where |how |why |if |whether |me$)(?P<x>.+)", re.I)
_FORGET = re.compile(r"(?:please )?forget (?:that |about |what i said about |everything (?:about |you know about )?)?(?!it$|that$|this$|about )(?P<x>.+)", re.I)
_RECALL = re.compile(r"what do you (?:know|remember)(?: about me)?|what have i told you(?: about me)?"
                     r"|what (?:have you|did you) remember(?:ed)?(?: about me)?", re.I)
_VAGUE = {"this", "that", "it", "these", "those", "this one", "that one", "what you said", "what it says", "what that says"}


def parse(text: str) -> tuple[str, str] | None:
    """("remember", the fact) | ("forget", what) | ("recall", "") for the owner's words, else None."""
    said = _LEAD.sub("", text).strip().rstrip(".!?")
    if _RECALL.fullmatch(said):
        return "recall", ""
    for action, pattern in (("remember", _REMEMBER), ("forget", _FORGET)):
        if m := pattern.fullmatch(said):
            return action, m.group("x").strip()
    return None


_YOU = {"my": "your", "i": "you", "i'm": "you're", "me": "you", "mine": "yours", "myself": "yourself", "am": "are"}


def _to_you(text: str) -> str:
    return re.sub(r"\b(i'm|my|i|me|mine|myself|am)\b", lambda m: _YOU[m.group(0).lower()], text, flags=re.I)


def answer(store: Store | None, words: str, source: str, run: str) -> tuple[str, dict[str, Any] | None]:
    """Carry out the owner's "remember / forget / what do you know" and say what was done."""
    found = parse(words)
    if store is None or found is None:
        return "I can't keep memories here.", None
    action, x = found
    if action == "recall":
        known = store.all("memory")
        if not known:
            return "You haven't asked me to remember anything yet.", None
        items = [f"{_to_you(r.text)} ({'you said' if r.source == 'said' else 'you approved'}, {_day(r.when)})" for r in known]
        return f"You've told me {len(items)} thing{'s' * (len(items) != 1)}.", {"kind": "list", "items": items}
    if source not in OWNER_WORDS:
        return "I only remember what you tell me yourself.", None
    if _norm(x) in _VAGUE:
        return "Tell me in your own words, like “remember that my manager is Ada”.", None
    if action == "remember" and re.search(r"\b(?:password|passcode|pin)\b", x, re.I):
        return "I don't keep passwords or PINs: a password manager keeps them safer.", None
    if action == "remember" and (any(_luhn(d) for d in re.findall(r"\d{13,19}", re.sub(r"[\s-]", "", x))) or (
            re.search(r"\d", x) and re.search(r"\b(?:card|account|id|passport|social security|ssn|bank)\b", x, re.I))):
        return "I don't keep card or ID numbers: keep them in a password manager or your wallet app.", None
    if len(x) > MAX_TEXT:
        return "That's too long for me to keep: say it in a sentence.", None
    if action == "remember":
        before = store.get("memory", key_of(x))
        if before is not None and _norm(before.text) == _norm(x):
            return f"I already know {_to_you(x)}.", None
        store.write("memory", x, source="said", words=words, run=run)
        was = f" Before, it was: {_to_you(before.text)}." if before is not None else ""
        return f"Okay, I'll remember {_to_you(x)}.{was}", None
    matches = _matching(store, x)
    if not matches:
        return f"I don't know anything about {_to_you(x)}.", None
    if len(matches) > 1:
        return (f"I know {len(matches)} things about {_to_you(x)}. Which should I forget?",
                {"kind": "list", "items": [_to_you(r.text) for r in matches]})
    store.forget("memory", matches[0].key, run=run)
    return f"Okay, I've forgotten {_to_you(matches[0].text)}.", None


def _luhn(digits: str) -> bool:
    """A card number's check digit (Luhn): tells a card from a phone number of the same length."""
    total = sum(d if i % 2 == 0 else (d * 2 - 9 if d > 4 else d * 2) for i, d in enumerate(map(int, reversed(digits))))
    return total % 10 == 0


def _matching(store: Store, what: str) -> list[Record]:
    known = store.all("memory")
    if exact := [r for r in known if r.key == key_of(what) or _norm(r.text) == _norm(what)]:
        return exact
    words = set(_norm(what).split()) - {"my", "the", "a", "about"}
    return [r for r in known if words and words <= set(_norm(r.text).split())]


def _day(when: str) -> str:
    d = datetime.fromisoformat(when).astimezone()
    return f"{d.day} {d.strftime('%b')}"
