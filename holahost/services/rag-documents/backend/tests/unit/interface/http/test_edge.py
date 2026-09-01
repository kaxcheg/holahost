"""Unit tests for this service's edge policy (spec §3.1, §8.1 steps 1-3).

The point of these is *ordering*. Each of the four checks is easy to get right on its
own; what §8.1 actually specifies is which one wins when several would fail, and — the
reason any of this is middleware at all — that none of them waits for the request body
to be read first.
"""

import json
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from holahost_auth import TokenContext
from holahost_http import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestIdMiddleware,
    log_rejection,
)
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Receive, Scope, Send
from tests._support.fakes import FakeRateLimiter
from tests._support.http import register_test_handlers

from application.limits import MAX_UPLOAD_SIZE
from config.logging import configure_logging
from interface.http.api_base import API_BASE_URL
from interface.http.edge import (
    HEALTH_PATH,
    MAX_REQUEST_BODY_SIZE,
    MISSING_REQUEST_ID_ERROR,
    REPORTED_UPLOAD_LIMIT,
    bucket_for,
)

# `log_rejection` is what `create_edge_app` wires into all four middleware for the real
# app; it is imported here because this file assembles the stack by hand, to check the
# ordering the factory is otherwise responsible for.

_TOKEN = TokenContext(subject="user-123", client_id="cli-1", roles=(), act=None)
_DOCUMENTS = f"{API_BASE_URL}/documents"
_HEADERS = {"X-Request-ID": "test-request-id"}


class StubAuthMiddleware:
    """Stands in for `HolahostAuthMiddleware`: same scope key, no JWKS.

    Occupies the real one's slot in the stack so the surrounding order is the real
    order — the alternative, dropping auth from the stack under test, would leave the
    ordering claims untested exactly where they matter.
    """

    def __init__(self, app: ASGIApp, *, accepts: bool = True) -> None:
        self.app = app
        self._accepts = accepts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["path"] == HEALTH_PATH:
            await self.app(scope, receive, send)
            return
        if not self._accepts:
            log_rejection(scope, outcome="401", detail="stub rejects")
            await _send_json(scope, receive, send, 401, {"detail": "Unauthorized"})
            return
        scope.setdefault("state", {})["token"] = _TOKEN
        await self.app(scope, receive, send)


async def _send_json(
    scope: Scope, receive: Receive, send: Send, status: int, body: dict[str, str]
) -> None:
    from fastapi.responses import JSONResponse

    await JSONResponse(status_code=status, content=body)(scope, receive, send)


def build_app(
    *, accepts_auth: bool = True, rate_limiter: FakeRateLimiter | None = None
) -> tuple[FastAPI, list[int]]:
    """The production stack, with auth stubbed. Records bytes that reached the route."""
    read_sizes: list[int] = []
    app = FastAPI(
        middleware=[
            Middleware(
                RequestIdMiddleware,
                missing_header_error=MISSING_REQUEST_ID_ERROR,
                exempt_paths=(HEALTH_PATH,),
                on_rejected=log_rejection,
            ),
            Middleware(
                BodySizeLimitMiddleware,
                max_bytes=MAX_REQUEST_BODY_SIZE,
                reported_limit=REPORTED_UPLOAD_LIMIT,
                on_rejected=log_rejection,
            ),
            Middleware(StubAuthMiddleware, accepts=accepts_auth),
            Middleware(
                RateLimitMiddleware,
                limiter=rate_limiter or FakeRateLimiter(),
                bucket_for=bucket_for,
                on_rejected=log_rejection,
            ),
        ]
    )
    register_test_handlers(app)

    @app.post(_DOCUMENTS)
    async def create(request: Request) -> dict[str, int]:
        read_sizes.append(len(await request.body()))
        return {"ok": 1}

    @app.get(HEALTH_PATH)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app, read_sizes


class TestBucketMapping:
    def test_create_and_replace_are_ingest(self) -> None:
        assert bucket_for("POST", _DOCUMENTS) == "ingest"
        assert bucket_for("PUT", f"{_DOCUMENTS}/doc-1") == "ingest"

    def test_search_is_a_read_despite_being_a_post(self) -> None:
        # §8.1 step 3: split by what the operation costs, not by the verb.
        assert bucket_for("POST", f"{_DOCUMENTS}/doc-1/search") == "read"

    def test_get_and_delete_are_reads(self) -> None:
        assert bucket_for("GET", f"{_DOCUMENTS}/doc-1") == "read"
        assert bucket_for("DELETE", f"{_DOCUMENTS}/doc-1") == "read"

    def test_health_is_not_limited(self) -> None:
        assert bucket_for("GET", HEALTH_PATH) is None


