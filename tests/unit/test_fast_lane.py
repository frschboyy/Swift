"""The fast lane (ADR-007 §10): everyday questions answered by Swift itself, never by the agent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from swift.routing import route
from swift.routing.fast import answer, city_time

# Tuesday 27 October 2026, 14:05, in UTC+2 (no DST: Europe changed back on the 25th).
NOW = datetime(2026, 10, 27, 14, 5, tzinfo=timezone(timedelta(hours=2)))


def said(text: str) -> str | None:
    return answer(text, NOW)


# ---- time ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("What time will it be in two minutes?", "It'll be 14:07."),
        ("what time is it in 3 hours", "It'll be 17:05."),
        ("What's the time in half an hour", "It'll be 14:35."),
        ("what time will it be in an hour and a half", "It'll be 15:35."),
        ("what's 3 hours from now", "It'll be 17:05."),
        ("what time was it 90 minutes ago", "It was 12:35."),
        ("what time will it be in 12 hours", "It'll be 02:05 tomorrow."),
        ("So, what time is it?", "It's 14:05."),
        ("tell me the time", "It's 14:05."),
    ],
)
def test_time_with_arithmetic(text: str, expected: str) -> None:
    assert said(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("What time is it in Tokyo?", "It's 21:05 in Tokyo."),
        ("what time is it in New York", "It's 08:05 in New York."),  # US DST runs to 1 November
        ("what time is it in Bucharest?", "It's 14:05 in Bucharest."),
        ("What time is it in Sydney", "It's 23:05 in Sydney."),  # AEDT, UTC+11
        ("what's the time in London", "It's 12:05 in London."),
    ],
)
def test_time_in_another_city(text: str, expected: str) -> None:
    assert said(text) == expected


def test_city_daylight_saving_rules() -> None:
    summer = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    winter = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    assert city_time("london", summer).hour == 13 and city_time("london", winter).hour == 12
    assert city_time("new york", summer).hour == 8 and city_time("new york", winter).hour == 7
    assert city_time("sydney", summer).hour == 22 and city_time("sydney", winter).hour == 23
    assert city_time("tokyo", summer).hour == 21 and city_time("nowhere", summer) is None
    # Chile keeps summer time from September to April (audit 2026-11-09: Swift said 11:00, not 12:00).
    assert city_time("santiago", summer).hour == 8 and city_time("santiago", winter).hour == 9
    assert city_time("santiago", datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)).hour == 12


# ---- dates ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("and what's the date?", "It's Tuesday, 27 October 2026."),
        ("what month is it?", "It's October."),
        ("So what year is it", "It's 2026."),
        ("Swift, what week is it?", "It's week 44."),
        ("next Friday's date", "Next Friday is 30 October."),
        ("what's the date next friday", "Next Friday is 30 October."),
        ("what date is it tomorrow", "Tomorrow is Wednesday, 28 October 2026."),
        ("what day is the 3rd of November", "3 November is a Tuesday."),
        ("what day of the week is November 3rd", "3 November is a Tuesday."),
        ("what day was 25 December 2025", "25 December 2025 was a Thursday."),
        ("how many days until Christmas", "59 days until Christmas, on Friday 25 December."),
        ("how many weeks until christmas", "8 weeks and 3 days until Christmas, on Friday 25 December."),
        ("how long until halloween", "4 days until Halloween, on Saturday 31 October."),
        ("when is christmas", "Christmas is Friday, 25 December 2026, in 59 days."),
        ("what's the date in 3 weeks", "In 3 weeks is Tuesday, 17 November 2026."),
        ("how many days left in the year", "65 days left in the year, after today."),
        ("how many days since the 1st of january", "299 days since 1 January."),
    ],
)
def test_dates_with_arithmetic(text: str, expected: str) -> None:
    assert said(text) == expected


# ---- conversions and arithmetic -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("convert 5 km to miles", "5 kilometres is 3.11 miles."),
        ("how many miles is 10 km", "10 kilometres is 6.21 miles."),
        ("what's 30 degrees celsius in fahrenheit", "30 degrees Celsius is 86 degrees Fahrenheit."),
        ("70 f in c", "70 degrees Fahrenheit is 21.1 degrees Celsius."),
        ("minus 40 c in f", "-40 degrees Celsius is -40 degrees Fahrenheit."),
        ("how many pounds in 3 kilos", "3 kilograms is 6.61 pounds."),
        ("how many feet in a mile", "1 mile is 5,280 feet."),
        ("how many cm in an inch", "1 inch is 2.54 centimetres."),
        ("what's 100 mph in km/h", "100 miles per hour is 160.9 kilometres per hour."),
        ("how many seconds in a day", "1 day is 86,400 seconds."),
    ],
)
def test_unit_conversions(text: str, expected: str) -> None:
    assert said(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("what's 15% of 80", "15% of 80 is 12."),
        ("what is 12 times 7", "That's 84."),
        ("twenty three plus nineteen", "That's 42."),
        ("what's two hundred and fifty times four", "That's 1,000."),
        ("100 divided by 7", "That's 14.29."),
        ("what's the square root of 144", "The square root of 144 is 12."),
        ("2 to the power of 10", "That's 1,024."),
        ("what's 7 squared", "That's 49."),
        ("20% off 50", "50 with 20% off is 40."),
        ("what percent of 80 is 20", "20 is 25% of 80."),
        ("what's 10 divided by 0", "You can't divide by zero."),
    ],
)
def test_arithmetic_and_percentages(text: str, expected: str) -> None:
    assert said(text) == expected


def test_spelling() -> None:
    assert said("how do you spell necessary") == "“necessary” is spelled N-E-C-E-S-S-A-R-Y."


@pytest.mark.parametrize(
    "text",
    [
        "What's the capital of France",
        "Fix the failing test.",
        "what time is it in the docs folder",
        "what's in the executors folder",
        "Remind me in 3 hours to call mum",
        "what's 5 and 3",
        "what's the weather",
        "what is it",
        "2 to the power of 1000000",
    ],
)
def test_anything_else_is_not_answered(text: str) -> None:
    assert said(text) is None


# ---- routing: these never reach the agent ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "What time will it be in two minutes?",
        "What time is it in Bucharest?",
        "next Friday's date",
        "how many days until Christmas",
        "what day is the 3rd of November",
        "convert 5 km to miles",
        "what's 15% of 80",
        "Hey Swift, what's 12 times 7?",
        "how do you spell rhythm",
    ],
)
def test_fast_lane_requests_are_local(text: str) -> None:
    r = route(text)
    assert (r.route, r.action) == ("local", "answer")


@pytest.mark.parametrize(
    ("text", "action"),
    [("and what's the date?", "date"), ("so what time is it", "time"), ("what month is it?", "answer"),
     ("Swift, what year is it", "answer")],
)
def test_tolerant_phrasing_stays_local(text: str, action: str) -> None:
    r = route(text)
    assert (r.route, r.action) == ("local", action)
