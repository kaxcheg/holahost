import io

import pymupdf
import pytest
from docx import Document

from application.exceptions import InvalidPayloadError, UnsupportedMediaTypeError
from infrastructure.ingestion.composite_file_parser import CompositeFileParser

_PDF_MIME = "application/pdf"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _pdf_bytes(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for body in pages:
        page = doc.new_page()
        page.insert_text((72, 72), body)
    return doc.tobytes()


def _docx_bytes(text: str) -> bytes:
    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_pdf_yields_one_segment_per_page_with_page_index() -> None:
    segments = CompositeFileParser().parse(_pdf_bytes(["alpha", "beta"]), _PDF_MIME)
    assert [s.page for s in segments] == [0, 1]
    assert "alpha" in segments[0].text and "beta" in segments[1].text


def test_docx_yields_single_segment_page_none() -> None:
    segments = CompositeFileParser().parse(_docx_bytes("hello docx"), _DOCX_MIME)
    assert len(segments) == 1 and segments[0].page is None
    assert "hello docx" in segments[0].text


def test_plain_text_decoded_page_none() -> None:
    segments = CompositeFileParser().parse(b"plain body", "text/plain")
    assert segments == [type(segments[0])(text="plain body", page=None)]


def test_unknown_mime_raises_unsupported() -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        CompositeFileParser().parse(b"x", "image/png")


def test_corrupt_pdf_raises_invalid_payload() -> None:
    with pytest.raises(InvalidPayloadError):
        CompositeFileParser().parse(b"not really a pdf", _PDF_MIME)


def test_corrupt_docx_raises_invalid_payload() -> None:
    with pytest.raises(InvalidPayloadError):
        CompositeFileParser().parse(b"not really a docx", _DOCX_MIME)


def test_undecodable_text_raises_invalid_payload() -> None:
    with pytest.raises(InvalidPayloadError):
        CompositeFileParser().parse(b"\xff\xfe\x00bad", "text/plain")
