"""Build the parity set (ADR-016 §9.1): Siri-class requests, translated to a Windows PC.

Usage:  uv run python eval/parity/build.py      # writes eval/parity/parity.jsonl

Each base request is written once with the lane it *should* take once the gap is closed
(``ideal``), then expanded with the ways people actually start a request ("hey Swift", "can
you", "please" and so on), so the set measures phrasing tolerance as well as coverage.

Lanes: ``system`` (Swift does it on the PC), ``fast`` (Swift answers: time, dates, maths),
``light`` (one quick model answer), ``web`` (a current answer from the web: Phase I, not
built), ``agent`` (Claude Code with tools: email, calendar, files, research), ``control``.
``excluded`` rows are Siri features that do not carry over to a PC (ADR-016 §1.3); they are
kept, with the reason, so the exclusion is a decision and not an omission.

``must_not`` marks a request that would be *harmful* in a lane ("shut down the computer" must
never be done without a confirmation, "search the codebase" is not a web search): the scorer
counts those as failures however the rest scores.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent

# (category, ideal lane, [phrasings], extra fields)
BASE: list[tuple[str, str, list[str], dict]] = [
    # ---- timers, alarms, reminders ------------------------------------------------------
    ("timer", "system", ["set a timer for 10 minutes", "set a 5 minute timer for the pasta", "timer for an hour and a half",
                         "start a timer for 30 seconds", "set a timer for twenty minutes"], {}),
    ("timer", "system", ["how long is left on the timer", "how much time is left on my timer", "what timers do I have"], {}),
    ("timer", "system", ["cancel the timer", "cancel all my timers", "stop the pasta timer"], {}),
    ("alarm", "system", ["wake me up at seven", "set an alarm for 6:30 am", "set an alarm for seven thirty tomorrow",
                         "wake me at half past six"], {}),
    ("reminder", "system", ["remind me to call Sam at five", "remind me in 20 minutes to take the pizza out",
                            "remind me to call mum tomorrow at 9 am", "set a reminder to stretch in an hour",
                            "remind me to leave for the station at 5 pm"], {}),
    ("reminder", "agent", ["remind me to call Sam", "remind me every weekday at 9 to check the lab bookings"],
     {"note": "no time / repeating: the agent asks or sets it up (the dialogue phase will ask itself)"}),
    # ---- sound and media ----------------------------------------------------------------
    ("volume", "system", ["volume up", "turn the volume down a bit", "set the volume to 30 percent", "louder",
                          "make it quieter", "what's the volume", "mute the sound", "unmute"], {}),
    ("media", "system", ["pause the music", "play the music", "next song", "skip this song", "previous track",
                         "stop the music"], {}),
    ("media", "agent", ["play some jazz", "play Taylor Swift on Spotify"],
     {"note": "choosing what to play needs a music connector (Phase E)"}),
    # ---- display and device -------------------------------------------------------------
    ("theme", "system", ["turn on dark mode", "switch to light mode", "turn off dark mode"], {}),
    ("brightness", "system", ["set brightness to 40", "turn the brightness down", "dim the screen",
                              "make the screen brighter"], {}),
    ("radio", "system", ["turn off wifi", "turn on bluetooth", "is my wifi on", "turn on airplane mode",
                         "bluetooth off"], {}),
    ("focus", "system", ["turn on do not disturb", "focus mode on"], {}),
    ("lock", "system", ["lock the computer", "lock my pc"], {}),
    ("power", "agent", ["shut down the computer", "restart my pc", "put the computer to sleep"],
     {"must_not": "system", "note": "power actions need a confirmation: the agent's card for now"}),
    ("info", "system", ["what's my battery", "how much space do I have left", "how much ram am I using",
                        "what's my cpu usage", "how long has my computer been on"], {}),
    ("settings", "system", ["open bluetooth settings", "open the wi-fi settings", "open display settings",
                            "open settings"], {}),
    ("window", "system", ["minimize this window", "show the desktop", "snap this window to the left",
                          "maximize the window"], {}),
    ("screenshot", "system", ["take a screenshot"], {}),
    ("search", "system", ["search the web for pasta recipes", "google best laptops 2026"], {}),
    ("search", "agent", ["search the codebase for every place we call transcribe", "search my email for the invoice"],
     {"must_not": "system", "note": "not a web search"}),
    # ---- quick answers ------------------------------------------------------------------
    ("time", "fast", ["what time is it", "what time is it in Tokyo", "what's the date", "what day is it tomorrow",
                      "how many days until Christmas"], {}),
    ("maths", "fast", ["what's 15 percent of 80", "12 times 7", "convert 5 km to miles", "what's 30 celsius in fahrenheit",
                       "square root of 144"], {}),
    ("language", "light", ["what's a synonym for happy", "how do you say thank you in French", "what does ubiquitous mean"], {}),
    ("facts", "light", ["who wrote Middlemarch", "what's the capital of Peru", "how tall is Mount Everest"], {}),
    # ---- current information (Phase I web lane: not built) -------------------------------
    ("web", "web", ["what's the weather today", "will it rain tomorrow", "who won the football last night",
                    "what's the latest news", "is the pharmacy open now"],
     {"note": "Phase I: web answers lane; today the agent answers in 7-18 s"}),
    # ---- the owner's own things (agent with tools) --------------------------------------
    ("email", "agent", ["email Ada saying I'll be late", "read my latest email", "reply to the last email from Sam"], {}),
    ("calendar", "agent", ["what's on my calendar tomorrow", "add a meeting with Sam on Friday at 3",
                           "move my 2 pm meeting to 4"], {}),
    ("personal", "agent", ["find the hotel confirmation number in my email", "when is my flight"],
     {"note": "Phase I personal index would make these instant"}),
    ("writing", "agent", ["rewrite this more formally", "write a haiku about tea here"], {}),
    ("files", "agent", ["tidy my downloads folder", "how big is my downloads folder"], {}),
    # ---- control --------------------------------------------------------------------------
    ("control", "control", ["stop", "never mind", "repeat that"], {}),
    # ---- not on a PC (ADR-016 §1.3) ---------------------------------------------------------
    ("excluded", "excluded", ["call mum", "text Sam that I'm on my way", "take a photo", "how many steps did I take today",
                              "pay Sam 20 dollars", "navigate home"],
     {"note": "phone, camera, health, wallet and car features don't carry over to a PC"}),
]

PREFIXES = ["", "hey swift ", "can you ", "please "]
# Not every request reads naturally with every prefix ("can you what time is it").
QUESTION_STARTS = ("what", "how", "who", "is ", "when", "will", "do ", "does", "why", "which")


def variants(text: str) -> list[str]:
    out = []
    for prefix in PREFIXES:
        if prefix in ("can you ", "please ") and text.startswith(QUESTION_STARTS):
            continue
        if prefix == "can you " and (text[0].isdigit() or text.startswith("square")):
            continue  # "can you 12 times 7" isn't how anyone asks
        if prefix == "can you " and text in ("stop", "never mind", "repeat that", "louder", "unmute"):
            continue
        out.append((prefix + text).strip())
    return out


def build() -> list[dict]:
    rows = []
    for category, ideal, phrasings, extra in BASE:
        for base in phrasings:
            for n, text in enumerate(variants(base)):
                row = {"id": f"{category}-{len(rows):03d}", "text": text, "category": category, "ideal": ideal,
                       "base": base, "variant": n}
                row.update(extra)
                rows.append(row)
    return rows


if __name__ == "__main__":
    rows = build()
    (HERE / "parity.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"wrote {len(rows)} rows to {HERE / 'parity.jsonl'}")
