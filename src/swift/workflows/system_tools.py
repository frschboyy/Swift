"""The system lane as a tool for the agent (ADR-016 §3, Phase A2): ``system_action``.

The lane answers the owner's own words directly. A request that mixes a system action with work
for the agent ("turn the volume down and write a haiku about tea") goes to the agent, which
can then do the system part with this tool.

**Only what the owner asked for.** The phrase the agent passes is parsed with the same grammar
as the lane, and each intent must also be found, with the same details, in a clause of the
owner's own request (``RunScope.said``), or of their own answer to one of the run's questions
(``RunScope.answers``: said aloud, or typed in the text box; an answer typed on the card arrives as a
click and doesn't count; never a click on an option the run wrote, never a bare yes). An answer asks
only for a switch the owner can see and put back (``FROM_ANSWERS``). So a web page, a file or the model itself can never
lock the PC, switch off Wi-Fi or open a search the owner didn't ask for: the tool answers
"not asked for" and does nothing.

Through the gateway like every tool: ``system_action`` is reversible and journaled; switching
Wi-Fi or Bluetooth off, or airplane mode on, is ``system_action_disruptive`` and needs the
confirm card.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from loguru import logger

from swift.connectors.base import ConnectorError
from swift.security.gateway import Action
from swift.system import intents as it
from swift.workflows.scope import RunScope
from swift.workflows.tools import ToolHost, ToolResult, ToolSpec, _obj

# Where one thing the owner asked for ends and the next begins.
_CLAUSE = re.compile(
    r"\b(?:and then|and also|after that|and|then|also|while|before|after|once|so that|because|but first|first)\b"
)

_SENTENCE = re.compile(r"(?<=[.!?;])\s+")


def owner_intents(said: str, answers: list[str] | tuple[str, ...] = ()) -> list[it.Intent]:
    """Every system intent in the owner's own words, clause by clause: the request, and their answers
    to the run's questions. A short answer ("I meant Wi-Fi") also stands in for one word of the
    request, which speech recognition may have misheard ("turn off the wafer")."""
    found = _intents(said)
    for answer in answers:
        found += [i for i in _intents(answer) if i.name in FROM_ANSWERS]
        short = _LEAD.sub("", it.normalize(answer)).strip()
        if not short or len(short.split()) > MAX_STAND_IN or _NOT.search(short):
            continue  # "not Bluetooth" never stands in for anything
        for sentence in _SENTENCE.split(said):
            for clause in _CLAUSE.split(it.normalize(sentence)):
                words = clause.split()
                for i in range(len(words)):
                    one = it.parse_one(" ".join([*words[:i], short, *words[i + 1:]]))
                    if one is not None and one.name in FROM_ANSWERS:
                        found.append(one)
    return found


# What may lead an answer that names the thing meant: "I meant Wi-Fi", "Swift, the Wi-Fi". Not "no":
# "no Bluetooth" must reach ``_NOT`` (review of 20ff906).
_LEAD = re.compile(r"^(?:(?:hey|ok|okay|swift|sorry|actually|i|meant|mean|said|it's|its|it|is|the|my)\s+)+")
# What an answer may ask for: switches the owner can see and put back. Never lock, a search, a window,
# a settings page, a screenshot or a timer: an answer is heard on the open microphone, where a TV
# saying "lock the PC" must not lock it, and none of those has a card (review of 20ff906).
FROM_ANSWERS = frozenset({
    "radio", "airplane", "dnd", "volume.set", "volume.step", "mute", "media", "brightness.set", "brightness.step", "theme",
})
_NOT = re.compile(r"\b(?:not|don't|dont|never|no)\b")
# An answer longer than this is a request of its own, read whole, never put inside another.
MAX_STAND_IN = 3


def _intents(said: str) -> list[it.Intent]:
    whole = it.parse(said)
    if whole is not None:
        return whole
    # Sentence ends first: normalizing drops the punctuation, and speech recognition writes full stops
    # ("Turn the volume down. Write a haiku." found nothing, so the tool refused: 2026-11-05).
    found: list[it.Intent] = []
    for sentence in _SENTENCE.split(said):
        for clause in _CLAUSE.split(it.normalize(sentence)):
            if clause.strip() and (one := it.parse_one(clause)) is not None:
                found.append(one)
    return found


def _same(a: it.Intent, b: it.Intent) -> bool:
    return a.name == b.name and a.slots == b.slots


async def system_action(host: ToolHost, scope: RunScope, args: dict[str, Any]) -> ToolResult:
    lane = host.system
    if lane is None:
        return ToolResult(False, "Swift's system actions are off here. Nothing was done.")
    phrase = str(args.get("request", "")).strip()
    wanted = it.parse(phrase)
    if not wanted:
        return ToolResult(False, f"“{phrase}” isn't a system action Swift knows (timers, volume, media, "
                                 "dark mode, brightness, radios, lock, settings pages, windows). Nothing was done.")
    if any(it.missing(i) for i in wanted):
        return ToolResult(False, "That needs a detail first (how long, or when). Ask the owner with ask_owner, then "
                                 "pass the whole action (\"set a timer for 10 minutes\"). Nothing was done.", expected=True)
    asked = owner_intents(scope.said, scope.answers)
    missing = [i for i in wanted if not any(_same(i, a) for a in asked)]
    if not missing and any(not any(_same(i, a) for a in owner_intents(scope.said)) for i in wanted):
        logger.info("system action asked for in an answer")  # owner check 201: only the answer named it
    if missing:
        return ToolResult(False, "The owner didn't ask for that in this request, so Swift didn't do it. "
                                 "Only system actions the owner asked for in their own words can be done.", expected=True)
    said: list[str] = []
    for intent in wanted:
        disruptive = it.disruptive(intent)
        result: dict[str, str] = {}

        async def perform(intent: it.Intent = intent, result: dict[str, str] = result) -> str:
            outcome = await lane.run_intents([intent])
            if not outcome.ok:
                raise ConnectorError(outcome.said)
            result["said"] = outcome.said
            return intent.name  # the receipt: the intent only, never its words

        token = uuid.uuid4().hex  # each call is its own action: "volume up" twice is two changes
        question, note = (await lane.question([intent])) if disruptive else ("", "")
        action = Action(
            tool="system_action_disruptive" if disruptive else "system_action",
            targets=(),
            title=question if disruptive else intent.name,
            detail=note,
            artifact_id=None,
            digest=lambda token=token: hashlib.sha256(token.encode()).hexdigest(),
            perform=perform,
            targets_required=False,
        )
        outcome = await host.gateway.execute(scope, action)
        if outcome.status != "done":
            reason = outcome.reason or "It wasn't done."
            done = " ".join(said)
            return ToolResult(False, (done + " " if done else "") + reason, expected=outcome.status in ("rejected", "denied"))
        said.append(result.get("said", "Done."))
    return ToolResult(True, " ".join(said))


SYSTEM_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "system_action",
        "Do an everyday action on the owner's PC that they asked for in this request: a timer or reminder with a time, "
        "volume or mute, play/pause/next track, dark or light mode, brightness, Wi-Fi or Bluetooth on/off, lock the PC, "
        "open a Windows settings page, minimize or snap the window, a screenshot. Pass the owner's own phrase for that "
        "part, e.g. 'turn the volume down'. Only actions the owner asked for are done; never use it on your own initiative.",
        _obj(["request"], request={"type": "string"}),
        "reversible", system_action,
    ),
)
