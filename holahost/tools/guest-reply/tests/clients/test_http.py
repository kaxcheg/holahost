"""One call: the headers it carries, the answer it reads, and each refusal as this tool's error."""

from __future__ import annotations

import json
import socket
import threading

import httpx
import pytest
from pydantic import BaseModel, SecretStr
from pytest_httpserver import HTTPServer
from werkzeug import Request, Response

from guest_reply.clients import documents
from guest_reply.clients.auth import StaticToken
from guest_reply.clients.http import MAX_RETRY_AFTER, RETRY_ON_429_MAX, ServiceCaller
from guest_reply.errors import (
    DocumentNotFoundError,
    GuestReplyError,
    LimitReachedError,
    ProviderUnavailableError,
    RequestRejectedError,
    ServiceUnreachableError,
    TokenRejectedError,
    UnexpectedResponseError,
)
from tests._support import REQUEST_ID, TOKEN, caller, envelope

_PATH = "/documents/x"
_URL = f"{documents.API_BASE}{_PATH}"


class _Echo(BaseModel):
    value: int


def _fetch(caller_: ServiceCaller, *, read_timeout: float = 5.0) -> _Echo:
    return caller_.fetch(_Echo, "GET", _PATH, read_timeout=read_timeout)


def _documents(
    httpserver: HTTPServer, http: httpx.Client, waits: list[int] | None = None
) -> ServiceCaller:
    return caller(httpserver, http, documents.API_BASE, waits=waits)


class TestTheCall:
    def test_it_carries_the_token_and_the_request_id(
        self, httpserver: HTTPServer, http: httpx.Client
    ) -> None:
        httpserver.expect_request(_URL, method="GET").respond_with_json({"value": 1})
        _fetch(_documents(httpserver, http))
        request, _ = httpserver.log[0]
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.headers["X-Request-ID"] == REQUEST_ID

    def test_the_answer_is_read_into_the_model(
        self, httpserver: HTTPServer, http: httpx.Client
    ) -> None:
        httpserver.expect_request(_URL).respond_with_json({"value": 7, "extra": "ignored"})
        assert _fetch(_documents(httpserver, http)) == _Echo(value=7)

    def test_a_call_without_a_body_succeeds_on_204(
        self, httpserver: HTTPServer, http: httpx.Client
    ) -> None:
        httpserver.expect_request(_URL, method="DELETE").respond_with_data("", status=204)
        _documents(httpserver, http).send("DELETE", _PATH, read_timeout=5.0)
        assert len(httpserver.log) == 1

    def test_a_success_body_outside_the_contract_is_unexpected(
        self, httpserver: HTTPServer, http: httpx.Client
    ) -> None:
        httpserver.expect_request(_URL).respond_with_json({"other": 1})
        with pytest.raises(UnexpectedResponseError):
            _fetch(_documents(httpserver, http))


_PUBLISHED: list[tuple[int, str, dict[str, object], type[GuestReplyError]]] = [
    (404, "NotFoundError", {}, DocumentNotFoundError),
    (413, "UploadTooLargeError", {"limit": 8388608, "actual": 9000000}, RequestRejectedError),
    (415, "UnsupportedMediaTypeError", {}, RequestRejectedError),
    (422, "EmptyDocumentError", {"min_chars": 1}, RequestRejectedError),
    (
        400,
        "UnknownModelError",
        {"requested": "big", "available_aliases": ["fast"]},
        RequestRejectedError,
    ),
    (409, "DuplicateRequestError", {"state": "in_flight"}, RequestRejectedError),
    (
        429,
        "BudgetExhaustedError",
        {"scope": "client", "resets_at": "2026-09-29T00:00:00Z"},
        LimitReachedError,
    ),
    (502, "UpstreamLlmError", {"attempts": 3, "upstream_status": 529}, ProviderUnavailableError),
    (500, "InternalError", {}, UnexpectedResponseError),
]


