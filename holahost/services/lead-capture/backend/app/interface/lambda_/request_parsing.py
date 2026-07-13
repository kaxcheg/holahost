"""Parse AWS Lambda Function URL events into application command DTOs (spec §8.5 / §9.0).

Each ``parse_*`` builds the primitive ``*Cmd`` for one endpoint. Validation is split (C-19 / C-36):

* **This layer owns shape/contract validation.** JSON bodies are validated against a per-endpoint
  pydantic model (required fields + types); a malformed request — unparseable JSON, a missing
  required field, or a wrong-typed value — raises ``InvalidPayloadError(reason="invalid_json")`` →
  422. The models are SHAPE-ONLY (no value constraints), so a present empty string passes and the
  use case reports ``reason="empty"`` — keeping a frontend contract bug distinct from a user-empty
  value. Multipart uploads are parsed with ``python_multipart`` (same ``invalid_json`` contract).
* **The use cases own value/semantic validation** (empty / format / length, via the VO
  constructors, §9.0).

Secrets are wrapped in ``SecretStr``; header-sourced auth (magic-link / BYOK) stays lenient
(absent → ``""`` → 401 in the use case — an auth outcome, not a payload-shape error).
"""

from __future__ import annotations

import base64
from io import BytesIO
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError
from python_multipart import parse_form

from application.dto.generate import GenerateResponseCmd
from application.dto.ingestion import UploadGuidebookCmd
from application.dto.leads import CaptureLeadCmd, ResolveMagicLinkCmd
from application.dto.sample import SampleGenerateCmd
from application.exceptions import InvalidPayloadError
from infrastructure.common.sha256_ip_hasher import Sha256IpHasher

if TYPE_CHECKING:
    from config.config import Settings

API_KEY_HEADER = "X-Api-Key"
MAGIC_LINK_HEADER = "X-Magic-Link"


class _RequestBody(BaseModel):
    """Base for endpoint request-body models — SHAPE-only (types/required), no value constraints.

    Value validation (empty / format / length) stays in the use cases (§9.0), so a present empty
    string passes here and is reported as ``reason="empty"`` downstream — distinct from a missing
    field (``reason="invalid_json"``). Unknown fields are ignored (forgiving on extras).
    """

    model_config = ConfigDict(extra="ignore")


class _SampleBody(_RequestBody):
    message: str


class _CaptureBody(_RequestBody):
    email: str
    flow: str
    honeypot: str = ""


class _GenerateBody(_RequestBody):
    message: str


def _headers(event: dict[str, Any]) -> dict[str, str]:
    """Return the event headers as a lowercase-keyed dict (Function URL keys are case-insensitive)."""
    raw = event.get("headers") or {}
    return {str(k).lower(): str(v) for k, v in raw.items()}


def _body_bytes(event: dict[str, Any]) -> bytes:
    """Return the raw request body bytes.

    Function URL v2.0 delivers ``body`` as a string: base64 when ``isBase64Encoded`` is true (binary
    payloads — multipart uploads), otherwise the UTF-8 text body (JSON). Multipart file content is
    binary, so the body is handled as bytes throughout.
    """
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    return body.encode("utf-8") if isinstance(body, str) else bytes(body)


def _validate_body[BodyT: _RequestBody](model: type[BodyT], event: dict[str, Any]) -> BodyT:
    """Parse + shape-validate the JSON body against ``model``.

    :raises InvalidPayloadError: on unparseable JSON, a missing required field, or a wrong-typed
        value (``reason="invalid_json"``, ``field`` from the first error) — a malformed request,
        distinct from a user-empty value (which the use case validates as ``reason="empty"``).
    """
    try:
        return model.model_validate_json(_body_bytes(event) or b"{}")
    except ValidationError as exc:
        errors = exc.errors()
        loc = errors[0]["loc"] if errors else ()
        raise InvalidPayloadError(
            field=str(loc[0]) if loc else None, reason="invalid_json"
        ) from exc


