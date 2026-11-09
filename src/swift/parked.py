"""Conversations left unfinished, kept so they can be picked up later (ADR-014 §5).

A thread is **parked** when its run is stopped (Esc, "stop", Swift quitting), a confirm
card in it goes unanswered (including one held past ``hold_h`` while the owner was away), or
its answer was a question the owner didn't answer while Swift listened for a reply.
A parked thread keeps what a provider needs to go on: the request, the last steps, the
last draft or event Swift showed, and when.

- "Continue", "where were we", "go on" pick up the one the "Unfinished" line shows, if it was
  just shown, else the newest one; "finish the email to Ada" the one whose words match. The resumed run continues the same thread.
- After the next answer, the overlay shows one line, "Unfinished: <title>" (the title is from
  the owner's own words, never Swift's wrapper around them), at most
  ``OFFER_TIMES`` times; "not now" stops it, "forget that" drops the thread.
- **Fresh or resumed (owner checks 131 and 8, 2026-11-09).** A new request with the same intent as an
  item in the stack starts fresh, on a new card, and that item leaves the stack: the stack never holds
  two of the same. The same intent: the same system actions with the same details ("turn on airplane
  mode", "can you turn airplane mode on?"), else the same words, case and punctuation aside. An item
  is picked up only when the owner asks for it: "continue", "finish the email to Ada", a click on it.
- Kept ``keep_s`` (24 h) in a local JSON file, so a restart doesn't lose them. Nothing about
  them leaves the machine.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from loguru import logger

KEEP_S = 24 * 3600
# Swift's own question about a change for now ("Turn off Bluetooth?"), unanswered in the stack.
QUESTION_KEEP_S = 10 * 60
# Parked threads kept at most; the oldest go first.
MAX_PARKED = 10
# The "Unfinished: …" line after an answer, at most this many times per thread.
OFFER_TIMES = 3
# A thread parked less than this long ago isn't offered: the owner just left it.
OFFER_AFTER_S = 60.0
# Where a workflow's request quotes the owner (swift/workflows/library.py ``Package.request``).
SAID_MARKER = "[The request, as the owner said it]"

# "finish the email to Ada": the words after the verb name the task.
_NAMED = re.compile(
    r"^(?:(?:please|ok|okay|now|so)[,\s]+)*(?:finish|continue|resume|complete|get back to|go back to|carry on with"
    r"|pick up|keep going with)\s+(?:(?:the|my|that|our|with)\s+)*(?P<what>.+?)[.!?]*$",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-z0-9']+")
_STOP = frozenset(
    "a an the to of for on in at about with my me our your and or it that this one please up some "
    "from by is was be i you we draft".split()
)


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1}


def _same(words: str) -> str:
    """What a request asks for, to compare two: its system actions and their details when it is one
    ("turn on airplane mode" and "can you turn airplane mode on?" are one), else its words as said,
    case and punctuation aside."""
    from swift.system import intents as it  # the grammar the lane uses, so "the same" means the same

    found = it.parse(words) if words.strip() else None
    if found:
        return "intents:" + repr(sorted((i.name, sorted(i.slots.items())) for i in found))
    return " ".join(_WORD.findall(words.lower()))


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _ago(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    return f"{minutes // 60} h {minutes % 60:02d} min ago"


@dataclass(frozen=True)
class Parked:
    thread: str
    # The owner's request, as sent to the provider (without Swift's added context).
    request: str
    # "stopped" | "unanswered" (a confirm card) | "asked" (Swift's question)
    reason: str
    at: float
    # What the run had done, a few steps in one line.
    progress: str = ""
    # The last email or event Swift showed on a card, in one line.
    proposed: str = ""
    offered: int = 0
    dismissed: bool = False
    # The request in the owner's own words (a workflow's ``request`` wraps them in its playbook).
    said: str = ""
    # How long it is kept (s); 0: the default (``KEEP_S``). Swift's question about a change for now
    # ("Turn off Bluetooth?") keeps ``QUESTION_KEEP_S``: an hour later it means nothing (2026-11-05).
    keep_s: float = 0.0

    @property
    def words(self) -> str:
        """What the owner asked, in their words."""
        if self.said:
            return self.said
        _, marker, said = self.request.rpartition(SAID_MARKER)  # parked before ``said`` was kept
        return said.strip() if marker else self.request

    @property
    def title(self) -> str:
        words = self.words
        return _clip(words[:1].upper() + words[1:], 48)

    def as_context(self, now: float) -> str:
        """Prepended to the resumed request, like the follow-up context (ADR-007 §9)."""
        why = {
            "stopped": "it was stopped",
            "asked": "Swift asked the user a question and the answer hadn't come yet",
        }.get(self.reason, "a confirm card in it went unanswered")
        lines = [
            f"[Context: an unfinished task the user is coming back to, left {_ago(now - self.at)} ({why}). "
            "Pick it up where it stopped; don't redo what was already done, and check anything that may "
            "have changed since.]",
        ]
        if self.progress:
            lines.append(f"What was done before it stopped: {_clip(self.progress, 600)}")
        if self.proposed:
            lines.append(f"The last thing Swift showed the user, not approved yet: {_clip(self.proposed, 400)}")
        return "\n".join(lines) + "\n\n[The task]\n"


def named_task(text: str) -> str | None:
    """The task named in "finish the email to Ada" ("email to Ada"); None if it doesn't name one."""
    m = _NAMED.match(" ".join(text.split()))
    return m.group("what") if m else None


