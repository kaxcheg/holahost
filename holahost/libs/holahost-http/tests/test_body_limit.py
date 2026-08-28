from collections.abc import Iterator

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware import Middleware
from starlette.types import Scope

from holahost_http.body_limit import (
    MULTIPART_OVERHEAD_ALLOWANCE,
    BodySizeLimitMiddleware,
    body_cap_for_upload,
)
from holahost_http.errors import (
    PayloadTooLargeError,
    RateLimitExceededError,
    RejectionLogger,
)

CAP = 1024


def build_app(on_rejected: RejectionLogger | None = None) -> tuple[FastAPI, list[int]]:
    """An app that records how many body bytes actually reached the route."""
    read_sizes: list[int] = []
    app = FastAPI(
        middleware=[Middleware(BodySizeLimitMiddleware, max_bytes=CAP, on_rejected=on_rejected)]
    )

    @app.post("/upload")
    async def upload(request: Request) -> dict[str, int]:
        body = await request.body()
        read_sizes.append(len(body))
        return {"received": len(body)}

    return app, read_sizes


def test_body_within_the_cap_reaches_the_route() -> None:
    app, read_sizes = build_app()
    response = TestClient(app).post("/upload", content=b"x" * CAP)
    assert response.status_code == 200
    assert read_sizes == [CAP]


def test_declared_oversize_is_refused_without_reaching_the_route() -> None:
    app, read_sizes = build_app()
    response = TestClient(app).post("/upload", content=b"x" * (CAP + 1))
    assert response.status_code == 413
    assert read_sizes == []
    body = response.json()
    assert body["error"]["code"] == "PayloadTooLargeError"
    assert body["error"]["details"] == {"limit": CAP, "actual": CAP + 1}


def test_undeclared_oversize_is_cut_off_mid_stream() -> None:
    """Without a Content-Length there is no header to check, so the cap has to be
    enforced by counting — otherwise any client opts out of it by not sending one."""
    app, read_sizes = build_app()

    def chunks() -> Iterator[bytes]:
        for _ in range(10):
            yield b"x" * 512  # 5 KiB total, five times the cap

    # httpx sends a generator body as Transfer-Encoding: chunked, no Content-Length.
    response = TestClient(app).post("/upload", content=chunks())
    assert response.status_code == 413
    assert read_sizes == []
    # `actual: null`, not an absent key: the size was never learned (reporting the
    # partial count would dress a lower bound up as a measurement), but one identity
    # answers with one set of keys either way.
    assert response.json()["error"]["details"] == {"limit": CAP, "actual": None}


def test_rejection_is_reported_to_the_logger() -> None:
    recorded: list[str] = []

    def on_rejected(scope: Scope, *, outcome: str, detail: str | None = None) -> None:
        recorded.append(outcome)

    app, _ = build_app(on_rejected=on_rejected)
    TestClient(app).post("/upload", content=b"x" * (CAP + 1))
    assert recorded == ["PayloadTooLargeError"]


def test_request_without_a_body_passes_through() -> None:
    app = FastAPI(middleware=[Middleware(BodySizeLimitMiddleware, max_bytes=CAP)])

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    assert TestClient(app).get("/health").status_code == 200


class TestReportedLimit:
    """What a 413 advertises has to be the number the caller can act on."""

    FILE_LIMIT = 512

    def _app(self) -> FastAPI:
        return FastAPI(
            middleware=[
                Middleware(
                    BodySizeLimitMiddleware,
                    max_bytes=body_cap_for_upload(self.FILE_LIMIT),
                    reported_limit=self.FILE_LIMIT,
                )
            ]
        )

    def test_declared_oversize_reports_the_service_limit_not_the_transport_cap(self) -> None:
        app = self._app()

        @app.post("/upload")
        async def upload(request: Request) -> dict[str, int]:
            return {"received": len(await request.body())}

        oversize = body_cap_for_upload(self.FILE_LIMIT) + 1
        response = TestClient(app).post("/upload", content=b"x" * oversize)

        assert response.status_code == 413
        details = response.json()["error"]["details"]
        # The bug: reporting the derived body cap sent a client back with a number
        # slightly above what the service itself accepts, so trimming to it was refused
        # again — same status, same code, a different `limit`.
        assert details == {"limit": self.FILE_LIMIT, "actual": oversize}

    def test_undeclared_oversize_reports_the_service_limit(self) -> None:
        app = self._app()

        @app.post("/upload")
        async def upload(request: Request) -> dict[str, int]:
            return {"received": len(await request.body())}

        def chunks() -> Iterator[bytes]:
            # Comfortably past the derived cap (the file limit plus the framing
            # allowance), with no Content-Length for the header check to read.
            for _ in range(256):
                yield b"x" * 1024

        response = TestClient(app).post("/upload", content=chunks())

        assert response.status_code == 413
        # `actual: null`, same as the un-derived case.
        assert response.json()["error"]["details"] == {"limit": self.FILE_LIMIT, "actual": None}

    def test_defaults_to_the_cap_when_a_service_has_no_limit_of_its_own(self) -> None:
        app, _ = build_app()
        response = TestClient(app).post("/upload", content=b"x" * (CAP + 1))
        assert response.json()["error"]["details"]["limit"] == CAP


class TestBodyCapForUpload:
    """The cap measures the whole body; a service's limit measures the file inside it."""

    def test_leaves_room_above_the_file_limit(self) -> None:
        eight_mib = 8 * 1024 * 1024
        assert body_cap_for_upload(eight_mib) == eight_mib + MULTIPART_OVERHEAD_ALLOWANCE

    def test_a_file_of_exactly_the_limit_still_fits_with_its_framing(self) -> None:
        # The bug this exists to prevent: passing the bare file limit as `max_bytes`
        # makes a legal maximum-size upload fail with 413, depending on how many bytes
        # of boundary the client happened to send.
        file_limit = 4096
        app, read_sizes = build_app_with_cap(body_cap_for_upload(file_limit))
        response = TestClient(app).post(
            "/upload", files={"file": ("guide.txt", b"x" * file_limit, "text/plain")}
        )
        assert response.status_code == 200
        assert read_sizes[0] > file_limit  # framing really did add bytes


def build_app_with_cap(cap: int) -> tuple[FastAPI, list[int]]:
    read_sizes: list[int] = []
    app = FastAPI(middleware=[Middleware(BodySizeLimitMiddleware, max_bytes=cap)])

    @app.post("/upload")
    async def upload(request: Request) -> dict[str, int]:
        read_sizes.append(len(await request.body()))
        return {"received": len(await request.body())}

    return app, read_sizes


class TestWireIdentityIsTheClassName:
    """`code` is not declared anywhere, and not transformed either — it is the class
    name verbatim, so a value seen in a log greps straight back to the class that
    produced it. A rename is a contract change and has to look like one."""

    def test_payload_too_large(self) -> None:
        assert PayloadTooLargeError(1).code == "PayloadTooLargeError"

    def test_rate_limit_exceeded(self) -> None:
        assert RateLimitExceededError(retry_after=1).code == "RateLimitExceededError"

    def test_the_class_answers_too(self) -> None:
        # No helper needed for the class-level case: an interface layer answering an
        # unpublished subclass as its published ancestor reads `__name__` directly.
        assert PayloadTooLargeError.__name__ == PayloadTooLargeError(1).code
