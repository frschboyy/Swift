"""T0-03 (P0-3): the redaction filter masks secrets and content in every sink."""

from __future__ import annotations

import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from loguru import logger

from swift.config.paths import AppPaths
from swift.logging_setup import REDACTED, redact, setup_logging

TOKEN_CHARS = string.ascii_letters + string.digits + "-_"

# --- fixed fixtures ----------------------------------------------------------

SECRETS = {
    "bearer": ("Authorization: Bearer abcDEF123.xyz-_~+/==", "abcDEF123"),
    "basic": ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA"),
    "access": ("token is ya29.a0AfH6SMBx-very_long.token", "a0AfH6SMBx"),
    "refresh": ("refresh 1//0gAbCdEfGhIjKlMnOpQrStUv", "0gAbCdEfGhIjKlMnOp"),
    "client_secret": ("GOCSPX-AbCdEf123456_-xyz in config", "AbCdEf123456"),
    "api_key": ("key AIzaSyA1234567890abcdefghijklmnopqrstuv end", "SyA1234567890"),
    "jwt": ("id eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig_nature-x", "eyJzdWIiOiIxIn0"),
    "json": ('{"refresh_token": "opaque-value-123", "x": 1}', "opaque-value-123"),
    "query": ("GET /cb?code=1&access_token=abc123secret&state=2", "abc123secret"),
    "password": ("password = hunter2", "hunter2"),
    "quoted_spaces": ("client_secret='two words here'", "two words here"),
    "api_key_kv": ("API_KEY: sk-live-999", "sk-live-999"),
}


@pytest.mark.parametrize("name", list(SECRETS))
def test_fixture_secrets_removed(name: str) -> None:
    text, secret = SECRETS[name]
    out = redact(text)
    assert secret not in out, out
    assert REDACTED in out


@pytest.mark.parametrize(
    "text",
    [
        "author=Jane Doe",
        "max_tokens=512 num_tokens: 3",
        "Opened C:/Users/me/Documents/report.pdf",
        "Send email 'Weekly update' to dean.smith@uni.edu",
        "wake score=0.83 threshold=0.5",
    ],
)
def test_benign_text_unchanged(text: str) -> None:
    assert redact(text) == text


def test_redact_is_idempotent() -> None:
    for text, _ in SECRETS.values():
        once = redact(text)
        assert redact(once) == once


# --- property tests ----------------------------------------------------------

token_body = st.text(alphabet=TOKEN_CHARS, min_size=12, max_size=60)
# Padding has no token characters, so it can never contain the secret itself.
padding = st.text(alphabet=st.characters(exclude_characters=TOKEN_CHARS), max_size=40)


@st.composite
def embedded_secret(draw: st.DrawFn) -> tuple[str, str]:
    body = draw(token_body)
    kind = draw(st.sampled_from(["ya29", "refresh", "gocspx", "bearer", "kv", "json"]))
    secret, rendered = {
        "ya29": (f"ya29.{body}", f"ya29.{body}"),
        "refresh": (f"1//{body}", f"1//{body}"),
        "gocspx": (f"GOCSPX-{body}", f"GOCSPX-{body}"),
        "bearer": (body, f"Bearer {body}"),
        "kv": (body, f"refresh_token={body}"),
        "json": (body, f'"client_secret": "{body}"'),
    }[kind]
    return secret, f"{draw(padding)} {rendered} {draw(padding)}"


@settings(max_examples=1000, deadline=None)
@given(embedded_secret())
def test_embedded_secret_never_survives(case: tuple[str, str]) -> None:
    secret, text = case
    assert secret not in redact(text)


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=200))
def test_redact_total_and_idempotent(text: str) -> None:
    once = redact(text)
    assert redact(once) == once


# --- through the real sinks --------------------------------------------------


def _read_log(paths: AppPaths) -> str:
    logger.complete()
    return (paths.logs_dir / "swift.log").read_text(encoding="utf-8")


@pytest.fixture
def logs(paths: AppPaths):
    setup_logging(paths, "DEBUG")
    yield paths
    logger.remove()


def test_message_redacted_in_file(logs: AppPaths) -> None:
    logger.info("got token ya29.SECRETVALUE123456")
    assert "SECRETVALUE" not in _read_log(logs)


def test_content_extra_replaced_by_length(logs: AppPaths) -> None:
    logger.bind(transcript="draft an email to my dean", body="Dear Dean").info("heard command")
    log = _read_log(logs)
    assert "draft an email" not in log and "Dear Dean" not in log
    assert "[REDACTED:25 chars]" in log


def test_interaction_record_words_redacted(logs: AppPaths) -> None:
    # Fields of the interaction record that hold the owner's or Swift's words (found in the
    # owner's swift.log on 2026-11-04): only their length reaches the file.
    logger.bind(
        transcript_heard="Yes, Friday works",
        unclear=["TestMe"],
        asked_unanswered='Did you mean "Test Me" as the contact\'s name?',
        status="done",
    ).info("interaction finished")
    log = _read_log(logs)
    assert "Friday works" not in log and "TestMe" not in log and "Test Me" not in log
    assert "status='done'" in log


def test_non_content_extra_secrets_redacted(logs: AppPaths) -> None:
    logger.bind(headers={"Authorization": "Bearer abcdefSECRET"}).info("request")
    log = _read_log(logs)
    assert "abcdefSECRET" not in log
    assert "request" in log


def test_exception_traceback_redacted(logs: AppPaths) -> None:
    try:
        raise ValueError("bad refresh 1//0gTOPSECRETREFRESHTOKEN")
    except ValueError:
        logger.exception("google auth failed")
    log = _read_log(logs)
    assert "TOPSECRET" not in log
    assert "ValueError" in log and "google auth failed" in log


def test_an_exception_s_message_stays_out_of_a_traceback(logs: AppPaths) -> None:
    path, words = "C:/Users/owner/visa interview notes.docx", "while writing about the visa interview"

    def opens_the_file() -> None:  # a traceback prints these source lines, so they name the variables only
        raise OSError(path)

    try:
        try:
            opens_the_file()
        except OSError as inner:
            raise RuntimeError(words) from inner
    except RuntimeError:
        logger.exception("interaction failed")
    log = _read_log(logs)
    assert "visa interview" not in log
    assert "opens_the_file" in log and "OSError" in log and "RuntimeError" in log and "interaction failed" in log


def test_log_content_only_at_debug(paths: AppPaths) -> None:
    setup_logging(paths, "DEBUG", log_content=True)
    try:
        logger.bind(transcript="visible at debug").debug("d")
        logger.bind(transcript="hidden at info").info("i")
        log = _read_log(paths)
    finally:
        logger.remove()
    assert "visible at debug" in log
    assert "hidden at info" not in log
