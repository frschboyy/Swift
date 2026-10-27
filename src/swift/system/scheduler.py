"""Swift's own clock: timers, alarms and reminders that survive a restart (ADR-016 §3.3).

One list of items, each due at a wall-clock time. The list is kept in a small JSON file
(written whole, replaced atomically; it holds a handful of rows), so a timer set before the
PC slept or Swift restarted is still there. ``run`` is the only loop: it sleeps until the
next item is due, in slices of at most ``SLICE_S`` so a suspend/resume or a clock change is
noticed, and calls ``on_fire`` once per item.

An item found due at start-up, or after a long sleep, fires once and is marked ``missed`` so
the card can say "this was due at 15:02". Nothing here speaks or draws: the session decides how
a due item reaches the owner (``Session.notify_due``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from loguru import logger

Kind = Literal["timer", "alarm", "reminder"]
KINDS: tuple[Kind, ...] = ("timer", "alarm", "reminder")
# Longest single sleep: the wall clock is looked at again after this.
SLICE_S = 20.0
# Due this long ago when noticed: it is called missed, not just on time.
MISSED_S = 45.0
MAX_ITEMS = 200


@dataclass
class Item:
    id: int
    kind: Kind
    due: float  # epoch seconds
    label: str = ""
    created: float = 0.0

    @property
    def title(self) -> str:
        return self.label or {"timer": "Timer", "alarm": "Alarm", "reminder": "Reminder"}[self.kind]


OnFire = Callable[[Item, bool], Awaitable[None]]


class SchedulerError(ValueError):
    pass


class Scheduler:
    def __init__(self, path: Path | None = None, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self.clock = clock
        self.items: list[Item] = []
        self._next_id = 1
        self._wake = asyncio.Event()
        self._load()

    # ---- the list ----------------------------------------------------------------------

    def add(self, kind: Kind, due: float, label: str = "") -> Item:
        if len(self.items) >= MAX_ITEMS:
            raise SchedulerError("That's too many timers and reminders; cancel some first.")
        item = Item(self._next_id, kind, float(due), label.strip()[:120], self.clock())
        self._next_id += 1
        self.items.append(item)
        self._changed()
        return item

    def remove(self, item_id: int) -> Item | None:
        for item in self.items:
            if item.id == item_id:
                self.items.remove(item)
                self._changed()
                return item
        return None

    def restore(self, item: Item) -> None:
        """Put back an item removed (the undo of "cancel the timer"); its id is kept."""
        if not any(i.id == item.id for i in self.items):
            self.items.append(item)
            self._next_id = max(self._next_id, item.id + 1)
            self._changed()

    def pending(self, kind: Kind | None = None) -> list[Item]:
        return sorted((i for i in self.items if kind in (None, i.kind)), key=lambda i: (i.due, i.id))

    def find(self, kind: Kind | None = None, label: str = "") -> list[Item]:
        """The pending items of ``kind`` whose label contains ``label`` (all of ``kind`` if it is empty)."""
        want = label.strip().lower()
        return [i for i in self.pending(kind) if not want or want in i.label.lower()]

    def remaining(self, item: Item) -> float:
        return max(0.0, item.due - self.clock())

    # ---- firing ------------------------------------------------------------------------

    def due(self) -> list[Item]:
        now = self.clock()
        return [i for i in self.pending() if i.due <= now]

    async def run(self, on_fire: OnFire) -> None:
        while True:
            self._wake.clear()
            for item in self.due():
                self.remove(item.id)
                missed = self.clock() - item.due > MISSED_S
                try:
                    await on_fire(item, missed)
                except Exception:
                    logger.exception("a due {kind} could not be shown", kind=item.kind)
            nxt = self.pending()[:1]
            wait = SLICE_S if not nxt else max(0.0, min(SLICE_S, nxt[0].due - self.clock()))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), wait + 0.01)

    def _changed(self) -> None:
        self._save()
        self._wake.set()

    # ---- the file ----------------------------------------------------------------------

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
            self.items = [Item(**row) for row in rows if row.get("kind") in KINDS]
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("schedule file unreadable; starting empty", error=str(exc))
            self.items = []
        self._next_id = max((i.id for i in self.items), default=0) + 1

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps([asdict(i) for i in self.items]), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            logger.warning("schedule file not saved", error=str(exc))
