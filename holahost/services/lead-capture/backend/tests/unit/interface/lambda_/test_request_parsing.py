import base64
import json
from typing import Any

import pytest

from application.exceptions import InvalidPayloadError
from interface.lambda_ import request_parsing as rp
from tests._support.settings import make_settings


def _evt(
    *,
    method: str = "POST",
    path: str = "/api/lead-capture/sample/generate",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    b64: bool = False,
    ip: str = "1.2.3.4",
) -> dict[str, Any]:
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": method, "sourceIp": ip}},
        "headers": headers or {},
        "body": body,
        "isBase64Encoded": b64,
    }


def test_parse_sample_generate() -> None:
    cmd = rp.parse_sample_generate(_evt(body=json.dumps({"message": "hola"})), make_settings())
    assert cmd.message == "hola"
    assert len(cmd.ip_hash) == 64  # sha256 hex


def test_parse_capture_lead_reads_fields_and_ua() -> None:
    evt = _evt(
        path="/api/lead-capture/leads/capture",
        headers={"user-agent": "Mozilla/5.0"},
        body=json.dumps({"email": "h@example.com", "flow": "guidebook", "honeypot": ""}),
    )
    cmd = rp.parse_capture_lead(evt, make_settings())
    assert cmd.email == "h@example.com"
    assert cmd.flow == "guidebook"
    assert cmd.ua_short == "Mozilla/5.0"
    assert cmd.honeypot == ""


def test_parse_resolve_magic_link_from_header() -> None:
    evt = _evt(
        method="GET", path="/api/lead-capture/magic-link/resolve", headers={"x-magic-link": "MTOK"}
    )
    cmd = rp.parse_resolve_magic_link(evt, make_settings())
    assert cmd.magic_link.get_secret_value() == "MTOK"
    assert len(cmd.ip_hash) == 64


def test_parse_generate_response_reads_secrets() -> None:
    evt = _evt(
        path="/api/lead-capture/generate",
        headers={"x-magic-link": "MTOK", "x-api-key": "sk-byok"},
        body=json.dumps({"message": "q"}),
    )
    cmd = rp.parse_generate_response(evt, make_settings())
    assert cmd.magic_link.get_secret_value() == "MTOK"
    assert cmd.byok.get_secret_value() == "sk-byok"
    assert cmd.message == "q"


def test_base64_body_decoded() -> None:
    raw = base64.b64encode(json.dumps({"message": "x"}).encode()).decode()
    cmd = rp.parse_sample_generate(_evt(body=raw, b64=True), make_settings())
    assert cmd.message == "x"


def test_unicode_json_body_decoded_utf8() -> None:
    # Real Lambda delivers a non-base64 JSON body as a UTF-8 string; latin-1 would crash on these.
    body = json.dumps({"message": "¿Dónde? Привет 🚀"}, ensure_ascii=False)
    cmd = rp.parse_sample_generate(_evt(body=body), make_settings())
    assert cmd.message == "¿Dónde? Привет 🚀"


def test_missing_or_non_string_required_field_raises_invalid_json() -> None:
    # Absent / null / wrong-type required field = malformed request (frontend contract bug),
    # distinct from a user-empty value (C-36): 422 ERR_INVALID_PAYLOAD reason="invalid_json".
    for body in (json.dumps({}), json.dumps({"message": None}), json.dumps({"message": 42})):
        with pytest.raises(InvalidPayloadError) as exc:
            rp.parse_sample_generate(_evt(body=body), make_settings())
        assert exc.value.code == "ERR_INVALID_PAYLOAD"
        assert exc.value.reason == "invalid_json"


def test_present_empty_required_field_is_a_user_value() -> None:
    # Present + "" is a USER value → flows through; the use case reports reason="empty".
    cmd = rp.parse_sample_generate(_evt(body=json.dumps({"message": ""})), make_settings())
    assert cmd.message == ""


def test_unparseable_json_body_raises_invalid_json() -> None:
    with pytest.raises(InvalidPayloadError) as exc:
        rp.parse_sample_generate(_evt(body="{not valid json"), make_settings())
    assert exc.value.reason == "invalid_json"


def test_capture_missing_required_field_raises_invalid_json() -> None:
    body = json.dumps({"flow": "guidebook"})  # email absent
    with pytest.raises(InvalidPayloadError) as exc:
        rp.parse_capture_lead(
            _evt(path="/api/lead-capture/leads/capture", body=body), make_settings()
        )
    assert exc.value.field == "email"
    assert exc.value.reason == "invalid_json"


def test_capture_honeypot_optional_defaults_empty() -> None:
    body = json.dumps({"email": "h@example.com", "flow": "guidebook"})  # honeypot absent → ""
    cmd = rp.parse_capture_lead(
        _evt(path="/api/lead-capture/leads/capture", body=body), make_settings()
    )
    assert cmd.honeypot == ""


def test_upload_missing_name_raises_invalid_json() -> None:
    raw = (
        b'--B\r\nContent-Disposition: form-data; name="file"; filename="g.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n%PDF data\r\n--B--\r\n"
    )
    evt = _evt(
        path="/api/lead-capture/ingest/upload",
        headers={"x-magic-link": "M", "content-type": "multipart/form-data; boundary=B"},
        body=base64.b64encode(raw).decode("ascii"),
        b64=True,
    )
    with pytest.raises(InvalidPayloadError) as exc:
        rp.parse_upload_guidebook(evt, make_settings())
    assert exc.value.field == "name"


def test_upload_missing_file_raises_invalid_json() -> None:
    raw = b'--B\r\nContent-Disposition: form-data; name="name"\r\n\r\nMy Place\r\n--B--\r\n'
    evt = _evt(
        path="/api/lead-capture/ingest/upload",
        headers={"x-magic-link": "M", "content-type": "multipart/form-data; boundary=B"},
        body=base64.b64encode(raw).decode("ascii"),
        b64=True,
    )
    with pytest.raises(InvalidPayloadError) as exc:
        rp.parse_upload_guidebook(evt, make_settings())
    assert exc.value.field == "file"


def test_parse_upload_multipart() -> None:
    # Lambda ships binary multipart base64-encoded (isBase64Encoded=true). File content includes
    # non-UTF-8 bytes to prove binary-safety.
    file_content = b"%PDF-1.4 \x00\xff binary"
    raw = (
        b'--B\r\nContent-Disposition: form-data; name="name"\r\n\r\nMy Place\r\n'
        b'--B\r\nContent-Disposition: form-data; name="file"; filename="g.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n" + file_content + b"\r\n--B--\r\n"
    )
    evt = _evt(
        path="/api/lead-capture/ingest/upload",
        headers={"x-magic-link": "MTOK", "content-type": "multipart/form-data; boundary=B"},
        body=base64.b64encode(raw).decode("ascii"),
        b64=True,
    )
    cmd = rp.parse_upload_guidebook(evt, make_settings())
    assert cmd.name == "My Place"
    assert cmd.mime_type == "application/pdf"
    assert cmd.file_bytes == file_content
    assert cmd.magic_link.get_secret_value() == "MTOK"