class TestRefusals:
    @pytest.mark.parametrize(
        ("status", "code", "details", "kind"), _PUBLISHED, ids=[row[1] for row in _PUBLISHED]
    )
    def test_a_published_error_keeps_the_services_code_and_details(
        self,
        httpserver: HTTPServer,
        http: httpx.Client,
        status: int,
        code: str,
        details: dict[str, object],
        kind: type[GuestReplyError],
    ) -> None:
        httpserver.expect_request(_URL).respond_with_json(
            envelope(code, "said", details), status=status
        )
        with pytest.raises(kind) as error:
            _fetch(_documents(httpserver, http))
        assert (error.value.code, error.value.details) == (code, details)

    def test_401_is_a_rejected_token(self, httpserver: HTTPServer, http: httpx.Client) -> None:
        httpserver.expect_request(_URL).respond_with_json({"detail": "Unauthorized"}, status=401)
        with pytest.raises(TokenRejectedError) as error:
            _fetch(_documents(httpserver, http))
        assert error.value.code == "TokenRejectedError"
        assert TOKEN not in error.value.message
        assert len(httpserver.log) == 1  # a static token is not worth sending twice

    def test_503_is_a_service_that_cannot_validate_tokens(
        self, httpserver: HTTPServer, http: httpx.Client
    ) -> None:
        httpserver.expect_request(_URL).respond_with_json(
            {"detail": "Service Unavailable"}, status=503
        )
        with pytest.raises(ServiceUnreachableError, match="minter"):
            _fetch(_documents(httpserver, http))

    def test_a_404_without_the_envelope_is_not_a_missing_document(
        self, httpserver: HTTPServer, http: httpx.Client
    ) -> None:
        # A route this service does not have: the URL points at the other service.
        httpserver.expect_request(_URL).respond_with_json({"detail": "Not Found"}, status=404)
        with pytest.raises(UnexpectedResponseError) as error:
            _fetch(_documents(httpserver, http))
        assert error.value.details == {"status": 404}

    def test_a_body_that_is_not_json_is_unexpected(
        self, httpserver: HTTPServer, http: httpx.Client
    ) -> None:
        httpserver.expect_request(_URL).respond_with_data("<html>bad gateway</html>", status=502)
        with pytest.raises(UnexpectedResponseError):
            _fetch(_documents(httpserver, http))


class TestNoAnswer:
    def test_a_closed_port_is_unreachable(self, http: httpx.Client) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        caller_ = ServiceCaller(
            http,
            origin=f"http://127.0.0.1:{port}",
            api_base=documents.API_BASE,
            token=StaticToken(SecretStr(TOKEN)),
            request_id=REQUEST_ID,
            on_wait=lambda _seconds: None,
        )
        with pytest.raises(ServiceUnreachableError, match="unreachable"):
            _fetch(caller_)

    def test_a_slow_answer_times_out(self, httpserver: HTTPServer, http: httpx.Client) -> None:
        release = threading.Event()

        def slow(_request: Request) -> Response:
            release.wait(5)
            return Response(json.dumps({"value": 1}), content_type="application/json")

        httpserver.expect_request(_URL).respond_with_handler(slow)
        try:
            with pytest.raises(ServiceUnreachableError, match="in time"):
                _fetch(_documents(httpserver, http), read_timeout=0.2)
        finally:
            release.set()


def _rate_limited(retry_after: str | None) -> tuple[dict[str, object], dict[str, str]]:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    body = envelope("RateLimitExceededError", "rate limit exceeded", {"retry_after_seconds": 2})
    return body, headers


class TestRateLimit:
    def test_a_short_limit_is_waited_out_and_the_call_repeated(
        self, httpserver: HTTPServer, http: httpx.Client
    ) -> None:
        body, headers = _rate_limited("2")
        httpserver.expect_ordered_request(_URL).respond_with_json(body, status=429, headers=headers)
        httpserver.expect_ordered_request(_URL).respond_with_json({"value": 1})
        waits: list[int] = []
        assert _fetch(_documents(httpserver, http, waits)) == _Echo(value=1)
        assert waits == [2]

    def test_the_waits_are_bounded(self, httpserver: HTTPServer, http: httpx.Client) -> None:
        body, headers = _rate_limited("2")
        for _ in range(RETRY_ON_429_MAX + 1):
            httpserver.expect_ordered_request(_URL).respond_with_json(
                body, status=429, headers=headers
            )
        waits: list[int] = []
        with pytest.raises(LimitReachedError) as error:
            _fetch(_documents(httpserver, http, waits))
        assert error.value.code == "RateLimitExceededError"
        assert waits == [2] * RETRY_ON_429_MAX
        assert len(httpserver.log) == RETRY_ON_429_MAX + 1

    @pytest.mark.parametrize("retry_after", [str(MAX_RETRY_AFTER + 1), "soon", None])
    def test_a_long_or_unreadable_wait_is_not_made(
        self, httpserver: HTTPServer, http: httpx.Client, retry_after: str | None
    ) -> None:
        body, headers = _rate_limited(retry_after)
        httpserver.expect_request(_URL).respond_with_json(body, status=429, headers=headers)
        waits: list[int] = []
        with pytest.raises(LimitReachedError):
            _fetch(_documents(httpserver, http, waits))
        assert (waits, len(httpserver.log)) == ([], 1)

    def test_a_budget_is_not_waited_out(self, httpserver: HTTPServer, http: httpx.Client) -> None:
        details = {"scope": "client", "resets_at": "2026-09-29T00:00:00Z"}
        httpserver.expect_request(_URL).respond_with_json(
            envelope("BudgetExhaustedError", "budget exhausted", details),
            status=429,
            headers={"Retry-After": "30"},
        )
        waits: list[int] = []
        with pytest.raises(LimitReachedError) as error:
            _fetch(_documents(httpserver, http, waits))
        assert (error.value.code, waits) == ("BudgetExhaustedError", [])
