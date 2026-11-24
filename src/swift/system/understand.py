"""One understanding step (IA-01 phase 1; docs/explorations/intent-architecture.md §5.1, §5.3).

``understand(text)`` says what kind of thing the owner said (the speech act) and which system intents the grammar
(``intents.parse``) finds in it, after a gate: a question changes nothing, and a request taken back ("Lock the
computer. No wait, don't.") asks for nothing. ``propose(text, family_of)`` is Swift's guess when the grammar finds
nothing (IA-01 phase 2, below): it only ever makes Swift ask.

Who calls it, and who keeps the bare grammar (review condition C1-1):

- **Call it:** the router's system check (``rules._route``), ``SystemLane.claims`` and ``SystemLane.run``, and the
  agent tool's provenance check (``system_tools.owner_intents``, with ``each_clause``). These decide whether Swift
  acts on, or lets the agent act on, what the owner said, so they must agree: a request the router sends to the lane
  is one ``claims`` and ``run`` take, and one the lane refuses is one ``system_action`` refuses too.
- **Keep the bare grammar:** ``restated.restated_as`` and ``same_request`` (they compare the owner's words with a
  question already on screen, or an earlier request; a restatement approves Swift's own question, so it must stay a
  grammar match and never anything wider, P2-2), ``dialogue.elide`` (reads a follow-up against the intents already
  done), ``session._brisk_system`` (sizes a reply) and ``SystemLane.matches``. None of them acts on its own: each
  works on a request one of the callers above already let through, or only words a reply. ``timers.heard`` reads
  its own two phrases, not the grammar.
- **Swift's guess** (``propose``) is called only by the router through ``rules.with_guess`` (from
  ``ClassifierEstimate.route``), and taken only by the session's ``rules.guessed``. None of the bare-grammar callers
  above sees a guess.

The gate on grammar matches (C1-3):

- **Question:** a sentence that ends in "?" and doesn't lead with a request ("can you", "please", or one of the
  verbs below) is a question. A change that can be read as a question about its state (a radio, dark mode, do not
  disturb) is dropped, so "Bluetooth on?" no longer switches Bluetooth on (HA-SYS-03). Everything else stays:
  the grammar's reads ("is my wifi on?") and verbless requests ("volume up?", "timer for 5 minutes?").
- **Taken back:** a clause that is only a retraction ("no wait, don't", "never mind", "cancel that"), and no
  intent itself, drops the intents of the clauses before it (HA-SYS-10); a request after it is kept ("No. Turn
  the volume down."). A clause that negates its own request ("don't
  turn off the wifi") is no grammar match today, so nothing else changes.

Swift's guess (phase 2; review conditions P2-1 to P2-8; CLAUDE.md "Swift's guess"):

- Only for a command found positively (a leading verb or a request lead, one clause, no question), with no
  negation, retraction, third party, report, past or elsewhere anywhere in it (``_VETO``, P2-3), that the grammar
  finds nothing in.
- The family is the classifier's vote (``classifier.FamilyVote``; None while it isn't loaded: no guess). Its slots
  come from the grammar's own readers (``seconds_of``, ``find_when``, on/off, the device words) and every one the
  intent needs must be read from the owner's words, never asked (P2-1). Only ``PROPOSABLE`` intents (P2-5).
- Only from a request the owner started (``may_guess``: the hotkey, the wake phrase, typing; P2-4). The router
  attaches the guess (``rules.with_guess``); the session takes it only for those sources (``rules.guessed``).
- The lane asks it as its own yes/no question showing every slot (``SystemLane.propose``, P2-6) and runs it only
  with ``confirmed`` after a yes, never through ``start``, ``fill`` or ``redo`` (P2-1). ``restated`` keeps the bare
  grammar, so saying the guessed-from words again asks again (P2-2).

``Understood.record()`` and ``Guess.record()`` are the run record's ``understood`` field: names and numbers only,
never slots or words (P2-8).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Literal

from swift import intake
from swift.system import intents as it

Act = Literal["command", "question", "negation", "other"]

# What only reads: kept in a question ("how long is left on my timer?").
READS = frozenset({"radio.get", "volume.get", "timer.left", "list", "info"})

# A request found positively: it leads with one of these (the grammar's own leading verbs, the commands that are a
# word alone, "next", "louder", and the agent's common ones, so the record counts a command the grammar missed).
# shortcut: a fixed list; phase 2's proposals need it measured on the owner's saved requests first.
_VERBS = frozenset("""
    set start make create begin put add give get turn switch enable disable activate deactivate connect disconnect
    reconnect kill stop exit leave raise lower increase decrease reduce boost drop cut crank bring change dim brighten
    mute unmute silence pause play resume skip next previous louder quieter softer open close show lock minimize
    maximize restore snap take search google look go wake remind cancel time
    write send find tell email draft check read summarize call text book schedule move delete copy rename save
    download translate explain list run count nudge
