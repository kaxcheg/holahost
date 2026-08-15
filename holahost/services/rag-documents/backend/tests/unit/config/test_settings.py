from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.settings import Settings


def _env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    base = {
        "ENV": "dev",
        "DATABASE_URL": "postgresql://user:pass@localhost/rag_documents",
        "EMBEDDING_MODEL": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "EMBEDDING_CACHE_DIR": "/cache/fastembed",
        "CHUNK_WINDOW_TOKENS": "120",
        "CHUNK_OVERLAP_TOKENS": "16",
        "SEARCH_TOP_K": "5",
        "SIMILARITY_THRESHOLD": "0.30",
        "MAX_QUERY_LENGTH": "4000",
        "RATE_LIMIT_DEFAULT": "600",
        "RATE_LIMIT_INGEST": "60",
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

    def test_loads_auth_config_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _env(monkeypatch)
        settings = Settings()
        assert settings.jwks_url == "https://auth.dev.holahost.internal/.well-known/jwks.json"
        assert settings.expected_algorithm == "RS256"
        assert settings.expected_issuer == "holahost-auth-dev"
        assert settings.expected_audience == "rag-documents"

    def test_missing_required_field_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _env(monkeypatch)
        monkeypatch.delenv("DATABASE_URL")
        with pytest.raises(ValidationError):
            Settings()

    def test_missing_jwks_url_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _env(monkeypatch)
        monkeypatch.delenv("JWKS_URL")
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
            == "postgresql://user:pass@localhost/rag_documents"
        )
