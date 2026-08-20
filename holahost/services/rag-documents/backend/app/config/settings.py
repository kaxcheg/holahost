from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, PostgresDsn, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime configuration loaded from environment variables (§3.7/§3.8).

    One class with an `env` discriminator (not per-env subclasses) — per-environment
    behavior branches inside validators such as `_validate_chunking_window`, since
    there is a single config source (`os.environ`); staging/prod populate
    `POSTGRES_PASSWORD` via `scripts.bootstrap._fetch_password_if_needed` BEFORE this class is
    constructed (R-24 composition root reads `env` first to decide whether to run it —
    out of scope here).

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
    postgres_user: str = Field(min_length=1)
    postgres_password: SecretStr = Field(min_length=1)
    postgres_db: str = Field(min_length=1)
    # Defaults match docker-compose.yml's `postgres` service (DNS name on the compose
    # network, standard port) — real for dev/staging/prod. Overridden only by
    # integration tests, which point at a testcontainers instance on a random port
    # instead (tests/integration/interface/http/conftest.py's `client` fixture).
    postgres_host: str = "postgres"
    postgres_port: int = 5432
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> SecretStr:
        """Postgres DSN, assembled from the fields above, not read from its own env var.

        `PostgresDsn.build` over f-string interpolation: it percent-encodes special
        characters in user/password correctly (an f-string wouldn't — a `@` or `:` in a
        generated Secrets Manager password would silently produce a malformed URL, not
        an error). Bare `postgresql` scheme, not `+psycopg`: the driver dialect is an
        infrastructure concern, not a settings one — `build_engine`
        (`infrastructure/db/sqlalchemy_unit_of_work.py`) and `migrations/env.py` both
        already add `+psycopg` themselves, from a raw DSN, at the point that actually
        needs to know which driver is in use.
        """
        dsn = PostgresDsn.build(
            scheme="postgresql",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            path=self.postgres_db,
        )
        return SecretStr(str(dsn))

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
