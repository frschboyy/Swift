"""Dialogue (ADR-016 §5.1): Swift asks the owner something, listens, and works out the answer.

A small state holder the session owns, on top of ADR-013's threads. Nothing here touches the
microphone, the overlay or a model: the session shows and says the question, opens the
microphone, and hands what was said to ``Dialogue.answer``.

*Questions.* A run asks through Swift's ``ask_owner`` tool, a lane asks when a slot is missing
("For how long?") or a change needs a yes ("Turn off Wi-Fi?"). Kinds: ``yes_no``, ``choice``
(``options``), ``free``, and the slot kinds the lanes use: ``duration``, ``time``, ``number``.
One question is asked at a time; another waits behind it (``Dialogue.ask``).

*Answers* (``resolve``): yes and no ("yeah", "go ahead", "nope"); ordinals and names ("the
second one", "Sam Lee, not Sam Okoro"); numbers, lengths of time and clock times; corrections
("no, make it four"); cancel ("never mind"). "Never mind, what time is it?" drops the question
and the rest is a new request (``elsewhere``); so is a clear request said instead of an answer,
when the session's ``is_request`` says so. What can't be worked out is ``unclear``: asked once
more, then the question goes to the waiting stack (``Dialogue.answer`` returns ``shelve``).

*Carry-over* (``Carry``): the last local answer or system change, kept ``CARRY_S`` so "and
tomorrow?", "what about in Tokyo?", "make it louder" or "no, make it four" resolve against it.
It is the fast lane's follow-up context too (``Carry.moment``), not a second mechanism, and it
is forgotten when the owner goes away (``Dialogue.forget``).

Content stays out of the log: callers log kinds and counts only (``Answer.kind``).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from typing import Any, Literal

from swift import clock as swift_clock
from swift.routing import fast
from swift.system import intents as it

# What ``ask_owner`` takes; the lanes also ask for a length of time, a clock time or a number.
ASK_KINDS = ("yes_no", "choice", "free")
KINDS = (*ASK_KINDS, "duration", "time", "number")
MAX_OPTIONS = 8
MAX_QUESTION = 300
# How long the last answer or change is kept for "and tomorrow?" / "make it louder" (§5.1: ~60 s).
CARRY_S = 60.0
# How long a radio switched by Swift (Wi-Fi, Bluetooth, airplane mode) can still be "turned back on".
SWITCH_KEEP_S = 30 * 60.0
# An unclear answer is asked again this many times before the question goes to the stack.
REASKS = 1

AnswerKind = Literal["yes", "no", "choice", "value", "text", "cancel", "unclear", "elsewhere", "wait"]


@dataclass(eq=False)
class Question:
    """Something Swift asked and waits for."""

    text: str
    kind: str = "free"
    options: tuple[str, ...] = ()
    # "run": a provider asked (``ask_owner``), waiting on ``future``; "lane": Swift itself asked.
    source: str = "lane"
    thread: str | None = None
    # The slot a lane asked for ("seconds", "when") and what to finish with it (the intents).
    slot: str | None = None
    payload: Any = None
    # A yes to this one goes ahead with a change the owner just asked for ("Turn off Wi-Fi?"). Said or
    # clicked, a plain yes does it (owner, 2026-11-04: reversible changes need no name); typed, it
    # never does, since typing never approves (ADR-015 §10).
    yes_needs_name: bool = False
    # Who asked: the session's request object, so only that request's end drops it (audit A-08).
    owner: Any = None
    id: str = field(default_factory=lambda: f"ask-{uuid.uuid4().hex[:8]}")
    asked_at: float = field(default_factory=swift_clock.now)
    reasked: int = 0
    future: asyncio.Future[Answer] | None = None
    # Said aloud: the microphone opens when Swift has finished saying it.
    spoken: bool = False
    # A lane's question on its own card: the card's run id, and a quiet line under the question
    # ("Swift needs the internet for most requests") that is shown, never said.
    run_id: str | None = None
    note: str = ""
    closed: bool = False
    # The owner's words that led to it, for the stack if it goes unanswered (never logged).
    request: str = ""
    # Its window for the answer (swift/answer_window.py): one deadline, its own (seams audit S3).
    # Swift's own question (the system lane's), not a provider's.
    own: bool = False
    window: Any = field(default=None, repr=False, compare=False)
    # Said again in other words ("Sorry, was that a yes or a no? …"): what its card shows meanwhile.
    reask_text: str | None = None

    def as_message(self) -> dict[str, Any]:
        return {"ask_id": self.id, "question": self.text, "kind": self.kind, "options": list(self.options),
                "thread_id": self.thread, **({"note": self.note} if self.note else {})}

    @property
    def expects_free_text(self) -> bool:
        return self.kind == "free" or (self.kind == "choice" and not self.options)


@dataclass(frozen=True)
class Answer:
    kind: AnswerKind
    # choice: the option; value: seconds (duration), ``it.When`` (time) or a number; text: the words.
    value: Any = None
    index: int | None = None
    # elsewhere: the new request; no: what followed it ("no, make it four").
    rest: str = ""
    # "no, make it four" / "actually five": a correction, not a plain answer.
    corrected: bool = False
    # Said with Swift's name ("Swift, yes"): the bar for a yes that does something disruptive.
    named: bool = False
    # elsewhere: said with "never mind" first, so the question is dropped, not only set aside.
    dropped: bool = False
    # The owner's own words for this answer, said or typed (never a click on an option the run wrote,
    # never a yes or no): ``system_action`` counts them as the owner asking (owner check 128, 2026-11-09).
    said: str = ""

    def for_run(self) -> dict[str, Any]:
        """What ``ask_owner`` returns to the provider."""
        if self.kind in ("yes", "no"):
            out: dict[str, Any] = {"answered": True, "answer": self.kind}
            if self.rest:
                out["and_said"] = self.rest
            return out
        if self.kind == "choice":
            return {"answered": True, "answer": self.value, "option": (self.index or 0) + 1}
        if self.kind == "value":
            value = self.value
            if isinstance(value, it.When):
                value = _say_when(value)
            return {"answered": True, "answer": value}
        if self.kind == "text":
            return {"answered": True, "answer": self.value}
        if self.kind == "cancel":
            return {"answered": False, "reason": "The owner said never mind: don't do this part. Stop and say so."}
        return {"answered": False, "reason": "No answer."}


# ---- reading what was said ----------------------------------------------------------------------

_NAME = re.compile(r"^\W*(?:(?:hey|hi|hello|ok|okay)\s+)?swift\b[\s,.:!-]*", re.IGNORECASE)
_FILLER = re.compile(r"^(?:(?:um+|uh+|er+|erm|hmm+|well|so|oh|ah)\b[\s,.]*)+", re.IGNORECASE)
_CANCEL = re.compile(
    r"^\W*(?:no[\s,.]+)?(?:never ?mind|cancel(?: (?:that|it|the question))?|forget (?:it|that|about it)|don'?t bother"
    r"|skip (?:it|that)|nothing|none of (?:them|those)|stop asking)\b[\s,.!?-]*",
    re.IGNORECASE,
)
_YES = re.compile(
    r"^(?:yes|yeah|yep|yup|ya|yes please|sure|ok|okay|alright|all right|go ahead|do it|please do|please|correct"
    r"|that'?s right|right|exactly|absolutely|of course|definitely|affirmative|confirm(?:ed)?|approve(?:d)?"
    r"|sounds good|that'?s fine|fine|go for it)\b"
)
_NO = re.compile(r"^(?:no|nope|nah|no thanks|no thank you|not really|don'?t|do not|negative|leave it|keep it"
                 r"|reject|wrong|that'?s wrong|not that)\b")
# What makes a reply a correction: "no, make it four", "actually five", "change it to six", "make that 6 pm".
_CORRECTION = re.compile(
    r"^(?:no[\s,]+|nope[\s,]+|actually[\s,]+|sorry[\s,]+|i mean[\s,]+|i meant[\s,]+|wait[\s,]+)*"
    r"(?:make (?:it|that)|change (?:it|that) to|set (?:it|that) to|let'?s (?:say|do|make it)|instead|rather)\s+"
)
# The owner needs a moment ("hold on", "I'm not sure"): the question stays, with a whole window (D-02).
_HOLD = re.compile(
    r"(?:hold on|hang on|wait|one (?:sec|second|moment|minute)|just a (?:sec|second|moment|minute)"
    r"|give me a (?:sec|second|moment|minute)|i'?m not sure|not sure|let me think|i need to think|i'?ll think)"
    r"(?: a (?:sec|second|moment|minute|bit))?(?: (?:please|then))?"
)
# After a yes, words that only restate the change or are politeness ("Yeah, turn it off for now,
# thanks"): still a yes. Anything else after it (a question) isn't (D-02).
_YES_REST = frozenset(
    "turn switch put it that this off on please thanks thank you for now just do go ahead then right away again"
    " the a ok okay sure".split()
)
_ASKING = re.compile(r"\b(?:what|why|how|when|where|who|which|can|could|will|would|is|are|does|do you)\b")
_LEAD = re.compile(r"^(?:no|nope|actually|sorry|i mean|i meant|wait|rather|instead|and|but|just)[\s,]+")
_ORDINALS = {
    "first": 0, "1st": 0, "one": 0, "second": 1, "2nd": 1, "two": 1, "third": 2, "3rd": 2, "three": 2,
    "fourth": 3, "4th": 3, "four": 3, "fifth": 4, "5th": 4, "five": 4, "sixth": 5, "6th": 5, "six": 5,
    "seventh": 6, "7th": 6, "seven": 6, "eighth": 7, "8th": 7, "eight": 7,
}
_ORDINAL = re.compile(
    r"^(?:the |that |it'?s the |its the )?(?:(?P<ord>first|second|third|fourth|fifth|sixth|seventh|eighth|1st|2nd|3rd|4th|5th"
    r"|6th|7th|8th|last|other|top|bottom)(?: one| option| choice| person| contact)?|(?:number|option|choice) (?P<num>\w+)"
    r"|(?P<digit>\d))(?: (?:one|please))?$"
)
_NOT = re.compile(r"\b(?:not|rather than|instead of|but not)\b")
_WORD = re.compile(r"[a-z0-9']+")
_NAME_STOP = frozenset("the a an one is it its it's that this please i mean meant the one with from at".split())


def clean(text: str) -> str:
    """What was said, without Swift's name or a leading "um", lower case, punctuation as spaces."""
    t = _NAME.sub("", text.replace("’", "'").strip())
    t = _FILLER.sub("", t)
    return " ".join(re.sub(r"[^\w\s':.]", " ", t.lower()).replace(".", " ").split())


