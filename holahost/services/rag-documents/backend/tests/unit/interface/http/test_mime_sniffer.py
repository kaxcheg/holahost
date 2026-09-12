"""Unit tests for content-based MIME sniffing."""

from interface.http.mime_sniffer import sniff_mime_type


class TestSniffMimeType:
    def test_pdf_magic_bytes(self) -> None:
        assert sniff_mime_type(b"%PDF-1.4\n...", filename="doc.pdf") == "application/pdf"

    def test_pdf_ignores_wrong_extension(self) -> None:
        assert sniff_mime_type(b"%PDF-1.4\n...", filename="doc.txt") == "application/pdf"

    def test_docx_zip_with_word_document_xml(self) -> None:
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", "<xml/>")
        content = buf.getvalue()

        result = sniff_mime_type(content, filename="doc.docx")

        assert result == ("application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    def test_zip_without_word_document_xml_is_unsupported(self) -> None:
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "not a docx")

        result = sniff_mime_type(buf.getvalue(), filename="doc.docx")

        assert result == "application/zip"  # outside ALLOWED_MIME_TYPES -> 415, not 400

    def test_markdown_by_extension(self) -> None:
        assert sniff_mime_type(b"# Title\n\nBody", filename="guide.md") == "text/markdown"

    def test_plain_text_default(self) -> None:
        assert sniff_mime_type(b"just some text", filename="guide.txt") == "text/plain"

    def test_no_filename_defaults_to_plain(self) -> None:
        assert sniff_mime_type(b"just some text", filename=None) == "text/plain"

    def test_binary_non_pdf_non_zip_is_unsupported(self) -> None:
        result = sniff_mime_type(b"\x89PNG\r\n\x1a\n...", filename="image.png")
        assert result == "application/octet-stream"  # outside ALLOWED_MIME_TYPES -> 415
