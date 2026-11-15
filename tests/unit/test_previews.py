from __future__ import annotations

import base64
import zipfile
from pathlib import Path

import pytest

from swift import previews
from swift import shapes
from swift.executors.claude_code import _Run, _show_checked_shape
from swift.executors.read_scope import ReadScope


def _ooxml(path: Path, parts: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(name, text.encode("utf-8") if isinstance(text, str) else text)


@pytest.mark.asyncio
async def test_word_excerpt_is_text_and_xml_entities_are_decoded(tmp_path: Path) -> None:
    path = tmp_path / "brief.docx"
    _ooxml(path, {
        "word/document.xml": (
            '<w:document xmlns:w="urn:word"><w:body><w:p><w:r><w:t>Tea &amp; history</w:t>'
            "</w:r></w:p></w:body></w:document>"
        ),
    })

    preview = await previews.prepare(str(path))

    assert preview.kind == "docx" and preview.title == "brief.docx"
    assert preview.excerpt == "Tea & history"
    assert preview.thumbnail is None and preview.pages is None


@pytest.mark.asyncio
async def test_powerpoint_uses_first_slide_text(tmp_path: Path) -> None:
    path = tmp_path / "slides.pptx"
    _ooxml(path, {
        "ppt/presentation.xml": (
            '<p:presentation xmlns:p="urn:ppt" xmlns:r="urn:relationships"><p:sldIdLst>'
            '<p:sldId r:id="rId2"/></p:sldIdLst></p:presentation>'
        ),
        "ppt/_rels/presentation.xml.rels": (
            '<Relationships><Relationship Id="rId1" Target="slides/slide1.xml"/>'
            '<Relationship Id="rId2" Target="slides/slide2.xml"/></Relationships>'
        ),
        "ppt/slides/slide1.xml": '<p:sld xmlns:p="urn:ppt" xmlns:a="urn:drawing"><a:t>Later</a:t></p:sld>',
        "ppt/slides/slide2.xml": (
            '<p:sld xmlns:p="urn:ppt" xmlns:a="urn:drawing"><a:t>First</a:t><a:t>slide</a:t></p:sld>'
        ),
    })

    preview = await previews.prepare(str(path))

    assert preview.excerpt == "First slide"


@pytest.mark.asyncio
async def test_excel_excerpt_reads_shared_and_inline_cell_text(tmp_path: Path) -> None:
    path = tmp_path / "numbers.xlsx"
    _ooxml(path, {
        "xl/workbook.xml": (
            '<workbook xmlns:r="urn:relationships"><sheets><sheet r:id="rId2"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Target="worksheets/sheet2.xml"/></Relationships>'
        ),
        "xl/sharedStrings.xml": (
            '<sst xmlns="urn:sheet"><si><t>Owners</t></si><si><r><t>Runs</t></r><r><t> locally</t></r></si></sst>'
        ),
        "xl/worksheets/sheet1.xml": '<worksheet xmlns="urn:sheet"><sheetData><row><c><v>ignored</v></c></row></sheetData></worksheet>',
        "xl/worksheets/sheet2.xml": (
            '<worksheet xmlns="urn:sheet"><sheetData><row><c t="s"><v>0</v></c><c t="s"><v>1</v></c>'
            '<c t="inlineStr"><is><t>daily</t></is></c><c><v>42</v></c></row></sheetData></worksheet>'
        ),
    })

    preview = await previews.prepare(str(path))

    assert preview.excerpt == "Owners Runs locally daily 42"


@pytest.mark.asyncio
async def test_excel_excerpt_works_without_shared_strings(tmp_path: Path) -> None:
    path = tmp_path / "inline.xlsx"
    _ooxml(path, {
        "xl/workbook.xml": '<workbook xmlns:r="urn:relationships"><sheets><sheet r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": (
            '<worksheet xmlns="urn:sheet"><sheetData><row><c t="inlineStr"><is><t>Only inline</t></is></c>'
            "</row></sheetData></worksheet>"
        ),
    })

    assert (await previews.prepare(str(path))).excerpt == "Only inline"


@pytest.mark.asyncio
async def test_office_xml_declarations_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad.docx"
    _ooxml(path, {"word/document.xml": '<!DOCTYPE x [<!ENTITY e "expanded">]><x>&e;</x>'})

    with pytest.raises(previews.PreviewError, match="xml_declarations_refused"):
        await previews.prepare(str(path))