def _raw_rest(text: str, match: re.Match[str]) -> str:
    rest = text[match.end():].strip(" ,.;:-")
    rest = _LEAD.sub("", rest.lower()) if rest.lower().startswith(("and ", "just ")) else rest
    return rest.strip()


def _words(text: str) -> list[str]:
    return [w.strip("'") for w in _WORD.findall(text.lower())]


def _close(a: str, b: str) -> bool:
    return a == b or (len(a) >= 3 and len(b) >= 3 and SequenceMatcher(None, a, b).ratio() >= 0.8)


def _option_score(words: list[str], option: str) -> int:
    names = [w for w in _words(option) if w not in _NAME_STOP]
    return sum(1 for w in words if w not in _NAME_STOP and any(_close(w, n) for n in names))


def _choose(said: str, options: tuple[str, ...]) -> int | None:
    """Which option ``said`` names: by ordinal ("the second one") or by name ("Sam Lee, not Sam
    Okoro"). None when it names none, or two equally."""
    t = said.strip()
    if m := _ORDINAL.match(t):
        word = m.group("ord") or m.group("num") or m.group("digit")
        if word in ("last", "bottom"):
            return len(options) - 1
        if word == "top":
            return 0
        if word == "other":
            return None
        if word is not None and word.isdigit():
            index = int(word) - 1
        else:
            index = _ORDINALS.get(word or "", -1)
        return index if 0 <= index < len(options) else None
    parts = _NOT.split(t, maxsplit=1)
    wanted = _words(parts[0])
    # "Sam Lee, not Sam Okoro": "Sam" is in both, so only "Okoro" counts against.
    unwanted = [w for w in _words(parts[1]) if w not in wanted] if len(parts) > 1 else []
    if not [w for w in wanted if w not in _NAME_STOP] and unwanted:
        # "Not Sam Okoro" alone: the one it names least, if that is a single one.
        against = [_option_score(unwanted, o) for o in options]
        left = [i for i, a in enumerate(against) if a < max(against)]
        return left[0] if len(left) == 1 else None
    scores = [_option_score(wanted, o) - 2 * _option_score(unwanted, o) for o in options]
    best = max(scores, default=0)
    if best <= 0 or scores.count(best) > 1:
        return None
    return scores.index(best)


