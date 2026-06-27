import json
from types import SimpleNamespace
from typing import Any

import pytest

from application.exceptions import NotFoundError
from interface.lambda_.router import dispatch
from tests._support.settings import make_settings


def _evt(
    *, method: str = "POST", path: str = "/api/sample/generate", body: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": method, "sourceIp": "1.2.3.4"}},
        "headers": headers or {},
        "body": body,
        "isBase64Encoded": False,
    }


def _container() -> SimpleNamespace:
    return SimpleNamespace(
        settings=make_settings(),
        sample_generate=object(),
        capture_lead=object(),
        resolve_magic_link=object(),
        upload_guidebook=object(),
        generate_response=object(),
    )


def test_dispatch_sample_generate() -> None:
    c = _container()
    cmd, use_case = dispatch(_evt(body=json.dumps({"message": "h"})), c)
    assert use_case is c.sample_generate
    assert cmd.message == "h"


def test_dispatch_generate_route_reads_byok() -> None:
    c = _container()
    evt = _evt(
        path="/api/generate",
        headers={"x-magic-link": "M", "x-api-key": "K"},
        body=json.dumps({"message": "q"}),
    )
    cmd, use_case = dispatch(evt, c)
    assert use_case is c.generate_response
    assert cmd.byok.get_secret_value() == "K"


def test_dispatch_get_route() -> None:
    c = _container()
    _, use_case = dispatch(
        _evt(method="GET", path="/api/magic-link/resolve", headers={"x-magic-link": "M"}), c
    )
    assert use_case is c.resolve_magic_link


def test_dispatch_unknown_route_raises_not_found() -> None:
    with pytest.raises(NotFoundError):
        dispatch(_evt(path="/api/nope"), _container())
