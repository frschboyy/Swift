"""Tier 1 of the router (ADR-007 §3): deterministic rules, no model, offline.

- **control**: the whole utterance is a command to Swift ("stop", "never mind",
  "approve"). Matching is on the whole utterance only, so "stop reminding me
  to take a break" is a request, not a stop.
- **local**: Swift answers itself (time, date).
- **claude**: everything else. A leading "use opus / use haiku" picks the model
  and is removed; "think hard about ..." asks for the strongest model and is kept.
  Demand (light or standard) comes from ``demand_fn``: by default the keyword
  ``demand.estimate``; the backend passes the local classifier (ADR-007 §4).

Mis-taking a request for a command loses it, so control and local patterns are
deliberately narrow: an unmatched command still reaches Claude Code, just slower.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from swift.routing.demand import estimate

RouteName = Literal["control", "local", "claude"]
Demand = Literal["light", "standard"]
Override = Literal["opus", "sonnet", "haiku"]

_WAKE = re.compile(r"^\s*(hey|hi|ok|okay)?\s*swift\b[\s,.:!-]*", re.IGNORECASE)
_FILLER = re.compile(r"\b(um+|uh+|er+|please)\b")

CONTROL: dict[str, str] = {
    "stop": r"stop|stop (it|that|talking)|quiet|be quiet|shut up|hush|enough",
    "cancel": r"cancel|cancel (it|that)|never ?mind|forget (it|that)|scratch that",
    "mute": r"mute|stop listening( for a (while|bit))?",
    "approve": r"yes|yeah|yep|sure|approve|approve (it|that)|approved|(ok|okay)( do it)?|do it|go ahead"
    r"|(yes|yeah|ok|okay),? go ahead( and (run|do) it)?",
    "reject": r"no|nope|no thanks|no thank you|reject|reject (it|that)|deny( it)?|don'?t|(no,? )?don'?t do (it|that)",
    "repeat": r"repeat|repeat (it|that)|say (it|that) again|come again|what did you say",
    "help": r"help|what can you do",
}
LOCAL: dict[str, str] = {
    "time": r"what time is it( now)?|what'?s the time( now| right now)?|what is the time( now)?|tell me the time",
    "date": r"what'?s the date( today)?|what is the date( today)?|what'?s today'?s date|what is today'?s date"
    r"|what day is it( today)?|(which|what) day of the week is it( today)?|what'?s the day today",
}
_CONTROL = [(action, re.compile(rf"(?:{pattern})")) for action, pattern in CONTROL.items()]
_LOCAL = [(action, re.compile(rf"(?:{pattern})")) for action, pattern in LOCAL.items()]

_USE_MODEL = re.compile(r"^(?:use|using|with|on) (opus|sonnet|haiku)(?: model)?(?:,| to| for| and)?\s+(.+)$", re.IGNORECASE)
_THINK_HARD = re.compile(r"^think (?:really )?(?:hard|harder|carefully|deeply)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Route:
    route: RouteName
    # The request as it should be sent: wake word and a "use <model>" prefix removed.
    text: str
    # control: stop | cancel | mute | approve | reject | repeat | help; local: time | date.
    action: str | None = None
    demand: Demand | None = None
    override: Override | None = None


def _normalize(text: str) -> str:
    t = _FILLER.sub(" ", _WAKE.sub("", text).lower())
    t = re.sub(r"[^\w\s']", " ", t)
    return " ".join(t.split())


def strip_wake(text: str) -> str:
    return _WAKE.sub("", text).strip()


def route(text: str, default_demand: Demand = "standard",
          demand_fn: Callable[[str], str | None] = estimate) -> Route:
    """Route a transcript. ``default_demand`` applies when ``demand_fn`` isn't sure (returns None)."""
    norm = _normalize(text)
    for action, pattern in _CONTROL:
        if pattern.fullmatch(norm):
            return Route("control", text.strip(), action=action)
    for action, pattern in _LOCAL:
        if pattern.fullmatch(norm):
            return Route("local", text.strip(), action=action)

    request = strip_wake(text) or text.strip()
    if m := _USE_MODEL.match(request):
        model, rest = m.group(1).lower(), m.group(2).strip()
        override: Override = model  # type: ignore[assignment]
        return Route("claude", rest[:1].upper() + rest[1:], demand="light" if model == "haiku" else "standard", override=override)
    if _THINK_HARD.match(request):
        return Route("claude", request, demand="standard", override="opus")
    return Route("claude", request, demand=demand_fn(request) or default_demand)  # type: ignore[arg-type]


def route_for_eval(text: str) -> tuple[str, str | None]:
    """Adapter for spikes/routing/eval_routes.py."""
    r = route(text)
    return r.route, r.demand
