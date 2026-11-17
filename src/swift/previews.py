"""Local document previews for B4. The worker proposes a path; Swift renders only files it may read."""

from __future__ import annotations

import asyncio
import base64
import posixpath
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PART_LIMIT = 2_000_000
PNG_LIMIT = 1_000_000
PDF_TIMEOUT_S = 15
EXCERPT_CHARS = 600
ZIP_ENTRY_LIMIT = 10_000
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PARTS = {
    ".docx": "word/document.xml",
}
_SHEETS = re.compile(r"xl/worksheets/sheet(\d+)\.xml$")
_SLIDES = re.compile(r"ppt/slides/slide\d+\.xml$")


@dataclass(frozen=True)
class PreparedPreview:
    path: str
    title: str
    kind: Literal["pdf", "docx", "pptx", "xlsx"]
    thumbnail: str | None = None
    pages: int | None = None
    excerpt: str | None = None


class PreviewError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def prepare(path: str) -> PreparedPreview:
    file = Path(path)
    try:
        available = await asyncio.to_thread(file.is_file)
    except OSError:
        available = False
    if not available:
        raise PreviewError("file_unavailable")
    if file.drive.startswith("\\\\"):
        raise PreviewError("remote_file_refused")
    suffix = file.suffix.lower()
    if suffix == ".pdf":
        image, pages = await _render_pdf(file)
        return PreparedPreview(str(file), file.name, "pdf", base64.b64encode(image).decode("ascii"), pages)
    if suffix not in {*_PARTS, ".pptx", ".xlsx"}:
        raise PreviewError("unsupported_file")
    excerpt = await asyncio.to_thread(_office_excerpt, file, suffix)
    if not excerpt:
        raise PreviewError("empty_excerpt")
    return PreparedPreview(str(file), file.name, suffix[1:], excerpt=excerpt)


async def _render_pdf(file: Path) -> tuple[bytes, int]:
    script = Path(__file__).with_name("pdf_page.ps1")
    if not script.is_file():
        raise PreviewError("renderer_missing")
    try:
        with tempfile.TemporaryDirectory(prefix="swift-preview-") as folder:
            output = Path(folder) / "page.png"
            process = await asyncio.create_subprocess_exec(
                "powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script),
                "-Out", str(output), "-File", str(file),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=PDF_TIMEOUT_S)
            except TimeoutError:
                process.kill()
                await process.wait()
                raise PreviewError("renderer_timed_out") from None
            if process.returncode != 0:
                raise PreviewError("renderer_failed")
            match = re.fullmatch(rb"ok\tpages=(\d+)\r?\n?", stdout)
            if match is None:
                raise PreviewError("renderer_output_invalid")
            try:
                if output.stat().st_size > PNG_LIMIT:
                    raise PreviewError("renderer_output_invalid")
                image = output.read_bytes()
            except OSError:
                raise PreviewError("renderer_output_missing") from None
    except FileNotFoundError:
        raise PreviewError("renderer_unavailable") from None
    except OSError:
        raise PreviewError("renderer_failed") from None
    if not image.startswith(PNG_SIGNATURE) or len(image) > PNG_LIMIT:
        raise PreviewError("renderer_output_invalid")
    return image, int(match.group(1))


def _read_part(archive: zipfile.ZipFile, name: str) -> tuple[bytes, bool]:
    info = archive.getinfo(name)
    with archive.open(info) as part:
        data = part.read(PART_LIMIT)
    truncated = info.file_size > PART_LIMIT
    if b"\x00" in data:
        raise PreviewError("xml_encoding_refused")
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise PreviewError("xml_declarations_refused")
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        if not truncated or exc.end != len(data) or exc.reason != "unexpected end of data":
            raise PreviewError("xml_encoding_refused") from None
        try:
            data[:exc.start].decode("utf-8-sig")
        except UnicodeDecodeError:
            raise PreviewError("xml_encoding_refused") from None
    return data, truncated


def _xml_events(data: bytes, truncated: bool) -> Iterator[tuple[str, ET.Element]]:
    parser = ET.XMLPullParser(events=("end",))
    try:
        parser.feed(data)
        yield from parser.read_events()
        if not truncated:
            parser.close()
            yield from parser.read_events()
    except ET.ParseError:
        raise PreviewError("invalid_document_xml") from None


