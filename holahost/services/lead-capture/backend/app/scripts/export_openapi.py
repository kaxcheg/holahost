"""Export the backend HTTP contract to ``docs/openapi.yaml`` (spec §11.3 / §5 / §10.8).

Single source of truth for the frontend type codegen (``openapi-typescript`` -> ``generated.ts``,
ticket F-06). The document is DERIVED from the live backend symbols, so it cannot silently drift:

* paths / methods          <- ``interface.lambda_.router._ROUTES`` (integrity-checked below)
* request body schemas     <- the pydantic shape models in ``request_parsing`` (``model_json_schema``)
* success response schemas <- the result dataclasses in ``application.dto.*`` (mirrors ``asdict``)
* error ``code`` enum + statuses <- ``interface.lambda_.response_envelope.HTTP_STATUS_BY_CODE``

Run with ``make -C backend export-openapi``; the CI drift guard is ``make -C backend check-openapi``.

The document is emitted as JSON, which is a strict subset of YAML 1.2 -- so ``docs/openapi.yaml`` is
valid YAML (consumed by ``openapi-typescript``) and valid JSON, while needing no YAML dependency.

OpenAPI paths are the sub-paths under a ``/api/capture-lead`` server (e.g. ``/sample/generate``), matching
the frontend ``VITE_API_BASE_URL=/api/capture-lead`` convention (§11.6): server URL + path = the backend
``rawPath`` (``/api/capture-lead/sample/generate``). The service is mounted at ``/api/capture-lead`` by the
Holahost gateway (API-Gateway model: ``/api/<service>/*``).
"""

from __future__ import annotations

import dataclasses
import json
import os
import types
import typing
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from application.dto.generate import GenerateResponseResult
from application.dto.ingestion import IngestionResult
from application.dto.leads import ResolveMagicLinkResult
from application.dto.sample import SampleGenerateResult
from application.exceptions import ApplicationError
from interface.lambda_.request_parsing import (
    API_KEY_HEADER,
    MAGIC_LINK_HEADER,
    _CaptureBody,
    _GenerateBody,
    _SampleBody,
)
from interface.lambda_.response_envelope import HTTP_STATUS_BY_CODE, InternalDetails
from interface.lambda_.router import _ROUTES

# This file: holahost/services/lead-capture/backend/app/scripts/export_openapi.py; parents[3] == the
# lead-capture service root, where docs/ sits next to backend/ (both owned by the microservice).
_OUTPUT_PATH = Path(__file__).resolve().parents[3] / "docs" / "openapi.yaml"

# Single source of the mount prefix: API_BASE_URL (§11.6), the same value the router strips and the
# gateway routes; the canonical default keeps `make export-openapi` runnable offline.
_API_PREFIX = os.getenv("API_BASE_URL", "/api/capture-lead")

