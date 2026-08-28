from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Receive, Scope, Send

from holahost_http.errors import RateLimitExceededError
from holahost_http.in_memory_rate_limiter import InMemoryRateLimiter
from holahost_http.rate_limit import RateLimiter, RateLimitMiddleware


@dataclass(frozen=True)
class FakeCaller:
    subject: str
    client_id: str

    @property
    def is_service_token(self) -> bool:
        return self.subject == self.client_id


class StubAuthMiddleware:
    """Stands in for `HolahostAuthMiddleware` — writes the same scope key."""

    def __init__(self, app: ASGIApp, *, caller: FakeCaller | None) -> None:
        self.app = app
        self._caller = caller

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._caller is not None:
            scope.setdefault("state", {})["token"] = self._caller
        await self.app(scope, receive, send)


def bucket_for(method: str, path: str) -> str | None:
    if path == "/health":
        return None
    return "ingest" if method == "POST" else "read"


def build_app(limiter: RateLimiter, caller: FakeCaller | None = None) -> FastAPI:
    caller = caller or FakeCaller(subject="u", client_id="c")
    app = FastAPI(
        middleware=[
            Middleware(StubAuthMiddleware, caller=caller),
            Middleware(RateLimitMiddleware, limiter=limiter, bucket_for=bucket_for),
        ]
    )

    @app.post("/documents")
    def create() -> dict[str, str]:
        return {"ok": "created"}

    @app.get("/documents")
    def read() -> dict[str, str]:
        return {"ok": "read"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def limiter(**caps: int) -> InMemoryRateLimiter:
    return InMemoryRateLimiter(
        cap_by_bucket={
            ("ingest", False): caps.get("user_ingest", 100),
            ("read", False): caps.get("user_read", 100),
            ("ingest", True): caps.get("service_ingest", 100),
            ("read", True): caps.get("service_read", 100),
        },
        window_seconds=3600,
    )


def test_requests_under_the_ceiling_pass() -> None:
    client = TestClient(build_app(limiter(user_ingest=3)))
    assert [client.post("/documents").status_code for _ in range(3)] == [200, 200, 200]


def test_request_over_the_ceiling_is_429_with_retry_after() -> None:
    client = TestClient(build_app(limiter(user_ingest=1)))
    client.post("/documents")
    response = client.post("/documents")
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert response.json()["error"]["code"] == "RateLimitExceededError"


def test_buckets_are_counted_separately() -> None:
    client = TestClient(build_app(limiter(user_ingest=1, user_read=5)))
    client.post("/documents")
    assert client.post("/documents").status_code == 429
    assert client.get("/documents").status_code == 200


def test_unlimited_route_is_not_counted() -> None:
    client = TestClient(build_app(limiter(user_read=1)))
    assert [client.get("/health").status_code for _ in range(5)] == [200] * 5


def test_service_and_user_tokens_hit_different_ceilings() -> None:
    """A service token's `sub` is its own `client_id`, so its counter is one aggregate
    for the whole integration; an exchanged token's covers a single user."""
    shared = limiter(user_ingest=1, service_ingest=3)

    service = TestClient(build_app(shared, FakeCaller(subject="svc", client_id="svc")))
    assert [service.post("/documents").status_code for _ in range(3)] == [200, 200, 200]
    assert service.post("/documents").status_code == 429

    user = TestClient(build_app(shared, FakeCaller(subject="u1", client_id="svc")))
    assert user.post("/documents").status_code == 200
    assert user.post("/documents").status_code == 429


def test_each_user_of_a_client_gets_its_own_counter() -> None:
    shared = limiter(user_ingest=1)
    for subject in ("u1", "u2", "u3"):
        client = TestClient(build_app(shared, FakeCaller(subject=subject, client_id="c")))
        assert client.post("/documents").status_code == 200


def test_limited_route_without_an_authenticated_caller_is_a_wiring_error() -> None:
    """Silently unlimited is the one outcome a limiter must never produce."""
    app = FastAPI(
        middleware=[Middleware(RateLimitMiddleware, limiter=limiter(), bucket_for=bucket_for)]
    )

    @app.post("/documents")
    def create() -> dict[str, str]:
        return {"ok": "created"}

    client = TestClient(app, raise_server_exceptions=True)
    with pytest.raises(RuntimeError, match="authentication middleware"):
        client.post("/documents")


def test_limiter_raises_the_port_error_directly() -> None:
    """The middleware is one consumer; the port stands on its own."""
    counters = limiter(user_read=1)
    counters.check(client_id="c", subject="u", bucket="read", is_service=False)
    with pytest.raises(RateLimitExceededError) as excinfo:
        counters.check(client_id="c", subject="u", bucket="read", is_service=False)
    assert excinfo.value.retry_after > 0
