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


# Hosts that are this PC, and the "\\?\" and "\\.\" prefixes, in a path that starts with two slashes.
_HERE = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "?", ".", os.environ.get("COMPUTERNAME", "localhost").lower()})
_SPLIT = re.compile(r"""[\s"'`;|&<>()=,]+""")
_VAR = re.compile(r"\$\{env:(\w+)\}|\$env:(\w+)|\$\{(\w+)\}|\$(\w+)|%(\w+)%", re.IGNORECASE)


def _flat(path: str) -> str:
    """For comparing inside a command's text: lower case, forward slashes, Git Bash's /c/ and this PC's c$ share as c:/."""
    path = re.sub(r"/+", "/", path.lower().replace("\\", "/"))
    path = re.sub(r"(?<![\w:.])/(?:localhost|127\.0\.0\.1)/([a-z])\$(?=/|$)", r"\1:", path)
    return re.sub(r"(?<![\w:.])/(?:mnt/)?([a-z])(?=/)", r"\1:", path)


class ReadScope:
    def __init__(self, read_dirs: Iterable[str], never: Iterable[str] = (), home: str | None = None) -> None:
        self.home = home or os.path.expanduser("~")
        self.read_dirs = tuple(_norm(d) for d in read_dirs if d)
        self.never = tuple(_norm(p) for p in (*default_never(home), *never) if p)

    def in_command(self, command: str, cwd: str | None) -> str | None:
        """The never-read place a shell command names, or None (owner check 213, 2026-11-13).

        Read, Glob and Grep are judged by ``verdict``; a command reached the same files on a card the
        owner approved. This reads the command's text, so it is a safeguard, not a wall:
        shortcut: a path built in pieces, by a wildcard or inside a script isn't seen, nor is a
        search of a whole folder that holds one (`grep -r … ~`, which gets a card as Grep does there);
        the real fix is running the agent's shell where it can't open these folders at all.
        """
        env = {k.upper(): v for k, v in os.environ.items()} | {"HOME": self.home, "USERPROFILE": self.home}
        text = _VAR.sub(lambda m: env.get(next(g for g in m.groups() if g).upper(), m.group(0)), command)
        text = text.replace("\\ ", " ")  # Git Bash's escaped space: "User\ Data"
        # Read both ways, and either one refuses: a quote ends a word (r'~/.ssh/x', -C"$HOME"), and a
        # quote joins what it holds to what follows ("$HOME"/.ssh). Each alone misses the other's spelling.
        for view in (text, re.sub(r"""["'`]""", "", text)):
            if place := self._named([t for t in _SPLIT.split(view) if t], cwd):
                return place
        return None

    def _named(self, tokens: list[str], cwd: str | None) -> str | None:
        tokens = [self.home + t[1:] if t == "~" or t.startswith(("~/", "~\\")) else t for t in tokens]
        flat = _flat(" ".join(tokens))
        said = {_flat(t).rstrip("/") for t in tokens}
        home = _flat(_norm(self.home))
        for never in self.never:
            n = _flat(never)
            if n in flat:  # named whole, however the rest is quoted or spaced
                return never
            # Named in two steps: `cd "$LOCALAPPDATA" && cat Swift/…`.
            parent = os.path.dirname(n)
            while len(parent) >= len(home) and parent != os.path.dirname(parent):
                rest = re.escape(n[len(parent):].lstrip("/"))
                if parent in said and re.search(rf"(?<![\w.\-]){rest}(?![\w\-])", flat.replace(n, "")):
                    return never
                parent = os.path.dirname(parent)
        base = cwd or os.getcwd()
        # A relative path ("../../.ssh/id_rsa") or a secret-looking name (".env"). A name counts wherever it
        # stands, also as a word in a search or a message: telling those apart let real reads through.
        for token in tokens:
            token = re.sub(r"^/(?:mnt/)?([a-zA-Z])(?=/)", r"\1:", token)
            if (m := re.match(r"[\\/]{2}([^\\/]+)", token)) and m.group(1).lower() not in _HERE:
                # Another computer's share: judged by its name only, since resolving it goes looking for the host.
                if any(fnmatch.fnmatch(re.split(r"[\\/]", token.rstrip("\\/"))[-1].lower(), p) for p in NEVER_NAMES):
                    return token
                continue
            try:
                path = token if os.path.isabs(token) else os.path.join(base, token)
                if self.verdict(path) == "never":
                    return path
            except (OSError, ValueError):  # not a path at all (a URL, an option): nothing to judge
                continue
        return None

    def verdict(self, path: str) -> Verdict:
        try:
            target = _norm(path)
        except OSError:
            # A volume or device spelling that can't be opened (\\?\GLOBALROOT\Device\HarddiskVolume9):
            # where it leads can't be known, so it is refused, never raised to the CLI as an error.
            return "never"
        name = os.path.basename(target)
        if any(_inside(target, n) for n in self.never) or any(fnmatch.fnmatch(name, p) for p in NEVER_NAMES):
            return "never"
        # A folder that holds a never-read folder (a search of the whole home folder): ask, never blanket.
        if any(_inside(n, target) and n != target for n in self.never):
            return "ask"
        return "read" if any(_inside(target, d) for d in self.read_dirs) else "ask"


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
