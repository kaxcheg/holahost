from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.settings import Settings
from interface.http.dependencies import get_auth_config


def _env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    base = {
        "ENV": "dev",
        "POSTGRES_USER": "user",
        "POSTGRES_PASSWORD": "pass",
        "POSTGRES_DB": "rag_documents",
        "EMBEDDING_MODEL": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "EMBEDDING_CACHE_DIR": "/cache/fastembed",
        "CHUNK_WINDOW_TOKENS": "120",
        "CHUNK_OVERLAP_TOKENS": "16",
        "SEARCH_TOP_K": "5",
        "SIMILARITY_THRESHOLD": "0.30",
        "MAX_QUERY_LENGTH": "4000",
        "RATE_LIMIT_USER_INGEST": "60",
        "RATE_LIMIT_USER_READ": "600",
        "RATE_LIMIT_SERVICE_INGEST": "60",
        "RATE_LIMIT_SERVICE_READ": "600",
        "JWT_CLOCK_SKEW_SECONDS": "30",
        "JWKS_URL": "https://auth.dev.holahost.internal/.well-known/jwks.json",
        "EXPECTED_ALGORITHM": "RS256",
        "EXPECTED_ISSUER": "holahost-auth-dev",
        "EXPECTED_AUDIENCE": "rag-documents",
    }
    for key, value in {**base, **overrides}.items():
        monkeypatch.setenv(key, value)


class TestSettings:
    def test_loads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _env(monkeypatch)
        settings = Settings()
        assert settings.env == "dev"
        assert settings.chunk_window_tokens == 120

    def test_missing_required_field_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _env(monkeypatch)
        monkeypatch.delenv("POSTGRES_PASSWORD")
        with pytest.raises(ValidationError):
            Settings()

    def test_chunk_overlap_must_be_smaller_than_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _env(monkeypatch, CHUNK_WINDOW_TOKENS="10", CHUNK_OVERLAP_TOKENS="10")
        with pytest.raises(ValidationError):
            Settings()

    def test_database_url_is_a_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _env(monkeypatch)
        settings = Settings()
        assert "user:pass" not in repr(settings.database_url)
        assert (
            settings.database_url.get_secret_value()
            == "postgresql+psycopg://user:pass@postgres:5432/rag_documents"
        )

    def test_database_url_uses_custom_host_and_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Defaults (`postgres`/5432) are docker-compose.yml's convention, not a hardcoded
        constant — integration tests point this at a testcontainers instance instead."""
        _env(monkeypatch, POSTGRES_HOST="localhost", POSTGRES_PORT="55432")
        settings = Settings()
        assert (
            settings.database_url.get_secret_value()
            == "postgresql+psycopg://user:pass@localhost:55432/rag_documents"
        )

    def test_database_url_percent_encodes_special_characters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`PostgresDsn.build`, not f-string interpolation: a `@`/`:` in a generated
        Secrets Manager password would silently produce a malformed URL otherwise."""
        _env(monkeypatch, POSTGRES_PASSWORD="p@ss:word")
        settings = Settings()
        assert (
            settings.database_url.get_secret_value()
            == "postgresql+psycopg://user:p%40ss%3Aword@postgres:5432/rag_documents"
        )


class TestTheAuthConfigTheServiceIsBuiltWith:
    """`AuthConfig` declares and reads its own five variables (`holahost-auth`), so what is
    left to check here is what this service is on the hook for: that its environment
    supplies them, and that the composition root hands the middleware the right audience.
    The shape of the object, its validators and its absent defaults are the library's."""

    def test_it_reads_this_services_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _env(monkeypatch)

        config = get_auth_config()

        assert config.expected_audience == "rag-documents"
        assert config.jwks_url == "https://auth.dev.holahost.internal/.well-known/jwks.json"
        assert config.jwt_clock_skew_seconds == 30

    def test_a_missing_variable_stops_the_service_starting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Reached at app-build time, which is inside `bootstrap()` — so an environment
        # missing one of the five is a process that refuses to start rather than one that
        # rejects every token later.
        _env(monkeypatch)
        monkeypatch.delenv("JWKS_URL")

        with pytest.raises(ValidationError):
            get_auth_config()