def _number(said: str) -> float | None:
    t = it.normalize(said)
    found = re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", t)
    if len(found) != 1:
        return None
    value = float(found[0])
    return int(value) if value.is_integer() else value


def _duration(said: str) -> float | None:
    t = it.normalize(said)
    t = re.sub(r"^(?:for |about |around |just )+", "", t)
    if t in ("an hour", "a hour", "hour"):
        return 3600.0
    if t in ("a minute", "minute"):
        return 60.0
    t = re.sub(r"\ban? (?=hour|minute|second|day|week)", "1 ", t)
    seconds = it.seconds_of(t)
    if seconds is not None:
        leftover = re.sub(rf"{it._DUR}", "", t).strip()  # noqa: SLF001 - one grammar for both
        return seconds if not leftover or leftover in ("please", "thanks") else None
    if (n := _number(t)) is not None and re.fullmatch(r"\d+(?:\.\d+)?", t):
        return float(n) * 60  # "for how long?" "five": minutes (a timer is reversible; the reply says it)
    return None


def _when(said: str) -> it.When | None:
    t = it.normalize(said)
    t = re.sub(r"^(?:remind me |make it |do it |for )", "", t)
    for candidate in (t, f"at {t}", re.sub(r"^(\S+) at ", r"\1 at ", t)):
        found = it.find_when(candidate)
        if found is not None and len(found[1].split()) <= 1:
            return found[0]
    return None