def _ip_hash(event: dict[str, Any], settings: Settings) -> str:
    """Compute the SHA-256 IP hash (the ``ip_hash: str`` Cmd field) from the source IP."""
    ip = event["requestContext"]["http"]["sourceIp"]
    return Sha256IpHasher(settings.ip_hash_salt).hash(ip).value


def _magic_link(event: dict[str, Any]) -> SecretStr:
    return SecretStr(_headers(event).get(MAGIC_LINK_HEADER.lower(), ""))


def parse_sample_generate(event: dict[str, Any], settings: Settings) -> SampleGenerateCmd:
    """POST /api/capture-lead/sample/generate → SampleGenerateCmd."""
    body = _validate_body(_SampleBody, event)
    return SampleGenerateCmd(message=body.message, ip_hash=_ip_hash(event, settings))


def parse_capture_lead(event: dict[str, Any], settings: Settings) -> CaptureLeadCmd:
    """POST /api/capture-lead/leads/capture → CaptureLeadCmd."""
    body = _validate_body(_CaptureBody, event)
    return CaptureLeadCmd(
        email=body.email,
        flow=body.flow,
        ip_hash=_ip_hash(event, settings),
        ua_short=_headers(event).get("user-agent"),
        honeypot=body.honeypot,
    )


def parse_resolve_magic_link(event: dict[str, Any], settings: Settings) -> ResolveMagicLinkCmd:
    """GET /api/capture-lead/magic-link/resolve → ResolveMagicLinkCmd (token from the X-Magic-Link header)."""
    return ResolveMagicLinkCmd(magic_link=_magic_link(event), ip_hash=_ip_hash(event, settings))


def parse_generate_response(event: dict[str, Any], settings: Settings) -> GenerateResponseCmd:
    """POST /api/capture-lead/generate → GenerateResponseCmd (magic-link + BYOK key from headers)."""
    body = _validate_body(_GenerateBody, event)
    return GenerateResponseCmd(
        magic_link=_magic_link(event),
        byok=SecretStr(_headers(event).get(API_KEY_HEADER.lower(), "")),
        message=body.message,
        ip_hash=_ip_hash(event, settings),
    )


def parse_upload_guidebook(event: dict[str, Any], settings: Settings) -> UploadGuidebookCmd:
    """POST /api/capture-lead/ingest/upload → UploadGuidebookCmd (multipart ``name`` + ``file``, §5.6)."""
    name, file_bytes, mime_type = _parse_multipart(event)
    return UploadGuidebookCmd(
        magic_link=_magic_link(event),
        ip_hash=_ip_hash(event, settings),
        name=name,
        file_bytes=file_bytes,
        mime_type=mime_type,
    )


def _parse_multipart(event: dict[str, Any]) -> tuple[str, bytes, str]:
    """Extract ``(name, file_bytes, mime_type)`` from a multipart/form-data body (§5.6).

    Shape/contract checks live here (C-36): a non-multipart content type, or a missing ``name`` field
    / ``file`` part, is a malformed request → ``InvalidPayloadError(reason="invalid_json")``. A present
    name/file (even empty) flows to the use case, which validates size / MIME / emptiness (§5.6).

    :raises InvalidPayloadError: on a non-multipart content type or a missing required part.
    """
    content_type = _headers(event).get("content-type", "")
    if "multipart/form-data" not in content_type:
        raise InvalidPayloadError(field="file", reason="invalid_json")
    fields: dict[str, str] = {}
    files: list[Any] = []

    def on_field(field: Any) -> None:
        fields[field.field_name.decode()] = (field.value or b"").decode()

    def on_file(file: Any) -> None:
        files.append(file)

    parse_form(
        {"Content-Type": content_type.encode()}, BytesIO(_body_bytes(event)), on_field, on_file
    )
    if "name" not in fields:
        raise InvalidPayloadError(field="name", reason="invalid_json")
    if not files:
        raise InvalidPayloadError(field="file", reason="invalid_json")
    upload = files[0]
    upload.file_object.seek(0)
    file_bytes: bytes = upload.file_object.read()
    return fields["name"], file_bytes, (upload.content_type or "")
