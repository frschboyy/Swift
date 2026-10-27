"""Tier 1 of the router (ADR-007 §3): deterministic rules, no model, offline.

- **control**: the whole utterance is a command to Swift ("stop", "never mind",
  "approve"). Matching is on the whole utterance only, so "stop reminding me
  to take a break" is a request, not a stop.
- **local**: Swift answers itself (time, date, "what workflows do I have?"), undoes what it
  wrote in an app ("undo that", ADR-012 §6), or opens an app, folder or project. "Open ..."
  is matched loosely here (a short phrase with no conjunction or verb in it); the session
  resolves the phrase against the ``local`` settings and sends it on to Claude Code when
  the target isn't a configured name, so only known names are ever opened. "Open this"
  opens the file selected in File Explorer (ADR-012 D1). "Undo that" is Swift's only when
  Swift wrote something; otherwise it goes on to Claude Code as before.
- **agent**: everything else, sent to the provider (Claude Code today, ADR-008). A leading "use opus / use haiku" picks the model
  and is removed; "think hard about ..." asks for the strongest model and is kept.
  Demand (light or standard) comes from ``demand_fn``: by default the keyword
  ``demand.estimate``; the backend passes the local classifier (ADR-007 §4).

Swift is the name the owner uses. A leading "hey Claude" / "ok Codex" (an agent's
name, ``executors.providers.AGENT_NAMES``) is removed like the wake word and kept
in ``addressed_as``, so the session can say once who it is (ADR-008). Alone, or as
"who are you?", it is the local ``identity`` answer.

During a run, ``route_midrun`` is the grammar for the run in front (ADR-010 §6): "show me",
"show the draft", "hide that" and the stop words. It never starts a run; anything else is None.
``route_redirect`` finds a change of mind ("actually, …", "no, I meant …", ADR-014 §7) and
``route_target`` a request named by what it's about ("stop the research one", ADR-013 §5.3).

Mis-taking a request for a command loses it, so control and local patterns are
deliberately narrow: an unmatched command still reaches Claude Code, just slower.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from swift.executors.providers import AGENT_NAMES
from swift.routing.demand import estimate

RouteName = Literal["control", "local", "agent"]
Demand = Literal["light", "standard"]
Override = Literal["opus", "sonnet", "haiku"]

_WAKE = re.compile(
    r"^\s*(?:(?:hey|hi|hello|ok|okay)|good\s+(?:morning|afternoon|evening))?\s*swift\b[\s,.:!-]*", re.IGNORECASE
)
_FILLER = re.compile(r"\b(um+|uh+|er+|please)\b")
_AGENT = r"claude(?: code)?|codex|hermes|chat ?gpt|gpt"
# Swift greeted by an agent's name. Only with a greeting, so "Claude Code is slow" stays a request.
_MISNAMED = re.compile(rf"^\s*(?:hey|hi|hello|ok|okay)\s+({_AGENT})\b[\s,.:!?-]*", re.IGNORECASE)
_AGENT_WORD = re.compile(rf"\b({_AGENT})\b")

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
    "identity": r"who are you|what are you|what'?s your name|what is your name|who am i (talking|speaking) (to|with)"
    rf"|are you ({_AGENT}|swift)|is (this|that) ({_AGENT})",
    "time": r"what time is it( now)?|what'?s the time( now| right now)?|what is the time( now)?|tell me the time",
    "date": r"what'?s the date( today)?|what is the date( today)?|what'?s today'?s date|what is today'?s date"
    r"|what day is it( today)?|(which|what) day of the week is it( today)?|what'?s the day today",
    "workflows": r"what workflows (do i have|have i got|are there|can you (run|do))|which workflows do (i|you) have"
    r"|(list|show)( me)? (my |the |all )?workflows|what are my workflows",
    "undo": r"undo|undo (that|it|this)|undo (what you (just )?(wrote|typed))|undo (the|your) (last )?(writing|typing)",
    # ADR-014 §5: pick up a conversation left unfinished, or not now.
    "resume": r"(let'?s |ok |okay )?(continue|carry on|keep going|go on|resume)( (it|that|where (we|i|you) left off"
    r"|from where (we|i|you) (left off|stopped)))?|where were we|what was i doing|where did we leave off"
    r"|pick up where (we|i|you) left off",
    "not_now": r"not now|not right now|later|maybe later",
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
    # control: stop | cancel | mute | approve | reject | repeat | help | new_topic;
    # local: time | date | identity | open | workflows | undo | resume | not_now.
    action: str | None = None
    demand: Demand | None = None
    override: Override | None = None
    # local "open": what was asked for ("downloads folder") and the app it should open in, if said.
    target: str | None = None
    app: str | None = None
    # The agent name Swift was called by ("claude"), a key of AGENT_NAMES.
    addressed_as: str | None = None


def _agent_key(name: str) -> str:
    key = " ".join(name.lower().split()).replace("chat gpt", "chatgpt")
    return key if key in AGENT_NAMES else "claude"


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


# A request about where the owner is (ADR-012 §5.1): "rewrite this", "write here", "open these".
_HERE = re.compile(r"\b(this|these|here|the selection|selected|highlighted|what i'?ve selected)\b", re.IGNORECASE)
_SELECTION = re.compile(r"\b(this|these|the selection|selected|highlighted|what i'?ve selected)\b", re.IGNORECASE)
DEICTIC = frozenset({"this", "that", "it", "these", "this file", "these files", "the selection", "the selected file",
                     "the selected files", "selected", "the file", "this one"})


def refers_here(text: str) -> bool:
    return bool(_HERE.search(text))


def refers_to_selection(text: str) -> bool:
    return bool(_SELECTION.search(text))


def _normalize(text: str) -> str:
    t = _FILLER.sub(" ", _WAKE.sub("", text).lower())
    t = re.sub(r"[^\w\s']", " ", t)
    return " ".join(t.split())


def strip_wake(text: str) -> str:
    return _WAKE.sub("", text).strip()


def route(text: str, default_demand: Demand = "standard",
          demand_fn: Callable[[str], str | None] = estimate) -> Route:
    """Route a transcript. ``default_demand`` applies when ``demand_fn`` isn't sure (returns None)."""
    if m := _MISNAMED.match(text):
        called = _agent_key(m.group(1))
        rest = text[m.end():].strip()
        if not rest:
            return Route("local", text.strip(), action="identity", addressed_as=called)
        return replace(_route(rest, default_demand, demand_fn), addressed_as=called)
    return _route(text, default_demand, demand_fn)


