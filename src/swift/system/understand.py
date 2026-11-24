"""One understanding step (IA-01 phase 1; docs/explorations/intent-architecture.md §5.1, §5.3).

``understand(text)`` says what kind of thing the owner said (the speech act) and which system intents the grammar
(``intents.parse``) finds in it, after a gate: a question changes nothing, and a request taken back ("Lock the
computer. No wait, don't.") asks for nothing. It proposes nothing: guessing an intent the grammar misses is phase 2.

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

The gate on grammar matches (C1-3):

- **Question:** a sentence that ends in "?" and doesn't lead with a request ("can you", "please", or one of the
  verbs below) is a question. A change that can be read as a question about its state (a radio, dark mode, do not
  disturb) is dropped, so "Bluetooth on?" no longer switches Bluetooth on (HA-SYS-03). Everything else stays:
  the grammar's reads ("is my wifi on?") and verbless requests ("volume up?", "timer for 5 minutes?").
- **Taken back:** a clause that is only a retraction ("no wait, don't", "never mind", "cancel that"), and no
  intent itself, drops the intents of the clauses before it (HA-SYS-10); a request after it is kept ("No. Turn
  the volume down."). A clause that negates its own request ("don't
  turn off the wifi") is no grammar match today, so nothing else changes.

``Understood.record()`` is the run record's ``understood`` field: names only, never slots or words (P2-8).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

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
    download translate explain list run
""".split())
_ASKS = frozenset("how what what's whats is are does do did why when where which who whose".split())
_NEGATES = re.compile(r"(?:don't|dont|do not(?! disturb)|never)\b")
_RETRACT = re.compile(
    r"(?:(?:oh|um|uh|wait|hold on|actually|sorry|no|nope)\s+)*"
    r"(?:no|nope|don't|dont|do not|never mind|nevermind|cancel that|scratch that|forget (?:it|that))"
    r"(?:\s+(?:wait|actually|don't|dont|do not))*"
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
