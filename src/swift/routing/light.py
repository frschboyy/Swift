"""The light lane (ADR-007 §10): quick facts and everyday language, one tool-free model call.

``kind(text)`` says whether a request is one of these: a word ("a synonym for happy", "what
does ubiquitous mean", "how do you say thank you in French"), a stable fact ("what's the
capital of Peru", "who wrote Middlemarch") or a few words to send ("reply politely to say
I'm late"). Such a request needs no files, apps, accounts or web: a single answer from the
cheapest model is enough, so it skips the agent session entirely (``swift.executors.quick``).

Anything about the owner's things ("my", "this", a file, an email to someone, the
calendar) or about now ("today", "latest", "weather") is not light: those need tools or
fresh data and go to the agent as before. When unsure, None: the agent still answers.
"""

from __future__ import annotations

import re

from swift.routing.fast import normalize

LANGUAGES = (
    "english french spanish german italian portuguese dutch polish romanian russian ukrainian greek turkish arabic "
    "hebrew hindi urdu bengali chinese mandarin cantonese japanese korean vietnamese thai indonesian malay swahili "
    "yoruba igbo hausa swedish norwegian danish finnish czech hungarian irish welsh latin"
).split()
_LANG = rf"(?:{'|'.join(LANGUAGES)})"

KINDS: dict[str, re.Pattern[str]] = {
    "synonym": re.compile(
        r"(?:what(?:'s| is| are)|give me|tell me|suggest|i need) ?(?:a |an |another |some |other |a few |a better |a nicer )?"
        r"(?:synonyms?|other words?|words?|alternatives?|different words?|better words?|nicer words?|another way to say"
        r"|a different way to say) (?:for|of|than|to|instead of) .{1,40}"
        r"|(?:a |an |another |other )?(?:synonyms?|antonyms?|other words?|another word) (?:for|of) .{1,40}"
    ),
    "antonym": re.compile(r"(?:what(?:'s| is) )?(?:the |an )?(?:opposite|antonym) (?:of|for) .{1,40}"),
    "define": re.compile(
        r"what does (?:the word )?.{1,40} mean|(?:define|definition of|meaning of) .{1,40}"
        r"|what(?:'s| is) the (?:meaning|definition) of .{1,40}|what(?:'s| is) (?:a|an) [a-z'-]+(?: [a-z'-]+)?"
    ),
    "translate": re.compile(
        rf"how (?:do|would|can) (?:you|i|we) say .{{1,80}} in {_LANG}|translate .{{1,80}} (?:in|into|to) {_LANG}"
        rf"|what(?:'s| is) .{{1,60}} in {_LANG}|how (?:do|would) {_LANG} (?:people )?say .{{1,60}}"
    ),
    "language": re.compile(
        r"is it .{1,30} or .{1,30}|(?:what(?:'s| is) )?the (?:plural|past tense|past participle|singular) of .{1,30}"
        r"|what rhymes with .{1,30}|(?:a )?words? that rhymes? with .{1,30}|how (?:do|should) (?:you|i) pronounce .{1,40}"
        r"|is .{1,30} a (?:real )?word|is .{1,30} (?:spelled|spelt) with .{1,20}|which is (?:correct|right) .{1,60}"
        r"|what(?:'s| is) the difference between .{1,40} and .{1,40}"
    ),
    "compose": re.compile(
        r"(?:(?:write|draft|give me|suggest|help me write|help me with|compose|come up with|what's) )?(?:me )?(?:a |an )?"
        r"(?:(?:polite|short|quick|friendly|nice|formal|casual|kind|brief|professional|gentle|warm|apologetic) )+"
        r"(?:reply|message|text|note|response|answer|way|thank you|apology|excuse|sentence|line)"
        r"(?: (?:to say|saying|that says|telling them|telling (?:him|her|someone)|to tell (?:them|him|her|someone)"
        r"|to ask|asking|to let (?:them|him|her|someone) know|for|about|to decline|declining|to accept|accepting)) .{3,160}"
        r"|(?:reply|respond|answer) (?:politely|nicely|kindly|formally|briefly|casually|warmly|professionally)"
        r" (?:to say|saying|that|to tell (?:them|him|her)|and say|to ask|and ask) .{3,160}"
        r"|how (?:do|can|should|could) i (?:politely |nicely |kindly |gently |professionally )?(?:say|tell (?:someone|them|him|her)"
        r"|ask (?:someone|them|him|her)) .{3,160}(?: politely| nicely| kindly| gently| professionally)?"
        r"|(?:rephrase|reword|make) .{3,160} (?:more |sound )?(?:polite|politely|formal|friendlier|friendly|nicer|professional)"
    ),
    "fact": re.compile(
        r"what(?:'s| is) the capital(?: city)? of .{1,40}|what(?:'s| is) the (?:population|currency|language|national animal"
        r"|official language|area|height|length|boiling point|freezing point|speed of (?:light|sound)|chemical symbol"
        r"|atomic number) (?:of|for) .{1,40}"
        r"|who (?:wrote|painted|invented|discovered|composed|directed|founded|designed|built|sang|played|created) .{2,60}"
        r"|when (?:was|were|did) .{2,60} (?:born|die|died|invented|founded|built|written|published|released|discovered"
        r"|happen|start|end|begin|sink|fall|land)|how (?:tall|high|long|big|deep|far|old|heavy|wide|hot|cold) is (?:the |a |an |mount |mt )?"
        r"[a-z' -]{2,40}|how many (?:legs|bones|teeth|planets|continents|oceans|states|countries|moons|strings|players|keys"
        r"|chromosomes|hearts|sides|days|weeks) (?:does|do|are there|is there|in|has|have|on) .{1,40}"
        r"|what (?:language|currency) (?:do they speak|is spoken|is used|do they use) in .{1,40}"
        r"|what(?:'s| is) the (?:largest|biggest|smallest|longest|tallest|highest|deepest|oldest) [a-z ]{2,40}"
        r"|what (?:year|century) (?:was|did|were) .{2,60}"
    ),
}