def _say_when(when: it.When) -> str:
    if when.seconds is not None:
        return f"in {it.say_duration(when.seconds)}"
    mer = f" {when.meridiem}" if when.meridiem else ""
    day = f" {when.day}" if when.day else ""
    return f"at {when.hour}:{when.minute:02d}{mer}{day}"


def _value(kind: str, said: str) -> Any:
    if kind == "duration":
        return _duration(said)
    if kind == "time":
        return _when(said)
    return _number(said)


def resolve(question: Question, text: str, *, is_request: Callable[[str], bool] | None = None) -> Answer:
    """What ``text`` answers to ``question`` (see the module docstring). ``is_request`` says whether
    words that don't answer it are a clear new request ("what time is it"): then ``elsewhere``."""
    named = _NAME.match(text.replace("’", "'")) is not None
    raw = _FILLER.sub("", _NAME.sub("", text.replace("’", "'").strip())).strip()
    said = clean(text)
    if not said:
        return Answer("unclear")
    if (m := _CANCEL.match(raw)) is not None:
        rest = _raw_rest(raw, m)
        if rest and (is_request is None or is_request(rest)):
            return Answer("elsewhere", rest=rest, named=named, dropped=True)
        return Answer("cancel", named=named)
    if question.kind != "free" and _HOLD.fullmatch(said):
        return Answer("wait", named=named)
    answer = _resolve_kind(question, said, raw)
    if answer.kind == "unclear" and is_request is not None and question.kind != "free" and is_request(raw):
        return Answer("elsewhere", rest=raw, named=named)
    return replace(answer, named=named)


