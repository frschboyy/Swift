"""Tier 1 of the router (ADR-007 §3): deterministic rules, no model, offline.

- **control**: the whole utterance is a command to Swift ("stop", "never mind",
  "approve"). Matching is on the whole utterance only, so "stop reminding me
  to take a break" is a request, not a stop.
- **local**: Swift answers itself (time, date) or opens an app, folder or project. "Open ..."
  is matched loosely here (a short phrase with no conjunction or verb in it); the session
  resolves the phrase against the ``local`` settings and sends it on to Claude Code when
  the target isn't a configured name, so only known names are ever opened.
- **claude**: everything else. A leading "use opus / use haiku" picks the model
  and is removed; "think hard about ..." asks for the strongest model and is kept.
  Demand (light or standard) comes from ``demand.estimate`` until the local
  classifier (ADR-007 §4) replaces it.

Mis-taking a request for a command loses it, so control and local patterns are
deliberately narrow: an unmatched command still reaches Claude Code, just slower.
"""

from __future__ import annotations

import re
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
    "new_topic": r"new topic|(let'?s )?(start over|start fresh)|fresh start|different topic",
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
    # control: stop | cancel | mute | approve | reject | repeat | help | new_topic; local: time | date | open.
    action: str | None = None
    demand: Demand | None = None
    override: Override | None = None
    # local "open": what was asked for ("downloads folder") and the app it should open in, if said.
    target: str | None = None
    app: str | None = None


# Words that make an "open ..." request something more than opening: it goes to Claude Code.
_NOT_OPEN = frozenset(
    "and then also so that which where who run fix edit find show tell read search check list create write add make build "
    "test tests explain what how why if when because but or after before while until once to from at about".split()
)
_OPEN = re.compile(r"(?:open|launch|bring up|pull up)(?: up)? (?P<rest>[\w' ]+)")
_OPEN_IN = re.compile(r"(?P<target>.+?) (?:in|with|using|on) (?P<app>.+)")
_OPEN_FOR = re.compile(r"(?P<app>.+?) for (?P<target>.+)")


def _open_request(norm: str) -> tuple[str, str | None] | None:
    m = _OPEN.fullmatch(norm)
    if m is None:
        return None
    rest = m.group("rest").strip()
    words = rest.split()
    if not 1 <= len(words) <= 8 or any(w in _NOT_OPEN for w in words):
        return None
    if m := _OPEN_IN.fullmatch(rest):
        return m.group("target"), m.group("app")
    if m := _OPEN_FOR.fullmatch(rest):
        return m.group("target"), m.group("app")
    return rest, None


def _normalize(text: str) -> str:
    t = _FILLER.sub(" ", _WAKE.sub("", text).lower())
    t = re.sub(r"[^\w\s']", " ", t)
    return " ".join(t.split())


def strip_wake(text: str) -> str:
    return _WAKE.sub("", text).strip()


def route(text: str, default_demand: Demand = "standard") -> Route:
    """Route a transcript. ``default_demand`` applies when the estimate isn't sure."""
    norm = _normalize(text)
    for action, pattern in _CONTROL:
        if pattern.fullmatch(norm):
            return Route("control", text.strip(), action=action)
    for action, pattern in _LOCAL:
        if pattern.fullmatch(norm):
            return Route("local", text.strip(), action=action)

    if (opened := _open_request(norm)) is not None:
        return Route("local", text.strip(), action="open", target=opened[0], app=opened[1])

    request = strip_wake(text) or text.strip()
    if m := _USE_MODEL.match(request):
        model, rest = m.group(1).lower(), m.group(2).strip()
        override: Override = model  # type: ignore[assignment]
        return Route("claude", rest[:1].upper() + rest[1:], demand="light" if model == "haiku" else "standard", override=override)
    if _THINK_HARD.match(request):
        return Route("claude", request, demand="standard", override="opus")
    return Route("claude", request, demand=estimate(request) or default_demand)


def route_for_eval(text: str) -> tuple[str, str | None]:
    """Adapter for spikes/routing/eval_routes.py."""
    r = route(text)
    return r.route, r.demand
