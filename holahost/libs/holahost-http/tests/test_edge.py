"""The edge factory: what it guarantees that a hand-assembled stack does not.

Everything here is about *order* and *omission*. The middleware themselves are tested in
their own files; what this one asserts is that a service cannot get the sequence wrong,
cannot mount a router outside the base path, and cannot end up with an app whose exception
mapping was never registered.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from holahost_observability import configure_logging
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Receive, Scope, Send

from holahost_http import (
    BodySizeLimitMiddleware,
    ErrorContract,
    InvalidPayloadError,
    MalformedRequestError,
    NotFoundError,
    RateLimitMiddleware,
    RequestIdMiddleware,
    create_edge_app,
)

_CONTRACT: ErrorContract = {InvalidPayloadError: 422, NotFoundError: 404}


class StubAuthMiddleware:
    """Stands in for `HolahostAuthMiddleware`: same constructor keywords, no JWKS.

    The real one lives in `holahost-auth`, which depends on this package — so this
    package's own tests cannot import it, and the factory takes the middleware built
    rather than building it.
    """

    # `app` positional-only, matching Starlette's middleware-factory protocol.
    def __init__(self, app: ASGIApp, /, *, public_paths: Any = (), **_: Any) -> None:
        self.app = app
        self.public_paths = public_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)


def _limiter() -> Any:
    class _NoLimit:
        def check(self, *, client_id: str, subject: str, bucket: str, is_service: bool) -> None:
            return None

    return _NoLimit()


def _build(
    *,
    public_paths: Any = ("/api/svc/health",),
    routers: list[APIRouter] | None = None,
    error_contract: ErrorContract | None = None,
) -> FastAPI:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return create_edge_app(
        title="svc",
        description="a service",
        api_base_url="/api/svc",
        routers=routers if routers is not None else [router],
        authentication=Middleware(StubAuthMiddleware, public_paths=public_paths),
        rate_limiter=_limiter(),
        bucket_for=lambda method, path: None,
        max_request_body_size=1024,
        missing_request_id_error=MalformedRequestError(),
        error_contract=error_contract if error_contract is not None else _CONTRACT,
    )


def _build_with(authentication: Middleware) -> FastAPI:
    """Build with a deliberately malformed authentication middleware."""
    return create_edge_app(
        title="svc",
        description="a service",
        api_base_url="/api/svc",
        routers=[],
        authentication=authentication,
        rate_limiter=_limiter(),
        bucket_for=lambda method, path: None,
        max_request_body_size=1024,
        missing_request_id_error=MalformedRequestError(),
        error_contract=_CONTRACT,
    )


def _stack(app: FastAPI) -> list[object]:
    # `Middleware.cls` is Starlette's middleware-factory protocol rather than `type`, so
    # the stack is compared as objects — identity is all these tests need.
    return [middleware.cls for middleware in app.user_middleware]


class TestTheOrderIsNotTheCallersToChoose:
    def test_the_stack_is_built_in_the_one_order_that_works(self) -> None:
        # Outermost first. Every position is load-bearing — see the module docstring.
        assert _stack(_build()) == [
            RequestIdMiddleware,
            BodySizeLimitMiddleware,
            StubAuthMiddleware,
            RateLimitMiddleware,
        ]

    def test_the_body_cap_is_inside_the_request_id_and_outside_authentication(self) -> None:
        # The two facts a hand-assembled stack most easily loses: a refusal that carries no
        # correlation id, and a body read in full before anyone is allowed to look at it.
        stack = _stack(_build())

        assert stack.index(RequestIdMiddleware) < stack.index(BodySizeLimitMiddleware)
        assert stack.index(BodySizeLimitMiddleware) < stack.index(StubAuthMiddleware)

    def test_the_rate_limit_is_inside_authentication(self) -> None:
        # It keys on the token, and authentication is its only writer.
        stack = _stack(_build())

        assert stack.index(StubAuthMiddleware) < stack.index(RateLimitMiddleware)


class TestPublicPathsAreDeclaredOnce:
    def test_the_request_id_requirement_exempts_what_authentication_exempts(self) -> None:
        # Read off the auth middleware rather than taken twice. Divergence is silent both
        # ways: a health check answered 422, or a route opened that nobody meant to open.
        app = _build(public_paths=("/api/svc/health", "/api/svc/ping"))
        request_id = next(
            m
            for m in app.user_middleware
            if m.cls is RequestIdMiddleware  # type: ignore[comparison-overlap]
        )

        assert request_id.kwargs["exempt_paths"] == ("/api/svc/health", "/api/svc/ping")

    def test_health_needs_neither_a_token_nor_a_request_id(self) -> None:
        client = TestClient(_build())

        assert client.get("/api/svc/health").status_code == 200

    def test_a_guarded_route_still_requires_the_request_id(self) -> None:
        router = APIRouter()

        @router.get("/things")
        def things() -> dict[str, int]:
            return {"n": 1}

        client = TestClient(_build(routers=[router]), raise_server_exceptions=False)

        assert client.get("/api/svc/things").status_code == 422
        assert client.get("/api/svc/things", headers={"X-Request-ID": "r-1"}).status_code == 200

    def test_authentication_built_without_public_paths_is_refused(self) -> None:
        # Caught where the app is built, not per request.
        with pytest.raises(TypeError, match="public_paths"):
            _build_with(Middleware(StubAuthMiddleware))

    def test_a_bare_string_of_paths_is_refused(self) -> None:
        # A string is a sequence of characters: it would exempt nothing while looking like
        # it exempted something.
        with pytest.raises(TypeError, match="public_paths"):
            _build_with(Middleware(StubAuthMiddleware, public_paths="/api/svc/health"))


class TestTheRejectionLoggerIsDerived:
    """A service passes nothing about the rejection event: its shape is the platform's,
    and every middleware gets the same logger, so a refusal looks the same whichever one
    answered."""

    def test_every_middleware_reports_through_one_logger(self) -> None:
        app = _build()
        loggers = {
            m.kwargs["on_rejected"] for m in app.user_middleware if "on_rejected" in m.kwargs
        }

        assert len(app.user_middleware) == 4
        assert len(loggers) == 1

    def test_an_authentication_middleware_carrying_its_own_is_refused(self) -> None:
        # Two loggers would split one event in two shapes; caught at build time.
        with pytest.raises(TypeError, match="on_rejected"):
            _build_with(
                Middleware(
                    StubAuthMiddleware,
                    public_paths=("/api/svc/health",),
                    on_rejected=lambda scope, *, outcome, detail=None: None,
                )
            )

    def test_a_refusal_reaches_the_log(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging()
        router = APIRouter()

        @router.get("/things")
        def things() -> dict[str, int]:
            return {"n": 1}

        TestClient(_build(routers=[router]), raise_server_exceptions=False).get("/api/svc/things")

        assert "op_completed" in capsys.readouterr().out


class TestWhatElseCannotBeForgotten:
    def test_every_router_is_mounted_under_the_base_path(self) -> None:
        # A router that forgot the prefix is unreachable through the gateway, which for a
        # health route means the deploy's smoke check silently never finds it.
        paths = {route.path for route in _build().routes}  # type: ignore[attr-defined]

        assert "/api/svc/health" in paths
        assert "/health" not in paths

    def test_the_exception_mapping_is_registered(self) -> None:
        # An app built with its edge in place but no handlers answers 500 to every error
        # the service publishes — and looks entirely healthy until one is raised. Checked
        # by raising one rather than by watching a callback fire: what matters is the
        # answer on the wire.
        configure_logging()
        router = APIRouter()

        @router.get("/gone")
        def gone() -> None:
            raise NotFoundError

        client = TestClient(_build(routers=[router]), raise_server_exceptions=False)

        response = client.get("/api/svc/gone", headers={"X-Request-ID": "r-1"})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NotFoundError"

    def test_a_contract_the_handlers_reject_stops_the_app_being_built(self) -> None:
        # `register_error_handlers` refuses a contract without `InvalidPayloadError`,
        # since that is what the framework's own validation is answered with. Raised here,
        # at build time, rather than on the first malformed request.
        with pytest.raises(RuntimeError, match="InvalidPayloadError"):
            _build(error_contract={NotFoundError: 404})
