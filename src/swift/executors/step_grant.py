"""B2: which commands a step card may approve ahead (owner, 2026-11-13).

Swift decides, never the agent: a command is reversible only when it is one plain command, in printable
ASCII with no shell syntax, whose leading words are on ``REVERSIBLE``. Everything else is irreversible
or ambiguous (a delete, a send, a payment, anything unknown), so a grant never covers it and it asks on
its own card. Deleting always asks (ADR-019) because no delete is on the list.

shortcut: a short allowlist, so most commands still ask; widen it only with the owner's say-so, one
command shape at a time, each with a test that its destructive forms stay out.
"""

from __future__ import annotations

import re
import shlex

# Leading words (lower case, ".exe" dropped) of commands that only make or change what can be undone,
# or only look. Not here on purpose: anything that sends or publishes (git push, gh repo create), signs
# in (gh auth login), deletes or discards (rm, git rm, git clean, git checkout, git reset) or runs code.
REVERSIBLE: frozenset[tuple[str, ...]] = frozenset({
    ("git", "init"), ("git", "add"), ("git", "commit"), ("git", "status"), ("git", "log"), ("git", "diff"),
    ("git", "show"), ("git", "remote", "add"), ("git", "remote", "-v"),
    ("gh", "auth", "status"), ("gh", "repo", "view"),
    ("mkdir",), ("ls",), ("dir",), ("pwd",),
})
# Shell syntax that could chain, redirect, expand or hide another command, in Bash or PowerShell.
_SYNTAX = re.compile(r"""[;&|<>`$(){}\[\]!%^\\*?]""")
# Forms of the listed commands that discard or overwrite: never approved ahead.
_DESTRUCTIVE = re.compile(r"^(--force.*|-f|--hard|--delete|-d|--output.*|--separate-git-dir.*)$", re.I)


def reversible(command: str) -> bool:
    """True only for one plain command Swift knows can be undone. Unknown or ambiguous: False."""
    if not command or command != command.strip() or not all(" " <= c <= "~" for c in command) or _SYNTAX.search(command):
        return False
    try:
        words = shlex.split(command, posix=False)
    except ValueError:
        return False
    words = [w.lower().removesuffix(".exe") if i == 0 else w for i, w in enumerate(words)]
    if words[:1] == ["git"] and len(words) > 3 and words[1] == "-C":  # in another folder; "-c" sets config: never
        words = [words[0], *words[3:]]
    if any(_DESTRUCTIVE.match(w.strip("\"'")) for w in words[1:]):
        return False
    lead = tuple(w.lower() for w in words)
    return any(lead[: len(shape)] == shape for shape in REVERSIBLE)
