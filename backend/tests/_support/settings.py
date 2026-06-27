"""``make_settings`` test factory — a fully-populated ``Settings`` with overridable fields."""

from __future__ import annotations

from config.config import Settings

_DEFAULTS: dict[str, object] = dict(
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


def make_settings(**overrides: object) -> Settings:
    """Build a fully-populated ``Settings`` for tests.

    Every required field is passed explicitly (init beats env), so the host environment never
    bleeds into a test ``Settings``. Pass ``**overrides`` to vary individual fields.
    """
    return Settings(**{**_DEFAULTS, **overrides})  # type: ignore[arg-type]
