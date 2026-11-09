"""The fast lane (ADR-007 §10): everyday questions Swift answers itself, in a few milliseconds.

``answer(text)`` returns a short spoken-style answer, or None when the request isn't one of
these. No model, no network, nothing logged; the router calls it to pick the lane and the
session calls it again (with the time then) to answer. Families:

- **time**: now, "in two minutes", "3 hours ago", "in an hour and a half", "what time is it in Tokyo";
- **date**: today, tomorrow, "next Friday's date", "what day is the 3rd of November",
  "how many days until Christmas", "what month / year / week is it";
- **conversions**: length, mass, volume, temperature, speed, time ("5 km in miles");
- **arithmetic**: "12 times 7", "15% of 80", "square root of 144", "20% off 50";
- **spelling**: "how do you spell necessary".

Phrasing is tolerant: a leading "and", "so", "ok", "Swift," or "can you tell me" is dropped,
and numbers can be words ("two hundred and fifty"). Anything not clearly one of these
returns None and goes on to the next lane: a wrong answer here is worse than a slow one.
City times come from a small table of cities with their DST rules (no tz database on Windows).
"""

from __future__ import annotations

import ast
import calendar
import math
import operator
import re
import string
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

# ---- normalizing what was said ------------------------------------------------------------

_WAKE = re.compile(
    r"^\s*(?:(?:hey|hi|hello|ok|okay)|good\s+(?:morning|afternoon|evening))?\s*swift\b[\s,.:!-]*", re.IGNORECASE
)
_LEAD = re.compile(
    r"^(?:(?:and|so|ok|okay|right|alright|all right|then|also|oh|well|but|now|hey|hi|um+|uh+|er+|hmm+|quick question"
    r"|one more thing|actually)\b[\s,]*)+"
)
_ASK = re.compile(
    r"^(?:(?:can|could|would|will) you (?:please )?(?:tell me|work out|figure out|calculate|check|say|(?=convert\b))|do you know"
    r"|tell me|i(?:'d| would) like to know|i want to know|i need to know|please|quickly)\b[\s,]*"
)
_TAIL = re.compile(r"(?:[\s,]+(?:please|then|again|for me|swift|thanks|thank you))+$")

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
_NUMBER_WORD = re.compile(
    rf"\b(?:{'|'.join([*_ONES, *_TENS, *_SCALES])})(?:(?:[\s-]+|\s+and\s+)(?:{'|'.join([*_ONES, *_TENS, *_SCALES])}))*\b"
)


def _word_number(words: str) -> str:
    total = current = 0
    for w in re.split(r"[\s-]+", words):
        if w == "and":
            continue
        if w in _ONES:
            current += _ONES[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = max(current, 1) * 100
        else:
            total += max(current, 1) * _SCALES[w]
            current = 0
    return str(total + current)


_PHRASES = [
    (r"\b(?:an|one) hour and a half\b", "90 minutes"),
    (r"\bhalf an hour\b", "30 minutes"),
    (r"\ba quarter of an hour\b|\bquarter of an hour\b|\ba quarter hour\b", "15 minutes"),
    (r"\b(\d+) and a half (\w+)", lambda m: f"{int(m.group(1)) + 0.5:g} {m.group(2)}"),
    (r"\ba couple of\b|\ba couple\b", "2"),
    (r"\ba dozen\b", "12"),
    (r"\b(?:a|an|one) (second|minute|hour|day|week|month|year|fortnight)\b", r"1 \1"),
    (r"\b(?:a|an|one) (?=(?:km|kilometre|kilometer|mile|metre|meter|foot|inch|yard|pound|kilo|kilogram|gram|ounce"
     r"|stone|litre|liter|gallon|pint|cup|tablespoon|teaspoon|centimetre|centimeter|millimetre|millimeter|tonne|ton)s?\b)",
     "1 "),
    (r"\bminus (?=\d)|\bnegative (?=\d)", "-"),
    (r"\bpoint (\d)", r".\1"),
]


def normalize(text: str) -> str:
    """Lower case, without Swift's name, lead-ins ("and", "can you tell me") or fillers; numbers as digits."""
    t = _WAKE.sub("", text.strip()).lower().replace("’", "'").replace("°", " degrees ")
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)  # 1,000
    t = re.sub(r"[?!]+|\.(?!\d)|[,;:\"]", " ", t)
    t = " ".join(t.split())
    t = _TAIL.sub("", _ASK.sub("", _LEAD.sub("", t)))
    t = _LEAD.sub("", t)
    t = _NUMBER_WORD.sub(lambda m: _word_number(m.group(0)), t)
    t = re.sub(r"(\d) point (\d)", r"\1.\2", t)
    for pattern, repl in _PHRASES:
        t = re.sub(pattern, repl, t)  # type: ignore[arg-type]
    return " ".join(t.split()).strip()


# ---- speaking numbers, times and dates -----------------------------------------------------


def _num(x: float) -> str:
    if abs(x - round(x)) < 1e-9 and abs(x) < 1e15:
        return f"{round(x):,}"
    if abs(x) >= 100:
        return f"{x:,.1f}".rstrip("0").rstrip(".")
    if abs(x) >= 0.01:
        return f"{x:.2f}".rstrip("0").rstrip(".")
    return f"{x:.3g}"


def _hm(t: datetime) -> str:
    return t.strftime("%H:%M")


def _day(d: date) -> str:
    return f"{d.strftime('%A')}, {d.day} {d.strftime('%B %Y')}"


def _relative(d: date, today: date) -> str:
    days = (d - today).days
    return {0: "today", 1: "tomorrow", -1: "yesterday", 2: "the day after tomorrow"}.get(days, "")


# ---- what an answer was about, for the follow-up ("and the date?") ------------------------------


