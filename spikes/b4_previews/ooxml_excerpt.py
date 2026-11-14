"""B4 spike: a text excerpt from .docx / .pptx / .xlsx with the standard library only (zip + XML).
Prints per file: kind, ok/fail, characters found, ms. Never prints the text.
"""
import re
import sys
import time
import zipfile

PARTS = {".docx": r"word/document\.xml", ".pptx": r"ppt/slides/slide1\.xml", ".xlsx": r"xl/sharedStrings\.xml"}
TEXT = re.compile(rb"<(?:w|a):t(?:\s[^>]*)?>([^<]*)</(?:w|a):t>|<t(?:\s[^>]*)?>([^<]*)</t>")


def excerpt(path: str, limit: int = 600) -> str:
    kind = path[path.rfind("."):].lower()
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if re.fullmatch(PARTS[kind], n))
        with z.open(name) as f:
            data = f.read(2_000_000)  # a cap: a huge document is cut, never read whole
    words = " ".join((a or b).decode("utf-8", "replace") for a, b in TEXT.findall(data))
    return " ".join(words.split())[:limit]


for path in sys.argv[1:]:
    kind = path[path.rfind("."):].lower()
    t0 = time.perf_counter()
    try:
        n = len(excerpt(path))
        print(f"{kind}\t{'ok' if n else 'empty'}\t{n} chars\t{(time.perf_counter() - t0) * 1000:.0f} ms")
    except Exception as e:  # noqa: BLE001
        print(f"{kind}\tfail\t{type(e).__name__}\t{(time.perf_counter() - t0) * 1000:.0f} ms")
