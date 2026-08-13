from __future__ import annotations

import io

import pymupdf
import pytest
from docx import Document as DocxDocument

from application.exceptions import DocumentParseError
from domain.value_objects.mime_type import MimeType
from infrastructure.ingestion.composite_file_parser import CompositeFileParser


def _make_pdf_bytes(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for page_text in pages:
        page = doc.new_page()
        if page_text:
            page.insert_text((72, 72), page_text)
    data: bytes = doc.tobytes()  # pymupdf's stub types this untyped/Any; it is bytes at runtime
    doc.close()
    return data


def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    doc = DocxDocument()
    for text in paragraphs:
        doc.add_paragraph(text)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


class TestCompositeFileParser:
    def test_pdf_one_fragment_per_page_1_indexed(self) -> None:
        content = _make_pdf_bytes(["first page", "second page"])
        fragments = CompositeFileParser().parse(content, MimeType("application/pdf"))
        assert len(fragments) == 2
        assert fragments[0].page.value == 1
        assert fragments[1].page.value == 2
        assert "first page" in fragments[0].text
        assert "second page" in fragments[1].text

    def test_pdf_blank_page_is_skipped_not_crashed_on(self) -> None:
        content = _make_pdf_bytes(["first page", "", "third page"])
        fragments = CompositeFileParser().parse(content, MimeType("application/pdf"))
        assert len(fragments) == 2
        assert fragments[0].page.value == 1
        assert fragments[1].page.value == 3  # blank page 2 skipped, provenance preserved

    def test_fully_blank_pdf_returns_empty_list(self) -> None:
        content = _make_pdf_bytes(["", ""])
        fragments = CompositeFileParser().parse(content, MimeType("application/pdf"))
        assert fragments == []

    def test_corrupt_pdf_raises_document_parse_error(self) -> None:
        with pytest.raises(DocumentParseError):
            CompositeFileParser().parse(b"not a pdf", MimeType("application/pdf"))

    def test_docx_single_pageless_fragment(self) -> None:
        content = _make_docx_bytes(["Hello", "World"])
        fragments = CompositeFileParser().parse(
            content,
            MimeType("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        )
        assert len(fragments) == 1
        assert fragments[0].page.value is None
        assert "Hello" in fragments[0].text
        assert "World" in fragments[0].text

    def test_blank_docx_returns_empty_list(self) -> None:
        content = _make_docx_bytes([])
        fragments = CompositeFileParser().parse(
            content,
            MimeType("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        )
        assert fragments == []

    def test_corrupt_docx_raises_document_parse_error(self) -> None:
        with pytest.raises(DocumentParseError):
            CompositeFileParser().parse(
                b"not a docx",
                MimeType("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            )

    def test_plain_text_single_pageless_fragment(self) -> None:
        fragments = CompositeFileParser().parse("héllo".encode(), MimeType("text/plain"))
        assert len(fragments) == 1
        assert fragments[0].text == "héllo"
        assert fragments[0].page.value is None

    def test_blank_plain_text_returns_empty_list(self) -> None:
        fragments = CompositeFileParser().parse(b"   \n  ", MimeType("text/plain"))
        assert fragments == []

    def test_invalid_utf8_raises_document_parse_error(self) -> None:
        with pytest.raises(DocumentParseError):
            CompositeFileParser().parse(b"\xff\xfe\x00", MimeType("text/plain"))

    # No test for the parser's own `UnsupportedMediaTypeError` fallback: `MimeType`'s
    # constructor already rejects anything outside `ALLOWED_MIME_TYPES` (which maps
    # 1:1 onto this parser's three branches), so there is no legitimately-constructed
    # `MimeType` value that reaches it — see the comment on `parse()`.