@dataclass(frozen=True)
class Moment:
    """The moment a time or date answer was about: "one week from today" is next Tuesday."""

    # Aware; in that city's own offset when the answer was another city's time.
    at: datetime
    # The answer gave a time of day ("It'll be 16:30"), not only a day.
    timed: bool
    city: str | None = None


class _Said(str):
    moment: Moment | None = None


def _said(text: str, at: datetime, timed: bool, city: str | None = None) -> str:
    out = _Said(text)
    out.moment = Moment(at, timed, city)
    return out


def _on(d: date, now: datetime) -> datetime:
    return now.replace(year=d.year, month=d.month, day=d.day)


# ---- durations ------------------------------------------------------------------------------

_UNIT_S = {
    "second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600,
    "day": 86400, "week": 604800, "fortnight": 1209600,
}
_N = r"-?\d+(?:\.\d+)?"
_DUR_PART = rf"(?:{_N}) ?(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|fortnights?|months?|years?)"
_DUR = rf"{_DUR_PART}(?:,? (?:and )?{_DUR_PART})*"


def _duration(text: str) -> tuple[timedelta, int] | None:
    """(time, months) in "2 hours and 30 minutes" / "3 months"."""
    seconds, months = 0.0, 0
    parts = re.findall(rf"({_N}) ?([a-z]+)", text)
    if not parts:
        return None
    for n, unit in parts:
        u = unit.rstrip("s") if unit not in ("hrs", "mins", "secs") else unit[:-1]
        if u in ("month", "year"):
            if float(n) != int(float(n)):
                return None
            months += int(float(n)) * (12 if u == "year" else 1)
        elif u in _UNIT_S:
            seconds += float(n) * _UNIT_S[u]
        else:
            return None
    return timedelta(seconds=seconds), months


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1]))


# ---- time ----------------------------------------------------------------------------------

_TIME_NOW = re.compile(
    r"(?:what(?:'s| is)? the time|what time is it|what time it is|the time|time|what time have you got|have you got the time)"
    r"(?: now| right now| at the moment| please)?"
)
_TIME_IN = re.compile(
    rf"(?:what(?:'s| is)? (?:the )?time (?:will it be|is it going to be|would it be|is it|it will be|be)?"
    rf"|what(?:'s| is| will be) the time|what time(?: will it be| is it going to be| would it be| is it)?"
    rf"|what(?:'s| is| will it be)|what time is|time)? ?(?:in (?P<in>{_DUR})|(?P<from>{_DUR}) (?:from now|from now on|later|time))"
)
_TIME_AGO = re.compile(rf"(?:what time (?:was it|was)|what was the time) (?P<ago>{_DUR}) ago")


def _time_answer(t: str, now: datetime) -> str | None:
    if _TIME_NOW.fullmatch(t):
        return _said(f"It's {_hm(now)}.", now, True)
    m = _TIME_IN.fullmatch(t)
    if m and "time" not in t and "from" not in t and "later" not in t:
        m = None  # "what's in 3 days" is a date question
    if m:
        dur = _duration(m.group("in") or m.group("from"))
        if dur is None or dur[1]:
            return None
        then = now + dur[0]
        if dur[0] >= timedelta(days=2):
            return _said(f"It'll be {_hm(then)} on {_day(then.date())}.", then, True)
        when = _relative(then.date(), now.date())
        return _said(f"It'll be {_hm(then)}" + (f" {when}." if when and when != "today" else "."), then, True)
    if m := _TIME_AGO.fullmatch(t):
        dur = _duration(m.group("ago"))
        if dur is None or dur[1]:
            return None
        then = now - dur[0]
        when = _relative(then.date(), now.date())
        return _said(f"It was {_hm(then)}" + (f" {when}." if when and when != "today" else "."), then, True)
    return None


# ---- other cities -------------------------------------------------------------------------

# City: (standard UTC offset in hours, DST rule or None).
CITIES: dict[str, tuple[float, str | None]] = {
    "london": (0, "eu"), "dublin": (0, "eu"), "lisbon": (0, "eu"), "edinburgh": (0, "eu"), "manchester": (0, "eu"),
    "paris": (1, "eu"), "berlin": (1, "eu"), "madrid": (1, "eu"), "barcelona": (1, "eu"), "rome": (1, "eu"),
    "milan": (1, "eu"), "amsterdam": (1, "eu"), "brussels": (1, "eu"), "vienna": (1, "eu"), "zurich": (1, "eu"),
    "geneva": (1, "eu"), "stockholm": (1, "eu"), "oslo": (1, "eu"), "copenhagen": (1, "eu"), "warsaw": (1, "eu"),
    "prague": (1, "eu"), "budapest": (1, "eu"), "munich": (1, "eu"), "frankfurt": (1, "eu"),
    "athens": (2, "eu"), "bucharest": (2, "eu"), "helsinki": (2, "eu"), "kyiv": (2, "eu"), "kiev": (2, "eu"),
    "sofia": (2, "eu"), "riga": (2, "eu"), "vilnius": (2, "eu"), "tallinn": (2, "eu"),
    "istanbul": (3, None), "moscow": (3, None), "riyadh": (3, None), "doha": (3, None), "nairobi": (3, None),
    "lagos": (1, None), "accra": (0, None), "johannesburg": (2, None), "cape town": (2, None),
    "tehran": (3.5, None), "dubai": (4, None), "abu dhabi": (4, None), "karachi": (5, None),
    "delhi": (5.5, None), "new delhi": (5.5, None), "mumbai": (5.5, None), "bangalore": (5.5, None),
    "kolkata": (5.5, None), "chennai": (5.5, None), "kathmandu": (5.75, None), "dhaka": (6, None),
    "bangkok": (7, None), "jakarta": (7, None), "hanoi": (7, None), "singapore": (8, None), "hong kong": (8, None),
    "beijing": (8, None), "shanghai": (8, None), "taipei": (8, None), "manila": (8, None), "kuala lumpur": (8, None),
    "perth": (8, None), "tokyo": (9, None), "osaka": (9, None), "seoul": (9, None), "brisbane": (10, None),
    "sydney": (10, "au"), "melbourne": (10, "au"), "canberra": (10, "au"), "adelaide": (9.5, "au"),
    "auckland": (12, "nz"), "wellington": (12, "nz"),
    "new york": (-5, "us"), "boston": (-5, "us"), "washington": (-5, "us"), "miami": (-5, "us"),
    "atlanta": (-5, "us"), "toronto": (-5, "us"), "montreal": (-5, "us"), "ottawa": (-5, "us"),
    "philadelphia": (-5, "us"), "detroit": (-5, "us"),
    "chicago": (-6, "us"), "dallas": (-6, "us"), "houston": (-6, "us"), "mexico city": (-6, None),
    "denver": (-7, "us"), "calgary": (-7, "us"), "phoenix": (-7, None),
    "los angeles": (-8, "us"), "san francisco": (-8, "us"), "seattle": (-8, "us"), "vancouver": (-8, "us"),
    "las vegas": (-8, "us"), "san diego": (-8, "us"), "anchorage": (-9, "us"), "honolulu": (-10, None),
    "sao paulo": (-3, None), "são paulo": (-3, None), "rio de janeiro": (-3, None), "buenos aires": (-3, None),
    "santiago": (-4, "cl"), "lima": (-5, None), "bogota": (-5, None),
    "utc": (0, None), "gmt": (0, None),
}