""".split())
_ASKS = frozenset("how what what's whats is are does do did why when where which who whose".split())
_NEGATES = re.compile(r"(?:don't|dont|do not(?! disturb)|never)\b")
# What takes a request back: one list, matched whole by the gate (``_RETRACT``) and anywhere by the guess's veto.
_TAKE_BACK = (r"(?:no|nope|nah|don't|dont|do not(?! disturb)|never mind|nevermind|cancel that|scratch that"
              r"|scrap that|forget (?:it|that)|on second thought)")
_RETRACT = re.compile(
    r"(?:(?:oh|um|uh|wait|hold on|actually|sorry|no|nope)\s+)*" + _TAKE_BACK
    + r"(?:\s+(?:wait|actually|don't|dont|do not))*"
)


@dataclass(frozen=True)
class Understood:
    act: Act
    # The grammar's intents after the gate; None when there are none.
    intents: list[it.Intent] | None

    def record(self) -> dict[str, Any]:
        """The run record's ``understood``: names only (P2-8). ``source`` is "grammar" or None; phase 2 adds "similar"."""
        return {"act": self.act, "source": "grammar" if self.intents else None,
                "family": [i.name for i in self.intents or ()]}


def _commands(sentence: str) -> bool:
    if it.polite(sentence):
        return True
    words = it.normalize(sentence).split()
    return bool(words) and words[0] in _VERBS


def _question(sentence: str) -> bool:
    return sentence.rstrip().endswith("?") and not _commands(sentence)


def _act(text: str, retracted: bool) -> Act:
    if retracted or _NEGATES.match(it.normalize(text)):
        return "negation"
    if _commands(text):
        return "command"
    words = it.normalize(text).split()
    if text.rstrip().endswith("?") or (words and words[0] in _ASKS):
        return "question"
    return "other"


def _has_read(i: it.Intent) -> bool:
    """A change that can be read as a question about its state: a radio, dark mode, do not disturb ("bluetooth on?").
    A verbless request with no read ("volume up?", "timer for 5 minutes?") is still a request (review F2)."""
    return i.name in ("radio", "theme", "dnd")


def _kept(found: list[it.Intent], question: bool) -> list[it.Intent]:
    return [i for i in found if not _has_read(i)] if question else found


def understand(text: str, each_clause: bool = False) -> Understood:
    """The speech act and the grammar's intents in ``text``, after the gate. ``each_clause`` (the provenance check):
    when the whole isn't one request, every clause that is one counts, as ``system_action`` has always read it.
    A retraction takes back what came before it, never what follows ("No. Turn the volume down.": review F1)."""
    parts = [(_question(sentence), c) for sentence in it.sentences(text) for c in it.clauses(sentence, loose=True)]
    taken = [n for n, (_, c) in enumerate(parts) if _RETRACT.fullmatch(c.strip()) and it.parse_one(c) is None]
    after = parts[taken[-1] + 1:] if taken else parts
    if taken and not any(it.parse_one(c) is not None for _, c in after):
        return Understood(_act(text, True), None)
    if taken:
        # Only the clauses after the last retraction, each read alone: the whole utterance isn't one request.
        found = _kept([one for ask, c in after if (one := it.parse_one(c)) is not None], False) if each_clause else []
        return Understood("command", found or None)
    act = _act(text, False)
    whole = it.parse(text)
    if whole is not None:
        found = _kept(whole, _question(text))
    elif each_clause:
        found = []
        for ask, c in parts:
            found += _kept([one] if (one := it.parse_one(c)) is not None else [], ask)
    else:
        found = []
    return Understood(act, found or None)


# ---- Swift's guess (phase 2) ------------------------------------------------------------------------------------

# What a guess may be about (P2-5): a new grammar intent isn't guessed until it is listed here. Never lock (a TV's
# yes on the open microphone must not lock the PC), search (a web address comes from the owner's words, foundation
# decision 4), settings, window or screenshot.
PROPOSABLE = frozenset({
    "timer.set", "alarm.set", "reminder.set", "volume.step", "volume.set", "mute", "media", "brightness.set",
    "brightness.step", "theme", "dnd", "radio",
})
# Who may start one (P2-4): a request the owner started. Never ``followup``, ``beside``, ``answer``, ``over_speech``.
GUESS_SOURCES = frozenset({"voice", "wake", "typed"})
# The family vote's share below which Swift doesn't guess.
GUESS_AT = 0.5

