"""Turning failures into something the owner can act on (ADR-009).

A provider fails in its own words: an SDK exception, an HTTP status buried in a
CLI message, "API Error: 529 Overloaded". The owner should read what happened in
plain language, what to do about it, and whether trying again could help. The
raw text is kept as ``detail``: logged, and shown on the card only on request.

``classify()`` knows failure *kinds*, not providers: titles use the provider's
display name, so a new provider gets readable errors without changes here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Severity = Literal["error", "info"]

DETAIL_MAX = 240


@dataclass(frozen=True)
class Failure:
    code: str
    # Card heading: what happened, in a few words.
    title: str
    # One sentence: what it means for the owner.
    message: str
    # What to do next.
    hint: str
    # True when trying the same request again could work (the overlay offers "Try again").
    retry: bool = False
    # The original text, for the card's "Details" and the log. Never the headline.
    detail: str | None = None
    # "info": nothing broke, the owner just needs a nudge (no speech, a too-short press).
    severity: Severity = "error"

    def as_message(self) -> dict[str, object]:
        """The ``error`` message fields (``ipc.protocol``), without ``agent``."""
        return {
            "code": self.code,
            "title": self.title,
            "message": self.message,
            "hint": self.hint,
            "retry": self.retry,
            "detail": self.detail,
            "severity": self.severity,
        }


# (code, pattern, title, message, hint, retry). First match wins, so specific kinds
# come before broad ones ("401" before "API error"). {name} is the provider's name;
# {signin} and {fallback} are its own hints, since only it knows how to fix those.
_KINDS: tuple[tuple[str, str, str, str, str, bool], ...] = (
    (
        "auth",
        r"invalid api key|not (logged|signed) in|/login|log ?in again|authenticat|unauthori[sz]ed|\b401\b|"
        r"\b403\b|forbidden|oauth token|token (has )?expired",
        "{name} isn't signed in",
        "{name} needs you to sign in before it can work on requests.",
        "{signin}",
        True,
    ),
    (
        "billing",
        r"credit balance|insufficient (credit|funds)|billing|payment required|\b402\b",
        "Out of credit",
        "The account {name} uses has run out of credit.",
        "Add credit or check the plan in your account settings, then try again.",
        False,
    ),
    (
        "rate_limited",
        r"rate[ _-]?limit|usage limit|\b429\b|too many requests|quota|limit (reached|exceeded)",
        "Usage limit reached",
        "{name} has hit its usage limit for now.",
        "Wait a few minutes and try again. If it keeps happening, check your plan's limits.",
        True,
    ),
    (
        "overloaded",
        r"overloaded|\b529\b|over capacity|at capacity",
        "{name} is busy right now",
        "The service behind {name} is overloaded.",
        "This usually clears within a minute. Try again shortly.",
        True,
    ),
    (
        "too_large",
        r"prompt is too long|context (length|window)|too many tokens|request too large|\b413\b",
        "That request was too large",
        "{name} couldn't fit everything it needed into one request.",
        "Try asking for something narrower, or say “new topic” to drop the previous context.",
        False,
    ),
    (
        "offline",
        r"getaddrinfo|enotfound|econnrefused|econnreset|enetunreach|ehostunreach|network|internet|"
        r"connection (error|refused|reset|aborted|closed)|connecterror|unable to connect|could not connect|"
        r"failed to connect|fetch failed|socket hang up|offline|name resolution|\bdns\b",
        "Can't reach {name}",
        "Swift couldn't connect to the service behind {name}.",
        "Check your internet connection, then try again.",
        True,
    ),
    (
        "timeout",
        r"timed? ?out|timeout|deadline exceeded",
        "{name} took too long",
        "{name} didn't respond in time.",
        "Try again. If your connection is slow, a shorter request may help.",
        True,
    ),
    (
        "service",
        r"\b50[0-4]\b|internal server error|service unavailable|bad gateway|api error|server error",
        "{name} had a service problem",
        "The service behind {name} returned an error. This is usually temporary.",
        "Try again in a moment.",
        True,
    ),
    (
        "crashed",
        r"exit(ed)? (with )?(code|status)|exit code|process (error|exited|terminated)|stopped without an answer|"
        r"cliconnection|broken pipe|terminated unexpectedly|crash",
        "{name} stopped unexpectedly",
        "{name} quit before it finished your request.",
        "{fallback}",
        True,
    ),
)

_COMPILED = tuple((code, re.compile(pattern, re.I), *rest) for code, pattern, *rest in _KINDS)


def clean_detail(text: str) -> str | None:
    """The raw failure text, one line and short enough for a card."""
    text = " ".join(text.split())
    if not text:
        return None
    return text if len(text) <= DETAIL_MAX else text[: DETAIL_MAX - 1].rstrip() + "…"


DEFAULT_HINT = "Try again. If it keeps happening, open the logs from Swift's tray menu."


def classify(text: str, name: str, *, fallback_hint: str = DEFAULT_HINT, signin_hint: str = "") -> Failure:
    """A ``Failure`` for raw failure ``text`` from the provider called ``name``.

    Unknown text keeps the provider's own words as the message (it may be a sentence
    the provider wrote for people), with ``fallback_hint`` as the hint.
    """
    signin = signin_hint or f"Sign in to {name} again, then try again."
    detail = clean_detail(text)
    for code, pattern, title, message, hint, retry in _COMPILED:
        if detail and pattern.search(detail):
            hint = hint.format(signin=signin, fallback=fallback_hint)
            return Failure(
                code, title.format(name=name), message.format(name=name), hint, retry=retry, detail=detail
            )
    return Failure(
        "executor_failed",
        f"{name} ran into a problem",
        detail or f"{name} couldn't finish the request.",
        fallback_hint,
        retry=True,
        # Already the message: no separate details.
        detail=None,
    )


__all__ = ["Failure", "Severity", "classify", "clean_detail"]