def _nth_sunday(year: int, month: int, n: int) -> date:
    """The ``n``th Sunday of the month (n = -1: the last)."""
    days = [d for d in range(1, calendar.monthrange(year, month)[1] + 1) if date(year, month, d).weekday() == 6]
    return date(year, month, days[n if n < 0 else n - 1])


def _at(d: date, hour: float) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(hours=hour)


def _dst(rule: str | None, utc: datetime, std: float) -> bool:
    y = utc.year
    if rule == "eu":
        return _at(_nth_sunday(y, 3, -1), 1) <= utc < _at(_nth_sunday(y, 10, -1), 1)
    if rule == "us":
        return _at(_nth_sunday(y, 3, 2), 2 - std) <= utc < _at(_nth_sunday(y, 11, 1), 2 - std - 1)
    if rule == "au":  # first Sunday of October to first Sunday of April, at 2:00 / 3:00 local
        return utc >= _at(_nth_sunday(y, 10, 1), 2 - std) or utc < _at(_nth_sunday(y, 4, 1), 3 - std - 1)
    if rule == "nz":  # last Sunday of September to first Sunday of April
        return utc >= _at(_nth_sunday(y, 9, -1), 2 - std) or utc < _at(_nth_sunday(y, 4, 1), 3 - std - 1)
    if rule == "cl":  # first Sunday of September to first Sunday of April, at midnight local
        return utc >= _at(_nth_sunday(y, 9, 1), -std) or utc < _at(_nth_sunday(y, 4, 1), -std - 1)
    return False


def city_time(city: str, now: datetime) -> datetime | None:
    """The time in ``city`` (one of ``CITIES``) when it is ``now`` here (an aware datetime)."""
    found = CITIES.get(city)
    if found is None:
        return None
    std, rule = found
    utc = now.astimezone(timezone.utc)
    offset = std + (1 if _dst(rule, utc, std) else 0)
    return (utc + timedelta(hours=offset)).replace(tzinfo=timezone(timedelta(hours=offset)))


_CITY = re.compile(
    r"(?:what(?:'s| is)? (?:the )?time(?: is it)?|what time is it(?: right)?(?: now)?|what time(?: is it)?|the time|time)"
    r" (?:now |right now )?in (?P<city>[a-z ]+?)(?: right now| now| at the moment)?"
)


def _city_answer(t: str, now: datetime) -> str | None:
    m = _CITY.fullmatch(t)
    if m is None:
        return None
    city = m.group("city").strip()
    there = city_time(city, now)
    if there is None:
        return None
    name = city.upper() if city in ("utc", "gmt") else city.title()
    when = _relative(there.date(), now.date())
    return _said(f"It's {_hm(there)} in {name}" + (f", {when}." if when and when != "today" else "."), there, True, city)


# ---- dates ----------------------------------------------------------------------------------

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS |= {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m} | {"sept": 9}
_WEEKDAYS = {d.lower(): i for i, d in enumerate(calendar.day_name)}
_MONTH = rf"(?:{'|'.join(sorted(_MONTHS, key=len, reverse=True))})"
_WEEKDAY = rf"(?:{'|'.join(_WEEKDAYS)})"
_ORD = r"(?P<d>\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"(?:,? (?P<y>\d{4}))?"
_EXPLICIT = [
    re.compile(rf"(?:the )?{_ORD} (?:of )?(?P<m>{_MONTH}){_YEAR}"),
    re.compile(rf"(?P<m>{_MONTH}) (?:the )?{_ORD}{_YEAR}"),
]
_HOLIDAYS = {
    "christmas": (12, 25), "christmas day": (12, 25), "christmas eve": (12, 24), "boxing day": (12, 26),
    "new year's eve": (12, 31), "new years eve": (12, 31), "new year's day": (1, 1), "new years day": (1, 1),
    "new year": (1, 1), "new year's": (1, 1), "the new year": (1, 1), "halloween": (10, 31),
    "valentine's day": (2, 14), "valentines day": (2, 14), "valentine's": (2, 14),
    "st patrick's day": (3, 17), "saint patrick's day": (3, 17), "bonfire night": (11, 5),
    "guy fawkes night": (11, 5), "independence day": (7, 4), "the fourth of july": (7, 4),
}