# About the owner's things, Swift's apps, or now: tools or fresh data (the agent), never this lane.
_NOT_LIGHT = re.compile(
    r"\b(?:my|mine|our|this|these|those|here|selected|selection|highlighted|screen|clipboard"
    r"|e-?mails?|e-?mail|inbox|send|calendar|meeting|reminder|remind|file|files|folder|folders|document|documents|doc"
    r"|project|repo|code|tests?|commit|branch|desktop|notepad|outlook|gmail|word document|in word|excel|spreadsheet"
    r"|today|tonight|tomorrow|yesterday|now|currently|current|latest|recent|recently|news|weather|forecast|price|prices"
    r"|stock|stocks|score|scores|this week|this year|live|open|search|look up|google|online|website|web|internet)\b"
)
# Composing only reads like the owner's own words: "my" and "this" are fine there ("say I'll miss my train").
_NOT_COMPOSE = re.compile(
    r"\b(?:e-?mails?|inbox|send|calendar|file|files|folder|document|selected|selection|highlighted|clipboard"
    r"|this (?:message|email|text|thread|chat)|reply to (?!say)\w+|outlook|gmail|teams|slack|whatsapp|in word)\b"
)

# "Write a short note about tea here": into the app in front (the agent's desktop_write), not an answer
# card; "say I'll be here at five" is still the owner's own words (audit 2026-10, A-10).
_WRITE_HERE = re.compile(
    r"\bhere\s*$|\b(?:write|type|put|paste|insert|add)\b"
    r"(?:(?!\b(?:saying|to say|that says|telling|to tell|asking|to ask|about)\b).)*\b(?:here|in there|in this)\b"
)
# "What does this error mean", "a synonym for this": about what the owner is looking at.
_ON_SCREEN = re.compile(r"\b(?:this|these|that one|my|here|error|warning|message)\b")


def kind(text: str) -> str | None:
    """The light lane's kind of request (``KINDS``), or None when it needs more than one model call."""
    t = re.sub(r"^(?:(?:can|could|would) you (?:please )?|please |i'd like |i want |i need )", "", normalize(text))
    if not t or len(t) > 200:
        return None
    for name, pattern in KINDS.items():
        if not pattern.fullmatch(t):
            continue
        if name == "compose":
            blocked = _NOT_COMPOSE.search(t) or _WRITE_HERE.search(t)
        elif name == "fact":
            blocked = _NOT_LIGHT.search(t)
        else:  # a word or phrase asked about can be anything ("a synonym for today"), but not what's on screen
            blocked = _NOT_COMPOSE.search(t) or _ON_SCREEN.search(t)
        return None if blocked else name
    return None


PROMPT = (
    "You are Swift, a voice assistant answering one quick question. Answer in one or two short sentences, "
    "plain spoken English, no markdown, headings or bullet points. For words (synonyms, antonyms, rhymes), give "
    "up to five, comma-separated. For a translation, give it and, if useful, a pronunciation hint. For a message "
    "the user wants to send, give only the message itself, ready to paste. If you aren't sure, or the answer may "
    "have changed recently, say so in a few words rather than guessing."
)

__all__ = ["KINDS", "LANGUAGES", "PROMPT", "kind"]
