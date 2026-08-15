"""Content-based MIME type resolution (spec §7.2, §3.8) — never trusts a client-supplied
label (multipart Content-Type, filename) except for the one case content genuinely
cannot resolve: text/markdown vs. text/plain, where the filename's extension is the
only available signal.
"""

from __future__ import annotations

import io
import zipfile

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def sniff_mime_type(content: bytes, filename: str | None) -> str:
    """Determine a file's real MIME type from its bytes.

    :param content: Raw file bytes.
    :param filename: The uploaded filename, if any — used only for the markdown/plain
        split; irrelevant to every other branch.
    :return: A MIME type string. Not guaranteed to be a member of
        `domain.value_objects.mime_type.ALLOWED_MIME_TYPES` — an unrecognized binary
        format deliberately returns a type outside that whitelist so `MimeType`'s own
        check rejects it (415 `ERR_UNSUPPORTED_MEDIA_TYPE`), rather than silently
        defaulting to text and failing later with a confusing parse error.
    """
    if content.startswith(_PDF_MAGIC):
        return "application/pdf"
    if content[:4] == _ZIP_MAGIC:
        return _DOCX_MIME if _has_word_document_xml(content) else "application/zip"
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"
    return "text/markdown" if (filename or "").lower().endswith(".md") else "text/plain"


def _has_word_document_xml(content: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False