def _when(phrase: str, today: date, past: bool = False) -> tuple[date, str] | None:
    """A spoken day ("next friday", "the 3rd of november", "christmas", "in 3 weeks") as (date, how to say it)."""
    p = re.sub(r"^(?:on|for|by) ", "", phrase.strip())
    p = re.sub(r"^the day (after|before) (tomorrow|yesterday)$", r"\1 \2", p)
    fixed = {"today": 0, "tomorrow": 1, "yesterday": -1, "after tomorrow": 2, "before yesterday": -2}
    if p in fixed:
        d = today + timedelta(days=fixed[p])
        return d, {"after tomorrow": "the day after tomorrow", "before yesterday": "the day before yesterday"}.get(p, p)
    if m := re.fullmatch(rf"(?P<which>next|this|this coming|coming|last|this past|on)? ?(?P<w>{_WEEKDAY})(?: week)?", p):
        target = _WEEKDAYS[m.group("w")]
        which = m.group("which") or ""
        ahead = (target - today.weekday()) % 7
        if which in ("last", "this past") or (past and not which):
            back = (today.weekday() - target) % 7 or 7
            d = today - timedelta(days=back)
        elif which == "next":
            d = today + timedelta(days=ahead or 7)
            if p.endswith(" week"):
                d += timedelta(days=7) if ahead else timedelta()
        else:
            d = today + timedelta(days=ahead)
        said = f"{which} {m.group('w').title()}".strip() if which != "on" else m.group("w").title()
        return d, said
    if m := re.fullmatch(rf"(?:in (?P<in>{_DUR})|(?P<from>{_DUR}) (?:from now|from today|time)|(?P<ago>{_DUR}) ago)", p):
        dur = _duration(m.group("in") or m.group("from") or m.group("ago"))
        if dur is None or dur[0].seconds or dur[0].microseconds:
            return None
        sign = -1 if m.group("ago") else 1
        return _add_months(today, sign * dur[1]) + sign * dur[0], p
    if m := re.fullmatch(r"(next|last) (week|month|year)", p):
        sign = 1 if m.group(1) == "next" else -1
        d = today + timedelta(weeks=sign) if m.group(2) == "week" else _add_months(today, sign * (12 if m.group(2) == "year" else 1))
        return d, p
    holiday = _HOLIDAYS.get(re.sub(r"^this ", "", p))
    for pattern in _EXPLICIT:
        if holiday is not None:
            break
        if m := pattern.fullmatch(p):
            month, day = _MONTHS[m.group("m")], int(m.group("d"))
            if m.group("y"):
                try:
                    return date(int(m.group("y")), month, day), _say_date(date(int(m.group("y")), month, day))
                except ValueError:
                    return None
            holiday = (month, day)
            break
    if holiday is None:
        return None
    month, day = holiday
    try:
        d = date(today.year, month, day)
        if past and d > today:
            d = date(today.year - 1, month, day)
        elif not past and d < today:
            d = date(today.year + 1, month, day)
    except ValueError:
        return None
    name = p if p in _HOLIDAYS else _say_date(d, year=False)
    return d, string.capwords(name) if p in _HOLIDAYS else name


def _say_date(d: date, year: bool = True) -> str:
    return f"{d.day} {d.strftime('%B')}" + (f" {d.year}" if year else "")


_DATE_NOW = re.compile(
    r"what(?:'s| is)? (?:the )?date(?: today| is it| is it today| today is)?|what(?:'s| is) today'?s date|today'?s date|the date"
    r"|what day is it(?: today)?|(?:which|what) day of the week is it(?: today)?|what(?:'s| is) the day(?: today)?"
    r"|what(?:'s| is) today|what is it today|date|what date is it(?: today)?|what day are we on|what's the date today"
)
_DATE_OF = re.compile(
    r"(?:what(?:'s| is| will be| was)? (?:the )?date|what date|what day|which day|what day of the week|what(?:'s| is))"
    r" (?:is it |will it be |was it |is |was |will be |falls on )?(?P<when>.+?)"
)
_DATE_POSSESSIVE = re.compile(r"(?:what(?:'s| is) )?(?P<when>.+?)'s date")
_WEEKDAY_OF = re.compile(
    r"what day(?: of the week)? (?P<tense>is|was|will|does|did|falls on|will be)? ?(?P<when>.+?)(?: be| fall on| on| fall)?"
)
_WHEN_IS = re.compile(r"when(?:'s| is| was) (?P<when>.+)")
_UNTIL = re.compile(
    r"how (?:many|much) (?P<unit>days|weeks|sleeps|months)(?: are there| is it| are left| left| to go| have i got| do i have| do we have)?"
    r" (?:until|till|til|to|before|left until|left till|left before)(?: it's)? (?P<when>.+)"
    r"|how long (?:is it |is there )?(?:until|till|til|to|before)(?: it's)? (?P<when2>.+)"
)
_SINCE = re.compile(
    r"how many (?P<unit>days|weeks) (?:has it been |is it |have passed |ago was it )?(?:since|from) (?P<when>.+?)(?: until today| to today)?"
    r"|how many (?P<unit2>days|weeks) ago (?:was|is) (?P<when2>.+)"
)
_LEFT = re.compile(r"how many days (?:are )?(?:left|remaining) (?:in|of) (?:the |this )?(?P<what>year|month|week)")


