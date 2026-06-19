from __future__ import annotations

from datetime import timedelta

from pydantic import Field, SecretStr
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
    """

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore", protected_namespaces=())

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

    @classmethod
    def from_env(cls) -> Settings:
        """Build ``Settings`` from environment variables (composition root, §8.6)."""
        return cls()
