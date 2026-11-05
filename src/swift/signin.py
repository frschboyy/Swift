"""The sign-ins Swift depends on, checked so they never stop it by surprise (2026-11-04).

Two sign-ins can end on the provider's side while Swift isn't in use: Google's (after 7 days
while the OAuth app is in Testing; docs/google_setup.md §4) and Claude Code's. Swift keeps
them, but it can't sign back in by itself: that always takes the owner on the provider's own
page, and Swift never enters credentials. So it checks them at start-up and once a day, and
right after one is refused, and offers one card per sign-in that opens that page
(``swift.executors.signin``).

The log gets the service and its status only: never the account, the email or a token.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from loguru import logger

Status = Literal["ok", "expired", "expiring", "absent", "unknown"]
Service = Literal["google", "claude"]

# Claude Code's login ending this soon is offered too, before it stops a request.
CLAUDE_WARN = timedelta(days=3)
STATUS_TIMEOUT_S = 20.0
# Once a day, so a sign-in that ends while Swift runs for days is offered before it's needed.
CHECK_EVERY_S = 86400.0
# A refusal seen in a run starts a check, but not more often than this.
RECHECK_AFTER_S = 600.0

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


def claude_status(claude: str | None, now: datetime | None = None) -> Status:
    """Blocking: Claude Code's own ``claude auth status``. It reads the local login only: a login
    revoked on the server still looks fine here, and is caught when a run is refused."""
    if not claude:
        return "unknown"
    try:
        out = subprocess.run(
            [claude, "auth", "status", "--json"], capture_output=True, text=True, encoding="utf-8",
            timeout=STATUS_TIMEOUT_S, creationflags=_NO_WINDOW, check=False,
        )
        data = json.loads(out.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return "unknown"
    return judge_claude(data, now or datetime.now(UTC))


def judge_claude(data: dict[str, object], now: datetime) -> Status:
    if not isinstance(data, dict) or "loggedIn" not in data:
        return "unknown"
    if not data["loggedIn"]:
        return "expired"
    ends = data.get("loginExpiresAt")
    if not isinstance(ends, str):
        return "ok"
    try:
        at = datetime.fromisoformat(ends.replace("Z", "+00:00"))
    except ValueError:
        return "ok"
    if at <= now:
        return "expired"
    return "expiring" if at - now <= CLAUDE_WARN else "ok"


def open_claude_login(claude: str) -> subprocess.Popen[bytes]:
    """A console window running ``claude auth login``: Claude Code opens its sign-in page in the
    browser and the owner signs in there. The window is the owner's; Swift only waits for it."""
    return subprocess.Popen([claude, "auth", "login"], creationflags=_NEW_CONSOLE, cwd=os.path.expanduser("~"))


class SigninWatch:
    """Checks the sign-ins and hands the ones that need the owner to ``offer``."""

    def __init__(
        self,
        offer: Callable[[set[Service]], None],
        *,
        google: Callable[[], str] | None,
        claude: Callable[[], Status] | None,
        busy: Callable[[], bool] = lambda: False,
    ) -> None:
        self.offer = offer
        self.google = google
        self.claude = claude
        self.busy = busy
        self._last = 0.0
        # When each sign-in was last offered on a card: a refusal is throttled on this, never on the last
        # check, since a check that read "ok" locally can't see a token revoked on the server (R-05).
        self._offered: dict[Service, float] = {}

    async def check(self) -> set[Service]:
        """The sign-ins that need the owner now; each one checked on a thread."""
        self._last = asyncio.get_running_loop().time()
        need: set[Service] = set()
        if self.google is not None:
            status = await asyncio.to_thread(self.google)
            logger.info("sign-in checked", service="google", status=status)
            if status == "expired":
                need.add("google")
        if self.claude is not None:
            status = await asyncio.to_thread(self.claude)
            logger.info("sign-in checked", service="claude", status=status)
            if status in ("expired", "expiring"):
                need.add("claude")
        if need:
            now = asyncio.get_running_loop().time()
            self._offered.update(dict.fromkeys(need, now))
            self.offer(need)
        return need

    def refused(self, service: Service) -> None:
        """A run was refused for a sign-in: offer it now (from the event loop), unless that sign-in was
        offered in the last 10 minutes (seams audit R-05: not "checked": a check can't see a revoked token)."""
        loop = asyncio.get_running_loop()
        last = self._offered.get(service)
        if last is not None and loop.time() - last < RECHECK_AFTER_S:
            return
        self._offered[service] = loop.time()
        logger.info("sign-in refused in a run", service=service)
        self.offer({service})

    async def run(self, every_s: float = CHECK_EVERY_S, first_after_s: float = 20.0, retry_s: float = 60.0) -> None:
        """At start-up (once Swift has settled), then once a day; never while a request runs."""
        await asyncio.sleep(first_after_s)
        while True:
            if self.busy():
                await asyncio.sleep(retry_s)
                continue
            try:
                await self.check()
            except Exception:  # noqa: BLE001 - a check must never stop Swift
                logger.exception("sign-in check failed")
            await asyncio.sleep(every_s)
