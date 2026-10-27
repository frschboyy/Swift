"""Swift's desktop on Windows (ADR-012 D1-D2). Owner-run checks only: tests use ``fake.py``.

What each part uses:

| Part | Through |
|---|---|
| App in front, its process, focused window, last input, cursor, key presses | Win32 (``ctypes``) |
| Word: the selection, writing, undo | Word's object model (pywin32 ``win32com``) |
| Outlook: a draft for the owner to send | Outlook's object model |
| File Explorer: the selected files | ``Shell.Application`` |
| Focused control's type, password flag, selection; Value pattern; Gmail's compose fields | UI Automation (``comtypes``) |

UI Automation needs ``comtypes`` (``uv sync`` after it was added to ``pyproject.toml``).
Without it, the context reports the focused window's class instead of the control type,
writing at the focus goes straight to paste or keystrokes, and Gmail can't be filled in
(Outlook still can). ``uia_available()`` says which.

Writing tries, in order (ADR-012 §5.3): Word's object model; UI Automation's Value
pattern (an empty field only: Value replaces the whole field, and Swift never guesses the
caret); a clipboard paste (only when the clipboard holds nothing or plain text, which is
put back afterwards); keystrokes. UI Automation's Text pattern can read a selection but
not insert, so it is used for reading only.

Every COM call runs on one thread of its own (COM apartments), never on the event loop.
Nothing read here is logged; titles are used only to check the never-read list.
"""

from __future__ import annotations

import asyncio
import ctypes
import itertools
import os
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from functools import partial
from typing import Any, TypeVar

import psutil
from loguru import logger

from swift.desktop.base import (
    BROWSERS, DesktopContext, DesktopError, Mode, NeverRead, Route, Where, WriteReceipt, app_name,
)

T = TypeVar("T")

GMAIL_COMPOSE_URL = "https://mail.google.com/mail/?view=cm&fs=1"
GMAIL_WAIT_S = 20.0
# Gmail's compose fields as UI Automation names them (its aria-labels).
GMAIL_FIELDS = {"to": ("To recipients", "To"), "subject": ("Subject",), "body": ("Message Body", "Message body")}
# A paste is read by the app after Ctrl+V is processed: wait before the clipboard changes again.
PASTE_SETTLE_S = 0.12
# How long a field Swift put the cursor in has to take it, before a paste.
FOCUS_WAIT_S = 1.0
MAX_SELECTION_READ = 100_000

# UI Automation control type ids -> the words the context uses.
CONTROL_TYPES = {
    50000: "button", 50003: "combo box", 50004: "edit", 50005: "link", 50007: "list item", 50008: "list",
    50020: "text", 50025: "custom", 50026: "group", 50029: "data item", 50030: "document", 50032: "window",
    50033: "pane", 50036: "table",
}
# Win32 window classes of focused controls, when UI Automation isn't available.
WINDOW_CLASSES = {"Edit": "edit", "_WwG": "document", "Chrome_RenderWidgetHostHWND": "document",
                  "Scintilla": "edit", "NetUIHWND": "pane", "DirectUIHWND": "list"}

# ---- Win32 -------------------------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True) if os.name == "nt" else None
GWL_STYLE = -16
ES_PASSWORD = 0x20
EM_GETSEL = 0x00B0
WM_GETTEXT, WM_GETTEXTLENGTH = 0x000D, 0x000E
INPUT_KEYBOARD, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 1, 0x2, 0x4
VK_RETURN, VK_CONTROL, VK_RIGHT = 0x0D, 0x11, 0x27
CF_TEXT, CF_OEMTEXT, CF_UNICODETEXT, CF_LOCALE = 1, 7, 13, 16
ULONG_PTR = ctypes.c_size_t


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hwndActive", wintypes.HWND),
                ("hwndFocus", wintypes.HWND), ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND), ("rcCaret", wintypes.RECT)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


def _foreground() -> int:
    return int(user32.GetForegroundWindow() or 0)


