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

*Asking* (ADR-016 §5.1). A disruptive change is asked about first ("Turn off Wi-Fi?"); an intent
with a detail missing ("set a timer", "remind me to call Sam") is asked for it ("For how long?",
"When?"). Either way the outcome holds the intents in ``pending`` and says what it asks
(``Outcome.ask``); the session's dialogue gets the answer and calls ``confirmed`` or ``fill``.
"No, make it four" right after a change is ``redo``: the change undone, then made again.

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

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from loguru import logger

from swift import clock
from swift.security.journal import Journal
from swift.system import intents as it
from swift.system.control import SystemControl, SystemUnavailable
from swift.system.scheduler import Item, Scheduler, SchedulerError

UNDO_S = 600.0
# Intents that change the device or reach outside Swift: journaled.
CHANGES = frozenset({
    "volume.step", "volume.set", "mute", "media", "theme", "brightness.set", "brightness.step", "lock",
    "settings", "window", "screenshot", "search", "radio", "airplane", "dnd",
})
# Where an intent sends something beyond this PC (the journal's ``domains``).
DOMAINS = {"search": ["google.com"]}


@dataclass(frozen=True)
class Outcome:
    said: str
    ok: bool = True
    # Intent names that ran, for the interaction log ("timer.set", "volume.step").
    intents: tuple[str, ...] = ()
    # Asked about, not done ("Turn off Wi-Fi?"): run them with ``SystemLane.confirmed`` on a yes.
    pending: tuple[it.Intent, ...] = ()
    # What was asked, as (dialogue kind, slot): ("yes_no", None) for a yes, ("duration", "seconds")
    # for "For how long?", ("time", "when") for "When?". None: nothing asked.
    ask: tuple[str, str | None] | None = None
    # The intents that ran, for the dialogue's carry-over ("make it louder", "no, make it four").
    done: tuple[it.Intent, ...] = ()
    # With a question: what it means, shown under it on the card, never said ("Swift needs the internet").
    note: str = ""