class TestRequestIdRequired:
    def test_missing_request_id_returns_422(self) -> None:
        app, _ = build_app()
        response = TestClient(app).post(_DOCUMENTS, files={"file": ("a.txt", b"x")})

        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "MalformedRequestError"
        # Mute on purpose: this is the one error answered before auth, and naming the
        # header would tell an unintended caller how to get past the check.
        assert body["error"]["details"] == {}
        assert "X-Request-ID" not in response.text

    def test_request_id_check_runs_before_auth(self) -> None:
        # Both would fail; §8.1 puts the transport contract first, so a caller that
        # broke it hears about that rather than about its credentials.
        app, _ = build_app(accepts_auth=False)
        response = TestClient(app).post(_DOCUMENTS, files={"file": ("a.txt", b"x")})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "MalformedRequestError"

    def test_health_is_exempt(self) -> None:
        app, _ = build_app()
        assert TestClient(app).get(HEALTH_PATH).status_code == 200


class TestBodyIsNotReadBeforeTheChecks:
    def test_oversized_body_is_refused_unread(self) -> None:
        app, read_sizes = build_app()
        response = TestClient(app).post(
            _DOCUMENTS,
            content=b"x" * (MAX_REQUEST_BODY_SIZE + 1),
            headers={**_HEADERS, "Content-Type": "application/octet-stream"},
        )

        assert response.status_code == 413
        assert read_sizes == []
        body = response.json()
        assert body["error"]["code"] == "PayloadTooLargeError"
        # The number a caller can act on is the service's own file limit, not the
        # derived transport cap: `UploadTooLargeError` — the other raise site of this
        # very code — reports exactly this, and a client that trimmed to the cap
        # instead got past the middleware only to be refused again by that check.
        assert body["error"]["details"]["limit"] == MAX_UPLOAD_SIZE
        assert REPORTED_UPLOAD_LIMIT == MAX_UPLOAD_SIZE < MAX_REQUEST_BODY_SIZE

    def test_anonymous_upload_is_refused_without_being_read(self) -> None:
        """What this layer exists for: `await request.form()` runs ahead of the
        endpoint's dependencies, so a check written as one would receive an
        unauthenticated 50 MiB POST in full before answering 401."""
        app, read_sizes = build_app(accepts_auth=False)

        def chunks() -> Iterator[bytes]:
            for _ in range(64):
                yield b"x" * 1024

        response = TestClient(app).post(_DOCUMENTS, content=chunks(), headers=_HEADERS)

        assert response.status_code == 401
        assert read_sizes == []

    def test_over_quota_caller_is_refused_without_being_read(self) -> None:
        app, read_sizes = build_app(rate_limiter=FakeRateLimiter(should_raise=True))

        def chunks() -> Iterator[bytes]:
            for _ in range(64):
                yield b"x" * 1024

        response = TestClient(app).post(_DOCUMENTS, content=chunks(), headers=_HEADERS)

        assert response.status_code == 429
        assert response.headers["Retry-After"] == "30"
        assert response.json()["error"]["code"] == "RateLimitExceededError"
        assert read_sizes == []


class TestRateLimitWiring:
    def test_identity_kind_reaches_the_limiter(self) -> None:
        limiter = FakeRateLimiter()
        app, _ = build_app(rate_limiter=limiter)
        TestClient(app).post(_DOCUMENTS, files={"file": ("a.txt", b"x")}, headers=_HEADERS)

        assert limiter.calls == [("cli-1", "user-123", "ingest", False)]

    def test_health_never_reaches_the_limiter(self) -> None:
        limiter = FakeRateLimiter()
        app, _ = build_app(rate_limiter=limiter)
        TestClient(app).get(HEALTH_PATH)

        assert limiter.calls == []


class TestRejectionsAreLoggedAtWarning:
    """Every outcome `log_rejection` can be handed is the caller's own doing — visible,
    but not the service failing, so `WARNING` rather than `INFO`."""

    def test_a_refused_request_logs_at_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging()
        app, _ = build_app()

        TestClient(app).post(_DOCUMENTS, files={"file": ("a.txt", b"x")})

        line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert line["level"] == "WARNING"
        assert line["outcome"] == "MalformedRequestError"
