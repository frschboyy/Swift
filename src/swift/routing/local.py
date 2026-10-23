"""Open apps, folders and projects by spoken name (ADR-007 §3, tier 1 "local").

Targets come only from the ``local`` settings and ``executor.working_dirs``: a spoken
phrase is looked up, never executed. A phrase that isn't a configured name resolves to
``None`` and the request goes to Claude Code instead.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from swift.routing.rules import Route
from swift.settings import Settings

Kind = Literal["app", "folder", "project"]

_DETERMINERS = re.compile(r"^(?:(?:my|the|a|an|our|up)\s+)+")
_KIND_WORDS = {"folder": "folder", "directory": "folder", "project": "project", "repo": "project", "repository": "project"}
_CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class OpenTarget:
    kind: Kind
    name: str  # as configured, for the result card
    path: str  # the app command, or the folder
    app: str | None = None  # command of the app a project opens in


def _key(phrase: str) -> str:
    return " ".join(_DETERMINERS.sub("", phrase.lower().strip()).split())


def _split_kind(phrase: str) -> tuple[str, Kind | None]:
    words = _key(phrase).split()
    if words and words[-1] in _KIND_WORDS:
        return " ".join(words[:-1]), _KIND_WORDS[words[-1]]  # type: ignore[return-value]
    return " ".join(words), None


class LocalOpener:
    def __init__(self, settings: Settings) -> None:
        cfg = settings.local
        self.enabled = cfg.enabled
        self.apps = {_key(k): v for k, v in cfg.apps.items()}
        home = Path(os.environ.get("USERPROFILE") or Path.home())
        self.folders = {name: str(home / name.title()) for name in ("documents", "downloads", "desktop")}
        self.folders.update({_key(k): v for k, v in cfg.folders.items()})
        self.projects = {Path(d).name.lower(): d for d in settings.executor.working_dirs}
        self.projects.update({_key(k): v for k, v in cfg.projects.items()})
        self.editor = _key(cfg.editor)

    def resolve(self, route: Route) -> OpenTarget | None:
        if not self.enabled or not route.target:
            return None
        name, kind = _split_kind(route.target)
        if route.app:
            return self._resolve_in_app(name, kind, _key(route.app))
        if not name:
            return None
        if kind is None and name in self.apps:
            return OpenTarget("app", name, self.apps[name])
        if kind in (None, "folder") and name in self.folders and Path(self.folders[name]).is_dir():
            return OpenTarget("folder", name, self.folders[name])
        if kind in (None, "project") and name in self.projects and Path(self.projects[name]).is_dir():
            return OpenTarget("project", name, self.projects[name], self.apps.get(self.editor))
        return None

    def _resolve_in_app(self, name: str, kind: Kind | None, app: str) -> OpenTarget | None:
        # "open <project> in <app>" and "open <app> for <project>".
        if app not in self.apps and name in self.apps:
            name, app = app, name
            name, kind = _split_kind(name)
        command = self.apps.get(app)
        if command is None:
            return None
        if kind in (None, "project") and name in self.projects and Path(self.projects[name]).is_dir():
            return OpenTarget("project", name, self.projects[name], command)
        if kind in (None, "folder") and name in self.folders and Path(self.folders[name]).is_dir():
            return OpenTarget("folder", name, self.folders[name], command)
        return None

    def launch(self, target: OpenTarget) -> None:
        """Start it without a console window. Raises OSError when it can't be started."""
        if target.kind == "app":
            os.startfile(target.path)  # type: ignore[attr-defined]  # Windows only
        elif target.app is not None:
            exe = shutil.which(target.app)
            if exe is None:
                os.startfile(target.path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen([exe, target.path], creationflags=_CREATE_NO_WINDOW, close_fds=True)
        else:
            os.startfile(target.path)  # type: ignore[attr-defined]