_NUM = "one two three four five six seven eight nine"
# "Set a timer four five minutes": normalize sums the two to "9", which the owner never said.
_TWO_NUMBERS = re.compile(rf"\b(?:{'|'.join(_NUM.split())}) (?:{'|'.join(_NUM.split())}|ten|eleven|twelve|thirteen|"
                          r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty)\b")
# Anything here vetoes a guess (P2-3): negation, retraction, condition, past, report, someone else, elsewhere. Also
# (review F1) a second verb or a copula ("Turn on dark mode is a great feature"), a how-to or "can you believe",
# "your" (a host talking: "turn your volume up") and a group addressed ("you guys").
_VETO = re.compile(
    r"\b(?:" + _TAKE_BACK + r"|never|not|without|leave|keep|wait|hold on|actually|sorry|cancel|scratch|scrap"
    r"|forget|if|unless|whether|maybe|yesterday|earlier|already|ago|last night|says?|said|told|he|she|they|someone"
    r"|somebody|everyone|everybody|him|her|them|his|their|your|yours|guys|kids|folks|y'?all"
    r"|is|was|were|are|went|goes|does|did|has|had|been|how|why|what|believe|explain)\b"
    r"|\b(?:remind|tell|ask|text|message|email|call|wake) (?!me\b|us\b|myself\b|up\b)"
    r"|\b(?:phone|tv|television|router|chrome|browser|car|echo|alexa|tablet|ipad|kindle|door|office"
    r"|kitchen|lights?|file)(?:'?s)?\b"
)
# Someone named: "remind Sam", "for Ada" (speech recognition writes names capitalized).
_NAMED = re.compile(r"\b(?:for|to|tell|remind|ask) (?!I\b)[A-Z][a-z]+")
# Someone addressed at the end: "Turn the volume down, Sam" (review F1).
_VOCATIVE = re.compile(r",\s*(?!(?:please|now|thanks|thank you|swift)\b)[a-z]+[.!]?\s*$", re.IGNORECASE)
# A time said with a change that isn't timed (review F3): "turn the wifi off tomorrow" mustn't ask "Turn off Wi-Fi?".
_TIMED = re.compile(r"\b(?:tomorrow|tonight|later|morning|afternoon|evening|noon|midnight|(?:at|in|by) \d)")
_TIMED_FAMILIES = frozenset({"timer", "alarm", "reminder"})

_UP = frozenset("up louder raise increase higher boost brighter brighten".split())
# Not "darker": dark mode or brightness, Swift can't tell (theme-v04 wants a question back, not a guess).
_DOWN = frozenset("down quieter softer lower decrease reduce dim dimmer".split())
_ON = frozenset("on enable activate connect reconnect".split())
_OFF = frozenset("off disable deactivate disconnect kill shut cut".split())
_MEDIA = {"pause": "pause stop hold", "play": "play resume continue unpause", "next": "next skip forward",
          "prev": "previous back"}


@dataclass(frozen=True)
class Guess:
    """Swift's guess: one intent, every slot read from the owner's words, and the vote it came from."""

    intent: it.Intent
    family: str
    score: float

    def record(self) -> dict[str, Any]:
        """The run record's ``understood`` for a guess: names and a number, never slots (P2-8)."""
        return {"act": "command", "source": "similar", "family": [self.intent.name], "score": round(self.score, 2)}


def may_guess(source: str | None) -> bool:
    """Whether a request from ``source`` may get a guess (P2-4; spoken-like sources count as ``voice``)."""
    return intake.SPOKEN_LIKE.get(source or "", source) in GUESS_SOURCES


def _one(words: set[str], up: frozenset[str], down: frozenset[str]) -> int | None:
    """+1 or -1 when the words say exactly one way; None when they say neither or both."""
    a, b = bool(words & up), bool(words & down)
    return None if a == b else (1 if a else -1)


def _number(t: str) -> int | None:
    """A level: the only number, said after "to" or "at" ("set the volume to 30"), with no direction word; else
    None. A direction with a number ("up 2 notches", "down to 5") is neither a level nor a step Swift can read for
    sure, so it gets no guess (review F2)."""
    found = re.findall(r"\b\d{1,3}\b", t)
    level = re.search(r"\b(?:to|at) (\d{1,3})\b", t)
    return int(level.group(1)) if len(found) == 1 and level and int(level.group(1)) <= 100 else None


def _numbered(words: set[str], t: str) -> bool:
    return bool(words & (_UP | _DOWN)) and re.search(r"\d", t) is not None


