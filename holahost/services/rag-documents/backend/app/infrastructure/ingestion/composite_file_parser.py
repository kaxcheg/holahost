from __future__ import annotations

import io
import zipfile

import pymupdf
from docx import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError

from application.exceptions import DocumentParseError, UnsupportedMediaTypeError
from application.ports.ingestion import TextFragment
from domain.value_objects.mime_type import ALLOWED_MIME_TYPES, MimeType
from domain.value_objects.page_number import PageNumber

_PDF = "application/pdf"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PLAIN_TEXT = frozenset({"text/plain", "text/markdown"})


class CompositeFileParser:
    """Adapter for the `FileParser` port — routes by MIME to pymupdf / python-docx / utf-8
    decode. Parsing itself writes nothing and shells out to nothing: it works on the
    `bytes` it is handed, in-process. How the upload got there is the transport's
    business — Starlette spools a large body to an anonymous temp file, which is why the
    guarantee is that the file is never *stored*, not that bytes never touch a disk.
    """

    def parse(self, content: bytes, mime_type: MimeType) -> list[TextFragment]:
        # The final branch is unreachable via any legitimately-constructed `MimeType`
        # today — its own `__post_init__` already rejects anything outside
        # `ALLOWED_MIME_TYPES`, which maps 1:1 onto the three branches below. Kept as a
        # defense-in-depth safety net (declared in the `FileParser` port's `raises`)
        # against future drift if `ALLOWED_MIME_TYPES` ever gains a member without a
        # matching parser branch — not exercised by a test for exactly that reason.
        value = mime_type.value
        if value == _PDF:
            return self._parse_pdf(content)
        if value == _DOCX:
            return self._parse_docx(content)
        if value in _PLAIN_TEXT:
            return self._parse_plain_text(content)
        raise UnsupportedMediaTypeError(allowed=tuple(sorted(ALLOWED_MIME_TYPES)))

    @staticmethod
    def _parse_pdf(content: bytes) -> list[TextFragment]:
        # Blank pages (common between chapters, or a fully image-only PDF) yield no
        # text — `TextFragment` rejects empty/whitespace-only text (application port
        # invariant), so they're skipped here rather than constructed. A PDF with
        # nothing extractable on any page ends up an empty list, which the use case's
        # own `MIN_EXTRACTED_TEXT_CHARS` check then correctly rejects — not a
        # crash on the first blank page.
        try:
            with pymupdf.open(stream=content, filetype="pdf") as doc:
                return [
                    TextFragment(text=text, page=PageNumber(index + 1))
                    for index, page in enumerate(doc)
                    if (text := page.get_text()).strip()
                ]
        except (pymupdf.FileDataError, ValueError, RuntimeError) as e:
            raise DocumentParseError from e

    @staticmethod
    def _parse_docx(content: bytes) -> list[TextFragment]:
        try:
            document = DocxDocument(io.BytesIO(content))
        except (PackageNotFoundError, zipfile.BadZipFile, ValueError) as e:
            raise DocumentParseError from e
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        # Same "no blank fragment" reasoning as `_parse_pdf`: an empty/whitespace-only
        # document becomes an empty list, not a `TextFragment` construction crash.
        if not text.strip():
            return []
        return [TextFragment(text=text, page=PageNumber(None))]

    @staticmethod
    def _parse_plain_text(content: bytes) -> list[TextFragment]:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as e:
            raise DocumentParseError from e
        if not text.strip():
            return []
        return [TextFragment(text=text, page=PageNumber(None))]
