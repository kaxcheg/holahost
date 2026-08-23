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
from holahost_http.errors import RejectionLogger

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
    assert body["error"]["code"] == "ERR_PAYLOAD_TOO_LARGE"
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
    # No `actual`: the size was never learned, and reporting the partial count would
    # dress a lower bound up as a measurement.
    assert response.json()["error"]["details"] == {"limit": CAP}


def test_rejection_is_reported_to_the_logger() -> None:
    recorded: list[str] = []

    def on_rejected(scope: Scope, *, outcome: str, detail: str | None = None) -> None:
        recorded.append(outcome)

    app, _ = build_app(on_rejected=on_rejected)
    TestClient(app).post("/upload", content=b"x" * (CAP + 1))
    assert recorded == ["ERR_PAYLOAD_TOO_LARGE"]


def test_request_without_a_body_passes_through() -> None:
    app = FastAPI(middleware=[Middleware(BodySizeLimitMiddleware, max_bytes=CAP)])

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    assert TestClient(app).get("/health").status_code == 200


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