def _radio_kind(t: str) -> str | None:
    words = t.split()
    wifi = bool(re.search(r"\b(?:wi-?fi|wi fi|wireless|internet)\b", t)) or any(
        it.heard_as_wifi(" ".join(words[i:i + n])) for n in (1, 2) for i in range(len(words)))
    blue = bool(re.search(r"\b(?:bluetooth|blue tooth)\b", t))
    return None if wifi == blue else ("wifi" if wifi else "bluetooth")


def _timer(t: str, words: set[str]) -> it.Intent | None:
    seconds = it.seconds_of(t)
    return it.Intent("timer.set", {"seconds": seconds, "label": ""}) if seconds and 0 < seconds <= it.MAX_TIMER_S else None


def _alarm(t: str, words: set[str]) -> it.Intent | None:
    found = it.find_when(t, prefer_am="wake" in words)
    return it.Intent("alarm.set", {"when": found[0]}) if found and found[0].hour is not None else None


def _reminder(t: str, words: set[str]) -> it.Intent | None:
    found = it.find_when(t)
    what = re.search(r"\bme (?:to|about|that|of) (.+)$", found[1]) if found else None
    label = what.group(1).strip() if what else ""
    if found is None or not label or len(label.split()) > 10 or re.search(r"\b(?:and|then|also)\b", label):
        return None  # the text must be the owner's, whole, and one thing (rem-c01: an email became a label)
    return it.Intent("reminder.set", {"when": found[0], "label": label})


def _volume(t: str, words: set[str]) -> it.Intent | None:
    if "unmute" in words or "un mute" in t:
        return it.Intent("mute", {"on": False})
    if words & {"mute", "silence"}:
        return it.Intent("mute", {"on": True})
    if _numbered(words, t):
        return None
    if (level := _number(t)) is not None:
        return it.Intent("volume.set", {"level": level})
    sign = _one(words, _UP, _DOWN)
    return it.Intent("volume.step", {"delta": 10 * sign}) if sign else None


def _brightness(t: str, words: set[str]) -> it.Intent | None:
    if _numbered(words, t):
        return None
    if (level := _number(t)) is not None:
        return it.Intent("brightness.set", {"level": level})
    sign = _one(words, _UP, _DOWN)
    return it.Intent("brightness.step", {"delta": 20 * sign}) if sign else None


def _media(t: str, words: set[str]) -> it.Intent | None:
    actions = [a for a, said in _MEDIA.items() if words & set(said.split())]
    return it.Intent("media", {"action": actions[0]}) if len(actions) == 1 else None


def _theme(t: str, words: set[str]) -> it.Intent | None:
    dark = _one(words, frozenset({"dark", "night"}), frozenset({"light"}))
    on = _one(words, _ON, _OFF) or 1
    return it.Intent("theme", {"dark": (dark > 0) == (on > 0)}) if dark else None


def _dnd(t: str, words: set[str]) -> it.Intent | None:
    on = _one(words, _ON, _OFF)
    return it.Intent("dnd", {"on": on > 0}) if on else None


def _radio(t: str, words: set[str]) -> it.Intent | None:
    kind, on = _radio_kind(t), _one(words, _ON, _OFF)
    return it.Intent("radio", {"kind": kind, "on": on > 0}) if kind and on else None


# The classifier's families (``families.jsonl``) and the grammar's readers for their slots.
_READERS: dict[str, Callable[[str, set[str]], it.Intent | None]] = {
    "timer": _timer, "alarm": _alarm, "reminder": _reminder, "volume": _volume, "brightness": _brightness,
    "media": _media, "theme": _theme, "focus": _dnd, "radio": _radio,
}


def propose(text: str, family_of: Callable[[str], tuple[str, float]] | None) -> Guess | None:
    """Swift's guess at a command the grammar missed, or None (see the module). ``family_of``: the classifier's
    family vote, None while it isn't loaded."""
    if family_of is None or it.parse(text) is not None:
        return None
    t = it.normalize(text)
    parts = [c for sentence in it.sentences(text) for c in it.clauses(sentence, loose=True)]
    # A "?" is a question unless it is asked as a request ("can you get the wifi back on?"): stricter than the gate.
    asked = text.rstrip().endswith("?") and not it.polite(text)
    if (len(parts) != 1 or not _commands(text) or asked or _VETO.search(t) or _NAMED.search(text)
            or _VOCATIVE.search(text.strip()) or _TWO_NUMBERS.search(text.lower())):
        return None
    family, score = family_of(text)
    if family not in _TIMED_FAMILIES and (_TIMED.search(t) or it.find_when(t) is not None):
        return None
    reader = _READERS.get(family)
    intent = reader(t, set(t.split())) if reader is not None and score >= GUESS_AT else None
    return Guess(intent, family, score) if intent is not None and intent.name in PROPOSABLE else None