def _route(text: str, default_demand: Demand, demand_fn: Callable[[str], str | None]) -> Route:
    norm = _normalize(text)
    for action, pattern in _CONTROL:
        if pattern.fullmatch(norm):
            return Route("control", text.strip(), action=action)
    for action, pattern in _LOCAL:
        if pattern.fullmatch(norm):
            called = _AGENT_WORD.search(norm) if action == "identity" else None
            return Route("local", text.strip(), action=action, addressed_as=_agent_key(called.group(1)) if called else None)

    if (opened := _open_request(norm)) is not None:
        return Route("local", text.strip(), action="open", target=opened[0], app=opened[1])

    request = strip_wake(text) or text.strip()
    if m := _USE_MODEL.match(request):
        model, rest = m.group(1).lower(), m.group(2).strip()
        override: Override = model  # type: ignore[assignment]
        return Route("agent", rest[:1].upper() + rest[1:], demand="light" if model == "haiku" else "standard", override=override)
    if _THINK_HARD.match(request):
        return Route("agent", request, demand="standard", override="opus")
    return Route("agent", request, demand=demand_fn(request) or default_demand)  # type: ignore[arg-type]


# Mid-run grammar (ADR-010 §6): what the owner may say while a run works. Whole utterance only.
_SHOW_WHAT = {
    "draft": "email_draft", "email": "email_draft", "message": "email_draft", "mail": "email_draft",
    "recipient": "recipient", "contact": "recipient", "who": "recipient",
    "progress": "send_status", "status": "send_status",
    "steps": "steps", "step": "steps",
}
_SHOW = re.compile(
    r"(?:(?:can you |could you )?show me|let me see|show|what are you doing|what'?s happening|what'?s going on)"
    r"(?: (?:it|that|this|the (?P<what>\w+)(?: you'?re writing| so far)?|what you'?re doing|your progress))?"
)
_HIDE = re.compile(r"(?:hide|close)(?: (?:it|that|this|the \w+))?|go back|back")


