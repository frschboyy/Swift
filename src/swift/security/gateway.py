"""The action gateway: the only path from a tool to a side effect (ADR-010 §4).

``execute`` runs every step in order and stops at the first that fails:

1. validate   the action's own checks (draft exists, fields filled in, not done already)
2. resolve    every target came from the owner's contacts in this run (T1)
3. policy     external side effects always need the owner's approval; reversible ones in
              the owner's own apps (a draft filled in, text written into Word) run
              without a card but are journalled like the rest (ADR-012 §7)
4. confirm    the overlay's confirm card, bound to the payload digest (confirm only)
5. journal    PENDING, metadata only
6. execute    after recomputing the digest: a change voids the approval (T3)
7. verify     the service must return an id; no id is a failure, never "sent"
8. journal    DONE or FAILED
9. audit      one log line through the redaction patcher

Policy fails closed: a tool the table doesn't know is denied.

Undo ("undo that", "that wasn't approved"): an action can say how to reverse itself
(``Action.undo``: a new ``Action`` built from the receipt, e.g. removing the event just
added). The gateway remembers the approved actions it did (``approved``), newest last.
``undo_last`` reverses the newest one, if it can be undone, through this same
``execute``: a confirm card, journalled with ``undoes`` naming the action it reverses.
A sent email has no undo, and the owner is told so.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Literal

from loguru import logger

from swift.connectors.base import Contact, ConnectorError
from swift.security.journal import Journal
from swift.workflows.scope import RunScope

# "revise": the owner wants a change first; ``reason`` holds their words (nothing was done).
# "unknown": the service may have done it; Swift couldn't tell (a dropped connection). Never "failed".
OutcomeStatus = Literal["done", "rejected", "denied", "failed", "revise", "unknown"]
Status = Literal["waiting_approval", "sending", "sent", "failed", "rejected"]

# Tool -> what it needs. Swift's table, never a connector's claim (ADR-005). There is no "auto":
# "reversible" is for the owner's own apps, in front of them, with the app's undo.
POLICY: dict[str, Literal["confirm", "reversible"]] = {
    "send_email": "confirm",
    "create_calendar_event": "confirm",
    "update_calendar_event": "confirm",
    "delete_calendar_event": "confirm",
    # "Open this" on a program or script: running it is not reversible.
    "desktop_open_program": "confirm",
    "fill_in_email": "reversible",
    "desktop_write": "reversible",
    "desktop_open": "reversible",
    # ADR-016 §3: a system action the owner asked for, done by the agent. Turning a radio off asks.
    "system_action": "reversible",
    "system_action_disruptive": "confirm",
}


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
    # False for actions with nobody on the other end (a calendar event for the owner, a write).
    targets_required: bool = True
    # How to reverse it once done: (scope, receipt) -> the reversing action (its own card).
    # None: it can't be undone (an email, once sent).
    undo: Callable[[RunScope, str], Action] | None = None
    # The journal id of the action this one reverses (set by ``undo_last``).
    undoes: str = ""


@dataclass
class Approved:
    """An action the owner approved and the gateway did: what "undo that" refers to."""

    action_id: str
    tool: str
    title: str
    receipt: str
    undo: Callable[[RunScope, str], Action] | None
    at: float = field(default_factory=time.monotonic)

    @property
    def undoable(self) -> bool:
        return self.undo is not None


@dataclass(frozen=True)
class Outcome:
    status: OutcomeStatus
    reason: str = ""
    receipt: str = ""


# How many approved actions are remembered for "undo that" (in memory, this Swift run only),
# and for how long after it was done "undo that" still means one.
KEEP_APPROVED = 20
UNDO_WINDOW_S = 15 * 60.0


class ActionGateway:
    def __init__(self, journal: Journal | None = None) -> None:
        self.journal = journal or Journal(None)
        # Approved and done, newest last; an undone one is removed.
        self.approved: list[Approved] = []

    def last_approved(self, within_s: float | None = None) -> Approved | None:
        """The newest action the owner approved that's still in place (done less than ``within_s`` ago)."""
        if not self.approved:
            return None
        last = self.approved[-1]
        if within_s is not None and time.monotonic() - last.at > within_s:
            return None
        return last

    async def undo_last(self, scope: RunScope, within_s: float | None = None) -> tuple[Approved | None, Outcome]:
        """Reverse the newest approved action, with its own confirm card. Denied if it can't be undone."""
        last = self.last_approved(within_s)
        if last is None:
            return None, Outcome("denied", "Swift hasn't done anything on the owner's approval recently.")
        if last.undo is None:
            return last, Outcome("denied", f"“{last.title}” can't be undone.")
        reverse = last.undo(scope, last.receipt)
        outcome = await self.execute(scope, replace(reverse, undoes=last.action_id))
        if outcome.status == "done" and last in self.approved:
            self.approved.remove(last)
        return last, outcome

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
            return self._deny(action, "This exact action was already done in this run; it won't be done twice.")
        # 2. resolve
        if action.targets_required and not action.targets:
            return self._deny(action, "There is no recipient.")
        for target in action.targets:
            if target.email.lower() not in scope.resolved:
                return self._deny(
                    action, f"{target.email} isn't one of the owner's contacts. Look the person up with find_contact."
                )
        # 3. policy
        policy = POLICY.get(action.tool)
        if policy is None:
            return self._deny(action, f"No policy allows {action.tool}.")
        # 4. confirm
        approved_digest = action.digest()
        if policy == "confirm":
            await status("waiting_approval")
            decision = await scope.confirm(action.title, action.detail, action.tool, action.artifact_id)
            if decision == "revise":
                logger.info("owner asked for a change", tool=action.tool)
                return Outcome("revise", scope.feedback)
            if decision != "approve":
                await status("rejected")
                why = "The owner didn't answer in time" if decision == "no_answer" else "The owner rejected it"
                logger.info("action not approved", tool=action.tool, decision=decision)
                return Outcome("rejected", why)
            if scope.closed:  # stopped (Esc, "stop") while the card was up
                await status("rejected")
                return Outcome("denied", "The run ended before it could be done.")
        # 5. journal
        action_id = uuid.uuid4().hex[:12]
        domains = sorted({t.email.rsplit("@", 1)[-1].lower() for t in action.targets})
        extra = {"undoes": action.undoes} if action.undoes else {}
        self.journal.write(action_id, "PENDING", tool=action.tool, digest=approved_digest[:16], domains=domains,
                           **extra)
        # 6. execute
        if action.digest() != approved_digest:
            self.journal.write(action_id, "FAILED", reason="changed_after_approval")
            await status("failed", reason="It changed after you approved it, so it wasn't done.")
            return Outcome("denied", "The content changed after the owner approved it; nothing was sent.")
        await status("sending")
        try:
            receipt = await action.perform()
        except ConnectorError as exc:
            if exc.code == "unknown":  # it may have been done: say so, never "failed" (audit 2026-10, A-05)
                self.journal.write(action_id, "UNKNOWN", reason=str(exc)[:200])
                await status("failed", reason=str(exc)[:200])
                logger.warning("action outcome unknown", tool=action.tool, action=action_id)
                return Outcome("unknown", str(exc))
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
        self.journal.write(action_id, "DONE", receipt=receipt, undoable=action.undo is not None)
        scope.sent.add(approved_digest)
        if policy == "confirm":
            scope.done.append((action.tool, action.title))
            if not action.undoes:  # undoing an undo isn't offered
                self.approved = [*self.approved, Approved(action_id, action.tool, action.title, receipt,
                                                          action.undo)][-KEEP_APPROVED:]
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