def _process(hwnd: int) -> tuple[int, int, str]:
    """(thread id, process id, executable name) of a window."""
    pid = wintypes.DWORD()
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        exe = psutil.Process(pid.value).name()
    except psutil.Error:
        exe = ""
    return tid, pid.value, exe


def _title(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, 512)
    return buffer.value


def _class(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def _focus(tid: int) -> int:
    info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
        return 0
    return int(info.hwndFocus or 0)


def _key(vk: int, up: bool = False) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=KEYBDINPUT(wVk=vk, dwFlags=KEYEVENTF_KEYUP if up else 0)))


def _send(inputs: list[INPUT]) -> None:
    if not inputs:
        return
    array = (INPUT * len(inputs))(*inputs)
    if user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT)) != len(inputs):
        raise DesktopError("Windows didn't accept Swift's key presses.", "Swift can't type into windows run as administrator.")


def _chord(modifier: int, key: int, times: int = 1) -> None:
    _send([_key(modifier), *([_key(key), _key(key, True)] * times), _key(modifier, True)])


def _type(text: str) -> None:
    inputs = []
    for char in text:
        if char == "\n":
            inputs += [_key(VK_RETURN), _key(VK_RETURN, True)]
            continue
        units = char.encode("utf-16-le")
        for i in range(0, len(units), 2):
            code = int.from_bytes(units[i:i + 2], "little")
            inputs += [INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=KEYBDINPUT(wScan=code, dwFlags=flags)))
                       for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
    _send(inputs)


def _edit_selection(hwnd: int) -> int:
    start, end = wintypes.DWORD(), wintypes.DWORD()
    user32.SendMessageW(hwnd, EM_GETSEL, ctypes.byref(start), ctypes.byref(end))
    return max(0, end.value - start.value)


def _edit_text(hwnd: int) -> str:
    length = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    buffer = ctypes.create_unicode_buffer(min(length, MAX_SELECTION_READ) + 1)
    user32.SendMessageW(hwnd, WM_GETTEXT, len(buffer), buffer)
    return buffer.value


# ---- clipboard ------------------------------------------------------------------------------------

_TEXT_FORMATS = {CF_TEXT, CF_OEMTEXT, CF_UNICODETEXT, CF_LOCALE}


def _clipboard(fn: Any) -> Any:
    import win32clipboard

    for _ in range(10):  # another app may hold it for a moment
        try:
            win32clipboard.OpenClipboard()
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.05)
    else:
        raise DesktopError("The clipboard is busy.", "Try again in a moment.")
    try:
        return fn(win32clipboard)
    finally:
        win32clipboard.CloseClipboard()


def _saved_clipboard() -> str | None:
    """The clipboard's text ("" when empty), or None when it holds more than text (it can't be put back)."""

    def read(cb: Any) -> str | None:
        formats, fmt = set(), cb.EnumClipboardFormats(0)
        while fmt:
            formats.add(fmt)
            fmt = cb.EnumClipboardFormats(fmt)
        if not formats <= _TEXT_FORMATS:
            return None
        return cb.GetClipboardData(CF_UNICODETEXT) if CF_UNICODETEXT in formats else ""

    return _clipboard(read)


def _set_clipboard(text: str) -> None:
    def write(cb: Any) -> None:
        cb.EmptyClipboard()
        if text:
            cb.SetClipboardData(CF_UNICODETEXT, text)

    _clipboard(write)


# ---- COM ----------------------------------------------------------------------------------------


def _com_thread() -> None:
    import pythoncom

    pythoncom.CoInitialize()


def _word(create: bool) -> Any:
    import win32com.client

    try:
        return win32com.client.GetActiveObject("Word.Application")
    except Exception:  # noqa: BLE001 - not running
        if not create:
            raise
    try:
        return win32com.client.Dispatch("Word.Application")
    except Exception as exc:  # noqa: BLE001
        raise DesktopError("Word isn't available on this computer.", "Ask for the text instead.") from exc