def route_midrun(text: str) -> Route | None:
    """A mid-run command: ``show`` (``target``: an artifact kind, "steps", or None), ``hide``,
    or a control action (stop / cancel / approve / reject ...). None for anything else."""
    norm = _normalize(text)
    if m := _SHOW.fullmatch(norm):
        what = m.group("what")
        if what is not None and what not in _SHOW_WHAT:
            return None
        return Route("control", text.strip(), action="show", target=_SHOW_WHAT.get(what or ""))
    if _HIDE.fullmatch(norm):
        return Route("control", text.strip(), action="hide")
    for action, pattern in _CONTROL:
        if pattern.fullmatch(norm):
            return Route("control", text.strip(), action=action)
    return None


# A change of mind mid-run (ADR-014 §7): the whole utterance is what the owner wants instead.
_REDIRECT = re.compile(
    r"^(?:(?:oh|wait|hmm|sorry|no|nope)\b[\s,.!-]*)*"
    r"(?:actually\b|instead\b|i meant\b|i mean\b|what i meant\b|change (?:it|that|this) to\b"
    r"|make (?:it|that|this) .+ instead\b|rather\b|scratch that,? (?:and )?)",
    re.IGNORECASE,
)
_INSTEAD = re.compile(r"\binstead[.!]?$", re.IGNORECASE)


def route_redirect(text: str) -> str | None:
    """The owner's change of mind, without Swift's name ("actually, make it Friday"); None if it isn't one."""
    said = strip_wake(text).strip()
    norm = said.lower()
    if len(norm.split()) < 2:  # "actually." alone says nothing to change
        return None
    if _REDIRECT.match(norm) or _INSTEAD.search(norm):
        return said
    return None


# A request named by what it's about (ADR-013 §5.3): "stop the research one", "show me the email one".
_TARGET = re.compile(
    r"(?P<verb>stop|cancel|show me|show|switch to|go to|back to|bring up|bring back)"
    r" (?:the |my )?(?P<what>[\w' ]+?)(?: one| request| task| thing)?"
)
_ALL = re.compile(r"(?:stop|cancel) (?:everything|all|all of (?:it|them)|all (?:the )?requests|them all)")


def route_target(text: str) -> tuple[str, str] | None:
    """("stop" | "show", the words naming the request), or ("stop", "*") for "stop everything"."""
    norm = _normalize(text)
    if _ALL.fullmatch(norm):
        return "stop", "*"
    m = _TARGET.fullmatch(norm)
    if m is None:
        return None
    # "Stop the music" is a request; "stop the music one" names a request.
    if m.group("verb") in ("stop", "cancel") and not norm.endswith((" one", " request", " task", " thing")):
        return None
    what = m.group("what").strip()
    if what in ("me", "it", "that", "this", "them", "everything", "me it", "me that"):
        return None
    verb = "stop" if m.group("verb") in ("stop", "cancel") else "show"
    return verb, what


def route_for_eval(text: str) -> tuple[str, str | None]:
    """Adapter for spikes/routing/eval_routes.py."""
    r = route(text)
    return r.route, r.demand
