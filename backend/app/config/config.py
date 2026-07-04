from __future__ import annotations

from datetime import timedelta
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime configuration loaded from environment variables (spec §8.0 / §10.2).

    Application-scoped field set (DEC-1): only the values consumed by the use cases (§9). Infra
    fields (DB / Resend / embedding / observability / CORS) are added by their own tickets
    (B-31+), co-located with the adapters that read them.

    Almost no field has a Python default — a missing env var fails fast at construction (§10.1); the
    env-specific sample-source params are Nullable, since each env sets only the source it uses:
    ``sample_guidebook_path`` (dev, local file) vs ``sample_guidebook_s3_*`` + ``aws_resources_region``
    (staging/prod, S3). Numeric
    invariants (``> 0``, non-empty secret) are enforced here so the application layer never
    re-checks them (§8.2.4 / §9.0). The ``model_id_*`` fields opt out of pydantic's ``model_``
    protected namespace.

    ``env`` is the deployment discriminator. There is a single config source (environment
    variables — under serverless the secrets are fetched into ``os.environ`` by the cold-start
    bootstrap before ``Settings`` is built), so per-environment behaviour lives in ONE class via
    :meth:`_enforce_prod_guardrails` (branching on ``env``), not in per-env subclasses — which would
    only be warranted by *different config sources* per env (clarifications C-17 / C-18).

    Environment-variable contract (source per deployment env)
    ---------------------------------------------------------
    All config is read from ``os.environ`` (single source). HOW a variable enters the
    environment differs by ``ENV`` — this split is the contract the infrastructure
    (Terraform / docker-compose) must honor:

    * Non-secret config (everything except the four secrets below): plain env vars in every
      env — dev: ``.env`` / docker-compose; staging|prod: Lambda env vars set by Terraform.
    * Secrets — ``database_url``, ``resend_api_key``, ``ip_hash_salt``,
      ``sample_server_api_key`` (all ``SecretStr``): dev — plain env vars from ``.env``;
      staging|prod — stored in AWS Secrets Manager as ``holahost/{env}/<name>`` and fetched
      into ``os.environ`` by the cold-start bootstrap (``scripts/bootstrap.py``) BEFORE
      ``Settings`` is built. NEVER passed as Terraform-injected Lambda env values
      (anti-pattern: secret material in the function config).
    * ``ENV`` is read by the bootstrap before ``Settings`` to choose the secret-loading +
      adapter branch (dev → no Secrets Manager, SMTP/Mailpit email; staging|prod → Secrets
      Manager, Resend email).
    * ``SMTP_HOST`` / ``SMTP_PORT`` are dev-only, consumed DIRECTLY by the dev email branch
      of the bootstrap (defaults ``localhost`` / ``1025``); intentionally NOT ``Settings``
      fields so the prod schema stays clean.
    """

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore", protected_namespaces=())

    env: Literal["dev", "staging", "prod"]
    model_id_sample: str
    model_id_real: str
    system_prompt: str
    max_output_tokens: int = Field(gt=0)
    retrieval_top_k: int = Field(gt=0)
    sample_server_api_key: SecretStr = Field(min_length=1)
    haiku_output_price_per_mtok: float = Field(gt=0)
    sample_budget_daily_cap_tokens: int = Field(gt=0)
    max_upload_size_bytes: int = Field(gt=0)
    min_upload_size_bytes: int = Field(gt=0)
    allowed_mime_types: frozenset[str] = Field(min_length=1)
    min_extracted_text_chars: int = Field(gt=0)
    max_chunks_per_guidebook: int = Field(gt=0)
    min_chunks_per_guidebook: int = Field(gt=0)
    magic_link_ttl_days: int = Field(gt=0)
    cleanup_batch_size: int = Field(gt=0)
    max_rate_limit_window_seconds: int = Field(gt=0)
    database_url: SecretStr = Field(min_length=1)
    ip_hash_salt: SecretStr = Field(min_length=1)
    magic_link_token_bytes: int = Field(gt=0)
    rate_limit_per_ip: int = Field(gt=0)
    rate_limit_per_magic_link: int = Field(gt=0)
    rate_limit_window_seconds: int = Field(gt=0)
    # Infrastructure adapter config (B-38…B-45). Co-located here per the one-class env model (§10.2).
    embedding_model_name: str
    # Sample-guidebook source — env-specific & mutually exclusive, so each param is Nullable; the wiring
    # (``make_sample_source``) picks one by ``env`` and fail-fasts if its params are unset. dev → the local
    # file ``sample_guidebook_path``; staging/prod → S3 (``sample_guidebook_s3_bucket``/``_key``).
    # ``aws_resources_region`` is the app's boto region (SM/S3); ALSO read raw in bootstrap.py for the
    # pre-Settings Secrets Manager client. Distinct from the Lambda-runtime AWS_REGION (= deploy region, CI).
    sample_guidebook_path: str | None = None
    aws_resources_region: str | None = None
    sample_guidebook_s3_bucket: str | None = None
    sample_guidebook_s3_key: str | None = None
    max_chunk_tokens: int = Field(gt=0)
    chunk_window: int = Field(gt=0)
    chunk_overlap: int = Field(ge=0)
    anthropic_base_url: str
    llm_timeout_seconds: float = Field(gt=0)
    resend_api_key: SecretStr = Field(min_length=1)
    resend_from: str
    # Magic-link URL contract is frontend-owned (the SPA's landing route + token query param, §11);
    # Terraform relays both into this backend (D-21). The wiring composes the URL prefix
    # ``{frontend_origin}{magic_link_path}?{magic_link_url_param}=`` for the EmailSender.
    magic_link_path: str
    magic_link_url_param: str
    email_timeout_seconds: float = Field(gt=0)
    frontend_origin: str

    @property
    def magic_link_ttl(self) -> timedelta:
        """Sliding-window TTL for magic_link / guidebook, from ``magic_link_ttl_days`` (§10.1)."""
        return timedelta(days=self.magic_link_ttl_days)

    @property
    def max_rate_limit_window(self) -> timedelta:
        """Rate-counter retention window, from ``max_rate_limit_window_seconds`` (§9.7 / §10.2).

        An int-seconds env field (plain integer for ops) exposed as a ``timedelta``, mirroring the
        ``magic_link_ttl_days`` -> ``magic_link_ttl`` convention; avoids ISO-8601 duration env values.
        """
        return timedelta(seconds=self.max_rate_limit_window_seconds)

    @model_validator(mode="after")
    def _enforce_prod_guardrails(self) -> Self:
        """Fail-fast guardrails that only apply in production (§10.1 — misconfig must not boot).

        The one-class env model: per-environment rules branch on ``env`` here rather than living in
        per-env subclasses. New prod-only invariants (e.g. real secrets, no placeholder keys) are
        added here.

        :raises ValueError: if a production deployment is misconfigured (e.g. a local database URL).
        """
        if self.env == "prod" and any(
            host in self.database_url.get_secret_value() for host in ("localhost", "127.0.0.1")
        ):
            raise ValueError("database_url must not point to localhost in prod")
        return self

    @model_validator(mode="after")
    def _validate_chunking_window(self) -> Self:
        """Chunk window must fit the embedder and overlap must be smaller than the window (§2.5).

        The embedder silently truncates inputs over ``max_chunk_tokens``; the chunker's window has
        to stay within it (C-07). This validator only checks the window/overlap relations against the
        operator-set ``max_chunk_tokens`` — it cannot load the model. That ``max_chunk_tokens`` does
        not exceed the model's REAL ceiling is enforced at the composition root (B-46) via
        ``FastEmbedEmbeddingModel.max_input_tokens()`` (fail-fast); the real limit is 128 (D6).

        :raises ValueError: if ``chunk_window > max_chunk_tokens`` or ``chunk_overlap >= chunk_window``.
        """
        if self.chunk_window > self.max_chunk_tokens:
            raise ValueError("chunk_window must be <= max_chunk_tokens")
        if self.chunk_overlap >= self.chunk_window:
            raise ValueError("chunk_overlap must be < chunk_window")
        return self

    @classmethod
    def from_env(cls) -> Settings:
        """Build ``Settings`` from environment variables (composition root, §8.6)."""
        return cls()
