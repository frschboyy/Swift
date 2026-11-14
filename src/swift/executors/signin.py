"""Signing in again as one of Swift's own runs (2026-11-04; ``swift.signin``).

Started when a check finds a sign-in Google or Claude Code no longer accepts. One confirm card
per sign-in; approving opens the provider's own page (Google's consent page in the browser, or
a window running ``claude auth login``) and the owner signs in there. Swift never sees or types
a password. Rejected or unanswered: nothing happens, and the next check asks again.
"""

from __future__ import annotations

import asyncio
import itertools
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable

from loguru import logger

from swift.connectors.base import ConnectorError
from swift.executors.base import SWIFT, ExecEvent, ExecResult, UnknownRun, WorkerTask
from swift.signin import Service, Status

REQUEST = "Sign in again"
# How long a card waits, and how long Swift waits for the owner to finish on the provider's page.
ANSWER_S = 300.0
SIGNIN_S = 300.0

CARDS: dict[Service, tuple[str, str]] = {
    "google": (
        "Sign in to Google again?",
        "Google ended Swift's sign-in, so calendar and email requests can't work until you sign in.\n\n"
        "Approve opens Google in your browser: choose your account and allow Swift. "
        "Reject: I'll ask again next time I check.",
    ),
    "claude": (
        "Sign in to Claude again?",
        "Swift's agent needs you to sign in again (your sign-in has ended or ends soon), "
        "so research, writing and other bigger requests can't run until you do.\n\n"
        "Approve opens a window that opens Claude's sign-in page in your browser. "
        "Reject: I'll ask again next time I check.",
    ),
}
NAMES: dict[Service, str] = {"google": "Google", "claude": "Claude"}


class SigninExecutor:
    name = "signin"
    provider = SWIFT

    def __init__(
        self,
        *,
        google_signin: Callable[[float], object] | None,
        claude: Callable[[], str | None],
        claude_check: Callable[[], Status],
        open_claude: Callable[[str], subprocess.Popen[bytes]],
        on_claude_back: Callable[[], Awaitable[None]] | None = None,
        answer_s: float = ANSWER_S,
        signin_s: float = SIGNIN_S,
    ) -> None:
        self.google_signin = google_signin
        self.claude = claude
        self.claude_check = claude_check
        self.open_claude = open_claude
        self.on_claude_back = on_claude_back
        self.answer_s = answer_s
        self.signin_s = signin_s
        self._ids = itertools.count(1)
        self._results: dict[str, ExecResult | None] = {}
        self._answers: dict[str, asyncio.Future[bool]] = {}
        self._wanted: set[Service] = set()

    @property
    def running(self) -> bool:
        return any(result is None for result in self._results.values())

    def want(self, services: set[Service]) -> bool:
        """Sign-ins to offer. False when a run is already offering them (nothing new to start)."""
        new = services - self._wanted
        self._wanted |= services
        return bool(new) and not self.running

    async def start(self, task: WorkerTask) -> str:
        run_id = f"signin-{next(self._ids)}"
        self._results[run_id] = None
        return run_id

    async def events(self, run_id: str) -> AsyncIterator[ExecEvent]:
        self._get(run_id)
        lines: list[str] = []
        try:
            for service in sorted(self._wanted):
                request_id = f"{run_id}:{service}"
                future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
                self._answers[request_id] = future
                title, detail = CARDS[service]
                yield ExecEvent("confirm", title, request_id=request_id, detail=detail, tool="sign_in")
                try:
                    approve = await asyncio.wait_for(future, self.answer_s)
                except TimeoutError:
                    approve = None
                finally:
                    self._answers.pop(request_id, None)
                if not approve:
                    lines.append(f"{NAMES[service]}: not signed in; I'll ask again next time I check.")
                    logger.info("sign-in offered", service=service, answer="no" if approve is False else "none")
                    continue
                yield ExecEvent("step", f"Waiting for you to sign in to {NAMES[service]} in your browser",
                                activity="waiting")
                ok = await (self._google() if service == "google" else self._claude())
                logger.info("sign-in offered", service=service, answer="yes", signed_in=ok)
                lines.append(f"{NAMES[service]}: signed in again." if ok
                             else f"{NAMES[service]}: the sign-in didn't finish; I'll ask again next time I check.")
        finally:
            self._wanted.clear()
        self._results[run_id] = ExecResult("done", " ".join(lines) or "Nothing to sign in to.")

    async def _google(self) -> bool:
        if self.google_signin is None:
            return False
        try:
            await asyncio.to_thread(self.google_signin, self.signin_s)
        except (ConnectorError, OSError, ValueError):
            return False
        except Exception:  # noqa: BLE001 - Google's flow failing must end in a line on the card
            logger.exception("google sign-in failed")
            return False
        return True

    async def _claude(self) -> bool:
        path = self.claude()
        if not path:
            return False
        try:
            proc = await asyncio.to_thread(self.open_claude, path)
            await asyncio.to_thread(proc.wait, self.signin_s)
        except subprocess.TimeoutExpired:
            pass  # the window is still open: check what Claude Code says anyway
        except OSError:
            return False
        ok = await asyncio.to_thread(self.claude_check) == "ok"
        if ok and self.on_claude_back is not None:
            await self.on_claude_back()
        return ok

    async def cancel(self, run_id: str) -> None:
        self._get(run_id)
        for request_id, future in list(self._answers.items()):
            if request_id.startswith(f"{run_id}:") and not future.done():
                future.cancel()
        if self._results[run_id] is None:
            self._results[run_id] = ExecResult("cancelled", "Stopped.")

    async def result(self, run_id: str) -> ExecResult:
        result = self._get(run_id)
        if result is None:
            return ExecResult("cancelled", "Stopped.")
        return result

    async def reply(self, request_id: str, approve: bool) -> None:
        future = self._answers.get(request_id)
        if future is not None and not future.done():
            future.set_result(approve)

    def _get(self, run_id: str) -> ExecResult | None:
        try:
            return self._results[run_id]
        except KeyError:
            raise UnknownRun(run_id) from None
