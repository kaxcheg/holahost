"""Settings: read from the environment, refused before any network call, never echoing the token."""

from __future__ import annotations

import pytest

from guest_reply.config import load_settings
from guest_reply.errors import ConfigurationError

_ENV = {
    "HOLAHOST_RAG_DOCUMENTS_URL": "http://localhost:8080",
    "HOLAHOST_LLM_CLIENT_URL": "http://localhost:8081",
    "HOLAHOST_TOKEN": "header.payload.signature",
}


def _set(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    for name, value in (_ENV | overrides).items():
        monkeypatch.setenv(name, value)


def test_the_variables_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch)
    settings = load_settings()
    assert (settings.rag_documents_url, settings.llm_client_url) == (
        "http://localhost:8080",
        "http://localhost:8081",
    )
    assert settings.token.get_secret_value() == "header.payload.signature"


def test_the_model_alias_defaults_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch)
    assert load_settings().model_alias == "default"


def test_the_model_alias_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, HOLAHOST_MODEL_ALIAS="fast")
    assert load_settings().model_alias == "fast"


@pytest.mark.parametrize("variable", sorted(_ENV))
def test_a_missing_variable_is_named(monkeypatch: pytest.MonkeyPatch, variable: str) -> None:
    _set(monkeypatch)
    monkeypatch.delenv(variable)
    with pytest.raises(ConfigurationError, match=variable) as error:
        load_settings()
    assert error.value.details == {variable: "not set"}


def test_an_empty_token_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, HOLAHOST_TOKEN="")
    with pytest.raises(ConfigurationError, match="HOLAHOST_TOKEN"):
        load_settings()


def test_a_trailing_slash_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, HOLAHOST_RAG_DOCUMENTS_URL="http://localhost:8080/")
    assert load_settings().rag_documents_url == "http://localhost:8080"


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8080", "http://[::1]:8080", "https://rag.example.com"]
)
def test_a_local_or_https_origin_is_accepted(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    _set(monkeypatch, HOLAHOST_RAG_DOCUMENTS_URL=url)
    assert load_settings().rag_documents_url == url


def test_plain_http_to_another_host_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, HOLAHOST_RAG_DOCUMENTS_URL="http://rag.example.com")
    with pytest.raises(ConfigurationError, match="requires https"):
        load_settings()


@pytest.mark.parametrize(
    "url", ["localhost:8080", "ftp://localhost", "http://localhost:8080/api/rag-documents"]
)
def test_anything_but_an_origin_is_refused(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    _set(monkeypatch, HOLAHOST_RAG_DOCUMENTS_URL=url)
    with pytest.raises(ConfigurationError, match="HOLAHOST_RAG_DOCUMENTS_URL"):
        load_settings()


def test_the_token_never_reaches_the_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        HOLAHOST_TOKEN="secret-token-value",
        HOLAHOST_RAG_DOCUMENTS_URL="http://rag.example.com",
    )
    monkeypatch.delenv("HOLAHOST_LLM_CLIENT_URL")
    with pytest.raises(ConfigurationError) as error:
        load_settings()
    assert "secret-token-value" not in f"{error.value} {error.value.details}"