def _resolve_kind(question: Question, said: str, raw: str) -> Answer:
    kind = question.kind
    if kind == "free" or (kind == "choice" and not question.options):
        return Answer("text", value=raw.strip(" ,"))
    correction = _CORRECTION.match(said)
    if kind == "yes_no":
        if correction is not None or ((m := _NO.match(said)) is not None and said[m.end():].strip(" ,")):
            # "No, make it four": a no, and what to do instead.
            rest = re.sub(r"^(?:no|nope|nah|actually|sorry|wait)[\s,]+", "", said).strip()
            return Answer("no", rest=rest, corrected=True)
        if _NO.match(said):
            return Answer("no")
        if (m := _YES.match(said)) is not None:
            rest = said[m.end():].strip(" ,")
            if len(rest.split()) > 4 and not _restates(question, rest):
                return Answer("unclear")  # "okay, what's the weather like there": not a yes
            return Answer("yes", rest=rest)
        return Answer("unclear")
    body = said[correction.end():] if correction is not None else _LEAD.sub("", said)
    if kind == "choice":
        options = question.options
        if len(options) == 1 and (_YES.match(said) and not _NO.match(said)):
            return Answer("choice", value=options[0], index=0)
        if _NO.match(said) and not body.strip():
            return Answer("no")
        index = _choose(body, options)
        if index is None and body != said:
            index = _choose(said, options)
        if index is None:
            return Answer("unclear")
        return Answer("choice", value=options[index], index=index, corrected=correction is not None)
    value = _value(kind, body)
    if value is None:
        return Answer("unclear")
    return Answer("value", value=value, corrected=correction is not None)


def _restates(question: Question, rest: str) -> bool:
    """Whether what follows a yes only restates the question's change, or is politeness (D-02)."""
    if _ASKING.match(rest):
        return False
    asked = set(re.findall(r"[a-z]+", question.text.lower()))
    left = [w for w in rest.split() if w not in _YES_REST and w not in asked]
    return len(left) <= 1


def reask_text(question: Question) -> str:
    """The question again, after an answer that couldn't be worked out."""
    if question.kind == "choice" and question.options:
        listed = " or ".join(question.options[:3]) if len(question.options) <= 3 else "the first, second, or another number"
        return f"Sorry, which one: {listed}?"
    if question.kind == "yes_no":
        return f"Sorry, was that a yes or a no? {question.text}"
    return f"Sorry, I didn't catch that. {question.text}"


# ---- the pending question, and what is carried over -----------------------------------------------


@dataclass(frozen=True)
class Turn:
    """What to do with something said while a question waits."""

    # "answered" (``answer``), "reask" (unclear, asked again), "shelve" (unclear twice: to the stack),
    # "cancelled", "elsewhere" (a new request: ``answer.rest``), "wait" (the owner needs a moment).
    action: Literal["answered", "reask", "shelve", "cancelled", "elsewhere", "wait"]
    answer: Answer
    question: Question


@dataclass
class Carry:
    """The last local answer or system change, for the next request's ellipsis (§5.1)."""

    thread: str | None
    at: float
    # A time or date answer's moment: "and the date?", "what about in Tokyo?" (fast lane).
    moment: fast.Moment | None = None
    # The system intents just carried out: "make it louder", "no, make it four".
    intents: tuple[it.Intent, ...] = ()
    # The answer as context for a follow-up the lanes can't answer (the session's ``Exchange``).
    exchange: Any = None


