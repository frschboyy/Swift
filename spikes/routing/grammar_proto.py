"""S3: fast-path grammar prototype (throwaway; the real one is agent/grammar.py in Phase 3).

parse(text) -> (intent, slots) or None (abstain). It is deliberately
conservative: a wrong fire is worse than an abstain, because an abstain falls
through to the LLM while a wrong fire acts on the wrong intent.
"""

from __future__ import annotations

import re

PROJECTS = ("thesis", "robotics")  # stand-in for profiles.toml

_WAKE = re.compile(r"^\s*(hey|ok|okay)\s+swift[\s,.!]*", re.I)
_FILLER = re.compile(r"\b(um+|uh+|erm)\b[\s,]*", re.I)

NUM = {"fifteen": 15, "twenty": 20, "thirty": 30, "forty five": 45, "forty-five": 45, "sixty": 60}

WHEN = (
    r"(?:next\s+\w+(?:\s+(?:morning|afternoon|evening))?|tomorrow(?:\s+(?:morning|afternoon|evening))?|"
    r"this\s+week|next\s+week|today|tonight|"
    r"(?:on\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(?:morning|afternoon|evening))?"
    r"(?:\s+at\s+\d{1,2}(?::\d\d)?\s*(?:am|pm)?)?)"
)

SCHEDULE = (
    r"(?:every\s+(?:other\s+)?\w+(?:\s+(?:morning|afternoon|evening))?(?:\s+at\s+\w+(?::\d\d)?\s*(?:am|pm)?)?|"
    r"tomorrow(?:\s+at\s+\w+(?::\d\d)?\s*(?:am|pm)?)?|tonight|in\s+\w+\s+(?:minutes?|hours?)|"
    r"at\s+\w+(?::\d\d)?\s*(?:am|pm)?|(?:on\s+)?(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"(?:\s+morning)?)"
)


def normalize(text: str) -> str:
    t = _WAKE.sub("", text)
    t = _FILLER.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t.rstrip(".!?").strip()


def _strip_my(s: str) -> str:
    return re.sub(r"^(my|the)\s+", "", s.strip(), flags=re.I)


def _project(t: str) -> str | None:
    for p in PROJECTS:
        if re.search(rf"\b{p}\b", t, re.I):
            return p
    return None


def _duration(t: str) -> int | None:
    if m := re.search(r"\b(\d{1,3})[\s-]*(?:minute|min)", t, re.I):
        return int(m.group(1))
    if m := re.search(r"\b(\d)\s*hours?\b", t, re.I):
        return int(m.group(1)) * 60
    if re.search(r"\b(half an hour|half hour)\b", t, re.I):
        return 30
    if re.search(r"\b(an|one)\s+hour\b", t, re.I):
        return 60
    for word, n in NUM.items():
        if re.search(rf"\b{word}[\s-]*minutes?\b", t, re.I):
            return n
    return None


def parse(text: str) -> tuple[str, dict] | None:
    t = normalize(text)
    low = t.lower()

    # --- control words (whole utterance only) ---
    controls = {
        "stop": r"stop|stop talking",
        "cancel": r"cancel|cancel that|never ?mind",
        "yes": r"yes|yeah|yep|confirm|do it|go ahead|yeah,? go ahead",
        "no": r"no|nope|no thanks",
        "mute": r"mute",
        "forget": r"forget that",
        "help": r"what can you do",
    }
    for action, pat in controls.items():
        if re.fullmatch(rf"(?:{pat})", low.rstrip(",")):
            return "control", {"action": action}

    # --- time / date ---
    if re.fullmatch(r"(what time is it|what's the time|tell me the time)", low):
        return "get_time", {}
    if re.fullmatch(r"(what's the date( today)?|what's today's date|what day is it|which day of the week is it)", low):
        return "get_date", {}

    # --- reminders ---
    if re.fullmatch(r"(what|list|show( me)?|read out)( all)?( my)? reminders( do i have)?", low):
        return "list_reminders", {}
    if m := re.fullmatch(r"(?:cancel|delete|remove)(?: the| my)? reminder about (.+)", low):
        return "cancel_reminder", {"target": m.group(1)}
    if m := re.fullmatch(r"(?:cancel|delete|remove)(?: the| my)? (.+?) reminder", low):
        return "cancel_reminder", {"target": m.group(1)}
    if m := re.fullmatch(r"stop reminding me to (.+)", low):
        return "cancel_reminder", {"target": m.group(1)}
    if m := re.fullmatch(r"(?:can you )?remind me (.+)", t, re.I):
        rest = m.group(1)
        if m2 := re.fullmatch(rf"({SCHEDULE})?\s*to (.+?)(?:\s+({SCHEDULE}))?", rest, re.I):
            sched = m2.group(1) or m2.group(3)
            return "create_reminder", {"text": m2.group(2).strip(), "schedule": sched.strip() if sched else None}
        return None
    if m := re.fullmatch(r"(every [\w\s:]+?),? remind me to (.+)", t, re.I):
        return "create_reminder", {"text": m.group(2), "schedule": m.group(1)}

    # --- email ---
    if re.fullmatch(
        r"(?:okay,? |ok,? |go ahead and |that looks good,? )?send (?:it|it off|that email|the email|the draft)"
        r"(?: now| to my \w+| i drafted earlier)?",
        low,
    ):
        return "send_draft", {}
    if m := re.fullmatch(r"make (?:it|that|the email|that email|the draft) (.+)", low):
        return "revise_draft", {"instruction": m.group(1)}
    if m := re.fullmatch(
        r"(?:draft|write|compose|start|prepare)(?: an?)? (?:new )?(?:email|message|reply|note)(?: for| to) (.+?)"
        r"(?:,? (?:about|explaining|saying|asking|thanking|re|that) (.+))?",
        t,
        re.I,
    ):
        topic = m.group(2)
        return "draft_email", {"recipient": _strip_my(m.group(1)), "topic": topic}

    # --- dev environment / tests ---
    open_env = re.search(r"\b(open|launch|load up|fire up)\b.*\b(development environment|dev environment|project|ide|vs code)\b", low)
    run_tests = re.search(r"\b(run|kick off)\b.*\btests?\b|\btest suite\b", low)
    if open_env and run_tests:
        return "open_dev_env_and_test", {"project": _project(low)}
    if open_env and re.fullmatch(r"(open|launch) (my|the) (\w+ )?(development environment|project|ide)", low):
        return "open_dev_env", {"project": _project(low)}
    if re.fullmatch(r"run (the |my )?(\w+ )?tests", low):
        return "run_tests", {"project": _project(low)}

    # --- latest document summary ---
    if re.search(r"\b(latest|newest|most recent)\b.*\breport\b", low) and re.search(r"\bsummar|outstanding|issues\b", low):
        return "summarize_latest_document", {"project": _project(low)}

    # --- meetings ---
    if re.search(r"\b(schedule|set up|book|arrange|organi[sz]e|find (?:a |time)|invite)\b", low) and (
        m := re.search(r"\bwith (my \w+(?: \w+)?|[A-Z]\w+(?: [A-Z]\w+)?)", t)
    ):
        attendee = _strip_my(re.split(r"\s+(?:next|on|tomorrow|this|to|for|sometime)\b", m.group(1))[0])
        when = re.search(WHEN, t, re.I)
        return "schedule_meeting", {"attendee": attendee, "duration_min": _duration(t), "when": when.group(0) if when else None}

    return None