def _date_answer(t: str, now: datetime) -> str | None:
    today = now.date()
    if _DATE_NOW.fullmatch(t):
        return _said(f"It's {_day(today)}.", now, False)
    if re.fullmatch(r"what (?:month|month of the year) is it(?: now| today)?|which month is it|what's the month", t):
        return f"It's {today.strftime('%B')}."
    if re.fullmatch(r"what year is it(?: now| today)?|which year is it|what's the year|what year are we in", t):
        return f"It's {today.year}."
    if re.fullmatch(r"(?:what|which) week (?:number )?(?:of the year )?is it(?: now| today)?|what(?:'s| is) the week number"
                    r"|what week number is it|what week of the year is it", t):
        return f"It's week {today.isocalendar().week}."
    if re.fullmatch(r"what day of the year is it(?: today)?", t):
        return f"It's day {today.timetuple().tm_yday} of {today.year}."
    if m := _LEFT.fullmatch(t):
        what = m.group("what")
        if what == "year":
            end = date(today.year, 12, 31)
        elif what == "month":
            end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        else:
            end = today + timedelta(days=6 - today.weekday())
        n = (end - today).days
        return f"{n} day{'s' if n != 1 else ''} left in the {what}, after today."
    if m := _UNTIL.fullmatch(t):
        unit = m.group("unit") or "days"
        found = _when(m.group("when") or m.group("when2"), today)
        if found is None:
            return None
        d, said = found
        days = (d - today).days
        if days < 0:
            return None
        if days == 0:
            return f"{said[:1].upper() + said[1:]} is today."
        if unit == "weeks":
            weeks, rest = divmod(days, 7)
            span = f"{weeks} week{'s' if weeks != 1 else ''}" + (f" and {rest} day{'s' if rest != 1 else ''}" if rest else "")
        elif unit == "months":
            months = (d.year - today.year) * 12 + d.month - today.month - (d.day < today.day)
            span = f"about {months} month{'s' if months != 1 else ''}" if months else f"{days} days"
        else:
            span = f"{days} day{'s' if days != 1 else ''}"
        return _said(f"{span[:1].upper() + span[1:]} until {said}, on {d.strftime('%A')} {_say_date(d, d.year != today.year)}.",
                     _on(d, now), False)
    if m := _SINCE.fullmatch(t):
        unit = m.group("unit") or m.group("unit2")
        found = _when(m.group("when") or m.group("when2"), today, past=True)
        if found is None:
            return None
        d, said = found
        days = (today - d).days
        if days < 0:
            return None
        n = days // 7 if unit == "weeks" else days
        u = unit.rstrip("s")
        return _said(f"{_num(n)} {u}{'s' if n != 1 else ''} since {said}.", _on(d, now), False)
    if m := _WHEN_IS.fullmatch(t):
        past = t.startswith("when was")
        found = _when(m.group("when"), today, past=past)
        if found is None:
            return None
        d, said = found
        days = (d - today).days
        rel = _relative(d, today)
        if rel:
            tail = f", {rel}"
        elif days > 0:
            tail = f", in {days} days"
        else:
            tail = f", {-days} days ago"
        return _said(f"{said[:1].upper() + said[1:]} {'was' if days < 0 else 'is'} {d.strftime('%A')}, {_say_date(d)}{tail}.",
                     _on(d, now), False)
    for pattern in (_WEEKDAY_OF, _DATE_OF, _DATE_POSSESSIVE):
        m = pattern.fullmatch(t)
        if m is None:
            continue
        past = " was " in f" {t} " or " did " in f" {t} "
        found = _when(m.group("when"), today, past=past)
        if found is None:
            continue
        d, said = found
        verb = "was" if d < today else "is"
        at = _on(d, now)
        if said in ("today", "tomorrow", "yesterday", "the day after tomorrow", "the day before yesterday"):
            verb = "was" if d < today else "is"
            return _said(f"{said[:1].upper() + said[1:]} {verb} {_day(d)}.", at, False)
        if re.fullmatch(rf"(?:next |this |last |coming |this coming )?{_WEEKDAY}(?: week)?", said.lower()):
            return _said(f"{said[:1].upper() + said[1:]} {verb} {_say_date(d, d.year != today.year)}.", at, False)
        if pattern is _WEEKDAY_OF or re.match(r"what day|which day", t):
            return _said(f"{said[:1].upper() + said[1:]} {verb} a {d.strftime('%A')}" + (
                f", {d.year}." if d.year != today.year and str(d.year) not in said else "."
            ), at, False)
        return _said(f"{said[:1].upper() + said[1:]} {verb} {_day(d)}.", at, False)
    return None


# ---- unit conversions ------------------------------------------------------------------------

# Name: (dimension, size in the dimension's base unit, singular, plural).
_UNITS: dict[str, tuple[str, float, str, str]] = {}


def _unit(names: str, dim: str, factor: float, one: str, many: str) -> None:
    for n in names.split("|"):
        _UNITS[n] = (dim, factor, one, many)


_unit("mm|millimetre|millimetres|millimeter|millimeters", "length", 0.001, "millimetre", "millimetres")
_unit("cm|centimetre|centimetres|centimeter|centimeters|centimetres", "length", 0.01, "centimetre", "centimetres")
_unit("m|metre|metres|meter|meters", "length", 1, "metre", "metres")
_unit("km|kms|kilometre|kilometres|kilometer|kilometers|k", "length", 1000, "kilometre", "kilometres")
_unit("in|inch|inches", "length", 0.0254, "inch", "inches")
_unit("ft|foot|feet", "length", 0.3048, "foot", "feet")
_unit("yd|yard|yards", "length", 0.9144, "yard", "yards")
_unit("mi|mile|miles", "length", 1609.344, "mile", "miles")
_unit("nautical mile|nautical miles", "length", 1852, "nautical mile", "nautical miles")
_unit("mg|milligram|milligrams|milligramme|milligrammes", "mass", 1e-6, "milligram", "milligrams")
_unit("g|gram|grams|gramme|grammes", "mass", 0.001, "gram", "grams")
_unit("kg|kgs|kilo|kilos|kilogram|kilograms|kilogramme|kilogrammes", "mass", 1, "kilogram", "kilograms")
_unit("t|tonne|tonnes|metric ton|metric tons", "mass", 1000, "tonne", "tonnes")
_unit("oz|ounce|ounces", "mass", 0.028349523125, "ounce", "ounces")
_unit("lb|lbs|pound|pounds", "mass", 0.45359237, "pound", "pounds")
_unit("st|stone|stones", "mass", 6.35029318, "stone", "stone")
_unit("ml|millilitre|millilitres|milliliter|milliliters", "volume", 0.001, "millilitre", "millilitres")
_unit("cl|centilitre|centilitres|centiliter|centiliters", "volume", 0.01, "centilitre", "centilitres")
_unit("l|litre|litres|liter|liters", "volume", 1, "litre", "litres")
_unit("tsp|teaspoon|teaspoons", "volume", 0.00492892, "teaspoon", "teaspoons")
_unit("tbsp|tablespoon|tablespoons", "volume", 0.0147868, "tablespoon", "tablespoons")
_unit("fl oz|fluid ounce|fluid ounces", "volume", 0.0295735, "US fluid ounce", "US fluid ounces")
_unit("cup|cups", "volume", 0.236588, "US cup", "US cups")
_unit("pint|pints", "volume", 0.568261, "UK pint", "UK pints")
_unit("us pint|us pints", "volume", 0.473176, "US pint", "US pints")
_unit("gallon|gallons|us gallon|us gallons", "volume", 3.785411784, "US gallon", "US gallons")
_unit("uk gallon|uk gallons|imperial gallon|imperial gallons", "volume", 4.54609, "UK gallon", "UK gallons")
_unit("kph|km/h|kmh|kilometres per hour|kilometers per hour|kilometres an hour|kilometers an hour", "speed", 1 / 3.6,
      "kilometre per hour", "kilometres per hour")
