from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING

import pymupdf
from docx import Document
from docx.opc.exceptions import PackageNotFoundError

from application.exceptions import InvalidPayloadError, UnsupportedMediaTypeError
from domain.value_objects.parsed_segment import ParsedSegment

_PDF = "application/pdf"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_TEXT = frozenset({"text/plain", "text/markdown"})
_SUPPORTED = sorted({_PDF, _DOCX, *_TEXT})


class CompositeFileParser:
    """FileParser adapter routing by MIME to pymupdf / python-docx / plain decode (spec §8.2.1, §2.5).

    PDF -> one ``ParsedSegment`` per page (0-based ``page``); DOCX -> a single whole-document segment
    (``page=None``, body paragraphs joined — table cells are NOT extracted, MVP limitation); MD/TXT ->
    a single decoded segment (``page=None``). All parsing is in-memory (no temp files). MIME routing is
    defense-in-depth: the use case already pre-validates the MIME against the allow-list (§9.0); an
    unknown MIME here still maps to ``UnsupportedMediaTypeError``. Corrupt / undecodable bytes map to
    ``InvalidPayloadError(field='file', reason='invalid_format')`` (D2) — the use case does NOT wrap
    ``parse`` in error mapping, so a 500 would leak otherwise.

    Structurally conforms to the FileParser port (no inheritance): see ``_conforms``.
    """

    def parse(self, file_bytes: bytes, mime_type: str) -> list[ParsedSegment]:
        """Parse ``file_bytes`` into page-annotated segments (see port).

        :raises UnsupportedMediaTypeError: unsupported ``mime_type``.
        :raises InvalidPayloadError: corrupt or undecodable file content.
        """
        if mime_type == _PDF:
            return self._parse_pdf(file_bytes)
        if mime_type == _DOCX:
            return self._parse_docx(file_bytes)
        if mime_type in _TEXT:
            return self._parse_text(file_bytes)
        raise UnsupportedMediaTypeError(allowed=_SUPPORTED)

    @staticmethod
    def _parse_pdf(file_bytes: bytes) -> list[ParsedSegment]:
        try:
            with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:  # type: ignore[no-untyped-call]  # pymupdf ships no stubs
                return [
                    ParsedSegment(text=page.get_text(), page=index)
                    for index, page in enumerate(doc)
                ]
        except (pymupdf.FileDataError, ValueError, RuntimeError) as exc:
            raise InvalidPayloadError(field="file", reason="invalid_format") from exc

    @staticmethod
    def _parse_docx(file_bytes: bytes) -> list[ParsedSegment]:
        try:
            document = Document(io.BytesIO(file_bytes))
        except (PackageNotFoundError, zipfile.BadZipFile, ValueError) as exc:
            raise InvalidPayloadError(field="file", reason="invalid_format") from exc
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        return [ParsedSegment(text=text, page=None)]

    @staticmethod
    def _parse_text(file_bytes: bytes) -> list[ParsedSegment]:
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidPayloadError(field="file", reason="invalid_format") from exc
        return [ParsedSegment(text=text, page=None)]


if TYPE_CHECKING:
    from application.ports.ingestion import FileParser

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: CompositeFileParser) -> FileParser:
        return x
