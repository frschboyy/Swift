"""User-facing failures (ADR-009): classification, the error message, and "Try again"."""

from __future__ import annotations

from settling import settled

import asyncio
from typing import Any

import pytest
from test_session import Recorder, make, run_demo

from swift.executors.base import ExecResult
from swift.executors.claude_code import ClaudeCodeExecutor
from swift.executors.claude_mapping import outcome_for, steps_for
from swift.executors.echo import EchoExecutor
from swift.executors.mock import MockExecutor
from swift.failures import classify
from swift.ipc.protocol import Message, decode
from swift.session import Session


@pytest.mark.parametrize(
    ("raw", "code", "retry"),
    [
        ("Invalid API key · Please run /login", "auth", True),
        ("API Error: 401 {\"type\":\"authentication_error\"}", "auth", True),
        ("Credit balance is too low", "billing", False),
        ("API Error: 429 rate_limit_error: Number of requests has exceeded your rate limit", "rate_limited", True),
        ("Claude AI usage limit reached|1761300000", "rate_limited", True),
        ("API Error: 529 {\"type\":\"overloaded_error\",\"message\":\"Overloaded\"}", "overloaded", True),
        ("API Error: 400 prompt is too long: 210000 tokens > 200000 maximum", "too_large", False),
        ("CLIConnectionError: getaddrinfo ENOTFOUND api.anthropic.com", "offline", True),
        ("Unable to connect to API due to poor internet connection", "offline", True),
        ("TimeoutError: Request timed out", "timeout", True),
        ("API Error: 500 Internal server error", "service", True),
        ("ProcessError: Command failed with exit code 1", "crashed", True),
    ],
)
def test_known_failures_are_classified(raw: str, code: str, retry: bool) -> None:
    failure = classify(raw, "Claude Code", signin_hint="Run claude.")
    assert failure.code == code and failure.retry is retry
    # The raw text is never the headline, only the detail.
    assert failure.detail and raw[:20] in failure.detail
    assert raw[:20] not in failure.title + failure.message
    assert "Claude Code" in failure.title + failure.message or code in ("billing", "too_large", "rate_limited")
    if code == "auth":
        assert failure.hint == "Run claude."


def test_unknown_failures_keep_the_providers_words_and_hint() -> None:
    failure = classify("I couldn't find a file called notes.md.", "Claude Code", fallback_hint="Check it.")
    assert failure.code == "executor_failed" and failure.title == "Claude Code ran into a problem"
    assert failure.message == "I couldn't find a file called notes.md." and failure.hint == "Check it."
    assert failure.detail is None


def test_long_details_are_clipped_to_one_line() -> None:
    failure = classify("API Error: 529 overloaded\n" + "x" * 1000, "Claude Code")
    assert failure.detail is not None and "\n" not in failure.detail and len(failure.detail) <= 240


def test_claude_results_and_retries_are_readable() -> None:
    outcome = outcome_for({"type": "result", "subtype": "success", "is_error": True, "result": "API Error: 529 Overloaded"})
    assert outcome is not None and outcome.failure is not None and outcome.failure.code == "overloaded"
    budget = outcome_for({"type": "result", "subtype": "error_max_budget_usd", "is_error": True})
    assert budget is not None and budget.failure is not None and budget.failure.code == "budget"
    [step] = steps_for({"type": "system", "subtype": "api_retry", "error": "rate_limit"})
    assert step.text == "Hit a usage limit, retrying…" and step.activity == "waiting"
    [step] = steps_for({"type": "system", "subtype": "api_retry", "error": "something_new"})
    assert step.text == "Connection hiccup, retrying…"


def test_claude_crash_without_a_result_is_classified() -> None:
    run = type("Run", (), {"models": [], "escalations": [], "cancelled": False, "stopped_by": None})()
    result = ClaudeCodeExecutor._final(run, None, ConnectionError("Connection reset by peer"))  # type: ignore[arg-type]
    assert result.failure is not None and result.failure.code == "offline"
    result = ClaudeCodeExecutor._final(run, None, RuntimeError("something odd"))  # type: ignore[arg-type]
    assert result.failure is not None and result.failure.code == "crashed"
    assert result.failure.detail == "RuntimeError: something odd"


def test_retry_is_a_valid_inbound_message() -> None:
    assert decode('{"v":1,"type":"retry","data":{}}').type == "retry"


async def test_error_card_carries_title_detail_and_retry() -> None:
    session, rec, _ = make()
    await run_demo(session, "error")
    err = rec.last("error")
    assert err["code"] == "crashed" and err["title"] == "Demo agent stopped unexpectedly"
    assert err["severity"] == "error" and err["retry"] is True
    assert "exited with code 1" in err["detail"]