_unit("mph|miles per hour|miles an hour|mile per hour", "speed", 0.44704, "mile per hour", "miles per hour")
_unit("m/s|metres per second|meters per second", "speed", 1, "metre per second", "metres per second")
_unit("knot|knots", "speed", 0.514444, "knot", "knots")
_unit("second|seconds|sec|secs", "time", 1, "second", "seconds")
_unit("minute|minutes|min|mins", "time", 60, "minute", "minutes")
_unit("hour|hours|hr|hrs", "time", 3600, "hour", "hours")
_unit("day|days", "time", 86400, "day", "days")
_unit("week|weeks", "time", 604800, "week", "weeks")
_unit("year|years", "time", 31557600, "year", "years")
_unit("sq ft|square foot|square feet", "area", 0.09290304, "square foot", "square feet")
_unit("sq m|square metre|square metres|square meter|square meters", "area", 1, "square metre", "square metres")
_unit("acre|acres", "area", 4046.8564224, "acre", "acres")
_unit("hectare|hectares", "area", 10000, "hectare", "hectares")
_unit("kb|kilobyte|kilobytes", "data", 1e3, "kilobyte", "kilobytes")
_unit("mb|megabyte|megabytes", "data", 1e6, "megabyte", "megabytes")
_unit("gb|gigabyte|gigabytes|gig|gigs", "data", 1e9, "gigabyte", "gigabytes")
_unit("tb|terabyte|terabytes", "data", 1e12, "terabyte", "terabytes")

_TEMPS = {
    "c": "c", "celsius": "c", "centigrade": "c", "degrees celsius": "c", "degrees c": "c", "degrees centigrade": "c",
    "f": "f", "fahrenheit": "f", "degrees fahrenheit": "f", "degrees f": "f",
    "k": "k", "kelvin": "k", "kelvins": "k",
}
_TEMP_NAME = {"c": "Celsius", "f": "Fahrenheit", "k": "kelvin"}
_UNIT_RE = "|".join(re.escape(u) for u in sorted([*_UNITS, *_TEMPS, "degrees"], key=len, reverse=True))
_CONVERT = [
    re.compile(rf"(?:convert |change |what(?:'s| is| are) |how much is |how many is )?(?P<n>{_N}) ?(?P<a>{_UNIT_RE})"
               rf" (?:to|in|into|in to|as|is how many|equals how many|is what in) (?P<b>{_UNIT_RE})"),
    re.compile(rf"how (?:many|much) (?P<b>{_UNIT_RE}) (?:is|are|in|make|makes|is there in|are there in|are in|is in|to|equals?)"
               rf" (?:a |an |one )?(?P<n>{_N})? ?(?P<a>{_UNIT_RE})"),
]


def _to_c(n: float, u: str) -> float:
    return n if u == "c" else (n - 32) * 5 / 9 if u == "f" else n - 273.15


def _from_c(c: float, u: str) -> float:
    return c if u == "c" else c * 9 / 5 + 32 if u == "f" else c + 273.15


def _convert_answer(t: str) -> str | None:
    t = re.sub(r"\bdegrees (celsius|centigrade|fahrenheit|c|f)\b", r"\1", t)
    for pattern in _CONVERT:
        m = pattern.fullmatch(t)
        if m is None:
            continue
        n = float(m.group("n")) if m.group("n") else 1.0
        a, b = m.group("a"), m.group("b")
        if a in _TEMPS or b in _TEMPS or "degrees" in (a, b):
            ta, tb = _TEMPS.get(a), _TEMPS.get(b)
            if ta is None and tb is not None:
                ta = "f" if tb == "c" else "c"
            if tb is None and ta is not None:
                tb = "f" if ta == "c" else "c"
            if ta is None or tb is None or ta == tb:
                return None
            out = _from_c(_to_c(n, ta), tb)
            deg = lambda u: "" if u == "k" else " degrees"  # noqa: E731
            return f"{_num(n)}{deg(ta)} {_TEMP_NAME[ta]} is {_num(round(out, 1))}{deg(tb)} {_TEMP_NAME[tb]}."
        ua, ub = _UNITS.get(a), _UNITS.get(b)
        if ua is None or ub is None or ua[0] != ub[0] or ua is ub:
            return None
        out = n * ua[1] / ub[1]
        name_a = ua[2] if n == 1 else ua[3]
        name_b = ub[2] if abs(out - 1) < 1e-9 else ub[3]
        return f"{_num(n)} {name_a} is {_num(out)} {name_b}."
    return None


# ---- arithmetic -----------------------------------------------------------------------------