@pytest.mark.asyncio
async def test_office_utf16_xml_is_refused_before_entity_parsing(tmp_path: Path) -> None:
    path = tmp_path / "utf16.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            '<!DOCTYPE x [<!ENTITY e "expanded">]><x>&e;</x>'.encode("utf-16"),
        )

    with pytest.raises(previews.PreviewError, match="xml_encoding_refused"):
        await previews.prepare(str(path))


@pytest.mark.asyncio
async def test_office_archive_entry_limit_applies_to_word_documents(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "many.docx"
    _ooxml(path, {"word/document.xml": "<document/>", "word/extra.xml": "<extra/>"})
    monkeypatch.setattr(previews, "ZIP_ENTRY_LIMIT", 1)

    with pytest.raises(previews.PreviewError, match="archive_too_many_entries"):
        await previews.prepare(str(path))


def test_large_office_part_may_be_truncated_mid_utf8_character(tmp_path: Path) -> None:
    path = tmp_path / "large.docx"
    prefix = b"<document>start</document><document>"
    part = prefix + b"a" * (previews.PART_LIMIT - len(prefix) - 1) + "é".encode() + b"</document>"
    _ooxml(path, {"word/document.xml": part})

    with zipfile.ZipFile(path) as archive:
        data, truncated = previews._read_part(archive, "word/document.xml")

    assert truncated and len(data) == previews.PART_LIMIT and data[-1:] == b"\xc3"


@pytest.mark.asyncio
async def test_preview_access_reuses_only_read_scope_or_an_exact_read_approval(tmp_path: Path) -> None:
    home = tmp_path / "home"
    documents = home / "Documents"
    documents.mkdir(parents=True)
    inside = documents / "brief.pdf"
    outside = tmp_path / "approved.pdf"
    secret = documents / ".env"
    inside.touch()
    outside.touch()
    secret.touch()
    scope = ReadScope([str(documents)], home=str(home))

    assert scope.permits_preview(str(inside), set())
    assert not scope.permits_preview(str(outside), set())
    assert scope.permits_preview(str(outside), {scope.key(str(outside))})
    assert not scope.permits_preview(str(secret), {scope.key(str(secret))})


@pytest.mark.asyncio
async def test_worker_preview_is_refused_outside_the_run_read_scope(tmp_path: Path) -> None:
    path = tmp_path / "outside" / "brief.docx"
    shape, problems = shapes.check({"shape": "preview", "path": str(path)})
    assert problems == [] and shape is not None
    run = _Run()

    message = await _show_checked_shape(run, shape, ReadScope([], home=str(tmp_path)), None)

    assert "allowed to read" in message
    assert run.shape is None and run.preview is None


@pytest.mark.asyncio
async def test_worker_preview_can_reuse_an_exactly_approved_read(tmp_path: Path) -> None:
    path = tmp_path / "outside" / "brief.docx"
    path.parent.mkdir()
    _ooxml(path, {"word/document.xml": '<w:document xmlns:w="urn:word"><w:t>Approved text</w:t></w:document>'})
    shape, problems = shapes.check({"shape": "preview", "path": str(path)})
    assert problems == [] and shape is not None
    reads = ReadScope([], home=str(tmp_path))
    run = _Run(approved_reads={reads.key(str(path))})

    message = await _show_checked_shape(run, shape, reads, None)

    assert message
    assert run.preview is not None and run.preview.excerpt == "Approved text"
    assert run.shape == shape


def _pdf() -> bytes:
    content = b"BT /F1 14 Tf 40 100 Td (Preview test) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    data = b"%PDF-1.4\n"
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n"
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    data += f"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return data


@pytest.mark.windows
@pytest.mark.asyncio
async def test_pdf_preview_renders_one_bounded_png_with_page_count(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(_pdf())

    preview = await previews.prepare(str(path))

    image = base64.b64decode(preview.thumbnail or "")
    assert preview.kind == "pdf" and preview.pages == 1
    assert image.startswith(previews.PNG_SIGNATURE) and len(image) <= previews.PNG_LIMIT
    assert int.from_bytes(image[16:20], "big") <= 512
    assert int.from_bytes(image[20:24], "big") <= 720
