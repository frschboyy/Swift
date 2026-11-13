"""What the owner said, as a typed system intent (ADR-016 §3.1): "set a timer for ten minutes",
"volume down", "remind me to call Sam at five", "lock the computer".

``parse(text)`` returns the list of intents for an utterance, or None. One intent in nearly every
case; a compound ("turn the volume down and pause the music") is split only when every part is
an intent on its own. There is no model and no network. The grammar is deliberately narrow:
*a wrong action is worse than a slow one*, so anything not clearly one of these (a reminder
with no time, "turn it up" about a thing that isn't sound, "open the Bluetooth thing") returns
None and goes on to the next lane, where the agent can ask.

*Slots.* An intent whose one missing detail Swift can ask for is still an intent: "set a timer" is
``timer.set`` with ``seconds`` None, "remind me to call Sam" is ``reminder.set`` with ``when`` None
(``missing``). The system lane asks "For how long?" / "When?" through the dialogue (ADR-016 §5.1),
so the grammar and the dialogue share one mechanism. Only a whole utterance may miss a slot, never
a part of a compound.

Families: timers, alarms and reminders (``schedule`` below), sound and media, brightness and
dark mode, lock, battery / disk / CPU / memory / uptime, Windows settings pages, window
management, screenshot, and a web search. Power actions (sleep, restart, shut down) are not
here: they need a spoken or on-card confirmation (ADR-016 §3.1), which waits for the
dialogue phase, so they still go to the agent and its confirm card.

Numbers may be words ("two hundred", "seven thirty"); ``fast.normalize`` turns them into digits
after the clock times are read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote_plus

from swift.routing import fast

MAX_TIMER_S = 24 * 3600
MAX_REMINDER_S = 366 * 24 * 3600

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(frozen=True)
class When:
    """When a reminder or alarm is due: a length of time from now, or a clock time."""

    seconds: float | None = None
    hour: int | None = None
    minute: int = 0
    meridiem: str | None = None  # "am" | "pm" | None
    day: str | None = None  # "today" | "tomorrow" | a weekday name | None
    next_week: bool = False  # "next monday"
    prefer_am: bool = False  # "wake me at 7": the morning one


@dataclass(frozen=True)
class Intent:
    name: str
    slots: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.slots[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.slots.get(key, default)


# ---- what was said, normalized --------------------------------------------------------------

_POLITE = re.compile(
    r"^(?:(?:can|could|would|will) you (?:please )?|i(?:'d| would) like you to |i want you to |i need you to"
    r"|go ahead and |please |hey )+"
)
_HOURS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
}
_MINUTES = {
    "oh five": 5, "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "twenty five": 25, "twenty-five": 25,
    "thirty": 30, "forty": 40, "forty five": 45, "forty-five": 45, "fifty": 50,
}
_H = "|".join(_HOURS)
_M = "|".join(sorted(_MINUTES, key=len, reverse=True))
_CLOCK_WORDS = [
    (re.compile(rf"\bhalf past ({_H})\b"), lambda m: f"{_HOURS[m.group(1)]}.30"),
    (re.compile(rf"\bquarter past ({_H})\b"), lambda m: f"{_HOURS[m.group(1)]}.15"),
    (re.compile(rf"\bquarter to ({_H})\b"), lambda m: f"{(_HOURS[m.group(1)] - 2) % 12 + 1}.45"),
    (re.compile(rf"\b(at|by|for) ({_H}) ({_M})\b"),
     lambda m: f"{m.group(1)} {_HOURS[m.group(2)]}.{_MINUTES[m.group(3)]:02d}"),
]


def normalize(text: str) -> str:
    t = re.sub(r"(?<=\d):(?=\d\d)", ".", text.lower().replace("’", "'"))  # fast.normalize drops colons
    for pattern, repl in _CLOCK_WORDS:
        t = pattern.sub(repl, t)  # "at seven thirty" before "seven thirty" becomes 37
    t = fast.normalize(t)
    return " ".join(_POLITE.sub("", t).split())


# ---- durations and clock times --------------------------------------------------------------

_N = r"\d+(?:\.\d+)?"
_UNIT = r"(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)"
_DUR = rf"{_N} ?{_UNIT}(?:(?:,? and |,? | and )?{_N} ?{_UNIT})*"
_UNIT_S = {"sec": 1, "second": 1, "min": 60, "minute": 60, "hour": 3600, "hr": 3600, "day": 86400, "week": 604800}


def seconds_of(text: str) -> float | None:
    total = 0.0
    parts = re.findall(rf"({_N}) ?({_UNIT})", text)
    for n, unit in parts:
        u = unit.rstrip("s") if unit not in ("hrs", "secs", "mins") else unit[:-1]
        if u not in _UNIT_S:
            return None
        total += float(n) * _UNIT_S[u]
    return total if parts else None


_MERIDIEM = r"(?: ?(?P<mer>a m|p m|am|pm|a\.m\.|p\.m\.))?"
_TIMEX = rf"(?P<h>\d{{1,2}})(?:[:.](?P<m>\d{{2}}))?{_MERIDIEM}(?: o'?clock)?"
_AT = re.compile(rf"\b(?:at|by|for) (?:{_TIMEX}|(?P<named>noon|midnight))\b")
_IN = re.compile(rf"\bin (?P<dur>{_DUR})\b")
_WD = "|".join(WEEKDAYS)
_DAY = re.compile(rf"\b(?P<day>today|tonight|tomorrow|this morning|this afternoon|this evening|(?:on |next |this )?(?:{_WD}))\b")


def _meridiem(raw: str | None) -> str | None:
    if not raw:
        return None
    return "am" if raw.startswith("a") else "pm"


def _clock(m: re.Match[str]) -> tuple[int, int, str | None] | None:
    if m.groupdict().get("named"):
        return (12, 0, "pm") if m.group("named") == "noon" else (0, 0, None)
    hour, minute = int(m.group("h")), int(m.group("m") or 0)
    if hour > 24 or minute > 59:
        return None
    mer = _meridiem(m.group("mer"))
    if hour > 12 and mer is not None:
        return None
    if hour > 12 and not m.group("m") and not mer:
        return None  # "at 15": too likely to be a quantity ("buy 15 apples")
    return hour % 24, minute, mer


_RECURRING = re.compile(r"\b(?:every|each|daily|weekly|monthly|yearly|annually|weekdays?|weekends?|repeat(?:ing|edly)?|recurring)\b")


def find_when(text: str, prefer_am: bool = False) -> tuple[When, str] | None:
    """The time in ``text`` and what is left of it ("call sam at 5" -> At 5, "call sam"), or None.
    A repeating request ("every weekday at 9") is not a one-off: None, so the agent can set it up."""
    if _RECURRING.search(text):
        return None
    spans: list[tuple[int, int]] = []
    if m := _IN.search(text):
        seconds = seconds_of(m.group("dur"))
        if seconds is None or not 0 < seconds <= MAX_REMINDER_S:
            return None
        spans.append(m.span())
        when = When(seconds=seconds)
    else:
        at = _AT.search(text)
        if at is None:
            return None  # a day alone ("tomorrow") needs asking what time: not here
        clock = _clock(at)
        if clock is None:
            return None
        spans.append(at.span())
        hour, minute, mer = clock
        day_word: str | None = None
        next_week = False
        if (d := _DAY.search(text)) is not None and not (at.start() <= d.start() < at.end()):
            spans.append(d.span())
            day_word = d.group("day")
            if day_word in ("tonight", "this evening", "this afternoon") and mer is None and hour < 12:
                mer = "pm"
            elif day_word == "this morning" and mer is None:
                mer = "am"
            if day_word in ("tonight", "this morning", "this afternoon", "this evening"):
                day_word = "today"
            elif day_word not in ("today", "tomorrow"):
                next_week = day_word.startswith("next ")
                day_word = day_word.split()[-1]
        when = When(hour=hour, minute=minute, meridiem=mer, day=day_word, next_week=next_week, prefer_am=prefer_am)
    rest = text
    for start, end in sorted(spans, reverse=True):
        rest = rest[:start] + " " + rest[end:]
    return when, " ".join(rest.split())


def resolve(when: When, now: datetime) -> datetime | None:
    """The moment ``when`` means after ``now`` (local, aware); None when it is already past."""
    if when.seconds is not None:
        return now + timedelta(seconds=when.seconds)
    assert when.hour is not None
    h = when.hour
    if h > 12 or h == 0:
        hours = [h]
    elif when.meridiem == "am":
        hours = [h % 12]
    elif when.meridiem == "pm":
        hours = [h % 12 + 12]
    elif when.prefer_am:
        hours = [h % 12]
    else:
        hours = [h % 12, h % 12 + 12]
    base = now.replace(second=0, microsecond=0)

    def at(day_offset: int, hour: int) -> datetime:
        return (base + timedelta(days=day_offset)).replace(hour=hour, minute=when.minute)

    if when.day == "today":
        options = [at(0, x) for x in hours]
    elif when.day == "tomorrow":
        options = [at(1, x) for x in hours]
    elif when.day in WEEKDAYS:
        # The coming one; "next friday" said on a Friday means a week on, and so does plain "friday".
        ahead = (WEEKDAYS.index(when.day) - now.weekday()) % 7 or 7
        options = [at(ahead, x) for x in hours]
    else:
        options = [at(d, x) for d in (0, 1) for x in hours]
    future = sorted(o for o in options if o > now)
    return future[0] if future else None


def say_when(due: datetime, now: datetime) -> str:
    """"14:30", "14:30 tomorrow", "14:30 on Friday"."""
    clock = due.strftime("%H:%M")
    days = (due.date() - now.date()).days
    if days == 0:
        return clock
    if days == 1:
        return f"{clock} tomorrow"
    return f"{clock} on {due.strftime('%A')}" if days < 7 else f"{clock} on {due.strftime('%A')} {due.day} {due.strftime('%B')}"


def say_duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s} second{'s' if s != 1 else ''}"
    parts: list[str] = []
    for name, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        n, s = divmod(s, size)
        if n:
            parts.append(f"{n} {name}{'s' if n != 1 else ''}")
    if s and len(parts) < 2:
        parts.append(f"{s} second{'s' if s != 1 else ''}")
    return " and ".join(parts[:2]) if len(parts) <= 2 else ", ".join(parts[:-1]) + " and " + parts[-1]


# ---- schedule: timers, alarms, reminders ----------------------------------------------------

_SET = r"(?:set|start|make|create|begin|put on|add)"
_LABEL = r"(?: (?:for|to|called|named|labelled|labeled|titled) (?P<label>[a-z0-9' ]{1,60}?))?"
_TIMER_A = re.compile(rf"(?:{_SET} )?(?:an? |the |my )?(?P<d>{_DUR}) (?:count ?down )?timer{_LABEL}")
_TIMER_B = re.compile(rf"(?:{_SET} )?(?:an? |the |my )?(?:count ?down )?timer (?:for|of|to) (?P<d>{_DUR}){_LABEL}")
_TIMER_C = re.compile(rf"(?:{_SET} )?(?:an? )?timer{_LABEL}")  # no length: needs asking
_TIMER_LEFT = re.compile(
    r"(?:how (?:long|much time)(?: is)?(?: there)?(?: left| remaining)(?: on| for| in)?(?: the| my)?(?: (?P<label>[a-z0-9' ]+?))?(?: timer)?"
    r"|(?:how long|how much time) (?:is|does) (?:the |my )?(?P<l2>[a-z0-9' ]+? )?timer (?:have )?(?:left)?"
    r"|(?:what'?s|what is) (?:the )?time (?:left|remaining)(?: on (?:the |my )?(?:[a-z0-9' ]+ )?timer)?"
    r"|(?:how long|how much) (?:is |has )?(?:left )?(?:on )?(?:the |my )?(?:[a-z0-9' ]+ )?timer(?: (?:got|has) left)?)"
)
_CANCEL = re.compile(
    r"(?:cancel|stop|delete|clear|turn off|remove|dismiss|kill|get rid of|switch off)"
    r"(?: (?:all|every|any)(?: of)?)?(?: (?:the|my|that|this|those))?(?: (?P<label>[a-z0-9' ]+?))?"
    r" (?P<what>timers?|alarms?|reminders?)(?: (?:for|called|named|to|about) (?P<l2>[a-z0-9' ]+))?"
)
_LIST = re.compile(
    r"(?:(?:what|which)(?: are| is)?(?: my| the)?(?: (?:timers?|alarms?|reminders?)))(?: (?:do i have|have i got|are (?:set|running|active)|"
    r"do i have (?:set|running)))?"
    r"|(?:what|which) (?P<w2>timers?|alarms?|reminders?)(?: do i have(?: set| running)?| are (?:set|running|active))"
    r"|(?:list|show(?: me)?|read(?: me)?|tell me) (?:all )?(?:my |the )?(?P<w3>timers?|alarms?|reminders?)"
    r"|(?:do i have|have i got) (?:any )?(?P<w4>timers?|alarms?|reminders?)(?: (?:set|running))?"
    r"|how many (?P<w5>timers?|alarms?|reminders?) (?:do i have|have i got|are (?:set|running))"
)
_ALARM = [
    re.compile(rf"(?:{_SET} )?(?:an? )?alarm (?P<when>(?:for|at) .+)"),
    re.compile(r"(?P<wake>wake me(?: up)?) (?P<when>(?:at|by|for) .+)"),
    re.compile(r"(?:alarm) (?P<when>(?:at|for) .+)"),
]
_REMIND = re.compile(rf"(?:{_SET} )?(?:an? )?reminder(?: for me)?(?: (?:to|about|that|for))? ?(?P<rest>.*)|remind me (?:to |about |that |of )?(?P<rest2>.+)")


# A reminder without a time is asked "When?" only in its plain shape: none of these in it.
_NO_SLOT_NOT = re.compile(r"\d|\b(?:at|in|by|morning|afternoon|evening|night|noon)\b")
_REMIND_TO = re.compile(r"\b(?:remind me|reminder(?: for me)?) to ")
_QUESTION_WORD = re.compile(r"(?:what|who|how|where|when|why|whether|if|which) ")
_JOINED = re.compile(r"\b(?:and|then|also)\b")
# The slot each intent can ask for, and the dialogue kind of its answer (ADR-016 §5.1).
SLOTS = {"timer.set": ("seconds", "duration"), "reminder.set": ("when", "time")}


def missing(intent: Intent) -> str | None:
    """The slot ``intent`` still needs ("seconds" for "set a timer"), or None."""
    slot = SLOTS.get(intent.name)
    return slot[0] if slot is not None and intent.get(slot[0]) is None else None


def _label(text: str, article: bool = True) -> str:
    t = re.sub(r"^(?:to|about|that|of|for)\s+", "", text.strip())
    t = re.sub(r"\s+(?:and|then|to|that)$", "", t)
    t = re.sub(r"^(?:and|then)\s+", "", t)
    if article:  # "the pasta" -> "pasta" (a reminder keeps its wording: "buy a cake")
        t = re.sub(r"^(?:the|a|an|my)\s+", "", t)
    return " ".join(t.split())[:100]


def _timer(m: re.Match[str]) -> Intent | None:
    seconds = seconds_of(m.group("d"))
    if seconds is None or not 0 < seconds <= MAX_TIMER_S:
        return None
    return Intent("timer.set", {"seconds": seconds, "label": _label(m.groupdict().get("label") or "")})


def _kind(word: str) -> str:
    return word.rstrip("s")


def _schedule(t: str) -> Intent | None:
    for pattern in (_TIMER_A, _TIMER_B):
        if m := pattern.fullmatch(t):
            return _timer(m)
    if (m := _TIMER_C.fullmatch(t)) and not _NO_SLOT_NOT.search(m.group("label") or "") and not _JOINED.search(t):
        # "Set a timer", "start a timer for the pasta": for how long? Asked (``missing``), never guessed.
        return Intent("timer.set", {"seconds": None, "label": _label(m.groupdict().get("label") or "")})
    if m := _TIMER_LEFT.fullmatch(t):
        label = _label(m.groupdict().get("label") or m.groupdict().get("l2") or "")
        return Intent("timer.left", {"label": "" if label in ("timer", "timers", "the timer", "my timer") else label})
    if m := _CANCEL.fullmatch(t):
        if _kind(m.group("what")) == "reminder" and m.group("label") and m.group("label") not in ("my", "the", "that", "this", "those", "all", "every", "any", "all my", "all the"):
            return None  # "cancel the Friday reminder": maybe a calendar event, so the agent looks
        label = _label(m.group("label") or m.group("l2") or "")
        every = bool(re.search(r"\b(?:all|every|any)\b", t)) or m.group("what").endswith("s")
        if label in ("my", "the", "that", "this", "those", "all", "every", "any"):
            label = ""
        return Intent("cancel", {"kind": _kind(m.group("what")), "label": label, "all": every and not label})
    if m := _LIST.fullmatch(t):
        what = next((g for g in (m.groupdict().get(k) for k in ("w2", "w3", "w4", "w5")) if g), None)
        if what is None:
            found = re.search(r"timers?|alarms?|reminders?", t)
            what = found.group(0) if found else None
        return Intent("list", {"kind": _kind(what)}) if what else None
    for pattern in _ALARM:
        if m := pattern.fullmatch(t):
            found = find_when(m.group("when"), prefer_am=bool(m.groupdict().get("wake")))
            if found is None or found[1]:
                return None
            return Intent("alarm.set", {"when": found[0]})
    if m := _REMIND.fullmatch(t):
        rest = (m.group("rest") if m.group("rest") is not None else m.group("rest2")) or ""
        found = find_when(rest)
        if found is None:
            # "Remind me to call Sam": what time? Not guessed: asked (``missing``). Only that plain shape:
            # a day without a time ("on Friday", "8am tomorrow"), a repeating one, a number, or "remind me
            # what we decided" (a question, not a reminder) still goes on to the agent.
            if _RECURRING.search(rest) or _DAY.search(rest) or _NO_SLOT_NOT.search(rest):
                return None
            if not _REMIND_TO.search(t):
                return None  # "remind me what we decided", "remind me how": a question about something
            label = _label(rest, article=False)
            if not label or len(label.split()) > 10 or _QUESTION_WORD.match(label):
                return None
            if _JOINED.search(label):
                return None  # maybe two requests: the agent sorts it out
            return Intent("reminder.set", {"when": None, "label": label})
        label = _label(found[1], article=False)
        if not label:
            return None
        return Intent("reminder.set", {"when": found[0], "label": label})
    return None


# ---- sound and media ------------------------------------------------------------------------

_VOL = r"(?:the )?(?:volume|sound|audio|speakers?|sound level|volume level)"
_PCT = r"(?:%| ?percent| ?per cent)?"
_STEP_WORDS = {"a bit": 5, "a little": 5, "a little bit": 5, "slightly": 5, "a notch": 5, "a lot": 25, "much": 25}
_AMOUNT = r"(?: (?:by )?(?P<amt>a bit|a little bit|a little|slightly|a notch|a lot|\d{1,3}))?"
_VOL_SET = [
    re.compile(rf"(?:set|change|make|put|turn|bring|adjust)? ?{_VOL} (?:up |down )?(?:to|at) (?P<n>\d{{1,3}}){_PCT}"),
    re.compile(rf"{_VOL} (?:to |at )?(?P<n>\d{{1,3}}){_PCT}"),
    re.compile(rf"(?:set|put|turn) it (?:to|at) (?P<n>\d{{1,3}}){_PCT}(?: volume)?"),
]
_VOL_UP_DOWN = [
    re.compile(rf"(?:turn|pump|bring|crank|put|make)? ?{_VOL} (?P<dir>up|down){_AMOUNT}{_PCT}"),
    re.compile(rf"(?:turn|pump|bring|crank|put) (?P<dir>up|down) {_VOL}{_AMOUNT}{_PCT}"),
    re.compile(rf"(?P<verb>raise|lower|increase|decrease|reduce|boost|drop|cut) {_VOL}{_AMOUNT}{_PCT}"),
    re.compile(rf"(?:turn|make) it (?P<dir>up|down){_AMOUNT}{_PCT}"),
    re.compile(rf"(?:make|turn) (?:it|{_VOL}|the music) (?:a (?:bit|little|little bit|lot) )?(?P<cmp>louder|quieter|softer|lower)(?: a (?:bit|little|lot))?"),
    re.compile(r"(?:a (?:bit|little|little bit|lot) )?(?P<cmp>louder|quieter)(?: a (?:bit|little|lot))?"),
]
_VOL_GET = re.compile(rf"(?:what'?s|what is|how loud is|check) {_VOL}(?: (?:at|set to))?|how loud is it|what volume (?:is it|am i) (?:at|on)")
_MUTE = re.compile(rf"(?:mute|silence) (?:the |my )?(?:volume|sound|audio|computer|laptop|pc|speakers?|everything)|(?P<un>unmute)(?: (?:the |my )?(?:volume|sound|audio|computer|laptop|pc|speakers?|everything))?"
                   rf"|turn (?:off|on) (?:the )?(?:sound|audio)|(?:un ?mute|turn the sound back on)")
_MEDIA = [
    (re.compile(r"(?:pause|stop|hold)(?: the| my| this)? (?:music|song|track|media|video|audio|playback|podcast|playing)"), "pause"),
    (re.compile(r"(?:pause|stop) (?:it|playback|the playback)"), "pause"),
    (re.compile(r"(?:play|resume|continue|start|unpause)(?: the| my| some)? (?:music|song|track|media|video|audio|playback|podcast)"), "play"),
    (re.compile(r"(?:resume|unpause)(?: playback)?|(?:resume|continue) (?:it|playing)"), "play"),
    (re.compile(r"(?:skip|next|forward)(?: to)?(?: the| this| that)?(?: next)?(?: song| track| one)"), "next"),
    (re.compile(r"(?:skip(?: it| this| that)?|next (?:song|track))"), "next"),
    (re.compile(r"(?:previous|last|prior) (?:song|track)|(?:go )?back (?:a|one) (?:song|track)|play the previous (?:song|track|one)|previous"), "prev"),
]

# ---- display, power, information ------------------------------------------------------------

_THEME = [
    re.compile(r"(?:turn|switch|set|change|go|put|flip|enable|activate)(?: (?:on|to|into|it to))? (?:the )?(?:windows )?(?P<m>dark|light)(?: mode| theme)?"),
    re.compile(r"(?P<verb>turn|switch) (?P<onoff>on|off) (?:the )?(?:windows )?(?P<m>dark|light)(?: mode| theme)"),
    re.compile(r"(?P<verb>enable|disable) (?:the )?(?:windows )?(?P<m>dark|light)(?: mode| theme)"),
    re.compile(r"(?P<m>dark|light) (?:mode|theme) (?P<onoff>on|off)"),
    re.compile(r"(?:use|switch to) (?:the )?(?P<m>dark|light) (?:mode|theme)"),
]
_SCREEN = r"(?:the )?(?:screen |display |monitor )?brightness"
_BRIGHT_SET = re.compile(rf"(?:set|change|make|put|turn|bring)? ?{_SCREEN} (?:up |down )?(?:to|at) (?P<n>\d{{1,3}}){_PCT}")
_BRIGHT_STEP = [
    re.compile(rf"(?:turn|bring|put|make)? ?{_SCREEN} (?P<dir>up|down){_AMOUNT}{_PCT}"),
    re.compile(rf"(?:turn|bring|put) (?P<dir>up|down) {_SCREEN}{_AMOUNT}{_PCT}"),
    re.compile(rf"(?P<verb>raise|lower|increase|decrease|reduce|boost) {_SCREEN}{_AMOUNT}{_PCT}"),
    re.compile(r"(?P<verb>dim|brighten)(?: up)? (?:the )?(?:screen|display|monitor)"),
    re.compile(r"(?:make|turn) (?:the )?(?:screen|display|monitor) (?P<cmp>brighter|dimmer|darker)"),
]
_LOCK = re.compile(r"lock(?: up)?(?: (?:my|the))?(?: computer| pc| laptop| screen| workstation| windows| machine)(?: now)?|lock (?:it|up)(?: now)?")
_INFO = [
    ("battery", re.compile(r"(?:what'?s|what is|how'?s|how is|check|tell me)(?: my| the)? battery(?: level| life| percentage| status| charge| left)?|how much battery(?: life| power)?(?: do i have| have i got| is left| is there)?(?: left)?|battery(?: level| percentage| status)|am i (?:plugged in|charging|on battery)|is (?:my|the) (?:laptop|pc|computer|battery) (?:plugged in|charging)")),
    ("disk", re.compile(r"how much (?:free )?(?:disk |storage |drive |hard drive )?space(?: do i have| is there)?(?: left| free| available| on (?:my |the )?(?:c )?(?:drive|disk))?|how full is (?:my |the )?(?:c )?(?:drive|disk)|(?:what'?s|what is) my (?:free )?(?:disk|storage) space|disk space(?: left| free)?")),
    ("cpu", re.compile(r"(?:what'?s|what is|check) (?:my )?(?:cpu|processor)(?: usage| load| use)?|how (?:busy|loaded|hard is) (?:is )?(?:my )?(?:cpu|computer|pc|processor|laptop)(?: working)?|cpu usage")),
    ("memory", re.compile(r"how much (?:ram|memory)(?: is)?(?: (?:am i|are we))?(?: using| used| free| left| in use| available)?(?: do i have)?|(?:what'?s|what is|check) my (?:ram|memory)(?: usage| use)?|memory usage")),
    ("uptime", re.compile(r"how long has (?:my |the )?(?:computer|pc|laptop|machine) been (?:on|running|up)|(?:what'?s|what is) my uptime|uptime")),
]
SETTINGS_PAGES: dict[str, tuple[str, str]] = {
    "": ("ms-settings:", "Settings"),
    "bluetooth": ("ms-settings:bluetooth", "Bluetooth settings"),
    "wifi": ("ms-settings:network-wifi", "Wi-Fi settings"),
    "wi-fi": ("ms-settings:network-wifi", "Wi-Fi settings"),
    "wi fi": ("ms-settings:network-wifi", "Wi-Fi settings"),
    "network": ("ms-settings:network", "Network settings"),
    "internet": ("ms-settings:network", "Network settings"),
    "display": ("ms-settings:display", "Display settings"),
    "screen": ("ms-settings:display", "Display settings"),
    "sound": ("ms-settings:sound", "Sound settings"),
    "audio": ("ms-settings:sound", "Sound settings"),
    "battery": ("ms-settings:batterysaver", "Battery settings"),
    "power": ("ms-settings:powersleep", "Power settings"),
    "apps": ("ms-settings:appsfeatures", "Apps settings"),
    "default apps": ("ms-settings:defaultapps", "Default apps settings"),
    "privacy": ("ms-settings:privacy", "Privacy settings"),
    "microphone": ("ms-settings:privacy-microphone", "Microphone privacy settings"),
    "notification": ("ms-settings:notifications", "Notification settings"),
    "notifications": ("ms-settings:notifications", "Notification settings"),
    "update": ("ms-settings:windowsupdate", "Windows Update"),
    "windows update": ("ms-settings:windowsupdate", "Windows Update"),
    "storage": ("ms-settings:storagesense", "Storage settings"),
    "personalization": ("ms-settings:personalization", "Personalization settings"),
    "background": ("ms-settings:personalization-background", "Background settings"),
    "accounts": ("ms-settings:yourinfo", "Account settings"),
    "time": ("ms-settings:dateandtime", "Date and time settings"),
    "date and time": ("ms-settings:dateandtime", "Date and time settings"),
    "language": ("ms-settings:regionlanguage", "Language settings"),
    "focus": ("ms-settings:quiethours", "Focus settings"),
    "printers": ("ms-settings:printers", "Printer settings"),
    "mouse": ("ms-settings:mousetouchpad", "Mouse settings"),
    "keyboard": ("ms-settings:easeofaccess-keyboard", "Keyboard settings"),
    "bluetooth and devices": ("ms-settings:bluetooth", "Bluetooth settings"),
}
_SETTINGS = re.compile(r"(?:open|show|go to|bring up|pull up|launch)(?: up)?(?: the| my| windows)? (?:(?P<page>[a-z -]+?) )?settings(?: page| app)?")
_WINDOW = [
    (re.compile(r"minimi[sz]e(?: (?:this|the|my|current))?(?: window| app| program)?"), "minimize"),
    (re.compile(r"maximi[sz]e(?: (?:this|the|my|current))?(?: window| app| program)?|make (?:this|the) window (?:full ?screen|bigger|full size)"), "maximize"),
    (re.compile(r"restore(?: (?:this|the|my|current))?(?: window| app| program)|un ?maximi[sz]e(?: (?:this|the))?(?: window)?"), "restore"),
    (re.compile(r"(?:show|go to|bring up)(?: me)? (?:the )?desktop|minimi[sz]e (?:all|everything|all (?:the |my )?windows|all (?:the |my )?apps)|clear (?:the |my )?screen"), "desktop"),
    (re.compile(r"snap(?: (?:this|the))?(?: window)? (?:to the )?left|(?:put|move|send) (?:this|the) window (?:to the )?left"), "snap_left"),
    (re.compile(r"snap(?: (?:this|the))?(?: window)? (?:to the )?right|(?:put|move|send) (?:this|the) window (?:to the )?right"), "snap_right"),
]
_SCREENSHOT = re.compile(r"(?:take|grab|capture|make)(?: me)? (?:a |the )?(?:screenshot|screen shot|screen capture|screen grab|snip)(?: of (?:the |my )?screen)?|(?:screenshot|screen shot|snip)(?: (?:this|the screen|please))?")
_QUERY = r"(?P<q>[a-z0-9' .&+-]{2,100})"
# Only when the web is named ("search the web for ...", "google ..."): plain "search for ..." could mean files or code.
_SEARCH = re.compile(
    rf"(?:search|look)(?: up)? (?:the web|the internet|online|google|bing|the net)(?: for| up| about)? {_QUERY}"
    rf"|(?:google|bing) (?:for |up |about )?(?P<q2>[a-z0-9' .&+-]{{2,100}})"
)
_SEARCH_WORDS = re.compile(r"\b(?:and|then|also|into|in word|save|email|send|write|summari[sz]e|compare|file|document|folder|calendar)\b")
_SEARCH_START = re.compile(r"^(?:search|google|bing|look)\b")


def _amount(m: re.Match[str], default: int = 10) -> int:
    raw = m.groupdict().get("amt")
    if not raw:
        return default
    if raw in _STEP_WORDS:
        return _STEP_WORDS[raw]
    return max(1, min(100, int(raw)))


def _direction(m: re.Match[str]) -> int | None:
    g = m.groupdict()
    word = g.get("dir") or g.get("cmp") or g.get("verb")
    if word in ("up", "louder", "raise", "increase", "boost", "brighten", "brighter"):
        return 1
    if word in ("down", "quieter", "softer", "lower", "decrease", "reduce", "drop", "cut", "dim", "dimmer", "darker"):
        return -1
    return None


def _sound(t: str) -> Intent | None:
    for pattern in _VOL_SET:
        if m := pattern.fullmatch(t):
            return Intent("volume.set", {"level": min(100, int(m.group("n")))})
    for pattern in _VOL_UP_DOWN:
        if m := pattern.fullmatch(t):
            sign = _direction(m)
            if sign is None:
                continue
            amount = _amount(m)
            if m.groupdict().get("cmp") and re.search(r"\b(?:a bit|a little|a lot)\b", t):
                amount = 5 if "lot" not in t else 25
            return Intent("volume.step", {"delta": sign * amount})
    if _VOL_GET.fullmatch(t):
        return Intent("volume.get")
    if m := _MUTE.fullmatch(t):
        unmute = bool(m.groupdict().get("un")) or t.startswith(("unmute", "un mute", "turn on", "turn the sound back"))
        return Intent("mute", {"on": not unmute})
    for pattern, action in _MEDIA:
        if pattern.fullmatch(t):
            return Intent("media", {"action": action})
    return None


def _display(t: str) -> Intent | None:
    for pattern in _THEME:
        if m := pattern.fullmatch(t):
            dark = m.group("m") == "dark"
            onoff = m.groupdict().get("onoff") or ("off" if m.groupdict().get("verb") in ("disable",) else "on")
            if m.groupdict().get("verb") == "enable":
                onoff = "on"
            return Intent("theme", {"dark": dark if onoff == "on" else not dark})
    if m := _BRIGHT_SET.fullmatch(t):
        return Intent("brightness.set", {"level": min(100, int(m.group("n")))})
    for pattern in _BRIGHT_STEP:
        if m := pattern.fullmatch(t):
            sign = _direction(m)
            if sign is not None:
                return Intent("brightness.step", {"delta": sign * _amount(m, 20)})
    return None


def _device(t: str) -> Intent | None:
    if _LOCK.fullmatch(t):
        return Intent("lock")
    for what, pattern in _INFO:
        if pattern.fullmatch(t):
            return Intent("info", {"what": what})
    if m := _SETTINGS.fullmatch(t):
        page = (m.group("page") or "").strip()
        if page in SETTINGS_PAGES:
            uri, title = SETTINGS_PAGES[page]
            return Intent("settings", {"uri": uri, "title": title})
        return None
    for pattern, action in _WINDOW:
        if pattern.fullmatch(t):
            return Intent("window", {"action": action})
    if _SCREENSHOT.fullmatch(t):
        return Intent("screenshot")
    if (m := _SEARCH.fullmatch(t)) is not None:
        q = (m.group("q") or m.group("q2")).strip()
        if q and not _SEARCH_WORDS.search(q) and len(q.split()) <= 12:
            return Intent("search", {"query": q, "url": "https://www.google.com/search?q=" + quote_plus(q)})
    return None


# ---- radios and Do Not Disturb (ADR-016 §3.2, Phase A2) ---------------------------------------

_RADIO = r"(?:the |my )?(?P<radio>wi-?fi|wi fi|wireless|bluetooth|blue tooth)"
_ONOFF = r"(?P<onoff>on|off)"
# "Back" and "again" too: "turn the Wi-Fi back on", "Bluetooth on again" (seams audit D-03: offline,
# these went to the agent and got "I'm offline", while the offline list itself says "turn it back on").
_AGAIN = r"(?: (?:back|again|now|please))*"
_RADIO_SWITCH = [
    re.compile(rf"(?:turn|switch|toggle|put|flip) {_RADIO} (?:back )?{_ONOFF}{_AGAIN}"),
    re.compile(rf"(?:turn|switch|put|flip) (?:back )?{_ONOFF} {_RADIO}{_AGAIN}"),
    # Not "connect to Wi-Fi": that can mean joining a network, not switching the radio on.
    re.compile(rf"(?P<verb>enable|disable|activate|deactivate|disconnect|re-?enable) {_RADIO}{_AGAIN}"),
    re.compile(rf"{_RADIO} (?:back )?{_ONOFF}{_AGAIN}"),
]
_RADIO_GET = re.compile(rf"(?:(?:is|are) {_RADIO} (?:on|off|enabled|working|switched on|turned on)"
                        rf"|(?:what'?s|what is|check) {_RADIO.replace('radio>', 'radio2>')}(?: status| state)?)")
_PLANE = r"(?:the )?(?:airplane|aeroplane|flight|plane) mode"
_AIRPLANE = [
    re.compile(rf"(?:turn|switch|put|flip) (?:back )?{_ONOFF} {_PLANE}{_AGAIN}"),
    re.compile(rf"(?:turn|switch|put|flip) {_PLANE} (?:back )?{_ONOFF}{_AGAIN}"),
    re.compile(rf"(?P<verb>enable|disable|activate|deactivate|start|stop|exit|leave) {_PLANE}"),
    re.compile(rf"{_PLANE} (?:back )?{_ONOFF}{_AGAIN}"),
    re.compile(rf"(?:go|put (?:it|the (?:computer|pc|laptop)))(?: in| into) {_PLANE}"),
]
_DND = r"(?:do not disturb|dnd|focus(?: mode| assist)?)"
_DND_SWITCH = [
    re.compile(rf"(?:turn|switch|put|flip) {_ONOFF} {_DND}"),
    re.compile(rf"(?:turn|switch|put|flip) {_DND} {_ONOFF}"),
    re.compile(rf"(?P<verb>enable|disable|activate|deactivate|start|stop) {_DND}"),
    re.compile(rf"{_DND} {_ONOFF}"),
]
_OFF_VERBS = ("disable", "deactivate", "disconnect", "stop", "exit", "leave")


def _on(m: re.Match[str]) -> bool:
    g = m.groupdict()
    if g.get("onoff"):
        return g["onoff"] == "on"
    return g.get("verb") not in _OFF_VERBS


def heard_as_wifi(words: str) -> bool:
    """Whether ``words`` is how speech recognition mishears "Wi-Fi": "wafer", "Wofo", "waffle", "why fi"
    (owner checks 201 and 206, 2026-11-13). Its consonants are a w then an f or v, and at most one more."""
    joined = words.replace(" ", "")
    if not joined.isalpha() or not joined.startswith("w") or len(joined) > 6 or len(words.split()) > 2:
        return False
    skeleton = re.sub(r"(.)\1+", r"\1", re.sub(r"[aeiouyh]", "", joined))
    return re.fullmatch(r"w[fv][rl]?", skeleton) is not None


# "Turn off the wafer": the radio slot, whatever was heard there, for ``heard_as_wifi``.
_HEARD_OFF = [
    re.compile(r"(?:turn|switch|put|flip) (?:the |my )?(?P<radio>[a-z]+(?: [a-z]+)?) off(?: (?:now|please))*"),
    re.compile(r"(?:turn|switch|put|flip) off (?:the |my )?(?P<radio>[a-z]+(?: [a-z]+)?)(?: (?:now|please))*"),
    re.compile(r"(?:disable|deactivate|disconnect) (?:the |my )?(?P<radio>[a-z]+(?: [a-z]+)?)"),
]


def _radios(t: str) -> Intent | None:
    for pattern in _RADIO_SWITCH:
        if m := pattern.fullmatch(t):
            kind = "bluetooth" if "blue" in m.group("radio") else "wifi"
            return Intent("radio", {"kind": kind, "on": _on(m)})
    for pattern in _HEARD_OFF:
        # Only off: that always has Swift's own "Turn off Wi-Fi?", so a wrong guess costs a "no". A guessed
        # "on" has no question and would act on a guess, so it stays unparsed.
        if (m := pattern.fullmatch(t)) and heard_as_wifi(m.group("radio")):
            return Intent("radio", {"kind": "wifi", "on": False})
    if m := _RADIO_GET.fullmatch(t):
        return Intent("radio.get", {"kind": "bluetooth" if "blue" in (m.group("radio") or m.group("radio2")) else "wifi"})
    for pattern in _AIRPLANE:
        if m := pattern.fullmatch(t):
            return Intent("airplane", {"on": _on(m)})
    for pattern in _DND_SWITCH:
        if m := pattern.fullmatch(t):
            return Intent("dnd", {"on": _on(m)})
    return None


# Changes that take something away the owner may be relying on: Swift asks first (ADR-016 §3.1).
def disruptive(intent: Intent) -> bool:
    return (intent.name == "radio" and not intent["on"]) or (intent.name == "airplane" and intent["on"])


def parse_one(text: str) -> Intent | None:
    """One intent from the whole of ``text``, or None."""
    t = normalize(text)
    if not t or len(t) > 160:
        return None
    return _schedule(t) or _sound(t) or _display(t) or _radios(t) or _device(t)


_SPLIT = re.compile(r"\s+(?:and then|and also|and|then|also|,)\s+|\s*,\s*(?:and |then )?")


def parse(text: str) -> list[Intent] | None:
    """The intents in ``text``: one, or several when every part of a compound is one; else None."""
    if (one := parse_one(text)) is not None:
        return [one]
    cleaned = normalize(text)
    parts = [p for p in _SPLIT.split(cleaned) if p.strip()]
    if not 2 <= len(parts) <= 3:
        return None
    found = [parse_one(p) for p in parts]
    if not all(found) or any(missing(i) for i in found if i is not None):
        return None  # only a whole utterance may leave a detail to ask for
    return [i for i in found if i is not None]