_OPS: dict[type, Callable[..., float]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_WORD_OPS = [
    (r"\bmultiplied by\b|\btimes\b|(?<=\d) x (?=\d)|(?<=\d)x(?=\d)|\bmultiply\b", "*"),
    (r"\bdivided by\b|\bover\b|\bdivide\b", "/"),
    (r"\bplus\b|\badded to\b", "+"),
    (r"\bminus\b|\btake away\b|\bless\b", "-"),
    (r"\bto the power of\b|\bto the power\b|\braised to\b|\^", "**"),
    (r"\bsquared\b", "**2"),
    (r"\bcubed\b", "**3"),
]


def _eval(expr: str) -> float | None:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e6):
                raise ValueError("too big")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sqrt" and len(node.args) == 1:
            return math.sqrt(ev(node.args[0]))
        raise ValueError("not arithmetic")

    try:
        value = ev(tree.body)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    return value if math.isfinite(value) else None


_MATH_LEAD = re.compile(
    r"^(?:what(?:'s| is| are| does)|whats|calculate|compute|work out|how much is|how much are|what do you get for|solve)\s+"
)
_PCT = rf"(?P<p>{_N}) ?(?:%|percent|per cent)"


def _math_answer(t: str) -> str | None:
    s = _MATH_LEAD.sub("", t)
    s = re.sub(r"\s+(?:equal|equals|make|makes|come to|is)$", "", s)
    if m := re.fullmatch(rf"{_PCT} of (?P<n>{_N})", s):
        p, n = float(m.group("p")), float(m.group("n"))
        return f"{_num(p)}% of {_num(n)} is {_num(p * n / 100)}."
    if m := (re.fullmatch(rf"{_PCT} (?:off|discount on|off of) (?P<n>{_N})", s)
             or re.fullmatch(rf"(?P<n>{_N}) (?:minus|less|with) {_PCT}(?: off)?", s)):
        p, n = float(m.group("p")), float(m.group("n"))
        return f"{_num(n)} with {_num(p)}% off is {_num(n * (1 - p / 100))}."
    if m := (re.fullmatch(rf"(?P<n>{_N}) (?:plus|add|with|and) {_PCT}", s)
             or re.fullmatch(rf"(?:add )?{_PCT} (?:to|on|on top of) (?P<n>{_N})", s)):
        p, n = float(m.group("p")), float(m.group("n"))
        return f"{_num(n)} plus {_num(p)}% is {_num(n * (1 + p / 100))}."
    if m := re.fullmatch(rf"(?:a )?{_PCT} tip on (?P<n>{_N})", s):
        p, n = float(m.group("p")), float(m.group("n"))
        return f"A {_num(p)}% tip on {_num(n)} is {_num(p * n / 100)}."
    if m := re.fullmatch(rf"(?P<a>{_N}) (?:is )?what (?:percent|percentage|per cent) of (?P<b>{_N})"
                         rf"|what (?:percent|percentage|per cent) (?:of (?P<b2>{_N}) )?is (?P<a2>{_N})(?: of (?P<b3>{_N}))?", s):
        a = float(m.group("a") or m.group("a2"))
        b_raw = m.group("b") or m.group("b2") or m.group("b3")
        if b_raw is None or float(b_raw) == 0:
            return None
        return f"{_num(a)} is {_num(a / float(b_raw) * 100)}% of {_num(float(b_raw))}."
    if m := re.fullmatch(rf"(?:the )?square root of (?P<n>{_N})|root (?P<n2>{_N})", s):
        n = float(m.group("n") or m.group("n2"))
        return f"The square root of {_num(n)} is {_num(math.sqrt(n))}." if n >= 0 else None
    if m := re.fullmatch(rf"(?P<a>{_N}) (?:divided by|over) (?P<b>{_N})", s):
        b = float(m.group("b"))
        if b == 0:
            return "You can't divide by zero."
    expr = s
    for pattern, repl in _WORD_OPS:
        expr = re.sub(pattern, f" {repl} ", expr)
    expr = re.sub(r"\bsquare root of\s*(-?\d+(?:\.\d+)?)", r"sqrt(\1)", expr)
    expr = " ".join(expr.split())
    # Only numbers and operators, at least one operator between two numbers.
    if not re.fullmatch(r"[\d\s.+\-*/()sqrt]+", expr) or not re.search(r"\d\s*(?:\*\*|[-+*/])\s*[\d(s-]|\*\*\s*\d", expr):
        return None
    if not re.match(r"\s*[-\d(s]", expr):
        return None
    value = _eval(expr)
    if value is None:
        return None
    return f"That's {_num(value)}."


# ---- spelling -------------------------------------------------------------------------------

_SPELL = re.compile(
    r"(?:how (?:do|would|should|can) (?:you|i|we|one) spell|how is|how's|spell(?: out)?|what(?:'s| is) the spelling of"
    r"|what is the correct spelling of|can you spell|could you spell) (?:the word )?(?P<w>[a-z][a-z' -]*?)(?: spelled| spelt)?"
)


def _spell_answer(t: str) -> str | None:
    m = _SPELL.fullmatch(t)
    if m is None or (t.startswith(("how is", "how's")) and not t.endswith(("spelled", "spelt"))):
        return None
    word = m.group("w").strip()
    if not word or len(word.split()) > 3 or len(word) > 40:
        return None
    letters = "-".join(c.upper() if c.isalpha() else c for c in word)
    return f"“{word}” is spelled {letters.replace('- -', ', ')}."


# ---- the lane ---------------------------------------------------------------------------------

_FAMILIES: tuple[Callable[[str, datetime], str | None], ...] = (
    _time_answer, _city_answer, _date_answer,
    lambda t, now: _convert_answer(t), lambda t, now: _math_answer(t), lambda t, now: _spell_answer(t),
)