class _Uia:
    """UI Automation through comtypes, made on the desktop thread."""

    def __init__(self) -> None:
        import comtypes.client

        try:
            from comtypes.gen import UIAutomationClient as client
        except ImportError:
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as client
        self.api = client
        self.automation = comtypes.client.CreateObject(client.CUIAutomation, interface=client.IUIAutomation)

    def focused(self) -> Any:
        return self.automation.GetFocusedElement()

    def pattern(self, element: Any, pattern_id: int, interface: Any) -> Any:
        try:
            found = element.GetCurrentPattern(pattern_id)
        except Exception:  # noqa: BLE001
            return None
        return found.QueryInterface(interface) if found else None

    def value(self, element: Any) -> Any:
        return self.pattern(element, self.api.UIA_ValuePatternId, self.api.IUIAutomationValuePattern)

    def selection(self, element: Any, limit: int) -> str | None:
        text = self.pattern(element, self.api.UIA_TextPatternId, self.api.IUIAutomationTextPattern)
        if text is None:
            return None
        ranges = text.GetSelection()
        return "".join(ranges.GetElement(i).GetText(limit) for i in range(ranges.Length))[:limit]

    def find(self, root: Any, names: tuple[str, ...]) -> Any:
        for name in names:
            condition = self.automation.CreatePropertyCondition(self.api.UIA_NamePropertyId, name)
            try:
                found = root.FindFirst(self.api.TreeScope_Descendants, condition)
            except Exception:  # noqa: BLE001 - a live page changed while being read (ADR-012 §9.2)
                continue
            if found:
                return found
        return None

    def same(self, a: Any, b: Any) -> bool:
        try:
            return bool(self.automation.CompareElements(a, b))
        except Exception:  # noqa: BLE001
            return False


# ---- writers ------------------------------------------------------------------------------------


class _Writer:
    route: Route
    app: str

    def __init__(self, desktop: WindowsDesktop) -> None:
        self.desktop = desktop
        self.chunks = self.chars = 0

    async def write(self, text: str, last: bool) -> None:
        await self.desktop._run(self._write, text, last)
        self.chunks += 1
        self.chars += len(text)

    async def changed(self) -> str | None:
        return await self.desktop._run(self._changed)

    async def finish(self) -> WriteReceipt:
        target = await self.desktop._run(self._finish)
        return WriteReceipt(self.app, self.route, self.chunks, self.chars, target)

    def live(self) -> WriteReceipt:
        return WriteReceipt(self.app, self.route, self.chunks, self.chars, self._live_target())

    def _write(self, text: str, last: bool) -> None: ...
    def _changed(self) -> str | None: ...
    def _finish(self) -> Any: ...
    def _live_target(self) -> Any: ...


class _WordWriter(_Writer):
    route: Route = "object_model"
    app = "Word"

    def __init__(self, desktop: WindowsDesktop, mode: Mode, new_document: bool) -> None:
        super().__init__(desktop)
        word = _word(create=True)
        word.Visible = True
        doc = word.Documents.Add() if new_document or word.Documents.Count == 0 else word.ActiveDocument
        doc.Activate()
        self.word, self.doc, self.name = word, doc, doc.FullName
        selection = word.Selection
        if selection.Start != selection.End and mode == "insert":
            selection.Collapse(0)  # wdCollapseEnd: after the selection, not over it
        elif selection.Start != selection.End:
            selection.Delete()
        try:  # everything Swift writes is one step of Word's own undo
            word.UndoRecord.StartCustomRecord("Swift")
            self.recording = True
        except Exception:  # noqa: BLE001 - older Word: undo step by step
            self.recording = False
        self.steps = 0
        self.expected = selection.Start

    def _write(self, text: str, last: bool) -> None:
        selection = self.word.Selection
        for prefix, style in (("## ", -3), ("# ", -2)):  # wdStyleHeading2, wdStyleHeading1
            if text.startswith(prefix):
                selection.Style = self.doc.Styles(style)
                text = text[len(prefix):]
                self.steps += 1
                break
        if text:
            selection.TypeText(text)
            self.steps += 1
        if not last:
            selection.TypeParagraph()
            self.steps += 1
        self.expected = selection.Start

    def _changed(self) -> str | None:
        try:
            if self.word.ActiveDocument.FullName != self.name:
                return "another document is in front in Word"
            if self.word.Selection.Start != self.expected:
                return "the cursor moved in Word"
        except Exception:  # noqa: BLE001
            return "Word stopped answering"
        return None

    def _finish(self) -> Any:
        if self.recording:
            try:
                self.word.UndoRecord.EndCustomRecord()
            except Exception:  # noqa: BLE001
                pass
        steps = 1 if self.recording else self.steps
        return ("word", self.name, self.doc.Content.End, steps)

    def _live_target(self) -> Any:
        return ("word", self.name, 0, 0)  # enough for ``show``; never for ``undo``