class ParkedThreads:
    def __init__(self, path: Path | None, *, keep_s: float = KEEP_S, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self.keep_s = keep_s
        self.clock = clock
        self._items: list[Parked] = self._load()

    # ---- what's parked ----------------------------------------------------------------

    def all(self) -> list[Parked]:
        """Newest first, expired ones dropped."""
        now = self.clock()
        kept = [p for p in self._items if now - p.at < (p.keep_s or self.keep_s)]
        if len(kept) != len(self._items):
            self._items = kept
            self._save()
        return sorted(kept, key=lambda p: p.at, reverse=True)

    def newest(self) -> Parked | None:
        items = self.all()
        return items[0] if items else None

    def get(self, thread: str) -> Parked | None:
        return next((p for p in self.all() if p.thread == thread), None)

    def find(self, text: str) -> Parked | None:
        """The parked thread "finish the email to Ada" names: most of the named words in its request."""
        what = named_task(text)
        if what is None:
            return None
        wanted = _words(what)
        if not wanted:
            return None
        best: tuple[float, Parked] | None = None
        for p in self.all():
            share = len(wanted & _words(p.words)) / len(wanted)
            if share >= 0.5 and (best is None or share > best[0]):
                best = (share, p)
        return best[1] if best else None

    # ---- changes ----------------------------------------------------------------

    def drop_same(self, words: str) -> bool:
        """The owner asked the same thing again: the unfinished one is replaced, not a second of it."""
        same = _same(words)
        kept = [p for p in self._items if not same or _same(p.words) != same]
        if len(kept) == len(self._items):
            return False
        self._items = kept
        self._save()
        return True

    def park(self, parked: Parked) -> None:
        same = _same(parked.words)
        self._items = [p for p in self._items if p.thread != parked.thread and (not same or _same(p.words) != same)] + [parked]
        self._items = sorted(self._items, key=lambda p: p.at)[-MAX_PARKED:]
        self._save()
        logger.info("conversation parked", reason=parked.reason)

    def drop(self, thread: str) -> Parked | None:
        found = next((p for p in self._items if p.thread == thread), None)
        if found is not None:
            self._items = [p for p in self._items if p.thread != thread]
            self._save()
        return found

    def offer(self, *, besides: str | None = None) -> Parked | None:
        """The thread to show as "Unfinished: …" now (counted as shown), or None."""
        now = self.clock()
        for p in self.all():
            if p.thread == besides or p.dismissed or p.offered >= OFFER_TIMES or now - p.at < OFFER_AFTER_S:
                continue
            self._replace(replace(p, offered=p.offered + 1))
            return p
        return None

    def dismiss(self, thread: str) -> None:
        """"Not now": still resumable, no longer offered."""
        found = next((p for p in self._items if p.thread == thread), None)
        if found is not None:
            self._replace(replace(found, dismissed=True))

    def _replace(self, parked: Parked) -> None:
        self._items = [parked if p.thread == parked.thread else p for p in self._items]
        self._save()

    # ---- the file ----------------------------------------------------------------

    def _load(self) -> list[Parked]:
        if self.path is None or not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            known = set(Parked.__dataclass_fields__)
            return [Parked(**{k: v for k, v in item.items() if k in known}) for item in raw.get("parked", [])]
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("parked conversations unreadable; starting without them", error=str(exc))
            return []

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"parked": [asdict(p) for p in self._items]}, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            logger.warning("couldn't save parked conversations", error=str(exc))
