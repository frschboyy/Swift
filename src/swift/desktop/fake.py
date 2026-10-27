"""An in-memory desktop for tests and debug mode: nothing on the real screen is read or touched."""

from __future__ import annotations

from dataclasses import dataclass, field

from swift.desktop.base import (
    DesktopContext, DesktopError, Mode, NeverRead, Route, Where, WriteReceipt, app_name,
)


@dataclass
class FakeApp:
    """One window: what it shows, and what Swift wrote into it."""

    exe: str
    control: str = "document"
    title: str = ""
    text: str = ""
    selected: str = ""
    password: bool = False
    files: list[str] = field(default_factory=list)
    route: Route = "value"


class FakeWriter:
    def __init__(self, desktop: FakeDesktop, app: FakeApp, route: Route, mode: Mode) -> None:
        self.desktop, self.target, self.route = desktop, app, route
        self.app = app_name(app.exe)
        self.chunks = self.chars = 0
        self.before = app.text
        if mode == "replace" and app.selected:
            app.text = app.text.replace(app.selected, "", 1)
            app.selected = ""

    async def write(self, text: str, last: bool) -> None:
        self.desktop.writes.append((self.app, text))
        self.target.text += text + ("" if last else "\n")
        self.chunks += 1
        self.chars += len(text)
        if self.desktop.on_write is not None:
            await self.desktop.on_write(self.chunks)

    async def changed(self) -> str | None:
        if self.desktop.front is not self.target and self.route != "object_model":
            return f"{self.app} isn't in front any more"
        return self.desktop.moved

    async def finish(self) -> WriteReceipt:
        return WriteReceipt(self.app, self.route, self.chunks, self.chars, (self.target, self.before))


class FakeDesktop:
    def __init__(self, front: FakeApp | None = None, never_read: NeverRead | None = None) -> None:
        self.front = front
        self.word = FakeApp("WINWORD.EXE", route="object_model")
        self.never_read = never_read or NeverRead()
        self.writes: list[tuple[str, str]] = []
        self.opened: list[str] = []
        self.shown: list[WriteReceipt] = []
        self.filled: list[tuple[str, list[str], str, str]] = []
        self.undone: list[WriteReceipt] = []
        # Set by a test: the reason the target changed, the owner's input tick, an app that fails.
        self.moved: str | None = None
        self.tick = 0
        self.cursor = (0, 0)
        self.unavailable: set[str] = set()
        self.on_write = None

    def _private(self, app: FakeApp) -> bool:
        return self.never_read.blocks(app.exe, app.title)

    async def context(self) -> DesktopContext:
        app = self.front
        if app is None:
            return DesktopContext()
        if self._private(app):
            return DesktopContext(1, app.exe, 1, private=True)
        selection = len(app.files) if app.exe.lower() == "explorer.exe" else len(app.selected)
        return DesktopContext(1, app.exe, 1, app.control, app.password, 0 if app.password else selection)

    async def selection_text(self, limit: int = 4000) -> str | None:
        app = self.front
        if app is None or self._private(app) or app.password or not app.selected:
            return None
        return app.selected[:limit]

    async def selected_files(self) -> list[str]:
        app = self.front
        if app is None or app.exe.lower() != "explorer.exe" or self._private(app):
            return []
        return list(app.files)

    async def writer(self, where: Where, mode: Mode, new_document: bool = False) -> FakeWriter:
        if where == "word":
            if "word" in self.unavailable:
                raise DesktopError("Word isn't installed.", "Install Word, or ask for the text instead.")
            if new_document:
                self.word = FakeApp("WINWORD.EXE", route="object_model")
            return FakeWriter(self, self.word, "object_model", mode)
        app = self.front
        if app is None:
            raise DesktopError("No app is in front to write in.", "Click where the text should go, then ask again.")
        if self._private(app) or app.password:
            raise DesktopError(f"Swift doesn't write in {app_name(app.exe)} there.", "")
        return FakeWriter(self, app, app.route, mode)

    async def owner_input(self) -> tuple[int, tuple[int, int]]:
        return self.tick, self.cursor

    async def undo(self, receipt: WriteReceipt) -> str:
        app, before = receipt.target
        app.text = before
        self.undone.append(receipt)
        return f"Undid what I wrote in {receipt.app}."

    async def show(self, receipt: WriteReceipt) -> str:
        app, _ = receipt.target
        self.front = app
        self.shown.append(receipt)
        return f"Here it is in {receipt.app}."

    async def open_path(self, path: str) -> None:
        self.opened.append(path)

    async def fill_in_email(self, app: str, to: list[str], subject: str, body: str) -> str:
        if app in self.unavailable:
            raise DesktopError(f"{app.title()} isn't available.", "")
        self.filled.append((app, to, subject, body))
        return f"{app}-compose-{len(self.filled)}"