class Dialogue:
    def __init__(self, clock: Callable[[], float] = swift_clock.now, carry_s: float = CARRY_S) -> None:
        self.clock = clock
        self.carry_s = carry_s
        # The question on screen, and those asked behind it, in order.
        self.pending: Question | None = None
        self.waiting: list[Question] = []
        # Two slots, each its own expiry (D-04): the last local answer (a time or date, as context) and
        # the last system change. A time answer in between never makes Swift forget the Wi-Fi it switched.
        self._carry: Carry | None = None
        self._change: Carry | None = None

    # ---- questions ---------------------------------------------------------------------------

    def ask(self, question: Question) -> bool:
        """Ask ``question``: on screen now (True), or behind the one asked before (False)."""
        if self.pending is None:
            self.pending = question
            return True
        self.waiting.append(question)
        return False

    def ask_first(self, question: Question) -> None:
        """Ask ``question`` on screen now: the one there waits behind it, first in line (seams audit T-01:
        the owner moved on to a new request, and that request's question is the one they're in)."""
        if self.pending is not None:
            self.waiting.insert(0, self.pending)
        self.pending = question

    def done(self, question: Question) -> Question | None:
        """``question`` no longer waits (answered, put off, dropped): the next one, if it came forward."""
        if question in self.waiting:
            self.waiting.remove(question)
            return None
        if self.pending is not question:
            return None
        self.pending = self.waiting.pop(0) if self.waiting else None
        if self.pending is not None:
            self.pending.asked_at = self.clock()
        return self.pending

    def of(self, owner: Any) -> list[Question]:
        """Every question ``owner`` asked, on screen or waiting."""
        return [q for q in ([self.pending] if self.pending else []) + self.waiting if q.owner is owner]

    def answer(self, text: str, *, is_request: Callable[[str], bool] | None = None) -> Turn | None:
        """Something said while a question waits; None when nothing does."""
        question = self.pending
        if question is None:
            return None
        found = resolve(question, text, is_request=is_request)
        if found.kind == "elsewhere":
            return Turn("elsewhere", found, question)
        if found.kind == "cancel":
            return Turn("cancelled", found, question)
        if found.kind == "wait":
            return Turn("wait", found, question)
        if found.kind == "unclear":
            if question.reasked < REASKS:
                question.reasked += 1
                return Turn("reask", found, question)
            return Turn("shelve", found, question)
        return Turn("answered", found, question)

    # ---- carry-over --------------------------------------------------------------------------

    def remember(self, thread: str | None, *, moment: fast.Moment | None = None,
                 intents: tuple[it.Intent, ...] = (), exchange: Any = None) -> None:
        """A system change (``intents``) or a local answer (``moment``, ``exchange``): each in its slot."""
        carry = Carry(thread, self.clock(), moment, tuple(intents), exchange)
        if intents:
            self._change = carry
        else:
            self._carry = carry

    def recall(self, thread: str | None) -> Carry | None:
        """The last local answer, if the request continues its thread or comes within ``carry_s``."""
        return self._fresh(self._carry, thread, self.carry_s)

    def recall_change(self, thread: str | None) -> Carry | None:
        """The last system change, for "make it louder" or "turn it back on": within ``carry_s`` or its
        thread, and a radio switched off or on (Wi-Fi, Bluetooth, airplane mode) for ``SWITCH_KEEP_S``,
        since the owner may want it back long after (D-03, D-04)."""
        change = self._change
        keep = SWITCH_KEEP_S if change is not None and any(i.name == "radio" for i in change.intents) else self.carry_s
        return self._fresh(change, thread, keep)

    def _fresh(self, carry: Carry | None, thread: str | None, keep_s: float) -> Carry | None:
        if carry is None:
            return None
        if (thread is not None and carry.thread == thread) or self.clock() - carry.at <= keep_s:
            return carry
        return None

    @property
    def carry(self) -> Carry | None:
        return self._carry

    def forget(self) -> None:
        """The owner went away: nothing said before carries over to what is said after."""
        self._carry = self._change = None


# ---- ellipsis against the last system change ("make it louder", "no, make it four") ---------------

_UP = re.compile(r"^(?:and |a (?:bit|little|touch) |bit |little |slightly |even )?(?:more|louder|higher|up|brighter|"
                 r"turn it up|make it (?:louder|brighter|higher)|(?:a )?(?:bit|little) (?:more|louder|higher|brighter))$")
_DOWN = re.compile(r"^(?:and |a (?:bit|little|touch) |bit |little |slightly |even )?(?:less|quieter|softer|lower|down|dimmer|darker|"
                   r"turn it down|make it (?:quieter|softer|lower|dimmer|darker)|(?:a )?(?:bit|little) (?:less|quieter|lower|dimmer))$")
# "Turn it back on" after Wi-Fi, Bluetooth or airplane mode was switched (owner checks 2026-11-04:
# with Wi-Fi off it went to the agent, which can't work offline). "Put it back": the other way.
_SWITCH = re.compile(r"^(?:no |actually |ok |okay |and |now |please )*(?:(?:turn|switch|flip|put) (?:it|that|them) "
                     r"(?:back )?(?P<a>on|off)|(?:turn|switch|flip) (?:back )?(?P<b>on|off) (?:it|that|them)|back (?P<c>on|off)"
                     r"|(?P<d>on|off) again|(?P<back>put (?:it|that|them) back|change (?:it|that) back|switch (?:it|that) back))"
                     r"(?: again| now| please)*$")