async def test_try_again_reruns_the_failed_request() -> None:
    session, rec, _ = make()
    await run_demo(session, "error")
    before = len([m for m in rec.messages if m.type == "error"])
    await session.handle(Message("retry", {}))
    assert session._task is not None
    await settled(session)
    assert len([m for m in rec.messages if m.type == "error"]) == before + 1
    # The retry failed again (scripted), so it can be retried again.
    assert session._retry is not None


class FailsOnce(EchoExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    async def start(self, request: str, **kw: Any) -> str:
        self.calls.append(request)
        return await super().start(request, **kw)

    async def result(self, run_id: str) -> ExecResult:
        if len(self.calls) == 1:
            return ExecResult("error", "API Error: 529 Overloaded")
        return await super().result(run_id)


async def test_try_again_sends_the_same_transcript_without_speaking() -> None:
    rec = Recorder()
    executor = FailsOnce()
    session = Session(rec, executor, debug_executor=MockExecutor(speed=0), router=None)
    await session.handle(Message("debug.ask", {"text": "Summarize the README."}))
    await settled(session)
    err = rec.last("error")
    assert err["code"] == "overloaded" and err["retry"] is True and err["title"] == "Swift is busy right now"
    await session.handle(Message("retry", {}))
    await settled(session)
    assert executor.calls == ["Summarize the README.", "Summarize the README."]
    assert rec.states()[-1] == "result"


async def test_no_retry_without_a_request_to_repeat() -> None:
    session, rec, _ = make()
    await session.handle(Message("retry", {}))
    assert session._task is None and not rec.messages


# ---- "Couldn't confirm model" (owner checks, 2026-10-27) ------------------------------------------

UNCONFIRMED = 'Couldn\'t confirm model "claude-haiku-5-5" with the API. Try again, or run /model to see available models.'


def test_an_unconfirmed_model_reads_plainly() -> None:
    from swift.failures import classify

    failure = classify(f"Exception: {UNCONFIRMED}", "Claude Code")
    assert failure.code == "models" and failure.retry
    assert failure.message == "Claude Code couldn't reach its models; check your connection or sign-in."
    assert "/model" not in failure.message + failure.hint + failure.title  # the CLI's advice isn't Swift's


class ModelClient:
    """Stands in for ClaudeSDKClient: Swift's model can't be confirmed; the default works (or not)."""

    made: list[ModelClient] = []
    default_works = True
    fail_on = "set_model"

    def __init__(self, options: object) -> None:
        self.models: list[str | None] = []
        self.prompts: list[str] = []
        ModelClient.made.append(self)

    async def connect(self) -> None: ...

    async def set_model(self, model: str | None) -> None:
        self.models.append(model)
        if model is not None and ModelClient.fail_on == "set_model":
            raise Exception(UNCONFIRMED)  # noqa: TRY002 - what the SDK raises

    async def query(self, prompt: str) -> None:
        self.prompts.append(prompt)

    async def receive_response(self):  # type: ignore[no-untyped-def]
        from test_claude_executor import sdk_messages

        if self.models[-1] is not None and ModelClient.fail_on == "query":
            raise Exception(UNCONFIRMED)  # noqa: TRY002
        if self.models[-1] is None and not ModelClient.default_works:
            raise Exception(UNCONFIRMED.replace("haiku", "default"))  # noqa: TRY002
        for message in sdk_messages("claude_read_only.jsonl"):
            yield message

    async def disconnect(self) -> None: ...


@pytest.mark.parametrize("fail_on", ["set_model", "query"])
async def test_an_unconfirmed_model_is_retried_once_with_the_default(tmp_path, fail_on: str) -> None:  # type: ignore[no-untyped-def]
    from swift.executors.claude_code import ClaudeCodeExecutor

    ModelClient.made, ModelClient.default_works, ModelClient.fail_on = [], True, fail_on
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", prewarm=False, client_factory=ModelClient)
    run_id = await ex.start("Summarise the README", demand="light")
    result = await asyncio.wait_for(ex.result(run_id), 5)
    client = ModelClient.made[0]
    assert result.status == "done"
    assert client.models == [ex.models["light"], None]  # Swift's model, then the CLI's default; ids unchanged
    assert result.meta["models"][-1] == "default"


async def test_when_the_default_fails_too_the_card_says_so_plainly(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from swift.executors.claude_code import ClaudeCodeExecutor

    ModelClient.made, ModelClient.default_works, ModelClient.fail_on = [], False, "set_model"
    ex = ClaudeCodeExecutor(cwd=str(tmp_path), claude="claude.exe", prewarm=False, client_factory=ModelClient)
    run_id = await ex.start("Summarise the README", demand="light")
    result = await asyncio.wait_for(ex.result(run_id), 5)
    assert result.status == "error" and result.failure is not None
    assert result.failure.code == "models"
    assert result.failure.message == "Claude Code couldn't reach its models; check your connection or sign-in."
    assert ModelClient.made[0].models == [ex.models["light"], None]  # tried once more, not again and again
