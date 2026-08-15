from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime configuration loaded from environment variables (§3.7/§3.8).

    One class with an `env` discriminator (not per-env subclasses) — per-environment
    behavior branches inside validators such as `_validate_chunking_window`, since
    there is a single config source (`os.environ`); staging/prod populate it via
    `config.sm_loader` BEFORE this class is constructed (R-24 composition root reads
    `env` first to decide whether to run the loader — out of scope here).

    Field set originally covered the R-11..R-19 subsystems; the four `jwks_url`/
    `expected_*` fields were added by R-20/R-24 for `holahost-auth` wiring. Deliberately
    does *not* carry `ALLOWED_MIME_TYPES`/`MAX_UPLOAD_SIZE`: those stay domain/
    application-owned constants (`domain.value_objects.mime_type.ALLOWED_MIME_TYPES`,
    `application.limits.MAX_UPLOAD_SIZE`) — the interface layer never needs its own
    copy of either, matching the project's "co-located with the adapter that reads it"
    convention.
    """

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    env: Literal["dev", "staging", "prod"]
    database_url: SecretStr = Field(min_length=1)
    embedding_model: str
    embedding_cache_dir: str
    chunk_window_tokens: int = Field(gt=0)
    chunk_overlap_tokens: int = Field(ge=0)
    search_top_k: int = Field(gt=0)
    similarity_threshold: float = Field(ge=-1.0, le=1.0)
    max_query_length: int = Field(gt=0)
    rate_limit_default: int = Field(gt=0)
    rate_limit_ingest: int = Field(gt=0)
    jwt_clock_skew_seconds: int = Field(ge=0)
    jwks_url: str = Field(min_length=1)
    expected_algorithm: str = Field(min_length=1)
    expected_issuer: str = Field(min_length=1)
    expected_audience: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_chunking_window(self) -> Self:
        """`chunk_overlap_tokens` must be smaller than `chunk_window_tokens` (§3.7).

        :raises ValueError: overlap >= window.
        """
        if self.chunk_overlap_tokens >= self.chunk_window_tokens:
            raise ValueError("chunk_overlap_tokens must be < chunk_window_tokens")
        return self

    @classmethod
    def from_env(cls) -> Settings:
        """Build `Settings` from environment variables (composition root, R-24)."""
        return cls()
