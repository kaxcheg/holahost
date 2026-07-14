import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from application.dto.sample import SampleGenerateResult
from application.exceptions import RateLimitExceededError
from interface.lambda_.handler import handle
from tests._support.settings import make_settings


class _Ctx:
    aws_request_id = "aws-req-1"


def _evt(
    *,
    method: str = "POST",
    path: str = "/api/capture-lead/sample/generate",
    body: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": method, "sourceIp": "1.2.3.4"}},
        "headers": headers or {},
        "body": body,
        "isBase64Encoded": False,
    }


def _container(execute: Callable[[Any], Any]) -> SimpleNamespace:
    use_case = SimpleNamespace(execute=execute)
    return SimpleNamespace(
        settings=make_settings(),
        sample_generate=use_case,
        capture_lead=use_case,
        resolve_magic_link=use_case,
        upload_guidebook=use_case,
        generate_response=use_case,
    )


def test_handle_success() -> None:
    c = _container(lambda cmd: SampleGenerateResult(response_text="hi"))
    resp = handle(_evt(body=json.dumps({"message": "q"})), _Ctx(), c)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"response_text": "hi"}


def test_handle_application_error_mapped() -> None:
    def boom(cmd: Any) -> Any:
        raise RateLimitExceededError(scope="ip", retry_after_seconds=5)

    resp = handle(_evt(body=json.dumps({"message": "q"})), _Ctx(), _container(boom))
    assert resp["statusCode"] == 429
    assert json.loads(resp["body"])["error"]["code"] == "ERR_RATE_LIMIT"


def test_handle_unhandled_returns_500_with_request_id() -> None:
    def boom(cmd: Any) -> Any:
        raise RuntimeError("kaboom")

    resp = handle(_evt(body=json.dumps({"message": "q"})), _Ctx(), _container(boom))
    assert resp["statusCode"] == 500
    assert json.loads(resp["body"])["error"]["details"]["request_id"] == "aws-req-1"


def test_handle_options_preflight() -> None:
    resp = handle(
        _evt(method="OPTIONS", path="/api/capture-lead/generate"),
        _Ctx(),
        _container(lambda cmd: None),
    )
    assert resp["statusCode"] == 204