class _ValueWriter(_Writer):
    route: Route = "value"

    def __init__(self, desktop: WindowsDesktop, app: str, element: Any, value: Any) -> None:
        super().__init__(desktop)
        self.app, self.element, self.value, self.text = app, element, value, ""

    def _write(self, text: str, last: bool) -> None:
        self.text += text + ("" if last else "\n")
        self.value.SetValue(self.text)

    def _changed(self) -> str | None:
        uia = self.desktop._uia()
        if uia is None or not uia.same(self.element, uia.focused()):
            return f"the focus moved in {self.app}"
        if self.value.CurrentValue.replace("\r\n", "\n") != self.text:
            return "you started typing"
        return None

    def _finish(self) -> Any:
        return ("value", self.value, self.text)

    def _live_target(self) -> Any:
        return ("value", self.value, self.text)


class _KeyWriter(_Writer):
    """Paste (``clipboard`` not None: the owner's text to put back) or keystrokes, into the focused window."""

    def __init__(self, desktop: WindowsDesktop, app: str, hwnd: int, focus: int, clipboard: str | None,
                 collapse: bool) -> None:
        super().__init__(desktop)
        self.app, self.hwnd, self.focus, self.clipboard = app, hwnd, focus, clipboard
        self.route = "keys" if clipboard is None else "paste"
        if collapse:  # insert after the selection, not over it
            _send([_key(VK_RIGHT), _key(VK_RIGHT, True)])

    def _write(self, text: str, last: bool) -> None:
        text += "" if last else "\n"
        if self.route == "keys":
            _type(text)
            return
        _set_clipboard(text.replace("\n", "\r\n"))
        _chord(VK_CONTROL, ord("V"))
        time.sleep(PASTE_SETTLE_S)

    def _changed(self) -> str | None:
        if _foreground() != self.hwnd:
            return f"{self.app} isn't in front any more"
        tid, _, _ = _process(self.hwnd)
        if self.focus and _focus(tid) != self.focus:
            return f"the focus moved in {self.app}"
        return None

    def _finish(self) -> Any:
        if self.route == "paste":
            time.sleep(PASTE_SETTLE_S)
            try:
                _set_clipboard(self.clipboard or "")
            except DesktopError:
                logger.warning("couldn't put the clipboard back")
        return ("keys", self.hwnd)

    def _live_target(self) -> Any:
        return ("keys", self.hwnd)


# ---- the desktop ------------------------------------------------------------------------------