def _xml_root(data: bytes, truncated: bool) -> ET.Element:
    if truncated:
        raise PreviewError("office_part_too_large")
    root = None
    for _, node in _xml_events(data, False):  # the last element to end is the root
        root = node
    if root is None:
        raise PreviewError("invalid_document_xml")
    return root


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _relationship_part(
    archive: zipfile.ZipFile, source: str, relations_name: str, item_name: str
) -> str:
    source_data, source_truncated = _read_part(archive, source)
    relations_data, relations_truncated = _read_part(archive, relations_name)
    source_root = _xml_root(source_data, source_truncated)
    relations = _xml_root(relations_data, relations_truncated)
    item = next((node for node in source_root.iter() if _local(node.tag) == item_name), None)
    relation_id = next(
        (value for key, value in item.attrib.items() if key.endswith("}id")), None
    ) if item is not None else None
    relation = next(
        (node for node in relations.iter()
         if _local(node.tag) == "Relationship" and node.get("Id") == relation_id),
        None,
    )
    target = relation.get("Target") if relation is not None and relation.get("TargetMode", "").lower() != "external" else None
    if not target or "\\" in target:
        raise PreviewError("related_part_missing")
    return posixpath.normpath(
        target.lstrip("/") if target.startswith("/") else posixpath.join(posixpath.dirname(source), target)
    )


def _powerpoint_text(archive: zipfile.ZipFile) -> str:
    slide_name = _relationship_part(
        archive, "ppt/presentation.xml", "ppt/_rels/presentation.xml.rels", "sldId"
    )
    if not _SLIDES.fullmatch(slide_name):
        raise PreviewError("slide_target_refused")
    data, truncated = _read_part(archive, slide_name)
    return " ".join(
        node.text or "" for _, node in _xml_events(data, truncated)
        if _local(node.tag) == "t"
    )


def _excel_text(archive: zipfile.ZipFile) -> str:
    names = archive.namelist()
    strings: list[str] = []
    if "xl/sharedStrings.xml" in names:
        data, truncated = _read_part(archive, "xl/sharedStrings.xml")
        for _, node in _xml_events(data, truncated):
            if _local(node.tag) == "si":
                strings.append("".join(child.text or "" for child in node.iter() if _local(child.tag) == "t"))
                node.clear()

    sheet_name = _relationship_part(
        archive, "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "sheet"
    )
    if not _SHEETS.fullmatch(sheet_name):
        raise PreviewError("worksheet_target_refused")
    if sheet_name not in names:
        raise PreviewError("worksheet_missing")
    data, truncated = _read_part(archive, sheet_name)
    parts = []
    for _, node in _xml_events(data, truncated):
        if _local(node.tag) != "c":
            continue
        value = next((child.text or "" for child in node if _local(child.tag) == "v"), "")
        if node.get("t") == "s":
            try:
                value = strings[int(value)]
            except (ValueError, IndexError):
                value = ""
        elif node.get("t") == "inlineStr":
            value = "".join(child.text or "" for child in node.iter() if _local(child.tag) == "t")
        if value:
            parts.append(value)
        node.clear()
    return " ".join(parts)


def _office_excerpt(path: Path, suffix: str) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            if len(archive.namelist()) > ZIP_ENTRY_LIMIT:
                raise PreviewError("archive_too_many_entries")
            if suffix == ".xlsx":
                text = _excel_text(archive)
            elif suffix == ".pptx":
                text = _powerpoint_text(archive)
            else:
                name = _PARTS[suffix]
                data, truncated = _read_part(archive, name)
                text = " ".join(
                    node.text or "" for _, node in _xml_events(data, truncated)
                    if _local(node.tag) == "t"
                )
    except PreviewError:
        raise
    except (OSError, KeyError, zipfile.BadZipFile, ValueError, RuntimeError, NotImplementedError, zlib.error):
        raise PreviewError("invalid_office_file") from None
    return " ".join(text.split())[:EXCERPT_CHARS]
