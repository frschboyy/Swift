"""Desktop context and writing where the owner is (ADR-012 D1-D2), behind one interface.

``Desktop`` is what Swift knows and does in the owner's apps:

- ``context()``: the foreground app, its process, the focused control's type, whether
  something is selected. Read when the owner speaks, kept for that request only, never
  stored or logged, and sent to a provider only when the request needs it ("this", "here").
- ``selection_text()`` and ``selected_files()``: read only when a request is about them.
- ``writer()``: text into the focused control or Word, by the most precise route
  (ADR-012 §5.3): the app's object model (Word), then UI Automation's Value pattern,
  then a clipboard paste, then keystrokes.
- ``undo()``: the app's own undo for what Swift wrote.

**Never read** (ADR-012 Q4): password managers, banking sites and private browser
windows by default, plus whatever the owner adds. For those, and for password fields,
the context says only that the app is private, and nothing is read or written.

``windows.py`` is the real implementation; ``fake.py`` is for tests and debug mode.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

from swift.connectors.base import ConnectorError

Route = Literal["object_model", "value", "paste", "keys"]
Where = Literal["focus", "word"]
Mode = Literal["insert", "replace"]

# Executable names (lower case) of password managers: never read.
PASSWORD_MANAGERS = (
    "1password.exe", "bitwarden.exe", "keepass.exe", "keepassxc.exe", "lastpass.exe", "dashlane.exe",
    "nordpass.exe", "enpass.exe", "roboform.exe", "proton pass.exe", "keeper.exe",
)
# Window-title words that mark a banking or payment site in a browser: never read.
BANKING_TITLES = ("bank", "banking", "paypal", "revolut", "monzo", "wise.com", "credit union", "brokerage")
# How browsers title a private window.
PRIVATE_TITLES = ("(incognito)", "incognito -", "inprivate", "private browsing", "(private)")
# Opened by "open this" only after a confirm card: running a program isn't reversible.
PROGRAMS = (".exe", ".msi", ".bat", ".cmd", ".com", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".scr", ".lnk",
            ".reg", ".hta", ".cpl", ".appref-ms")

APP_NAMES = {
    "winword.exe": "Word", "excel.exe": "Excel", "outlook.exe": "Outlook", "powerpnt.exe": "PowerPoint",
    "chrome.exe": "Chrome", "msedge.exe": "Edge", "brave.exe": "Brave", "firefox.exe": "Firefox",
    "explorer.exe": "File Explorer", "code.exe": "VS Code", "notepad.exe": "Notepad", "slack.exe": "Slack",
    "claude.exe": "Claude", "whatsapp.exe": "WhatsApp", "spotify.exe": "Spotify",
}
BROWSERS = frozenset({"chrome.exe", "msedge.exe", "brave.exe", "firefox.exe"})


class DesktopError(ConnectorError):
    """Swift couldn't do it in the app. ``hint`` says what the owner can do."""


@dataclass(frozen=True)
class NeverRead:
    """The never-read list (ADR-012 Q4). Matching is local; titles are never kept."""

    apps: frozenset[str] = frozenset(PASSWORD_MANAGERS)
    titles: tuple[str, ...] = BANKING_TITLES

    @classmethod
    def with_extra(cls, apps: list[str] | tuple[str, ...] = (), titles: list[str] | tuple[str, ...] = ()) -> NeverRead:
        return cls(
            frozenset(PASSWORD_MANAGERS) | {a.lower() for a in apps},
            BANKING_TITLES + tuple(t.lower() for t in titles if t.strip()),
        )

    def blocks(self, exe: str, title: str) -> bool:
        low = title.lower()
        return exe.lower() in self.apps or any(t in low for t in (*self.titles, *PRIVATE_TITLES))


def app_name(exe: str) -> str:
    return APP_NAMES.get(exe.lower(), exe.rsplit(".", 1)[0].title() if exe else "")


@dataclass(frozen=True)
class DesktopContext:
    """Where the owner is, at the moment they spoke. No text, no title."""

    hwnd: int = 0
    exe: str = ""
    pid: int = 0
    # The focused control's type: "document", "edit", "list item", ... or "unknown".
    control: str = "unknown"
    password: bool = False
    # Characters selected (files, in File Explorer); 0: nothing.
    selection: int = 0
    # On the never-read list: nothing but the app was read.
    private: bool = False

    @property
    def app(self) -> str:
        return app_name(self.exe)

    def describe(self) -> str:
        """For a provider: "Word (document), 69 characters selected"."""
        if not self.hwnd:
            return "No app is in front."
        if self.private:
            return f"{self.app} (private: Swift doesn't look at it)."
        what = "a password field" if self.password else self.control
        parts = [f"{self.app} ({what})"]
        if self.selection:
            unit = "files" if self.exe.lower() == "explorer.exe" else "characters"
            parts.append(f"{self.selection} {unit} selected")
        return ", ".join(parts) + "."

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self) | {"app": self.app}
        out.pop("hwnd")
        out.pop("pid")
        return out


@dataclass(frozen=True)
class WriteReceipt:
    """What Swift wrote, for "undo that": the app, the route, and how many undo steps."""

    app: str
    route: Route
    chunks: int
    chars: int
    # The implementation's handle on the target (a window, a document): never shown.
    target: Any = None


class Writer(Protocol):
    app: str
    route: Route

    async def write(self, text: str, last: bool) -> None:
        """One chunk (a paragraph). ``last``: no paragraph break after it."""
        ...

    async def changed(self) -> str | None:
        """Why the target isn't as Swift left it (the cursor moved, another window is in front), or None."""
        ...

    async def finish(self) -> WriteReceipt: ...


class Desktop(Protocol):
    async def context(self) -> DesktopContext: ...

    async def selection_text(self, limit: int = 4000) -> str | None:
        """The selected text in the focused control; None when private, a password, or unreadable."""
        ...

    async def selected_files(self) -> list[str]:
        """Paths selected in the File Explorer window in front."""
        ...

    async def writer(self, where: Where, mode: Mode, new_document: bool = False) -> Writer:
        """Raises ``DesktopError`` when there is nowhere Swift may write."""
        ...

    async def owner_input(self) -> tuple[int, tuple[int, int]]:
        """(tick of the last keyboard or mouse input, cursor position): to notice the owner typing."""
        ...

    async def undo(self, receipt: WriteReceipt) -> str:
        """Undo a write with the app's own undo. Returns what happened, for the result card."""
        ...

    async def show(self, receipt: WriteReceipt) -> str:
        """Bring the app and document Swift wrote in to the front ("show me", ADR-007 §10). Returns
        what happened, for the result card; raises ``DesktopError`` when it isn't there any more."""
        ...

    async def open_path(self, path: str) -> None: ...

    async def fill_in_email(self, app: str, to: list[str], subject: str, body: str) -> str:
        """Fill in a new email for the owner to send (Gmail compose, or an Outlook draft). Never sends."""
        ...