class WindowsDesktop:
    def __init__(self, never_read: NeverRead | None = None) -> None:
        self.never_read = never_read or NeverRead()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="swift-desktop", initializer=_com_thread)
        self._uia_state: _Uia | None | bool = False  # False: not tried yet
        self._outlook: dict[str, Any] = {}
        self._ids = itertools.count(1)

    async def _run(self, fn: Any, *args: Any) -> Any:
        return await asyncio.get_running_loop().run_in_executor(self._pool, partial(fn, *args))

    def _uia(self) -> _Uia | None:
        if self._uia_state is False:
            try:
                self._uia_state = _Uia()
            except Exception as exc:  # noqa: BLE001 - comtypes missing or UIA unavailable
                logger.info("UI Automation unavailable; using Win32 only", error=type(exc).__name__)
                self._uia_state = None
        return self._uia_state  # type: ignore[return-value]

    def uia_available(self) -> bool:
        return self._pool.submit(self._uia).result() is not None

    # ---- context ----

    async def context(self) -> DesktopContext:
        return await self._run(self._context)

    def _context(self) -> DesktopContext:
        hwnd = _foreground()
        if not hwnd:
            return DesktopContext()
        tid, pid, exe = _process(hwnd)
        if self.never_read.blocks(exe, _title(hwnd)):
            return DesktopContext(hwnd, exe, pid, private=True)
        control, password, selection = self._focused(exe.lower(), hwnd, _focus(tid) or hwnd)
        return DesktopContext(hwnd, exe, pid, control, password, 0 if password else selection)

    def _focused(self, exe: str, hwnd: int, focus: int) -> tuple[str, bool, int]:
        """(control type, password field, selection length) of the focused control."""
        if exe == "winword.exe":
            try:
                selection = _word(create=False).Selection
                return "document", False, max(0, selection.End - selection.Start)
            except Exception:  # noqa: BLE001
                pass
        if exe == "explorer.exe":
            return "list item", False, len(self._explorer_selection(hwnd))
        uia = self._uia()
        if uia is not None:
            try:
                element = uia.focused()
                password = bool(element.CurrentIsPassword)
                control = CONTROL_TYPES.get(element.CurrentControlType, "other")
                selected = 0 if password else len(uia.selection(element, MAX_SELECTION_READ) or "")
                return control, password, selected
            except Exception:  # noqa: BLE001 - fall back to Win32
                pass
        cls = _class(focus)
        password = cls == "Edit" and bool(user32.GetWindowLongW(focus, GWL_STYLE) & ES_PASSWORD)
        control = WINDOW_CLASSES.get(cls, "edit" if cls.startswith("RichEdit") else "unknown")
        selected = _edit_selection(focus) if control == "edit" and not password else 0
        return control, password, selected

    async def selection_text(self, limit: int = 4000) -> str | None:
        return await self._run(self._selection_text, limit)

    def _selection_text(self, limit: int) -> str | None:
        context = self._context()
        if not context.hwnd or context.private or context.password or not context.selection:
            return None
        exe = context.exe.lower()
        if exe == "winword.exe":
            return str(_word(create=False).Selection.Text)[:limit]
        uia = self._uia()
        if uia is not None:
            try:
                return uia.selection(uia.focused(), limit)
            except Exception:  # noqa: BLE001
                return None
        tid, _, _ = _process(context.hwnd)
        focus = _focus(tid)
        if focus and _class(focus) == "Edit":
            start, end = wintypes.DWORD(), wintypes.DWORD()
            user32.SendMessageW(focus, EM_GETSEL, ctypes.byref(start), ctypes.byref(end))
            return _edit_text(focus)[start.value:end.value][:limit]
        return None

    async def selected_files(self) -> list[str]:
        return await self._run(lambda: self._explorer_selection(_foreground()))

    def _explorer_selection(self, hwnd: int) -> list[str]:
        import win32com.client

        try:
            for window in win32com.client.Dispatch("Shell.Application").Windows():
                if int(window.HWND) == hwnd:
                    items = window.Document.SelectedItems()
                    return [str(items.Item(i).Path) for i in range(items.Count)]
        except Exception:  # noqa: BLE001 - not a folder window, or Explorer busy
            pass
        return []

    # ---- writing ----

    async def writer(self, where: Where, mode: Mode, new_document: bool = False) -> _Writer:
        return await self._run(self._writer, where, mode, new_document)

    def _writer(self, where: Where, mode: Mode, new_document: bool) -> _Writer:
        if where == "word":
            return _WordWriter(self, mode, new_document)
        context = self._context()
        if not context.hwnd:
            raise DesktopError("No app is in front to write in.", "Click where the text should go, then ask again.")
        if context.private or context.password:
            raise DesktopError(f"Swift doesn't write in {context.app} there.", "")
        exe = context.exe.lower()
        if exe == "winword.exe":
            return _WordWriter(self, mode, False)
        uia = self._uia()
        if uia is not None and not (mode == "replace" and context.selection):
            try:
                element = uia.focused()
                value = uia.value(element)
                if value is not None and not value.CurrentIsReadOnly and not str(value.CurrentValue).strip():
                    return _ValueWriter(self, context.app, element, value)
            except Exception:  # noqa: BLE001 - next rung
                pass
        tid, _, _ = _process(context.hwnd)
        saved = _saved_clipboard()
        collapse = mode == "insert" and context.selection > 0
        return _KeyWriter(self, context.app, context.hwnd, _focus(tid), saved, collapse)

    async def owner_input(self) -> tuple[int, tuple[int, int]]:
        info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
        user32.GetLastInputInfo(ctypes.byref(info))
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        return int(info.dwTime), (point.x, point.y)

    async def undo(self, receipt: WriteReceipt) -> str:
        return await self._run(self._undo, receipt)

    def _undo(self, receipt: WriteReceipt) -> str:
        kind = receipt.target[0]
        if kind == "word":
            _, name, end, steps = receipt.target
            word = _word(create=False)
            doc = next((d for d in word.Documents if d.FullName == name), None)
            if doc is None:
                raise DesktopError("That Word document isn't open any more.", "")
            if doc.Content.End != end:
                raise DesktopError("The document has changed since Swift wrote in it.", "Use Ctrl+Z in Word instead.")
            doc.Undo(steps)
            return "Undid what I wrote in Word."
        if kind == "value":
            _, value, text = receipt.target
            if value.CurrentValue.replace("\r\n", "\n") != text:
                raise DesktopError(f"The text in {receipt.app} has changed since.", f"Use Ctrl+Z in {receipt.app}.")
            value.SetValue("")
            return f"Removed what I wrote in {receipt.app}."
        _, hwnd = receipt.target
        if _foreground() != hwnd:
            raise DesktopError(f"{receipt.app} isn't in front.", f"Click in {receipt.app} and say “undo that” again.")
        _chord(VK_CONTROL, ord("Z"), receipt.chunks)
        return f"Pressed Ctrl+Z in {receipt.app} {receipt.chunks} time{'s' if receipt.chunks != 1 else ''}."

    async def show(self, receipt: WriteReceipt) -> str:
        return await self._run(self._show, receipt)

    def _show(self, receipt: WriteReceipt) -> str:
        kind = receipt.target[0]
        if kind == "word":
            try:
                word = _word(create=False)
            except Exception as exc:  # noqa: BLE001 - Word was closed
                raise DesktopError("Word isn't open any more.", "") from exc
            doc = next((d for d in word.Documents if d.FullName == receipt.target[1]), None)
            if doc is None:
                raise DesktopError("That Word document isn't open any more.", "")
            word.Visible = True
            doc.Activate()
            word.Activate()
            try:
                hwnd = int(word.ActiveWindow.Hwnd)  # Word 2013 and later
            except Exception:  # noqa: BLE001 - word.Activate() already brought it up
                hwnd = 0
        elif kind == "keys":
            hwnd = receipt.target[1]
        else:
            raise DesktopError(f"Swift can't bring {receipt.app} to the front.", f"Switch to {receipt.app} yourself.")
        if hwnd:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        return f"Here it is in {receipt.app}."

    async def open_path(self, path: str) -> None:
        await asyncio.to_thread(os.startfile, path)  # type: ignore[attr-defined]  # Windows only

    # ---- email, filled in for the owner to send ----

    async def fill_in_email(self, app: str, to: list[str], subject: str, body: str) -> str:
        if app == "outlook":
            return await self._run(self._outlook_draft, to, subject, body)
        if await self._run(self._uia) is None:
            raise DesktopError("Filling in Gmail needs UI Automation, which isn't installed yet.",
                               "Run `uv sync`, then restart Swift; or use Outlook.")
        await asyncio.to_thread(os.startfile, GMAIL_COMPOSE_URL)  # type: ignore[attr-defined]
        deadline = time.monotonic() + GMAIL_WAIT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            if (filled := await self._run(self._fill_gmail, to, subject, body)) is not None:
                return filled
        raise DesktopError("Gmail's compose window didn't appear.", "Check you're signed in to Gmail in your browser.")

    def _fill_gmail(self, to: list[str], subject: str, body: str) -> str | None:
        """Fill the compose window in front, once its fields exist; None while it is still loading."""
        hwnd = _foreground()
        _, _, exe = _process(hwnd)
        if exe.lower() not in BROWSERS:
            return None
        if self.never_read.blocks(exe, _title(hwnd)):
            raise DesktopError("Gmail opened in a private window.", "Open a normal window and try again.")
        uia = self._uia()
        assert uia is not None
        root = uia.automation.ElementFromHandle(hwnd)
        fields = {key: uia.find(root, names) for key, names in GMAIL_FIELDS.items()}
        if not all(fields.values()):
            return None
        # The subject last, and set directly: a paste meant for the body that Gmail sends to the field in
        # focus can't end up in it (owner checks, 2026-10-27: the message landed in the subject).
        for key, text in (("to", ", ".join(to)), ("body", body), ("subject", subject)):
            self._set_field(uia, fields[key], text, key)
        value = uia.value(fields["subject"])
        if value is not None and " ".join(str(value.CurrentValue).split()) != " ".join(subject.split()):
            logger.warning("gmail subject was wrong after filling in: set again")
            value.SetValue(subject)
        return f"gmail-compose-{next(self._ids)}"

    def _set_field(self, uia: _Uia, element: Any, text: str, field: str = "") -> None:
        value = uia.value(element)
        if value is not None and not value.CurrentIsReadOnly:
            value.SetValue(text)
            return
        element.SetFocus()
        if not self._has_focus(uia, element):
            raise DesktopError(f"Swift couldn't put the cursor in Gmail's {field or 'field'}, so it stopped there.",
                               "Finish the email yourself, or try again.")
        saved = _saved_clipboard()
        if saved is None:
            _type(text)
            return
        _set_clipboard(text.replace("\n", "\r\n"))
        _chord(VK_CONTROL, ord("V"))
        time.sleep(PASTE_SETTLE_S)
        _set_clipboard(saved)

    @staticmethod
    def _has_focus(uia: _Uia, element: Any) -> bool:
        """Whether the keyboard is in ``element`` (or inside it) yet: a paste goes wherever it is."""
        deadline = time.monotonic() + FOCUS_WAIT_S
        walker = uia.automation.RawViewWalker
        while True:
            try:
                node = uia.focused()
                for _ in range(6):
                    if node is None:
                        break
                    if uia.same(node, element):
                        return True
                    node = walker.GetParentElement(node)
            except Exception:  # noqa: BLE001 - the page changed while being read
                pass
            if time.monotonic() > deadline:
                return False
            time.sleep(0.05)

    def _outlook_draft(self, to: list[str], subject: str, body: str) -> str:
        import win32com.client

        try:
            outlook = win32com.client.Dispatch("Outlook.Application")
            mail = outlook.CreateItem(0)  # olMailItem
        except Exception as exc:  # noqa: BLE001
            raise DesktopError("Classic Outlook isn't available.", "Use Gmail instead, or start Outlook first.") from exc
        mail.To = "; ".join(to)
        mail.Subject = subject
        mail.Body = body
        mail.Display(False)  # shown, not sent: the owner presses Send
        receipt = f"outlook-draft-{next(self._ids)}"
        self._outlook[receipt] = mail
        return receipt


def describe() -> dict[str, Any]:
    """For the owner-run check: what this machine offers. Reads the app in front, prints no text."""
    desktop = WindowsDesktop()
    context = desktop._pool.submit(desktop._context).result()
    return {"uia": desktop.uia_available(), **context.as_dict(), "app": app_name(context.exe)}


if __name__ == "__main__":
    print(describe())
