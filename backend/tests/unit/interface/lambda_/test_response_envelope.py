import json

from application.dto.sample import SampleGenerateResult
from application.exceptions import NotFoundError, RateLimitExceededError
from interface.lambda_ import response_envelope as env
from tests._support.settings import make_settings


def test_status_map_complete() -> None:
    assert len(env.HTTP_STATUS_BY_CODE) == 15
    assert env.HTTP_STATUS_BY_CODE["ERR_RATE_LIMIT"] == 429
    assert env.HTTP_STATUS_BY_CODE["ERR_UPSTREAM_LLM"] == 502
    assert env.HTTP_STATUS_BY_CODE["ERR_INVALID_MAGIC_LINK"] == 401
    assert env.HTTP_STATUS_BY_CODE["ERR_INTERNAL"] == 500


def test_from_application_error_envelope() -> None:
    resp = env.from_application_error(
        RateLimitExceededError(scope="ip", retry_after_seconds=30), make_settings()
    )
    assert resp["statusCode"] == 429
    body = json.loads(resp["body"])
    assert body["error"]["code"] == "ERR_RATE_LIMIT"
    assert body["error"]["details"] == {"scope": "ip", "retry_after_s": 30}


def test_not_found_details() -> None:
    resp = env.from_application_error(NotFoundError(resource="guidebook"), make_settings())
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"]["details"] == {"resource": "guidebook"}


def test_security_and_cors_headers() -> None:
    resp = env.ok(None, make_settings(env="staging", frontend_origin="https://hola.host"))
    h = resp["headers"]
    assert h["Strict-Transport-Security"] == "max-age=31536000"
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["Cache-Control"] == "no-store"
    assert h["Access-Control-Allow-Origin"] == "https://hola.host"
    assert h["Access-Control-Allow-Methods"] == "GET, POST, OPTIONS"
    assert h["Access-Control-Allow-Headers"] == "Content-Type, X-Api-Key, X-Magic-Link"


def test_cors_origin_is_frontend_origin() -> None:
    # No env-branching: the allowed origin is purely the configured frontend_origin
    # (dev sets it to the Vite dev server, e.g. http://localhost:5173, via .env).
    resp = env.ok(None, make_settings(env="dev", frontend_origin="http://localhost:5173"))
    assert resp["headers"]["Access-Control-Allow-Origin"] == "http://localhost:5173"


def test_ok_none_is_sent() -> None:
    assert json.loads(env.ok(None, make_settings())["body"]) == {"status": "sent"}


def test_ok_serializes_result() -> None:
    body = json.loads(env.ok(SampleGenerateResult(response_text="hi"), make_settings())["body"])
    assert body == {"response_text": "hi"}


def test_internal_carries_request_id() -> None:
    resp = env.internal("req-123", make_settings())
    assert resp["statusCode"] == 500
    body = json.loads(resp["body"])
    assert body["error"]["code"] == "ERR_INTERNAL"
    assert body["error"]["details"]["request_id"] == "req-123"


def test_preflight_204() -> None:
    resp = env.preflight(make_settings())
    assert resp["statusCode"] == 204
    assert resp["headers"]["Access-Control-Allow-Methods"] == "GET, POST, OPTIONS"


def test_sanitize_strips_pii() -> None:
    assert "user@example.com" not in env._sanitize("contact user@example.com now")
