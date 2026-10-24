"""The action gateway: the only path from a tool to a side effect (ADR-010 §4).

``execute`` runs every step in order and stops at the first that fails:

1. validate   the action's own checks (draft exists, fields filled in, not sent already)
2. resolve    every target came from the owner's contacts in this run (T1)
3. policy     external side effects always need the owner's approval; nothing else runs
4. confirm    the overlay's confirm card, bound to the payload digest
5. journal    PENDING, metadata only
6. execute    after recomputing the digest: a change voids the approval (T3)
7. verify     the service must return an id; no id is a failure, never "sent"
8. journal    DONE or FAILED
9. audit      one log line through the redaction patcher

Policy fails closed: a tool the table doesn't know is denied.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from loguru import logger

from swift.connectors.base import Contact, ConnectorError
from swift.security.journal import Journal
from swift.workflows.scope import RunScope

OutcomeStatus = Literal["done", "rejected", "denied", "failed"]
Status = Literal["waiting_approval", "sending", "sent", "failed", "rejected"]

# Tool -> what it needs. Swift's table, never a connector's claim (ADR-005). There is no "auto".
POLICY: dict[str, Literal["confirm"]] = {"send_email": "confirm"}


@dataclass(frozen=True)
class Action:
    tool: str
    targets: tuple[Contact, ...]
    # The confirm card: what will happen, and the artifact it shows.
    title: str
    detail: str
    artifact_id: str | None
    # Recomputed just before executing; must match what was approved.
    digest: Callable[[], str]
    # Returns the service's id for what it did ("" if it gave none).
    perform: Callable[[], Awaitable[str]]
    # The action's own validation: an error message, or None.
    validate: Callable[[], str | None] = lambda: None
    # Progress for the overlay: (status, extra fields).
    on_status: Callable[[Status, dict[str, str]], Awaitable[None]] | None = None


@dataclass(frozen=True)
class Outcome:
    status: OutcomeStatus
    reason: str = ""
    receipt: str = ""


class ActionGateway:
    def __init__(self, journal: Journal | None = None) -> None:
        self.journal = journal or Journal(None)

    async def execute(self, scope: RunScope, action: Action) -> Outcome:
        async def status(state: Status, **extra: str) -> None:
            if action.on_status is not None:
                await action.on_status(state, extra)

        # 1. validate
        if scope.closed:
            return self._deny(action, "The run this action belonged to has ended.")
        if (problem := action.validate()) is not None:
            return self._deny(action, problem)
        if action.digest() in scope.sent:
            return self._deny(action, "This exact email was already sent in this run; it won't be sent twice.")
        # 2. resolve
        if not action.targets:
            return self._deny(action, "There is no recipient.")
        for target in action.targets:
            if target.email.lower() not in scope.resolved:
                return self._deny(
                    action, f"{target.email} isn't one of the owner's contacts. Look the person up with find_contact."
                )
        # 3. policy
        if POLICY.get(action.tool) != "confirm":
            return self._deny(action, f"No policy allows {action.tool}.")
        # 4. confirm
        approved_digest = action.digest()
        await status("waiting_approval")
        decision = await scope.confirm(action.title, action.detail, action.tool, action.artifact_id)
        if decision != "approve":
            await status("rejected")
            why = "The owner didn't answer in time" if decision == "no_answer" else "The owner rejected it"
            logger.info("action not approved", tool=action.tool, decision=decision)
            return Outcome("rejected", why)
        if scope.closed:  # stopped (Esc, "stop") while the card was up
            await status("rejected")
            return Outcome("denied", "The run ended before it could be sent.")
        # 5. journal
        action_id = uuid.uuid4().hex[:12]
        domains = sorted({t.email.rsplit("@", 1)[-1].lower() for t in action.targets})
        self.journal.write(action_id, "PENDING", tool=action.tool, digest=approved_digest[:16], domains=domains)
        # 6. execute
        if action.digest() != approved_digest:
            self.journal.write(action_id, "FAILED", reason="changed_after_approval")
            await status("failed", reason="It changed after you approved it, so it wasn't sent.")
            return Outcome("denied", "The content changed after the owner approved it; nothing was sent.")
        await status("sending")
        try:
            receipt = await action.perform()
        except ConnectorError as exc:
            return await self._failed(action, action_id, str(exc), status)
        except asyncio.CancelledError:
            self.journal.write(action_id, "FAILED", reason="interrupted")
            raise
        except Exception as exc:  # noqa: BLE001 - any connector bug is a failed action, not a crash
            logger.exception("connector failed")
            return await self._failed(action, action_id, f"{type(exc).__name__}: {exc}", status)
        # 7. verify
        if not receipt:
            return await self._failed(action, action_id, "The service didn't confirm it.", status)
        # 8. journal, 9. audit
        self.journal.write(action_id, "DONE", receipt=receipt)
        scope.sent.add(approved_digest)
        await status("sent", message_id=receipt)
        logger.info("action done", tool=action.tool, action=action_id, domains=domains)
        return Outcome("done", receipt=receipt)

    @staticmethod
    def _deny(action: Action, reason: str) -> Outcome:
        logger.info("action denied", tool=action.tool, reason=reason)
        return Outcome("denied", reason)

    async def _failed(
        self, action: Action, action_id: str, reason: str,
        status: Callable[..., Awaitable[None]],
    ) -> Outcome:
        self.journal.write(action_id, "FAILED", reason=reason[:200])
        await status("failed", reason=reason[:200])
        logger.warning("action failed", tool=action.tool, action=action_id, reason=reason[:200])
        return Outcome("failed", reason)
