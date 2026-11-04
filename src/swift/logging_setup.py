"""Logging with a mandatory redaction filter (§3, §11).

Every record passes through ``_patch`` before any sink sees it:
- secrets (bearer/basic credentials, Google tokens and client secrets, API
  keys, JWTs, ``key=value`` secrets) are masked in the message, in ``extra``
  values and in exception tracebacks;
- content fields in ``extra`` (transcripts, bodies, file contents, prompts)
  are replaced by their length, unless ``log_content`` is on *and* the record
  is DEBUG or lower.

Convention: pass user content via ``logger.bind(transcript=...)`` /
``extra``, never interpolated into the message text. Regex redaction is a
safety net for secrets, not a substitute for that convention.
"""

from __future__ import annotations

import re
import sys
import traceback
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from loguru import Record

    from swift.config.paths import AppPaths

REDACTED = "[REDACTED]"

CONTENT_KEYS: frozenset[str] = frozenset(
    {
        "transcript", "body", "content", "text", "file_content", "email_body", "prompt", "completion", "subject",
        # The interaction record's own word fields: what was heard as a reply, the words the
        # speech model was unsure of, and Swift's question left unanswered (ADR-016 §16).
        "transcript_heard", "unclear", "asked_unanswered",
    }
)

_SECRET_KEY_NAME = (
    r"[A-Za-z0-9_\-]*?"
    r"(?:api[_\-]?key|secret|token|passw(?:or)?d|pwd|auth|credentials?|private[_\-]?key|session[_\-]?id|cookie)"
)

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Authorization: Bearer xxx / Basic xxx
    (re.compile(r"(?i)\b(bearer|basic)(\s+)[A-Za-z0-9\-._~+/]+=*"), r"\1\2" + REDACTED),
    # Google OAuth access tokens, refresh tokens, client secrets, API keys
    (re.compile(r"ya29\.[0-9A-Za-z\-_.]+"), REDACTED),
    (re.compile(r"1//[0-9A-Za-z\-_]{10,}"), REDACTED),
    (re.compile(r"GOCSPX-[0-9A-Za-z\-_]+"), REDACTED),
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), REDACTED),
    # JSON Web Tokens
    (re.compile(r"eyJ[0-9A-Za-z\-_]+\.[0-9A-Za-z\-_]+\.[0-9A-Za-z\-_]*"), REDACTED),
    # key=value / "key": "value" / ?key=value forms
    (
        re.compile(
            r"(?i)(\b" + _SECRET_KEY_NAME + r"[\"']?\s*[:=]\s*)"
            r"(?!\[REDACTED\])(?:\"[^\"]*\"|'[^']*'|[^\s\"',;&}\]]+)"
        ),
        r"\1" + REDACTED,
    ),
]


def redact(text: str) -> str:
    """Mask secrets in ``text``. Idempotent."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_redact_value(v) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact(repr(value))


def make_patcher(log_content: bool) -> Callable[[Record], None]:
    debug_no = logger.level("DEBUG").no

    def _patch(record: Record) -> None:
        record["message"] = redact(record["message"])

        keep_content = log_content and record["level"].no <= debug_no
        extra = record["extra"]
        rendered: list[str] = []
        for key in list(extra):
            if key.startswith("_"):
                continue
            value = extra[key]
            if key in CONTENT_KEYS and not keep_content:
                extra[key] = f"[REDACTED:{len(str(value))} chars]"
            else:
                extra[key] = _redact_value(value)
            rendered.append(f"{key}={extra[key]!r}")
        extra["_extra"] = (" | " + " ".join(rendered)) if rendered else ""

        exc = record["exception"]
        if exc is not None:
            tb = "".join(traceback.format_exception(exc.type, exc.value, exc.traceback))
            extra["_exc"] = "\n" + redact(tb).rstrip("\n")
            record["exception"] = None
        else:
            extra["_exc"] = ""

    return _patch


LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | "
    "{message}{extra[_extra]}{extra[_exc]}\n"
)


def setup_logging(
    paths: AppPaths,
    level: str = "INFO",
    *,
    log_content: bool = False,
    rotation_mb: int = 10,
    retention_files: int = 5,
    console: bool = False,
) -> None:
    """Configure loguru. Safe to call again; replaces all existing sinks."""
    logger.remove()
    logger.configure(patcher=make_patcher(log_content), extra={"_extra": "", "_exc": ""})

    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    common: dict[str, Any] = {
        "level": level,
        "format": LOG_FORMAT,
        # Never render local variables or extended tracebacks: they would
        # bypass redaction (tracebacks are formatted by the patcher instead).
        "backtrace": False,
        "diagnose": False,
        "colorize": False,
    }
    logger.add(
        paths.logs_dir / "swift.log",
        rotation=f"{rotation_mb} MB",
        retention=retention_files,
        encoding="utf-8",
        **common,
    )
    # pythonw has no stderr.
    if console and sys.stderr is not None:
        logger.add(sys.stderr, **common)