_BY = re.compile(r"^(?:and |another |(?:and )?another )?(?P<n>\d{1,3})(?: percent| %|%)? (?P<dir>more|less|up|down|higher|lower)$")
_TO = re.compile(r"^(?:no |actually |nope )?(?:make it|make that|set it to|change it to|to|put it (?:at|on)|let'?s say|"
                 r"no make it|actually make it)? ?(?P<rest>.+)$")


def elide(text: str, before: tuple[it.Intent, ...]) -> tuple[list[it.Intent], bool] | None:
    """A fragment said after a system change, as intents against it: (intents, replaces). ``replaces``:
    the change before is undone first ("no, make it four" after a 3 minute timer). None: not one."""
    if not before:
        return None
    t = it.normalize(text)
    t = re.sub(r"^(?:swift |ok |okay |um |uh )+", "", t).strip(" ?.!")
    if not t or len(t.split()) > 8:
        return None
    last = before[-1]
    family = last.name.split(".")[0]
    if family in ("volume", "brightness"):
        if _UP.match(t) or _DOWN.match(t):
            delta = 10 if _UP.match(t) else -10
            if re.search(r"\b(?:bit|little|touch|slightly)\b", t):
                delta //= 2
            return [it.Intent(f"{family}.step", {"delta": delta})], False
        if m := _BY.match(t):
            n = int(m.group("n"))
            return [it.Intent(f"{family}.step", {"delta": n if m.group("dir") in ("more", "up", "higher") else -n})], False
        m = _TO.match(t)
        rest = m.group("rest") if m else ""
        if m and re.fullmatch(r"\d{1,3}(?: percent| %|%)?", rest) and re.match(r"^(?:no |actually |nope )?(?:make|set|change|to|put|let)", t):
            level = int(re.match(r"\d+", rest).group(0))  # type: ignore[union-attr]
            if 0 <= level <= 100:
                return [it.Intent(f"{family}.set", {"level": level})], False
        return None
    if last.name in ("radio", "airplane"):
        if (s := _SWITCH.match(t)) is None:
            return None
        said = s.group("a") or s.group("b") or s.group("c") or s.group("d")
        on = (said == "on") if said else not last["on"]
        return [it.Intent(i.name, {**i.slots, "on": on}) for i in before if i.name in ("radio", "airplane")], False
    if last.name not in ("timer.set", "alarm.set", "reminder.set"):
        return None
    m = re.match(r"^(?:no |nope |actually |sorry |wait )*(?:make (?:it|that)|change (?:it|that) to|set (?:it|that) (?:to|for)|"
                 r"i (?:said|meant)|let'?s (?:say|do))\s+(?P<rest>.+)$", t)
    if m is None:
        return None
    rest = m.group("rest").strip()
    if last.name == "timer.set":
        seconds = _duration_like(rest, last["seconds"])
        if seconds is None or not 0 < seconds <= it.MAX_TIMER_S:
            return None
        return [it.Intent("timer.set", {**last.slots, "seconds": seconds})], True
    when = _when(rest)
    if when is None and re.fullmatch(r"\d{1,2}(?:\.\d\d)?", rest):
        when = _when(f"at {rest}")
    if when is None:
        return None
    previous: it.When = last["when"]
    if when.seconds is None and when.day is None and previous.day is not None:
        when = replace(when, day=previous.day, next_week=previous.next_week)
    if last.name == "alarm.set":
        when = replace(when, prefer_am=previous.prefer_am)
    return [it.Intent(last.name, {**last.slots, "when": when})], True


def _duration_like(rest: str, before: float) -> float | None:
    """"Four" after a 3 minute timer is four minutes; "four hours" is four hours."""
    seconds = _duration(rest) if not re.fullmatch(r"\d+(?:\.\d+)?", it.normalize(rest)) else None
    if seconds is not None:
        return seconds
    n = _number(rest)
    if n is None:
        return None
    unit = 3600 if before >= 3600 and before % 3600 == 0 else 60 if before >= 60 else 1
    return float(n) * unit


__all__ = [
    "ASK_KINDS", "CARRY_S", "KINDS", "REASKS", "Answer", "Carry", "Dialogue", "Question", "Turn", "clean", "elide",
    "reask_text", "resolve",
]
