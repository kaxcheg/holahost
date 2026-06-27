from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import SecretStr, ValidationError

from config.config import Settings

_VALID: dict[str, object] = dict(
    env="dev",
    model_id_sample="claude-haiku-4-5-20251001",
    model_id_real="claude-sonnet-4-6",
    system_prompt="You are a helpful STR host assistant.",
    max_output_tokens=1000,
    retrieval_top_k=5,
    sample_server_api_key="sk-sample-key",
    haiku_output_price_per_mtok=1.0,
    sample_budget_daily_cap_tokens=200_000,
    max_upload_size_bytes=4_194_304,
    min_upload_size_bytes=1,
    allowed_mime_types=frozenset({"application/pdf", "text/plain"}),
    min_extracted_text_chars=20,
    max_chunks_per_guidebook=500,
    min_chunks_per_guidebook=1,
    magic_link_ttl_days=30,
    cleanup_batch_size=100,
    max_rate_limit_window_seconds=3600,
    database_url="postgresql://test",
    ip_hash_salt="test-salt",
    magic_link_token_bytes=32,
    rate_limit_per_ip=60,
    rate_limit_per_magic_link=60,
    rate_limit_window_seconds=3600,
    embedding_model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    sample_guidebook_path="docs/sample_guidebook.md",
    max_chunk_tokens=128,
    chunk_window=120,
    chunk_overlap=16,
    anthropic_base_url="https://api.anthropic.com",
    llm_timeout_seconds=30.0,
    resend_api_key="re_test_key",
    resend_from="dev@hola.host",
    magic_link_base_url="https://app.test/claim",
    magic_link_url_param="ml",
    email_timeout_seconds=10.0,
    frontend_origin="https://app.test",
)


class TestSettings:
    def test_constructs_from_explicit_values(self) -> None:
        s = Settings(**_VALID)  # type: ignore[arg-type]
        assert s.max_output_tokens == 1000
        assert isinstance(s.sample_server_api_key, SecretStr)
        assert s.sample_server_api_key.get_secret_value() == "sk-sample-key"
        assert s.allowed_mime_types == frozenset({"application/pdf", "text/plain"})

    def test_magic_link_ttl_property(self) -> None:
        s = Settings(**{**_VALID, "magic_link_ttl_days": 30})  # type: ignore[arg-type]
        assert s.magic_link_ttl == timedelta(days=30)

    def test_missing_required_field_fails_fast(self) -> None:
        partial = {k: v for k, v in _VALID.items() if k != "max_output_tokens"}
        with pytest.raises(ValidationError):
            Settings(**partial)  # type: ignore[arg-type]

    def test_non_positive_int_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(**{**_VALID, "max_output_tokens": 0})  # type: ignore[arg-type]

    def test_empty_secret_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(**{**_VALID, "sample_server_api_key": ""})  # type: ignore[arg-type]

    def test_empty_allowed_mime_types_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(**{**_VALID, "allowed_mime_types": frozenset()})  # type: ignore[arg-type]

    def test_invalid_env_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(**{**_VALID, "env": "production"})  # type: ignore[arg-type]

    def test_prod_rejects_localhost_database_url(self) -> None:
        with pytest.raises(ValidationError):
            Settings(  # type: ignore[arg-type]
                **{**_VALID, "env": "prod", "database_url": "postgresql://localhost:5432/db"}
            )

    def test_prod_accepts_remote_database_url(self) -> None:
        s = Settings(  # type: ignore[arg-type]
            **{**_VALID, "env": "prod", "database_url": "postgresql://main.db.neon.tech/app"}
        )
        assert s.env == "prod"

    def test_chunk_window_exceeding_max_chunk_tokens_rejected(self) -> None:
        # The chunker window must fit the embedder's ceiling, else it silently truncates (§2.5 / C-07).
        with pytest.raises(ValidationError):
            Settings(**{**_VALID, "max_chunk_tokens": 128, "chunk_window": 129})  # type: ignore[arg-type]

    def test_chunk_overlap_not_below_window_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(**{**_VALID, "chunk_window": 120, "chunk_overlap": 120})  # type: ignore[arg-type]

    def test_from_env_reads_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, val in _VALID.items():
            if key == "allowed_mime_types":
                monkeypatch.setenv(key.upper(), '["application/pdf","text/plain"]')
            elif key == "sample_server_api_key":
                monkeypatch.setenv(key.upper(), "sk-env")
            else:
                monkeypatch.setenv(key.upper(), str(val))
        s = Settings.from_env()
        assert s.max_rate_limit_window == timedelta(hours=1)
        assert s.magic_link_ttl == timedelta(days=30)
        assert s.allowed_mime_types == frozenset({"application/pdf", "text/plain"})
        assert s.sample_server_api_key.get_secret_value() == "sk-env"
