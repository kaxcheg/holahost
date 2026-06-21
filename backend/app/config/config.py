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

    No field has a Python default: a missing env var fails fast at construction (§10.1). Numeric
    invariants (``> 0``, non-empty secret) are enforced here so the application layer never
    re-checks them (§8.2.4 / §9.0). The ``model_id_*`` fields opt out of pydantic's ``model_``
    protected namespace.

    ``env`` is the deployment discriminator. There is a single config source (environment
    variables — under serverless the secrets are fetched into ``os.environ`` by the cold-start
    bootstrap before ``Settings`` is built), so per-environment behaviour lives in ONE class via
    :meth:`_enforce_prod_guardrails` (branching on ``env``), not in per-env subclasses — which would
    only be warranted by *different config sources* per env (clarifications C-17 / C-18).
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

    @property
    def rate_limit_window(self) -> timedelta:
        """Per-window size for the fixed-window rate limiter, from ``rate_limit_window_seconds``."""
        return timedelta(seconds=self.rate_limit_window_seconds)

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

    @classmethod
    def from_env(cls) -> Settings:
        """Build ``Settings`` from environment variables (composition root, §8.6)."""
        return cls()
