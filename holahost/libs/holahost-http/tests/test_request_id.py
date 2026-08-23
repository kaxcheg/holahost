from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware import Middleware
from starlette.types import Scope

from holahost_http.errors import PlatformError, RejectionLogger
from holahost_http.request_id import RequestIdMiddleware


def build_app() -> FastAPI:
    app = FastAPI(middleware=[Middleware(RequestIdMiddleware)])

    @app.get("/echo")
    def echo(request: Request) -> dict[str, object]:
        return {
            "request_id": request.state.request_id,
            "timed": request.state.start_time > 0,
        }

    return app


def test_header_is_recorded_and_echoed_back() -> None:
    response = TestClient(build_app()).get("/echo", headers={"X-Request-ID": "abc-123"})
    assert response.json() == {"request_id": "abc-123", "timed": True}
    assert response.headers["X-Request-ID"] == "abc-123"


def test_absence_is_recorded_and_never_synthesized() -> None:
    """§3.1: the service does not compensate for a missing perimeter by inventing one."""
    response = TestClient(build_app()).get("/echo")
    assert response.json() == {"request_id": None, "timed": True}
    assert "X-Request-ID" not in response.headers


def test_header_is_matched_case_insensitively() -> None:
    response = TestClient(build_app()).get("/echo", headers={"x-request-id": "lower"})
    assert response.json()["request_id"] == "lower"


class MalformedRequestError(PlatformError):
    """Stands in for a consuming service's own "you sent a bad request" error."""

    code = "ERR_INVALID_PAYLOAD"

    def __init__(self, field: str) -> None:
        super().__init__(f"invalid payload: {field}")
        self.field = field

    def details_dict(self) -> dict[str, object]:
        return {"field": self.field}


def build_guarded_app(on_rejected: RejectionLogger | None = None) -> FastAPI:
    return _guarded(
        FastAPI(
            middleware=[
                Middleware(
                    RequestIdMiddleware,
                    missing_header_error=MalformedRequestError("X-Request-ID"),
                    exempt_paths=("/health",),
                    on_rejected=on_rejected,
                )
            ]
        )
    )


def _guarded(app: FastAPI) -> FastAPI:
    @app.get("/echo")
    def echo() -> dict[str, str]:
        return {"ok": "reached"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


class TestRequiredHeader:
    def test_present_header_reaches_the_route(self) -> None:
        response = TestClient(build_guarded_app()).get("/echo", headers={"X-Request-ID": "abc-123"})
        assert response.status_code == 200

    def test_missing_header_is_answered_with_the_service_own_error(self) -> None:
        """The library owns the rule; the code and details come from the caller."""
        response = TestClient(build_guarded_app()).get("/echo")
        assert response.status_code == 422
        assert response.json()["error"] == {
            "code": "ERR_INVALID_PAYLOAD",
            "message": "invalid payload: X-Request-ID",
            "details": {"field": "X-Request-ID"},
        }

    def test_exempt_path_is_served_without_the_header(self) -> None:
        assert TestClient(build_guarded_app()).get("/health").status_code == 200

    def test_rejection_is_reported_to_the_logger(self) -> None:
        """Which header was missing reaches the log even when the body stays mute."""
        recorded: list[tuple[str, str | None]] = []

        def on_rejected(scope: Scope, *, outcome: str, detail: str | None = None) -> None:
            recorded.append((outcome, detail))

        TestClient(build_guarded_app(on_rejected=on_rejected)).get("/echo")
        assert recorded == [("ERR_INVALID_PAYLOAD", "missing x-request-id")]

    def test_status_is_the_caller_choice(self) -> None:
        app = _guarded(
            FastAPI(
                middleware=[
                    Middleware(
                        RequestIdMiddleware,
                        missing_header_error=MalformedRequestError("X-Request-ID"),
                        status=400,
                    )
                ]
            )
        )
        assert TestClient(app).get("/echo").status_code == 400

    def test_no_error_means_observe_only(self) -> None:
        """The default: record the absence, never turn it into a rejection."""
        assert TestClient(_guarded(build_app())).get("/echo").status_code == 200

    def test_exempt_path_still_echoes_a_header_that_did_arrive(self) -> None:
        """Exemption is from the requirement, not from the observation."""
        response = TestClient(build_guarded_app()).get(
            "/health", headers={"X-Request-ID": "probe-1"}
        )
        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "probe-1"