# Per-endpoint contract metadata (§5). ``path`` is the service-relative sub-path — it IS the router
# ``_ROUTES`` key and the emitted OpenAPI path; the mount prefix lives only in the ``_API_PREFIX`` server.
_ENDPOINTS: list[dict[str, Any]] = [
    {
        "method": "POST",
        "path": "/sample/generate",
        "summary": "Sample-flow reply generated on the server key (§5.3, US-01).",
        "headers": [],
        "request_json": "SampleGenerateRequest",
        "response": "SampleGenerateResult",
        "errors": [
            "ERR_RATE_LIMIT",
            "ERR_SAMPLE_BUDGET_EXHAUSTED",
            "ERR_INVALID_PAYLOAD",
            "ERR_UPSTREAM_LLM",
            "ERR_INTERNAL",
        ],
    },
    {
        "method": "POST",
        "path": "/leads/capture",
        "summary": "Capture an email and send the magic link (§5.4, US-02).",
        "headers": [],
        "request_json": "CaptureLeadRequest",
        "response": "StatusSentResponse",
        "errors": ["ERR_RATE_LIMIT", "ERR_INVALID_PAYLOAD", "ERR_UPSTREAM_EMAIL", "ERR_INTERNAL"],
    },
    {
        "method": "GET",
        "path": "/magic-link/resolve",
        "summary": "Resolve a magic-link token to the lead + guidebook metadata (§5.5, US-03).",
        "headers": [MAGIC_LINK_HEADER],
        "request_json": None,
        "response": "ResolveMagicLinkResult",
        "errors": ["ERR_RATE_LIMIT", "ERR_INVALID_MAGIC_LINK", "ERR_INTERNAL"],
    },
    {
        "method": "POST",
        "path": "/ingest/upload",
        "summary": "Upload a guidebook file or rendered template text (§5.6, US-04/US-05).",
        "headers": [MAGIC_LINK_HEADER],
        "request_multipart": "UploadGuidebookRequest",
        "response": "IngestionResult",
        "errors": [
            "ERR_RATE_LIMIT",
            "ERR_INVALID_MAGIC_LINK",
            "ERR_PAYLOAD_TOO_LARGE",
            "ERR_TOO_MANY_CHUNKS",
            "ERR_UNSUPPORTED_MEDIA_TYPE",
            "ERR_EMPTY_DOCUMENT",
            "ERR_INVALID_PAYLOAD",
            "ERR_INTERNAL",
        ],
    },
    {
        "method": "POST",
        "path": "/generate",
        "summary": "Real-flow reply to a guest message using the host's BYOK key (§5.7, US-06).",
        "headers": [MAGIC_LINK_HEADER, API_KEY_HEADER],
        "request_json": "GenerateRequest",
        "response": "GenerateResponseResult",
        "errors": [
            "ERR_RATE_LIMIT",
            "ERR_INVALID_MAGIC_LINK",
            "ERR_NO_GUIDEBOOK",
            "ERR_INVALID_API_KEY",
            "ERR_INVALID_PAYLOAD",
            "ERR_UPSTREAM_LLM",
            "ERR_INTERNAL",
        ],
    },
]

_PRIMITIVES: dict[type, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _primitive_name(tp: Any) -> str:
    """Map a primitive Python type to its JSON Schema ``type`` name.

    :raises TypeError: if ``tp`` is not a supported primitive (the export only models the
        primitive-only result DTOs of §8.1).
    """
    name = _PRIMITIVES.get(tp)
    if name is None:
        raise TypeError(f"unsupported field type for OpenAPI export: {tp!r}")
    return name


def _type_schema(annotation: Any) -> dict[str, Any]:
    """Map a (possibly ``X | None``) primitive annotation to a JSON Schema fragment.

    Optionals become a JSON-Schema 3.1 nullable type array (``{"type": ["string", "null"]}``) so
    ``openapi-typescript`` renders ``string | null`` -- matching ``dataclasses.asdict`` output where
    the key is always present but the value may be ``None``.
    """
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = typing.get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) != 1:
            raise TypeError(f"unsupported union for OpenAPI export: {annotation!r}")
        base = _primitive_name(non_none[0])
        nullable = len(non_none) != len(args)
        return {"type": [base, "null"]} if nullable else {"type": base}
    if origin is list:
        (item,) = typing.get_args(annotation)
        return {"type": "array", "items": {"type": _primitive_name(item)}}
    return {"type": _primitive_name(annotation)}


