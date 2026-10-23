"""Interim demand estimate (ADR-007 §4) until the local classifier exists.

``estimate`` returns "standard" when a request asks for changes, investigation
or judgment, "light" when it reads as a question, lookup, short draft or single
command, and None when neither is clear (the caller then uses its default,
Sonnet). Under-estimates are caught by escalation mid-run (ADR-007 §6); the
phrase lists are tuned on the train split of eval/routes.jsonl only.
"""

from __future__ import annotations

import re

# Asking for change, investigation or judgment: Sonnet or better.
_STANDARD = re.compile(
    r"\b("
    r"fix|refactor|implement|migrate|upgrade|port|debug(?! hotkey| key)|profile|benchmark|optimi[sz]e|speed up"
    r"|investigate|figure out|work out|find out why|why (is|does|do|did|are|was)\b"
    r"|compare|review|design|plan how|suggest|organi[sz]e(?! a meeting)|clean up|archive|go through"
    r"|rename|split|rewrite the|restructure|add (a |an )?(command line |cli )?(flag|setting|option|feature|test|tests|logging|support|type hints)"
    r"|write (unit )?tests|write a script|set up a(?! meeting| \w+ meeting)|change the (overlay|code|ui|design)|make the (orb|overlay|result|card|ui)"
    r"|undo|try again|do the same|that last change|what you just did|now commit"
    r")\b",
    re.IGNORECASE,
)
# Questions, lookups, drafts and single commands: Haiku first.
_LIGHT = re.compile(
    r"^("
    r"what|what's|which|who|when|where|how (many|much|long|big|do)|is there|are there|is the|did|do i|does"
    r"|show|list|find|search|look up|read|summari[sz]e|give me|tell me|explain|translate|convert|count"
    r"|draft|write (a|an|my|me)|compose|prepare|start an email|new email|email|send|reply|let .* know|put together"
    r"|in the .* folder|remind|set (a|up a) (\w+ )?reminder|add a reminder|don't let me forget|every .* remind|in .* remind|cancel|delete|remove|stop reminding|get rid"
    r"|schedule|book|find (a|time)|arrange|invite|set up a meeting|organi[sz]e a meeting|i need to (meet|write)|can you get me"
    r"|run|kick off|test my|check|open|launch|load|fire up|get my dev|set up my workspace|bring up|pull|commit|create a (new )?branch"
    r"|set the|update config|move the .* (hotkey|key)|make (it|that|the email|the draft)|shorten|tone|add that|change the subject|rewrite that"
    r"|can you|could you|play|i need|latest|new|add a next steps"
    r")\b",
    re.IGNORECASE,
)


_LEAD = re.compile(r"^((um+|uh+|er+|ok|okay|so|right|alright)[\s,.]+)+", re.IGNORECASE)


def estimate(request: str) -> str | None:
    if _STANDARD.search(request):
        return "standard"
    if _LIGHT.match(_LEAD.sub("", request.strip())):
        return "light"
    return None
