"""The system lane (ADR-016 §3): do what a system intent asks, then say what was done.

``SystemLane.run(text)`` parses the utterance (``intents.parse``), carries each intent out
through the ``SystemControl`` and the ``Scheduler``, and returns an ``Outcome``: one short line
in the spoken style of the fast lane ("Timer set for 10 minutes.", "Volume 35."). Nothing here
calls a model or the network. A request that is not one of these returns None, and the router
has already sent it on.

*Undo.* Volume, mute, theme and brightness changes, and every timer, alarm or reminder set or
cancelled, are reversible: the lane keeps the inverse of the last utterance for ``UNDO_S`` and
"undo that" runs it (``can_undo`` / ``undo``). Lock, media keys, windows, screenshots and
settings pages have nothing to undo and are not offered one.

*Failures* are sentences (``SystemUnavailable.message``), not stack traces: "This display doesn't
let Windows change its brightness." The outcome is then ``ok=False`` and the session logs it as an error.

*Journal.* Every change to the device (``CHANGES``) is written to the action journal like a
gateway action (ADR-010 §4): ``PENDING`` before, then ``DONE`` or ``FAILED``. Metadata only: the
intent's name, whether it can be undone and, for a web search, the domain; never the query or a
reminder's words. Reads, and Swift's own timers and reminders, change nothing outside Swift and
are not journaled. These changes skip the gateway's confirm step on purpose: each is local to
this PC and either reversible or harmless (ADR-016 §3.1, docs/architecture.md).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from swift.security.journal import Journal
from swift.system import intents as it
from swift.system.control import SystemControl, SystemUnavailable
from swift.system.scheduler import Item, Scheduler, SchedulerError

UNDO_S = 600.0
# Intents that change the device or reach outside Swift: journaled.
CHANGES = frozenset({
    "volume.step", "volume.set", "mute", "media", "theme", "brightness.set", "brightness.step", "lock",
    "settings", "window", "screenshot", "search",
})
# Where an intent sends something beyond this PC (the journal's ``domains``).
DOMAINS = {"search": ["google.com"]}


@dataclass(frozen=True)
class Outcome:
    said: str
    ok: bool = True
    # Intent names that ran, for the interaction log ("timer.set", "volume.step").
    intents: tuple[str, ...] = ()


Undo = Callable[[], Awaitable[str]]


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class SystemLane:
    def __init__(
        self,
        control: SystemControl,
        scheduler: Scheduler,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        journal: Journal | None = None,
    ) -> None:
        self.control = control
        self.scheduler = scheduler
        self.now = now
        self.journal = journal or Journal(None)
        self._undo: list[Undo] = []
        self._undo_at = 0.0

    # ---- entry points ------------------------------------------------------------------

    @staticmethod
    def matches(text: str) -> bool:
        return it.parse(text) is not None

    def claims(self, text: str) -> bool:
        """Whether Swift should handle ``text`` itself. A reminder to list or cancel when none was set
        here may be a calendar event or a task, so that goes to the agent, which has those."""
        found = it.parse(text)
        if found is None:
            return False
        return not any(
            i.name in ("cancel", "list") and i["kind"] == "reminder" and not self.scheduler.pending("reminder")
            for i in found
        )

    async def run(self, text: str) -> Outcome | None:
        found = it.parse(text)
        if found is None:
            return None
        said: list[str] = []
        undos: list[Undo] = []
        ok = True
        for intent in found:
            action_id = self._pending(intent.name)
            failed: str | None = None
            try:
                line, undo = await self._do(intent)
            except SystemUnavailable as exc:
                line, undo, ok, failed = exc.message, None, False, "unavailable"
            except SchedulerError as exc:
                line, undo, ok, failed = str(exc), None, False, "schedule"
            except Exception:  # a bug or a Windows surprise must not lose the request
                logger.exception("system intent failed", intent=intent.name)
                line, undo, ok, failed = "Something went wrong doing that.", None, False, "internal"
            self._settled(action_id, failed, undoable=undo is not None)
            said.append(line)
            if undo is not None:
                undos.append(undo)
        if undos:
            self._undo, self._undo_at = undos, time.monotonic()
        return Outcome(" ".join(said), ok, tuple(i.name for i in found))

    def can_undo(self) -> bool:
        return bool(self._undo) and time.monotonic() - self._undo_at <= UNDO_S

    async def undo(self) -> str:
        steps, self._undo = self._undo, []
        if not steps or time.monotonic() - self._undo_at > UNDO_S:
            return "There's nothing to undo."
        action_id = self._pending("undo", always=True)
        lines: list[str] = []
        failed: str | None = None
        for step in reversed(steps):
            try:
                lines.append(await step())
            except (SystemUnavailable, SchedulerError) as exc:
                lines.append(getattr(exc, "message", str(exc)))
                failed = "unavailable"
        self._settled(action_id, failed, undoable=False)
        return " ".join(lines)

    def _pending(self, name: str, always: bool = False) -> str | None:
        """Journal a device change before it runs; None for an intent that changes nothing outside Swift."""
        if not always and name not in CHANGES:
            return None
        action_id = uuid.uuid4().hex[:12]
        fields = {"domains": DOMAINS[name]} if name in DOMAINS else {}
        self.journal.write(action_id, "PENDING", tool=f"system.{name}", **fields)
        return action_id

    def _settled(self, action_id: str | None, failed: str | None, undoable: bool) -> None:
        if action_id is None:
            return
        if failed is None:
            self.journal.write(action_id, "DONE", undoable=undoable)
        else:
            self.journal.write(action_id, "FAILED", reason=failed)

    # ---- one intent --------------------------------------------------------------------

    async def _do(self, intent: it.Intent) -> tuple[str, Undo | None]:
        handler = getattr(self, "_" + intent.name.replace(".", "_"), None)
        if handler is None:  # an intent the grammar knows and the lane doesn't: a bug, not the owner's problem
            raise SystemUnavailable("I can't do that yet.")
        return await handler(intent)

    # ---- timers, alarms, reminders -----------------------------------------------------

    def _added(self, item: Item) -> Undo:
        async def undo() -> str:
            self.scheduler.remove(item.id)
            return f"Okay, I've removed the {item.kind}."
        return undo

    async def _timer_set(self, i: it.Intent) -> tuple[str, Undo | None]:
        due = self.now().timestamp() + i["seconds"]
        item = self.scheduler.add("timer", due, i["label"])
        label = f" for {i['label']}" if i["label"] else ""
        return f"Timer set for {it.say_duration(i['seconds'])}{label}.", self._added(item)

    async def _timer_left(self, i: it.Intent) -> tuple[str, Undo | None]:
        timers = self.scheduler.find("timer", i["label"])
        if not timers:
            return ("There's no timer running." if not i["label"] else f"There's no {i['label']} timer."), None
        parts = []
        for t in timers[:4]:
            left = it.say_duration(self.scheduler.remaining(t))
            parts.append(f"{left} left" + (f" on {t.label}" if t.label else ""))
        if len(timers) == 1:
            return f"{parts[0].capitalize()}.", None
        return f"{plural(len(timers), 'timer')}: " + "; ".join(parts) + ".", None

    async def _cancel(self, i: it.Intent) -> tuple[str, Undo | None]:
        kind = i["kind"]
        found = self.scheduler.find(kind, i["label"])
        if not found:
            what = f"{i['label']} {kind}" if i["label"] else kind
            return f"There's no {what} to cancel.", None
        if len(found) > 1 and not i["all"]:
            names = ", ".join(self._describe(x) for x in found[:3])
            return f"You have {plural(len(found), kind)}: {names}. Say “cancel all {kind}s” or name one.", None
        removed = [x for x in found if self.scheduler.remove(x.id) is not None]

        async def undo() -> str:
            for x in removed:
                self.scheduler.restore(x)
            return f"Okay, I've put back {plural(len(removed), kind)}."

        if len(removed) == 1:
            return f"Cancelled your {self._describe(removed[0])}.", undo
        return f"Cancelled {plural(len(removed), kind)}.", undo

    async def _list(self, i: it.Intent) -> tuple[str, Undo | None]:
        kind = i["kind"]
        found = self.scheduler.pending(kind)
        if not found:
            return f"You have no {kind}s.", None
        shown = "; ".join(self._describe(x) for x in found[:5])
        more = f" and {len(found) - 5} more" if len(found) > 5 else ""
        return f"You have {plural(len(found), kind)}: {shown}{more}.", None

    def _describe(self, item: Item) -> str:
        now = self.now()
        due = datetime.fromtimestamp(item.due).astimezone()
        if item.kind == "timer":
            left = it.say_duration(self.scheduler.remaining(item))
            return f"{item.label} timer, {left} left" if item.label else f"timer, {left} left"
        when = it.say_when(due, now)
        return f"{item.label} at {when}" if item.label else f"{item.kind} at {when}"

    async def _alarm_set(self, i: it.Intent) -> tuple[str, Undo | None]:
        due = it.resolve(i["when"], self.now())
        if due is None:
            return "That time has already passed.", None
        item = self.scheduler.add("alarm", due.timestamp(), "")
        return f"Alarm set for {it.say_when(due, self.now())}.", self._added(item)

    async def _reminder_set(self, i: it.Intent) -> tuple[str, Undo | None]:
        now = self.now()
        due = it.resolve(i["when"], now)
        if due is None:
            return "That time has already passed.", None
        item = self.scheduler.add("reminder", due.timestamp(), i["label"])
        if i["when"].seconds is not None:
            when = f"in {it.say_duration(i['when'].seconds)}"
        else:
            when = f"at {it.say_when(due, now)}"
        return f"I'll remind you to {i['label']} {when}.", self._added(item)

    # ---- sound and media ---------------------------------------------------------------

    async def _volume_step(self, i: it.Intent) -> tuple[str, Undo | None]:
        before = await self.control.get_volume()
        muted = await self.control.get_mute()
        target = max(0, min(100, before + i["delta"]))
        if target == before and not (muted and i["delta"] > 0):
            return f"The volume is already {'at the top' if i['delta'] > 0 else 'off'}.", None
        after = await self.control.set_volume(target)
        return f"Volume {after}.", self._restore_volume(before, muted)

    async def _volume_set(self, i: it.Intent) -> tuple[str, Undo | None]:
        before = await self.control.get_volume()
        muted = await self.control.get_mute()
        after = await self.control.set_volume(i["level"])
        return f"Volume set to {after}.", self._restore_volume(before, muted)

    def _restore_volume(self, level: int, muted: bool) -> Undo:
        async def undo() -> str:
            now = await self.control.set_volume(level)
            if muted:
                await self.control.set_mute(True)
            return f"Volume back to {now}."
        return undo

    async def _volume_get(self, i: it.Intent) -> tuple[str, Undo | None]:
        level = await self.control.get_volume()
        return f"The volume is {level}%{', and it is muted' if await self.control.get_mute() else ''}.", None

    async def _mute(self, i: it.Intent) -> tuple[str, Undo | None]:
        was = await self.control.get_mute()
        if was == i["on"]:
            return ("It's already muted." if was else "It isn't muted."), None
        await self.control.set_mute(i["on"])

        async def undo() -> str:
            await self.control.set_mute(was)
            return "Muted." if was else "Unmuted."
        return ("Muted." if i["on"] else "Unmuted."), undo

    async def _media(self, i: it.Intent) -> tuple[str, Undo | None]:
        action = i["action"]
        if action in ("pause", "play"):
            playing = await self.control.audio_playing()
            if action == "pause" and not playing:
                return "Nothing seems to be playing.", None
            if action == "play" and playing:
                return "It's already playing.", None
            await self.control.media_key("play_pause")
            return ("Paused." if action == "pause" else "Playing."), None
        await self.control.media_key("next" if action == "next" else "prev")
        return ("Next track." if action == "next" else "Previous track."), None

    # ---- display, power, information ---------------------------------------------------

    async def _theme(self, i: it.Intent) -> tuple[str, Undo | None]:
        was = await self.control.get_dark_mode()
        name = "dark" if i["dark"] else "light"
        if was == i["dark"]:
            return f"It's already in {name} mode.", None
        await self.control.set_dark_mode(i["dark"])

        async def undo() -> str:
            await self.control.set_dark_mode(was)
            return f"Back to {'dark' if was else 'light'} mode."
        return f"Switched to {name} mode.", undo

    def _restore_brightness(self, level: int) -> Undo:
        async def undo() -> str:
            return f"Brightness back to {await self.control.set_brightness(level)}."
        return undo

    async def _brightness_set(self, i: it.Intent) -> tuple[str, Undo | None]:
        before = await self.control.get_brightness()
        after = await self.control.set_brightness(i["level"])
        return f"Brightness set to {after}.", self._restore_brightness(before)

    async def _brightness_step(self, i: it.Intent) -> tuple[str, Undo | None]:
        before = await self.control.get_brightness()
        target = max(0, min(100, before + i["delta"]))
        if target == before:
            return f"The screen is already {'as bright as it goes' if i['delta'] > 0 else 'as dim as it goes'}.", None
        after = await self.control.set_brightness(target)
        return f"Brightness {after}.", self._restore_brightness(before)

    async def _lock(self, i: it.Intent) -> tuple[str, Undo | None]:
        await self.control.lock()
        return "Locked.", None

    async def _info(self, i: it.Intent) -> tuple[str, Undo | None]:
        what = i["what"]
        if what == "battery":
            b = await self.control.battery()
            if b is None:
                return "This computer has no battery.", None
            state = "plugged in" if b.plugged else "on battery"
            left = f", about {it.say_duration(b.minutes_left * 60)} left" if b.minutes_left and not b.plugged else ""
            return f"Battery's at {b.percent}%, {state}{left}.", None
        if what == "disk":
            d = await self.control.disk()
            return f"{d.free_gb:.0f} GB free of {d.total_gb:.0f} GB on {d.drive}.", None
        if what == "cpu":
            return f"The processor is at {await self.control.cpu_percent():.0f}%.", None
        if what == "memory":
            used, total = await self.control.memory()
            return f"{used:.1f} GB of {total:.0f} GB of memory in use.", None
        up = await self.control.uptime_s()
        return f"Up for {it.say_duration(max(60.0, up // 60 * 60))}.", None

    # ---- windows, settings, web --------------------------------------------------------

    async def _settings(self, i: it.Intent) -> tuple[str, Undo | None]:
        await self.control.open_uri(i["uri"])
        return f"Opening {i['title']}.", None

    async def _window(self, i: it.Intent) -> tuple[str, Undo | None]:
        await self.control.window(i["action"])
        said = {"minimize": "Minimized.", "maximize": "Maximized.", "restore": "Restored.", "desktop": "Showing the desktop.",
                "snap_left": "Snapped to the left.", "snap_right": "Snapped to the right."}
        return said[i["action"]], None

    async def _screenshot(self, i: it.Intent) -> tuple[str, Undo | None]:
        await self.control.screenshot()
        return "Snipping bar's open: drag to capture.", None

    async def _search(self, i: it.Intent) -> tuple[str, Undo | None]:
        await self.control.open_uri(i["url"])
        return f"Searching the web for {i['query']}.", None

    # ---- something due ------------------------------------------------------------------

    def due_text(self, item: Item, missed: bool) -> str:
        """What the card says when ``item`` is due."""
        if item.kind == "timer":
            text = f"Your {item.label} timer is up." if item.label else "Your timer is up."
        elif item.kind == "alarm":
            text = f"Alarm: it's {datetime.fromtimestamp(item.due).strftime('%H:%M')}."
        else:
            text = f"Reminder: {item.label}."
        if missed:
            text += f" (It was due at {datetime.fromtimestamp(item.due).strftime('%H:%M')}.)"
        return text
