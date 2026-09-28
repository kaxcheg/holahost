"""The scenarios, by the calls they make: HTTP is faked, the order is what is checked."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pytest_httpserver import HTTPServer

from guest_reply import flows
from guest_reply.clients.generation import Usage
from guest_reply.errors import (
    DocumentNotFoundError,
    FileUnreadableError,
    ProviderUnavailableError,
    RequestRejectedError,
    UnexpectedResponseError,
)
from tests._support import (
    DOCUMENT,
    DOCUMENT_ID,
    DOCUMENTS,
    GENERATE,
    SEARCH,
    calls,
    capture_upload,
    created,
    envelope,
    generated,
    hits,
    services,
)

_ANSWER = flows.Answer(
    text="Check-in is from 15:00.",
    chunks_used=1,
    usage=Usage(input_tokens=120, output_tokens=12),
    provider="anthropic",
    model="claude-haiku-4-5",
)


@pytest.fixture
def svc(httpserver: HTTPServer, http: httpx.Client) -> flows.Services:
    return services(httpserver, http)


@pytest.fixture
def guidebook(tmp_path: Path) -> Path:
    path = tmp_path / "guidebook.md"
    path.write_text("# Villa\nCheck-in from 15:00.\n", encoding="utf-8")
    return path


def _expect(httpserver: HTTPServer, method: str, path: str, body: Any, status: int = 200) -> None:
    httpserver.expect_ordered_request(path, method=method).respond_with_json(body, status=status)


def _expect_deleted(httpserver: HTTPServer) -> None:
    httpserver.expect_ordered_request(DOCUMENT, method="DELETE").respond_with_data("", status=204)


class TestIngest:
    def test_one_create_with_the_files_name(
        self, svc: flows.Services, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        seen: list[dict[str, Any]] = []
        httpserver.expect_request(DOCUMENTS, method="POST").respond_with_handler(
            capture_upload(created(), 201, seen)
        )
        assert flows.ingest(svc, guidebook, name=None).document_id == DOCUMENT_ID
        assert calls(httpserver) == [("POST", DOCUMENTS)]
        assert seen[0]["form"] == {"name": "guidebook.md"}
        assert seen[0]["files"] == {"file": ("guidebook.md", guidebook.read_bytes())}

    def test_a_name_replaces_the_files(
        self, svc: flows.Services, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        seen: list[dict[str, Any]] = []
        httpserver.expect_request(DOCUMENTS, method="POST").respond_with_handler(
            capture_upload(created(), 201, seen)
        )
        flows.ingest(svc, guidebook, name="Villa")
        assert seen[0]["form"] == {"name": "Villa"}

    @pytest.mark.parametrize("name", ["missing.md", "."])
    def test_an_unreadable_path_makes_no_call(
        self, svc: flows.Services, httpserver: HTTPServer, tmp_path: Path, name: str
    ) -> None:
        with pytest.raises(FileUnreadableError):
            flows.ingest(svc, tmp_path / name, name=None)
        assert httpserver.log == []


class TestReplace:
    def test_one_put(self, svc: flows.Services, httpserver: HTTPServer, guidebook: Path) -> None:
        _expect(httpserver, "PUT", DOCUMENT, created(4))
        assert flows.replace(svc, DOCUMENT_ID, guidebook, name=None).document_id == DOCUMENT_ID
        assert calls(httpserver) == [("PUT", DOCUMENT)]


class TestAsk:
    def test_search_then_generation(self, svc: flows.Services, httpserver: HTTPServer) -> None:
        _expect(httpserver, "POST", SEARCH, hits("Check-in from 15:00"))
        _expect(httpserver, "POST", GENERATE, generated())
        assert flows.ask(svc, DOCUMENT_ID, "When can I check in?") == _ANSWER
        assert calls(httpserver) == [("POST", SEARCH), ("POST", GENERATE)]

    def test_generation_gets_the_alias_and_the_fragments(
        self, svc: flows.Services, httpserver: HTTPServer
    ) -> None:
        _expect(httpserver, "POST", SEARCH, hits("Check-in from 15:00"))
        _expect(httpserver, "POST", GENERATE, generated())
        flows.ask(svc, DOCUMENT_ID, "When can I check in?")
        body = json.loads(httpserver.log[1][0].data)
        assert body["model"] == "fast"
        assert "Check-in from 15:00" in body["messages"][0]["content"]

    def test_an_empty_search_skips_generation(
        self, svc: flows.Services, httpserver: HTTPServer
    ) -> None:
        _expect(httpserver, "POST", SEARCH, hits())
        assert flows.ask(svc, DOCUMENT_ID, "Is there a sauna?") is None
        assert calls(httpserver) == [("POST", SEARCH)]

    def test_a_missing_document_stops_before_generation(
        self, svc: flows.Services, httpserver: HTTPServer
    ) -> None:
        _expect(httpserver, "POST", SEARCH, envelope("NotFoundError"), status=404)
        with pytest.raises(DocumentNotFoundError):
            flows.ask(svc, DOCUMENT_ID, "q")
        assert calls(httpserver) == [("POST", SEARCH)]


class TestOneShot:
    def test_ingest_ask_delete(
        self, svc: flows.Services, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        _expect(httpserver, "POST", DOCUMENTS, created(), status=201)
        _expect(httpserver, "POST", SEARCH, hits("Check-in from 15:00"))
        _expect(httpserver, "POST", GENERATE, generated())
        _expect_deleted(httpserver)
        shot = flows.ask_from_file(svc, guidebook, "When can I check in?")
        assert shot == flows.OneShot(document_id=DOCUMENT_ID, answer=_ANSWER, cleanup_failure=None)
        assert calls(httpserver) == [
            ("POST", DOCUMENTS),
            ("POST", SEARCH),
            ("POST", GENERATE),
            ("DELETE", DOCUMENT),
        ]

    def test_the_document_is_deleted_when_generation_fails(
        self, svc: flows.Services, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        _expect(httpserver, "POST", DOCUMENTS, created(), status=201)
        _expect(httpserver, "POST", SEARCH, hits("x"))
        _expect(httpserver, "POST", GENERATE, envelope("UpstreamLlmError"), status=502)
        _expect_deleted(httpserver)
        with pytest.raises(ProviderUnavailableError) as error:
            flows.ask_from_file(svc, guidebook, "q")
        assert error.value.cleanup_failure is None
        assert calls(httpserver)[-1] == ("DELETE", DOCUMENT)

    def test_a_failed_deletion_rides_on_the_original_error(
        self, svc: flows.Services, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        _expect(httpserver, "POST", DOCUMENTS, created(), status=201)
        _expect(httpserver, "POST", SEARCH, hits("x"))
        _expect(httpserver, "POST", GENERATE, envelope("UpstreamLlmError"), status=502)
        _expect(httpserver, "DELETE", DOCUMENT, envelope("InternalError"), status=500)
        with pytest.raises(ProviderUnavailableError) as error:
            flows.ask_from_file(svc, guidebook, "q")
        failure = error.value.cleanup_failure
        assert failure is not None
        assert failure.document_id == DOCUMENT_ID
        assert isinstance(failure.error, UnexpectedResponseError)

    def test_a_failed_deletion_after_an_answer_comes_back_beside_it(
        self, svc: flows.Services, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        _expect(httpserver, "POST", DOCUMENTS, created(), status=201)
        _expect(httpserver, "POST", SEARCH, hits("Check-in from 15:00"))
        _expect(httpserver, "POST", GENERATE, generated())
        _expect(httpserver, "DELETE", DOCUMENT, envelope("InternalError"), status=500)
        shot = flows.ask_from_file(svc, guidebook, "q")
        assert shot.answer == _ANSWER
        assert shot.cleanup_failure is not None
        assert shot.cleanup_failure.error.code == "InternalError"

    def test_a_document_already_gone_is_no_cleanup_failure(
        self, svc: flows.Services, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        _expect(httpserver, "POST", DOCUMENTS, created(), status=201)
        _expect(httpserver, "POST", SEARCH, hits("Check-in from 15:00"))
        _expect(httpserver, "POST", GENERATE, generated())
        _expect(httpserver, "DELETE", DOCUMENT, envelope("NotFoundError"), status=404)
        shot = flows.ask_from_file(svc, guidebook, "q")
        assert (shot.answer, shot.cleanup_failure) == (_ANSWER, None)

    def test_no_context_still_deletes(
        self, svc: flows.Services, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        _expect(httpserver, "POST", DOCUMENTS, created(), status=201)
        _expect(httpserver, "POST", SEARCH, hits())
        _expect_deleted(httpserver)
        assert flows.ask_from_file(svc, guidebook, "q").answer is None
        assert calls(httpserver) == [("POST", DOCUMENTS), ("POST", SEARCH), ("DELETE", DOCUMENT)]

    def test_a_failed_ingest_stops_everything(
        self, svc: flows.Services, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        _expect(httpserver, "POST", DOCUMENTS, envelope("UnsupportedMediaTypeError"), status=415)
        with pytest.raises(RequestRejectedError):
            flows.ask_from_file(svc, guidebook, "q")
        assert calls(httpserver) == [("POST", DOCUMENTS)]

    def test_a_defect_still_deletes_the_document(
        self,
        svc: flows.Services,
        httpserver: HTTPServer,
        guidebook: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def broken(*_args: object) -> None:
            raise RuntimeError("defect")

        monkeypatch.setattr(flows, "render", broken)
        _expect(httpserver, "POST", DOCUMENTS, created(), status=201)
        _expect(httpserver, "POST", SEARCH, hits("x"))
        _expect_deleted(httpserver)
        with pytest.raises(RuntimeError):
            flows.ask_from_file(svc, guidebook, "q")
        assert calls(httpserver)[-1] == ("DELETE", DOCUMENT)


class TestRemove:
    def test_one_delete(self, svc: flows.Services, httpserver: HTTPServer) -> None:
        _expect_deleted(httpserver)
        flows.remove(svc, DOCUMENT_ID)
        assert calls(httpserver) == [("DELETE", DOCUMENT)]

    def test_a_missing_document_is_not_found(
        self, svc: flows.Services, httpserver: HTTPServer
    ) -> None:
        _expect(httpserver, "DELETE", DOCUMENT, envelope("NotFoundError"), status=404)
        with pytest.raises(DocumentNotFoundError):
            flows.remove(svc, DOCUMENT_ID)
