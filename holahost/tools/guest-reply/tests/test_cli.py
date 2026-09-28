"""The command line end to end, against faked services: stdout, stderr and the exit code."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner, Result

from guest_reply.cli import EXIT_CODES, app
from guest_reply.errors import GuestReplyError
from tests._support import (
    DOCUMENT,
    DOCUMENT_ID,
    DOCUMENTS,
    GENERATE,
    SEARCH,
    TOKEN,
    calls,
    created,
    envelope,
    generated,
    hits,
    origin,
)

runner = CliRunner()


def _env(httpserver: HTTPServer) -> dict[str, str]:
    return {
        "HOLAHOST_RAG_DOCUMENTS_URL": origin(httpserver),
        "HOLAHOST_LLM_CLIENT_URL": origin(httpserver),
        "HOLAHOST_TOKEN": TOKEN,
        "HOLAHOST_MODEL_ALIAS": "fast",
    }


def _run(httpserver: HTTPServer, *args: str) -> Result:
    result = runner.invoke(app, list(args), env=_env(httpserver))
    assert TOKEN not in result.stdout + result.stderr
    return result


def _expect(httpserver: HTTPServer, method: str, path: str, body: Any, status: int = 200) -> None:
    httpserver.expect_ordered_request(path, method=method).respond_with_json(body, status=status)


def _deleted(httpserver: HTTPServer) -> None:
    httpserver.expect_ordered_request(DOCUMENT, method="DELETE").respond_with_data("", status=204)


def _request_ids(httpserver: HTTPServer) -> set[str]:
    return {request.headers["X-Request-ID"] for request, _ in httpserver.log}


@pytest.fixture
def guidebook(tmp_path: Path) -> Path:
    path = tmp_path / "guidebook.md"
    path.write_text("# Villa\nCheck-in from 15:00.\n", encoding="utf-8")
    return path


class TestIngest:
    def test_stdout_is_the_document_id_alone(self, httpserver: HTTPServer, guidebook: Path) -> None:
        _expect(httpserver, "POST", DOCUMENTS, created(), status=201)
        result = _run(httpserver, "ingest", str(guidebook))
        assert (result.exit_code, result.stdout, result.stderr) == (0, f"{DOCUMENT_ID}\n", "")

    def test_json_is_one_object_with_the_request_id(
        self, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        _expect(httpserver, "POST", DOCUMENTS, created(), status=201)
        result = _run(httpserver, "ingest", str(guidebook), "--json")
        assert json.loads(result.stdout) == {
            "document_id": DOCUMENT_ID,
            "chunk_count": 3,
            "request_id": _request_ids(httpserver).pop(),
        }

    def test_an_unreadable_file_is_exit_3_with_no_call(
        self, httpserver: HTTPServer, tmp_path: Path
    ) -> None:
        result = _run(httpserver, "ingest", str(tmp_path / "missing.md"))
        assert (result.exit_code, result.stdout) == (3, "")
        assert "FileUnreadableError" in result.stderr
        assert httpserver.log == []

    def test_a_refused_file_shows_the_code_and_the_details(
        self, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        body = envelope("UploadTooLargeError", "too large", {"limit": 8388608, "actual": 9000000})
        _expect(httpserver, "POST", DOCUMENTS, body, status=413)
        result = _run(httpserver, "ingest", str(guidebook))
        assert (result.exit_code, result.stdout) == (11, "")
        assert "UploadTooLargeError" in result.stderr
        assert "limit: 8388608" in result.stderr

    def test_a_json_error_carries_the_services_envelope(
        self, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        body = envelope("UploadTooLargeError", "too large", {"limit": 8388608, "actual": 9000000})
        _expect(httpserver, "POST", DOCUMENTS, body, status=413)
        result = _run(httpserver, "ingest", str(guidebook), "--json")
        assert result.exit_code == 11
        assert json.loads(result.stdout) == {
            "error": body["error"],
            "request_id": _request_ids(httpserver).pop(),
        }


class TestReplace:
    def test_the_same_document_id_comes_back(self, httpserver: HTTPServer, guidebook: Path) -> None:
        _expect(httpserver, "PUT", DOCUMENT, created())
        result = _run(httpserver, "replace", DOCUMENT_ID, str(guidebook))
        assert (result.exit_code, result.stdout) == (0, f"{DOCUMENT_ID}\n")

    def test_a_malformed_document_id_is_a_usage_error(
        self, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        result = _run(httpserver, "replace", "not-a-uuid", str(guidebook))
        assert result.exit_code == 2
        assert httpserver.log == []

    def test_someone_elses_document_is_not_found(
        self, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        _expect(httpserver, "PUT", DOCUMENT, envelope("NotFoundError"), status=404)
        result = _run(httpserver, "replace", DOCUMENT_ID, str(guidebook))
        assert result.exit_code == 4
        assert "document not found" in result.stderr


class TestAsk:
    def test_stdout_is_the_answer_alone(self, httpserver: HTTPServer) -> None:
        _expect(httpserver, "POST", SEARCH, hits("Check-in from 15:00"))
        _expect(httpserver, "POST", GENERATE, generated())
        result = _run(httpserver, "ask", DOCUMENT_ID, "When can I check in?")
        assert (result.exit_code, result.stdout, result.stderr) == (
            0,
            "Check-in is from 15:00.\n",
            "",
        )

    def test_json_carries_the_usage_and_the_model_that_answered(
        self, httpserver: HTTPServer
    ) -> None:
        _expect(httpserver, "POST", SEARCH, hits("Check-in from 15:00"))
        _expect(httpserver, "POST", GENERATE, generated())
        result = _run(httpserver, "ask", DOCUMENT_ID, "When?", "--json")
        assert json.loads(result.stdout) == {
            "answer": "Check-in is from 15:00.",
            "chunks_used": 1,
            "usage": {"input_tokens": 120, "output_tokens": 12},
            "provider": "anthropic",
            "model": "claude-haiku-4-5",
            "document_id": DOCUMENT_ID,
            "request_id": _request_ids(httpserver).pop(),
        }

    def test_no_context_is_exit_5_without_generation(self, httpserver: HTTPServer) -> None:
        _expect(httpserver, "POST", SEARCH, hits())
        result = _run(httpserver, "ask", DOCUMENT_ID, "Is there a sauna?")
        assert (result.exit_code, result.stdout) == (5, "")
        assert "no relevant context" in result.stderr
        assert calls(httpserver) == [("POST", SEARCH)]

    def test_no_context_in_json(self, httpserver: HTTPServer) -> None:
        _expect(httpserver, "POST", SEARCH, hits())
        result = _run(httpserver, "ask", DOCUMENT_ID, "q", "--json")
        assert result.exit_code == 5
        assert json.loads(result.stdout) == {
            "answer": None,
            "chunks_used": 0,
            "document_id": DOCUMENT_ID,
            "request_id": _request_ids(httpserver).pop(),
        }

    def test_an_unavailable_provider_is_exit_7(self, httpserver: HTTPServer) -> None:
        _expect(httpserver, "POST", SEARCH, hits("x"))
        _expect(httpserver, "POST", GENERATE, envelope("UpstreamLlmError"), status=502)
        assert _run(httpserver, "ask", DOCUMENT_ID, "q").exit_code == 7

    @pytest.mark.parametrize(
        "args",
        [
            ["--file", "guidebook.md", DOCUMENT_ID, "q"],
            ["q"],
            [DOCUMENT_ID, "q", "extra"],
            ["not-a-uuid", "q"],
        ],
    )
    def test_malformed_arguments_are_a_usage_error_with_no_call(
        self, httpserver: HTTPServer, args: list[str]
    ) -> None:
        result = _run(httpserver, "ask", *args)
        assert result.exit_code == 2
        assert httpserver.log == []


class TestOneShot:
    def test_the_answer_and_one_request_id_across_four_calls(
        self, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        _expect(httpserver, "POST", DOCUMENTS, created(), status=201)
        _expect(httpserver, "POST", SEARCH, hits("Check-in from 15:00"))
        _expect(httpserver, "POST", GENERATE, generated())
        _deleted(httpserver)
        result = _run(httpserver, "ask", "--file", str(guidebook), "When?", "--json")
        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["document_id"] == DOCUMENT_ID
        assert _request_ids(httpserver) == {output["request_id"]}
        assert len(httpserver.log) == 4

    def test_the_document_id_is_not_printed_without_json(
        self, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        _expect(httpserver, "POST", DOCUMENTS, created(), status=201)
        _expect(httpserver, "POST", SEARCH, hits("x"))
        _expect(httpserver, "POST", GENERATE, generated())
        _deleted(httpserver)
        result = _run(httpserver, "ask", "--file", str(guidebook), "When?")
        assert (result.exit_code, result.stdout) == (0, "Check-in is from 15:00.\n")

    def test_a_failed_generation_still_deletes(
        self, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        _expect(httpserver, "POST", DOCUMENTS, created(), status=201)
        _expect(httpserver, "POST", SEARCH, hits("x"))
        _expect(httpserver, "POST", GENERATE, envelope("UpstreamLlmError"), status=502)
        _deleted(httpserver)
        result = _run(httpserver, "ask", "--file", str(guidebook), "q")
        assert result.exit_code == 7
        assert calls(httpserver)[-1] == ("DELETE", DOCUMENT)

    def test_a_document_left_behind_is_reported_and_fails_the_command(
        self, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        _expect(httpserver, "POST", DOCUMENTS, created(), status=201)
        _expect(httpserver, "POST", SEARCH, hits("x"))
        _expect(httpserver, "POST", GENERATE, generated())
        _expect(httpserver, "DELETE", DOCUMENT, envelope("InternalError"), status=500)
        result = _run(httpserver, "ask", "--file", str(guidebook), "q", "--json")
        assert result.exit_code == 9
        output = json.loads(result.stdout)
        assert output["answer"] == "Check-in is from 15:00."
        assert output["cleanup_error"]["document_id"] == DOCUMENT_ID
        assert output["cleanup_error"]["error"]["code"] == "InternalError"
        assert f"guest-reply rm {DOCUMENT_ID}" in result.stderr

    def test_a_document_left_behind_after_a_failure_is_in_the_json_error(
        self, httpserver: HTTPServer, guidebook: Path
    ) -> None:
        _expect(httpserver, "POST", DOCUMENTS, created(), status=201)
        _expect(httpserver, "POST", SEARCH, hits("x"))
        _expect(httpserver, "POST", GENERATE, envelope("UpstreamLlmError"), status=502)
        _expect(httpserver, "DELETE", DOCUMENT, envelope("InternalError"), status=500)
        result = _run(httpserver, "ask", "--file", str(guidebook), "q", "--json")
        assert result.exit_code == 7
        output = json.loads(result.stdout)
        assert output["error"]["code"] == "UpstreamLlmError"
        assert output["cleanup_error"]["document_id"] == DOCUMENT_ID
        assert output["cleanup_error"]["error"]["code"] == "InternalError"


class TestRm:
    def test_nothing_on_stdout(self, httpserver: HTTPServer) -> None:
        _deleted(httpserver)
        result = _run(httpserver, "rm", DOCUMENT_ID)
        assert (result.exit_code, result.stdout) == (0, "")

    def test_json(self, httpserver: HTTPServer) -> None:
        _deleted(httpserver)
        result = _run(httpserver, "rm", DOCUMENT_ID, "--json")
        assert json.loads(result.stdout) == {
            "document_id": DOCUMENT_ID,
            "deleted": True,
            "request_id": _request_ids(httpserver).pop(),
        }

    def test_a_missing_document_is_exit_4(self, httpserver: HTTPServer) -> None:
        _expect(httpserver, "DELETE", DOCUMENT, envelope("NotFoundError"), status=404)
        result = _run(httpserver, "rm", DOCUMENT_ID)
        assert result.exit_code == 4
        assert "document not found" in result.stderr


class TestFailures:
    def test_missing_configuration_is_exit_1_before_any_call(self, httpserver: HTTPServer) -> None:
        env = _env(httpserver)
        del env["HOLAHOST_RAG_DOCUMENTS_URL"]
        result = runner.invoke(app, ["rm", DOCUMENT_ID], env=env)
        assert result.exit_code == 1
        assert "HOLAHOST_RAG_DOCUMENTS_URL" in result.stderr
        assert httpserver.log == []

    def test_missing_configuration_in_json(self, httpserver: HTTPServer) -> None:
        env = _env(httpserver)
        del env["HOLAHOST_TOKEN"]
        result = runner.invoke(app, ["rm", DOCUMENT_ID, "--json"], env=env)
        assert json.loads(result.stdout)["error"]["code"] == "ConfigurationError"

    def test_a_rejected_token_is_exit_10(self, httpserver: HTTPServer) -> None:
        _expect(httpserver, "DELETE", DOCUMENT, {"detail": "Unauthorized"}, status=401)
        result = _run(httpserver, "rm", DOCUMENT_ID)
        assert result.exit_code == 10
        assert "dev-minter token" in result.stderr

    def test_a_short_rate_limit_is_announced_and_waited_out(self, httpserver: HTTPServer) -> None:
        body = envelope("RateLimitExceededError", "rate limit exceeded", {"retry_after_seconds": 0})
        httpserver.expect_ordered_request(DOCUMENT, method="DELETE").respond_with_json(
            body, status=429, headers={"Retry-After": "0"}
        )
        _deleted(httpserver)
        result = _run(httpserver, "rm", DOCUMENT_ID)
        assert result.exit_code == 0
        assert "rate limited" in result.stderr

    def test_a_spent_budget_is_exit_6_with_its_reset(self, httpserver: HTTPServer) -> None:
        _expect(httpserver, "POST", SEARCH, hits("x"))
        body = envelope("BudgetExhaustedError", "budget", {"scope": "client", "resets_at": "T"})
        httpserver.expect_ordered_request(GENERATE, method="POST").respond_with_json(
            body, status=429, headers={"Retry-After": "43200"}
        )
        result = _run(httpserver, "ask", DOCUMENT_ID, "q")
        assert result.exit_code == 6
        assert "BudgetExhaustedError" in result.stderr
        assert "resets_at: T" in result.stderr

    def test_an_unreachable_service_is_exit_8(self, httpserver: HTTPServer) -> None:
        env = _env(httpserver) | {"HOLAHOST_RAG_DOCUMENTS_URL": "http://127.0.0.1:9"}
        result = runner.invoke(app, ["rm", DOCUMENT_ID], env=env)
        assert result.exit_code == 8

    def test_an_internal_error_is_exit_9(self, httpserver: HTTPServer) -> None:
        _expect(httpserver, "DELETE", DOCUMENT, envelope("InternalError"), status=500)
        assert _run(httpserver, "rm", DOCUMENT_ID).exit_code == 9

    def test_each_run_has_its_own_request_id(self, httpserver: HTTPServer) -> None:
        _deleted(httpserver)
        _deleted(httpserver)
        _run(httpserver, "rm", DOCUMENT_ID)
        _run(httpserver, "rm", DOCUMENT_ID)
        assert len(_request_ids(httpserver)) == 2


def test_every_error_class_has_its_own_exit_code() -> None:
    kinds = set(GuestReplyError.__subclasses__())
    assert set(EXIT_CODES) == kinds
    codes = list(EXIT_CODES.values())
    assert len(set(codes)) == len(codes)
    assert not {0, 2, 5} & set(codes)
