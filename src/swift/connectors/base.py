"""The connector boundary (ADR-005, ADR-010 §9).

A connector talks to one outside service. It declares a ``Manifest`` and offers
plain async methods; it never decides what is safe. Swift assigns side effects
in ``swift.workflows.tools``, and anything that changes the outside world
(``EmailConnector.send``) is called only by ``swift.security.gateway``
(enforced by ``tests/unit/test_architecture.py``).

Everything a connector returns is untrusted external data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Manifest:
    id: str
    name: str
    auth: Literal["none", "oauth"] = "none"


@dataclass(frozen=True)
class Contact:
    name: str
    email: str
    # Where Swift found it: "config" (the owner's contacts list) or the connector's id.
    source: str = "config"

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "email": self.email, "source": self.source}


@dataclass(frozen=True)
class OutgoingEmail:
    to: tuple[Contact, ...]
    subject: str
    body: str


@dataclass(frozen=True)
class SentMessage:
    message_id: str


class ConnectorError(RuntimeError):
    """The service refused or couldn't be reached. ``hint`` says what the owner can do."""

    def __init__(self, message: str, hint: str = "", *, code: str = "connector_failed") -> None:
        super().__init__(message)
        self.hint = hint
        self.code = code


class EmailConnector(Protocol):
    manifest: Manifest

    async def directory(self, query: str) -> list[Contact]:
        """The owner's contacts matching ``query`` (read-only)."""
        ...

    async def send(self, email: OutgoingEmail) -> SentMessage:
        """Send one email. Gateway only."""
        ...