Undo = Callable[[], Awaitable[str]]


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# Swift's question for "turn on airplane mode": what it will really do (owner check, 2026-11-09).
AIRPLANE_QUESTION = "I can't switch airplane mode itself. Turn off Wi-Fi and Bluetooth instead?"

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
        """Carry out what the owner said. A disruptive change (Wi-Fi or Bluetooth off, airplane mode
        on) is not done: the outcome asks, and holds the intents in ``pending`` for ``confirmed``."""
        found = it.parse(text)
        if found is None:
            return None
        return await self.start(found)

    async def start(self, found: list[it.Intent]) -> Outcome:
        """Carry out ``found``, or ask first: for a missing detail, or a yes to something disruptive."""
        names = tuple(i.name for i in found)
        for intent in found:
            if (slot := it.missing(intent)) is not None:
                return Outcome(self.ask_for(intent), True, names, pending=tuple(found), ask=(it.SLOTS[intent.name][1], slot))
        if any(it.disruptive(i) for i in found):
            said, note = await self.question(found)
            return Outcome(said, True, names, pending=tuple(found), ask=("yes_no", None), note=note)
        return await self._execute(found)

    @staticmethod
    def ask_for(intent: it.Intent) -> str:
        """The question for ``intent``'s missing detail."""
        if intent.name == "timer.set":
            return f"For how long{' is the ' + intent['label'] + ' timer' if intent['label'] else ''}?"
        return "When should I remind you?"

    async def fill(self, intents: tuple[it.Intent, ...], slot: str, value: Any) -> Outcome:
        """The owner answered the question for ``slot``: finish the intents with it (or ask again,
        for a yes, if the change is disruptive)."""
        filled: list[it.Intent] = []
        for intent in intents:
            if it.missing(intent) == slot:
                slots = intent.slots | {slot: value}
                intent = it.Intent(intent.name, slots)
            filled.append(intent)
        return await self.start(filled)

    async def redo(self, intents: list[it.Intent]) -> Outcome:
        """"No, make it four": the last change undone, then ``intents`` carried out instead."""
        if self.can_undo():
            steps, self._undo = self._undo, []
            for step in reversed(steps):
                try:
                    await step()
                except (SystemUnavailable, SchedulerError):
                    pass
        return await self.start(intents)

    async def confirmed(self, intents: tuple[it.Intent, ...]) -> Outcome:
        """The owner said yes to what ``run`` asked about."""
        return await self._execute(list(intents))

    async def run_intents(self, intents: list[it.Intent]) -> Outcome:
        """For the agent's ``system_action`` tool: the gateway already confirmed and journals it."""
        return await self._execute(intents, journaled=False)

    async def question(self, found: list[it.Intent]) -> tuple[str, str]:
        """The question, short ("Turn off Wi-Fi?"), and what it means, for a quiet line under it (owner,
        2026-11-04: the explanation was said first and got in the way)."""
        names = {i.name: i for i in found}
        if "airplane" in names:
            # Windows has no supported way for an app to switch airplane mode itself: say so before, not after
            # (owner check, 2026-11-09: "yes" turned the radios off and it was reported as airplane mode).
            return (AIRPLANE_QUESTION,
                    "Windows doesn't let apps switch airplane mode itself. Swift needs the internet for most requests.")
        radio = next(i for i in found if it.disruptive(i))
        if radio["kind"] == "wifi":
            return "Turn off Wi-Fi?", "Swift needs the internet for most requests: only quick commands until it's back."
        return "Turn off Bluetooth?", "A Bluetooth headset, mouse or keyboard would disconnect."

    async def _execute(self, found: list[it.Intent], journaled: bool = True) -> Outcome:
        said: list[str] = []
        undos: list[Undo] = []
        ok = True
        for intent in found:
            action_id = self._pending(intent.name) if journaled else None
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
            self._undo, self._undo_at = undos, clock.now()
        return Outcome(" ".join(said), ok, tuple(i.name for i in found), done=tuple(found) if ok else ())

    def can_undo(self) -> bool:
        return bool(self._undo) and clock.now() - self._undo_at <= UNDO_S

    async def undo(self) -> str:
        steps, self._undo = self._undo, []
        if not steps or clock.now() - self._undo_at > UNDO_S:
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

    # ---- radios, airplane mode, Do Not Disturb -----------------------------------------

    @staticmethod
    def _radio_name(kind: str) -> str:
        return "Wi-Fi" if kind == "wifi" else "Bluetooth"

    async def _radio(self, i: it.Intent) -> tuple[str, Undo | None]:
        kind, on, name = i["kind"], i["on"], self._radio_name(i["kind"])
        state = await self.control.radios()
        if kind not in state:
            return f"This PC has no {name}.", None
        if state[kind] == on:
            return f"{name} is already {'on' if on else 'off'}.", None
        await self.control.set_radio(kind, on)
        if (await self.control.radios()).get(kind) != on:
            return f"{name} didn't switch {'on' if on else 'off'}: it's still {'off' if on else 'on'}.", None

        async def undo() -> str:
            await self.control.set_radio(kind, not on)
            return f"{name} back {'off' if on else 'on'}."
        return f"{name} {'on' if on else 'off'}.", undo

    async def _radio_get(self, i: it.Intent) -> tuple[str, Undo | None]:
        state = await self.control.radios()
        name = self._radio_name(i["kind"])
        if i["kind"] not in state:
            return f"This PC has no {name}.", None
        return f"{name} is {'on' if state[i['kind']] else 'off'}.", None

    async def _airplane(self, i: it.Intent) -> tuple[str, Undo | None]:
        """Windows' own airplane switch has no supported API for apps: this switches every radio instead,
        reads them back, and says what actually happened, never "airplane mode" (owner check, 2026-11-09)."""
        before = await self.control.radios()
        if not before:
            return "This PC has no radios to switch.", None
        want = not i["on"]
        changed = [k for k, v in before.items() if v != want]
        for kind in changed:
            try:
                await self.control.set_radio(kind, want)
            except SystemUnavailable:  # the read-back says it's stuck; the others still switch, and undo (HA-SYS-01)
                logger.warning("airplane: a radio refused", kind=kind)
        after = await self.control.radios()
        verb = "on" if want else "off"
        names = " and ".join(self._radio_name(k) for k in before)
        stuck = [k for k in before if after.get(k) != want]
        moved = [k for k in changed if k not in stuck]

        async def undo() -> str:
            for kind in moved:
                await self.control.set_radio(kind, before[kind])
            return "Radios back as they were."
        if stuck:
            done = " and ".join(self._radio_name(k) for k in moved)
            left = " and ".join(self._radio_name(k) for k in stuck)
            said = (f"{done} {'is' if len(moved) == 1 else 'are'} {verb}, but " if moved else "") + (
                f"{left} didn't switch {verb}.")
            if want:
                said += " Windows' airplane mode may be on: its switch is in quick settings."
            return said, (undo if moved else None)
        if not changed:
            return f"{names} {'are' if len(before) > 1 else 'is'} already {verb}.", None
        tail = " Windows' own airplane mode switch is unchanged." if not want else ""
        return f"{names} {'are' if len(before) > 1 else 'is'} {verb}.{tail}", undo

    async def _dnd(self, i: it.Intent) -> tuple[str, Undo | None]:
        # Do Not Disturb lives in Windows' private settings store: no supported way for an app to switch it.
        await self.control.open_uri("ms-settings:notifications")
        return "Windows doesn't let apps switch Do Not Disturb, so I've opened the setting: it's the switch at the top.", None

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