def _object_schema(annotations: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON Schema object from an ordered ``name -> annotation`` map.

    Every key is ``required`` (mirrors ``dataclasses.asdict`` / a total ``TypedDict``: the key is
    always present); nullable fields carry a ``["<type>", "null"]`` type array.
    """
    props = {name: _type_schema(tp) for name, tp in annotations.items()}
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def _dataclass_schema(cls: type) -> dict[str, Any]:
    """Build a JSON Schema object for a result dataclass, mirroring ``dataclasses.asdict``."""
    hints = typing.get_type_hints(cls)
    return _object_schema({f.name: hints[f.name] for f in dataclasses.fields(cls)})


def _typeddict_schema(td: Any) -> dict[str, Any]:
    """Build a JSON Schema object for a (total) ``TypedDict`` error-``details`` type (§10.8)."""
    return _object_schema(typing.get_type_hints(td))


def _empty_object_schema() -> dict[str, Any]:
    """The ``details`` schema for codes that carry no detail keys (§10.8): an empty object."""
    return {"type": "object", "properties": {}, "additionalProperties": False}


def _request_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Build a request-body JSON Schema from a pydantic shape model, dropping pydantic ``title`` keys."""
    schema = model.model_json_schema()
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        if isinstance(prop, dict):
            prop.pop("title", None)
    return schema


def _application_error_subclasses() -> list[type[ApplicationError]]:
    """All (transitive) ``ApplicationError`` subclasses, registered by importing the exceptions module."""
    result: list[type[ApplicationError]] = []
    seen: set[type[ApplicationError]] = set()
    stack: list[type[ApplicationError]] = list(ApplicationError.__subclasses__())
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        result.append(cls)
        stack.extend(cls.__subclasses__())
    return result


def _details_schemas_by_code() -> dict[str, dict[str, Any]]:
    """Per-code ``details`` JSON Schema, DERIVED from each error's ``details_dict`` return type (§10.8).

    Each ``ApplicationError`` subclass annotates ``details_dict`` with a ``TypedDict`` (the single
    source, §11.3); subclasses that do not override it inherit the base ``Mapping`` return → empty
    details. ``ERR_INTERNAL`` has no subclass (base default ``code``; its ``details`` are built in
    ``response_envelope.internal``) → sourced from ``InternalDetails``.

    :raises RuntimeError: if two subclasses declare the same ``code``, if a subclass usurps the
        ``ERR_INTERNAL`` code, or if the collected code set differs from ``HTTP_STATUS_BY_CODE`` --
        forcing this exporter to stay in sync whenever an error code is added or removed.
    """
    by_code: dict[str, dict[str, Any]] = {}
    for cls in _application_error_subclasses():
        if cls.code in by_code:
            raise RuntimeError(
                f"duplicate error code {cls.code!r} across ApplicationError subclasses"
            )
        ret = typing.get_type_hints(cls.details_dict).get("return")
        by_code[cls.code] = (
            _typeddict_schema(ret) if typing.is_typeddict(ret) else _empty_object_schema()
        )
    if "ERR_INTERNAL" in by_code:
        raise RuntimeError("ERR_INTERNAL must not have a dedicated ApplicationError subclass")
    by_code["ERR_INTERNAL"] = _typeddict_schema(InternalDetails)

    if set(by_code) != set(HTTP_STATUS_BY_CODE):
        raise RuntimeError(
            "export_openapi error-details are out of sync with HTTP_STATUS_BY_CODE; "
            f"only here: {set(by_code) - set(HTTP_STATUS_BY_CODE)}; "
            f"only in status map: {set(HTTP_STATUS_BY_CODE) - set(by_code)}"
        )
    return by_code


def _error_variant_name(code: str) -> str:
    return f"Error_{code}"


def _error_variant_schema(code: str, details: dict[str, Any]) -> dict[str, Any]:
    """One discriminated ``{code, message, details}`` variant for a single error code (§10.8)."""
    return {
        "type": "object",
        "required": ["code", "message", "details"],
        "additionalProperties": False,
        "properties": {
            "code": {"type": "string", "enum": [code]},
            "message": {"type": "string"},
            "details": details,
        },
    }


def _error_envelope_schema() -> dict[str, Any]:
    """The error envelope ``{"error": <discriminated union on code>}`` (§5.0 / §10.8).

    ``error`` is a ``oneOf`` of one variant per code (each a ``$ref`` to ``Error_<CODE>``); the
    single-value ``code`` enum is the discriminant, so ``openapi-typescript`` renders a TypeScript
    discriminated union that narrows ``details`` by ``code`` (§11.3).
    """
    return {
        "type": "object",
        "required": ["error"],
        "additionalProperties": False,
        "properties": {
            "error": {
                "oneOf": [_ref(_error_variant_name(code)) for code in sorted(HTTP_STATUS_BY_CODE)],
            }
        },
    }


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _json_content(schema_name: str) -> dict[str, Any]:
    return {"application/json": {"schema": _ref(schema_name)}}


def _error_responses(codes: list[str]) -> dict[str, Any]:
    """One response per distinct HTTP status across ``codes``, each the shared ErrorEnvelope (§5)."""
    by_status: dict[int, list[str]] = {}
    for code in codes:
        by_status.setdefault(HTTP_STATUS_BY_CODE[code], []).append(code)
    responses: dict[str, Any] = {}
    for status in sorted(by_status):
        responses[str(status)] = {
            "description": "Error: " + ", ".join(by_status[status]),
            "content": _json_content("ErrorEnvelope"),
        }
    return responses


def _header_param(name: str) -> dict[str, Any]:
    return {"name": name, "in": "header", "required": True, "schema": {"type": "string"}}


def _operation(endpoint: dict[str, Any], operation_id: str) -> dict[str, Any]:
    """Build one OpenAPI operation object from an ``_ENDPOINTS`` entry."""
    responses: dict[str, Any] = {
        "200": {"description": "Success.", "content": _json_content(endpoint["response"])}
    }
    responses.update(_error_responses(endpoint["errors"]))
    responses["default"] = {
        "description": "Unexpected error.",
        "content": _json_content("ErrorEnvelope"),
    }

    operation: dict[str, Any] = {
        "operationId": operation_id,
        "summary": endpoint["summary"],
        "responses": responses,
    }

    headers = endpoint.get("headers") or []
    if headers:
        operation["parameters"] = [_header_param(h) for h in headers]

    if endpoint.get("request_json"):
        operation["requestBody"] = {
            "required": True,
            "content": _json_content(endpoint["request_json"]),
        }
    elif endpoint.get("request_multipart"):
        operation["requestBody"] = {
            "required": True,
            "content": {"multipart/form-data": {"schema": _ref(endpoint["request_multipart"])}},
        }
    return operation


def _build_paths() -> dict[str, Any]:
    """Build the ``paths`` object, asserting the endpoint set matches the live router (drift guard).

    :raises RuntimeError: if ``_ENDPOINTS`` and ``router._ROUTES`` describe different (method, path)
        sets -- forcing this exporter to be updated whenever a backend route is added or removed.
    """
    declared = {(e["method"], e["path"]) for e in _ENDPOINTS}
    registered = set(_ROUTES)
    if declared != registered:
        raise RuntimeError(
            "export_openapi is out of sync with router._ROUTES; "
            f"only here: {declared - registered}; only in router: {registered - declared}"
        )

    paths: dict[str, Any] = {}
    for endpoint in _ENDPOINTS:
        method, sub_path = endpoint["method"], endpoint["path"]
        _parse_fn, attr = _ROUTES[(method, sub_path)]
        paths.setdefault(sub_path, {})[method.lower()] = _operation(endpoint, attr)
    return paths


def _build_document() -> dict[str, Any]:
    """Assemble the full OpenAPI 3.1 document."""
    details_by_code = _details_schemas_by_code()
    schemas: dict[str, Any] = {
        "SampleGenerateRequest": _request_schema(_SampleBody),
        "CaptureLeadRequest": _request_schema(_CaptureBody),
        "GenerateRequest": _request_schema(_GenerateBody),
        "UploadGuidebookRequest": {
            "type": "object",
            "required": ["name", "file"],
            "properties": {
                "name": {"type": "string"},
                "file": {"type": "string", "format": "binary"},
            },
        },
        "SampleGenerateResult": _dataclass_schema(SampleGenerateResult),
        "ResolveMagicLinkResult": _dataclass_schema(ResolveMagicLinkResult),
        "IngestionResult": _dataclass_schema(IngestionResult),
        "GenerateResponseResult": _dataclass_schema(GenerateResponseResult),
        "StatusSentResponse": {
            "type": "object",
            "required": ["status"],
            "additionalProperties": False,
            "properties": {"status": {"type": "string", "enum": ["sent"]}},
        },
        "ErrorEnvelope": _error_envelope_schema(),
    }
    for code in sorted(HTTP_STATUS_BY_CODE):
        schemas[_error_variant_name(code)] = _error_variant_schema(code, details_by_code[code])
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "hola.host API",
            "version": "0.1.0",
            "description": (
                "Generated from the backend contract by app/scripts/export_openapi.py "
                "(spec §11.3) -- do not edit by hand."
            ),
        },
        "servers": [{"url": _API_PREFIX, "description": "Same-origin via CloudFront (§2.1)."}],
        "paths": _build_paths(),
        "components": {"schemas": schemas},
    }


def main() -> None:
    """Write the OpenAPI document to ``docs/openapi.yaml`` (JSON content, valid YAML)."""
    document = _build_document()
    _OUTPUT_PATH.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {_OUTPUT_PATH} ({len(document['paths'])} paths)")


if __name__ == "__main__":
    main()