def reply(text: str, now: datetime | None = None, previous: Moment | None = None) -> tuple[str, Moment | None] | None:
    """Swift's own answer to ``text`` and the moment it was about (None for a sum or a spelling),
    or None when it isn't one of the fast lane's questions. With ``previous`` (the moment of the
    thread's last local answer), a follow-up such as "and the date?" is about that moment."""
    now = now if now is not None and now.tzinfo is not None else (now or datetime.now()).astimezone()
    if previous is not None and (followed := follow_up(text, previous)) is not None:
        return followed
    if previous is not None and is_follow_up(text):
        return None  # "and the time?" after a day with no time: not "now"; the agent has the context
    t = normalize(text)
    if not t or len(t) > 120:
        return None
    for family in _FAMILIES:
        try:
            found = family(t, now)
        except (ValueError, OverflowError, KeyError, IndexError):
            found = None
        if found is not None:
            return str(found), getattr(found, "moment", None)
    return None


def answer(text: str, now: datetime | None = None) -> str | None:
    """Swift's own answer to ``text``, or None when it isn't one of the fast lane's questions."""
    found = reply(text, now)
    return found[0] if found is not None else None


# ---- follow-ups: "and the date?", "what time is that in Tokyo?" ---------------------------------

# Said as a follow-up: a leading "and" / "so" / "what about", or a word pointing back.
_FU_LEAD = re.compile(r"^\W*(?:(?:hey |hi |ok |okay )?swift\W+)?(?:and|so|what about|how about)\b")
_FU_REF = re.compile(r"\b(?:that|there|then)\b")
_FU = re.compile(
    r"(?:(?:what|which)(?:'s| is| was| will| would)? )?(?:(?:is|was|will|would) )?(?:the |its )?"
    r"(?P<what>date|day of the week|day|time|year|month)"
    r"(?: (?:is|was|will be|would be|of|on|for))?(?: (?:it|that|then|that day|that time))?(?: (?:be|fall on))?"
    r"(?: (?:in (?P<city>[a-z ]+?)|(?P<there>there)))?"
)
_FU_CITY = re.compile(r"(?:what about |how about )?(?:in )?(?P<city>[a-z ]+?)")


def refers_back(text: str) -> bool:
    """Whether ``text`` reads as a follow-up to the last answer ("and the date", "what's that in euros")."""
    raw = text.lower().replace("’", "'")
    return bool(_FU_LEAD.match(raw) or _FU_REF.search(raw))


def is_follow_up(text: str) -> bool:
    """Shaped like a follow-up about the last answer ("and the time?", "and in Tokyo?"), answerable or not."""
    t = normalize(text)
    lead = refers_back(text)
    if _FU.fullmatch(t) is not None:
        return lead or not t.startswith(("what", "which"))
    c = _FU_CITY.fullmatch(t)
    return lead and c is not None and c.group("city").strip() in CITIES


def follow_up(text: str, previous: Moment) -> tuple[str, Moment] | None:
    """A follow-up about ``previous``: its date, day, year or month, or its time (here, in a named
    city, or "there": the city it was about). None when it isn't one, or it can't be answered here
    ("what time is that" after an answer that had no time of day)."""
    t = normalize(text)
    if not t or len(t.split()) > 9:
        return None
    lead = refers_back(text)
    if lead and not previous.timed and (other := _other_day(t, previous)) is not None:
        return other  # "What's the date?" "It's Wednesday…" "And tomorrow?" (ADR-016 §5.1)
    m = _FU.fullmatch(t)
    if m is None:
        c = _FU_CITY.fullmatch(t) if lead and previous.timed else None
        if c is None or c.group("city").strip() not in CITIES:
            return None
        return _time_there(previous, c.group("city").strip())
    # "the date" alone is elliptical; "what's the date" is only a follow-up when it says so.
    if not (lead or not t.startswith(("what", "which"))):
        return None
    what = m.group("what")
    city = (m.group("city") or "").strip() or None
    if m.group("there"):
        city = previous.city
        if city is None:
            return None  # "there" with no place in the last answer: the agent asks
    if city is not None and city not in CITIES:
        return None
    if what == "time":
        if not previous.timed:
            return None
        return _time_there(previous, city) if city else (f"That's {_hm(previous.at)}.", previous)
    at = city_time(city, previous.at) if city else previous.at
    assert at is not None
    where = f" in {_city_name(city)}" if city and city != previous.city else ""
    if what == "date":
        said = f"That's {_day(at.date())}{where}."
    elif what == "year":
        said = f"That's in {at.year}."
    elif what == "month":
        said = f"That's in {at.strftime('%B')}."
    else:
        said = f"That's a {at.strftime('%A')}{where}."
    return said, Moment(at, previous.timed, city or previous.city)


def _other_day(t: str, previous: Moment) -> tuple[str, Moment] | None:
    """The same question about another day, after a date answer: "and tomorrow?", "what about Friday?"."""
    phrase = re.sub(r"^(?:what about|how about) ", "", t)
    today = datetime.now(previous.at.tzinfo).date()
    found = _when(phrase, today)
    if found is None:
        return None
    d, said = found
    name = said[:1].upper() + said[1:]
    verb = "was" if d < today else "is"
    told = _say_date(d) if said.lower().split()[-1] in _WEEKDAYS else _day(d)  # "Friday is 30 October 2026."
    return f"{name} {verb} {told}.", Moment(_on(d, previous.at), False, previous.city)


def _city_name(city: str) -> str:
    return city.upper() if city in ("utc", "gmt") else city.title()


def _time_there(previous: Moment, city: str) -> tuple[str, Moment]:
    there = city_time(city, previous.at)
    assert there is not None
    days = (there.date() - previous.at.date()).days
    day = f", {there.strftime('%A')}" if days else ""
    return f"That's {_hm(there)} in {_city_name(city)}{day}.", Moment(there, True, city)


__all__ = ["CITIES", "Moment", "answer", "city_time", "follow_up", "is_follow_up", "normalize", "refers_back", "reply"]
