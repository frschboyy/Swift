"""Which files Claude Code may read without asking (audit 2026-10, finding B-01; owner, 2026-10-28).

Read, Glob and Grep used to be pre-approved for any path on the disk. What they read goes to the
model, and a page or document a run read could steer it into reading Claude's own sign-in, SSH
keys or a browser profile. Now:

- **Inside the read folders** (the working folders, Documents and Downloads by default:
  ``executor.read_dirs``): read without a card, as before.
- **Anywhere else:** a confirm card first ("Read notes.txt?"). No answer or a no: not read, and the
  run goes on without it.
- **Never read**, card or not: secrets and credentials (``.ssh``, ``.claude``, ``.aws``, browser
  profiles, Windows' credential folders, Swift's own config and data folders, wherever the settings
  put them: the Google client file, recordings, transcripts and logs)
  and secret-looking files anywhere (``.env``, private keys, password databases), plus whatever
  the owner adds (``executor.never_read``).

Paths are resolved (``..``, junctions and symbolic links followed) before they are compared, and
compared without regard to case, as Windows does.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterable
from typing import Any, Literal

READ_TOOLS = frozenset({"Read", "Glob", "Grep"})

# Under the user's home folder.
_HOME_NEVER = (
    ".ssh", ".claude", ".aws", ".azure", ".gnupg", ".kube", ".docker", ".config/gcloud", ".config/gh",
    "AppData/Roaming/Microsoft/Credentials", "AppData/Local/Microsoft/Credentials",
    "AppData/Roaming/Microsoft/Protect", "AppData/Roaming/Microsoft/Crypto",
    "AppData/Local/Google/Chrome/User Data", "AppData/Local/Microsoft/Edge/User Data",
    "AppData/Local/BraveSoftware", "AppData/Roaming/Mozilla", "AppData/Roaming/Opera Software",
    "AppData/Roaming/Swift",  # Swift's config: the Google OAuth client file
    "AppData/Local/Swift",  # Swift's data: recordings, transcripts, logs (X-07: audio never leaves the PC)
    "AppData/Roaming/Claude", "AppData/Roaming/1Password", "AppData/Roaming/Bitwarden",
)
# File names never read, wherever they are.
NEVER_NAMES = (
    ".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12", "id_rsa*", "id_ed25519*", "id_ecdsa*", "*.kdbx",
    "client_secret*.json", "credentials.json", ".credentials.json", ".netrc", ".git-credentials", "*.ppk",
)
_WILDCARDS = "*?[{"

Verdict = Literal["read", "ask", "never"]


def _local(path: str) -> str:
    """The same file spelled as a local path: ``\\\\?\\C:\\…``, ``\\\\localhost\\c$\\…`` (this PC's drive shares)."""
    path = re.sub(r"^[\\/]{2}[?.][\\/]UNC[\\/]", r"\\\\", path, flags=re.IGNORECASE)  # \\?\UNC\host\… -> \\host\…
    path = re.sub(r"^[\\/]{2}[?.][\\/](?=[a-zA-Z]:)", "", path)  # \\?\C:\… -> C:\…; a volume name stays as it is
    hosts = "|".join(map(re.escape, ("localhost", "127.0.0.1", "::1", "[::1]", os.environ.get("COMPUTERNAME", "localhost"))))
    # To the drive's root, never "C:" alone, which Python reads as the current folder on that drive.
    return re.sub(rf"^[\\/]{{2}}(?:{hosts})[\\/]([a-zA-Z])\$(?:[\\/]|$)", r"\1:\\", path, flags=re.IGNORECASE)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(_local(os.path.expanduser(path))))


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)


def default_never(home: str | None = None) -> tuple[str, ...]:
    base = home or os.path.expanduser("~")
    return tuple(os.path.join(base, *p.split("/")) for p in _HOME_NEVER)


class ReadScope:
    def __init__(self, read_dirs: Iterable[str], never: Iterable[str] = (), home: str | None = None) -> None:
        self.read_dirs = tuple(_norm(d) for d in read_dirs if d)
        self.never = tuple(_norm(p) for p in (*default_never(home), *never) if p)

    def verdict(self, path: str) -> Verdict:
        target = _norm(path)
        name = os.path.basename(target)
        if any(_inside(target, n) for n in self.never) or any(fnmatch.fnmatch(name, p) for p in NEVER_NAMES):
            return "never"
        # A folder that holds a never-read folder (a search of the whole home folder): ask, never blanket.
        if any(_inside(n, target) and n != target for n in self.never):
            return "ask"
        return "read" if any(_inside(target, d) for d in self.read_dirs) else "ask"


# One name of each never-read kind, and ordinary names that a wide search takes in as well.
_SECRET_SAMPLES = (
    ".env", ".env.local", "x.pem", "x.key", "x.pfx", "x.p12", "id_rsa", "id_ed25519", "id_ecdsa", "x.kdbx",
    "client_secret.json", "credentials.json", ".credentials.json", ".netrc", ".git-credentials", "x.ppk",
)
_PLAIN_SAMPLES = ("main.py", "readme.md", "data.json", "notes.txt", "config.yaml", "index")


def _braces(glob: str) -> list[str]:
    """``*.{pem,key}`` as ``*.pem`` and ``*.key``."""
    m = re.search(r"\{([^{}]*)\}", glob)
    if m is None:
        return [glob]
    return [g for part in m.group(1).split(",") for g in _braces(glob[:m.start()] + part + glob[m.end():])]


def names_secret(glob: str) -> bool:
    """A Grep ``glob`` aimed at never-read files: it takes in a secret-named file and no ordinary one
    (".env", ".env*", "**/*.pem", "cred*.json", "*.{pem,key}").
    shortcut: a wide search ("*.json", or no glob) still looks inside a secret-named file in the folder;
    closing that needs every Grep to carry exclusions (owner's decision)."""
    for one in _braces(glob):
        name = one.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if name and any(fnmatch.fnmatchcase(s, name) for s in _SECRET_SAMPLES) and not any(
            fnmatch.fnmatchcase(p, name) for p in _PLAIN_SAMPLES
        ):
            return True
    return False


def target_path(tool: str, args: dict[str, Any], cwd: str | None) -> str:
    """The file or folder a read tool will look at: its path, or a pattern's fixed start, else the working folder."""
    base = cwd or os.getcwd()
    if tool == "Read":
        raw = str(args.get("file_path") or "")
    else:
        raw = str(args.get("path") or "")
        pattern = str(args.get("pattern") or "") if tool == "Glob" else ""
        if pattern:
            # A pattern's fixed start is a folder too: "../../.ssh/*" or "C:/Users/me/.aws/**".
            fixed = pattern
            for i, ch in enumerate(pattern):
                if ch in _WILDCARDS:
                    fixed = os.path.dirname(pattern[:i])
                    break
            raw = os.path.join(raw or base, fixed) if fixed else raw
    if not raw:
        return base
    return raw if os.path.isabs(raw) else os.path.join(base, raw)
