from __future__ import annotations

from typing import Literal, Self

from holahost_db import AppRoleSettings
from pydantic import Field, model_validator


class Settings(AppRoleSettings):
    """Typed runtime configuration loaded from environment variables (§3.7/§3.8).

    One class with an `env` discriminator rather than per-env subclasses: there is a single
    config source (`os.environ`), and staging/prod populate `POSTGRES_PASSWORD` via
    `scripts.bootstrap._fetch_password_if_needed` before this class is constructed.

    Inherits the application's Postgres identity from `holahost_db.AppRoleSettings`, so
    those credentials have one declaration shared with `scripts/provision_app_role.py`.
    The superuser pair lives in `SuperuserSettings`, a separate model, and never reaches
    this class — which is what keeps a serving process from holding the credential that
    bypasses row-level security.

    Carries none of the five token-validation variables either: `holahost_auth.AuthConfig`
    reads those itself. They are a platform contract, identical behind every service except
    for the value of `expected_audience`, and the auth library is where they belong — a
    middleware handed an object that also carries a database password sees more than it
    needs to.

    Deliberately carries no `ALLOWED_MIME_TYPES` / `MAX_UPLOAD_SIZE`: those are domain and
    application constants, co-located with the code that enforces them. The interface layer
    derives its transport cap from the latter without re-declaring the number.
    """

    env: Literal["dev", "staging", "prod"]
    embedding_model: str
    embedding_cache_dir: str
    chunk_window_tokens: int = Field(gt=0)
    chunk_overlap_tokens: int = Field(ge=0)
    search_top_k: int = Field(gt=0)
    similarity_threshold: float = Field(ge=-1.0, le=1.0)
    max_query_length: int = Field(gt=0)
    # Two dimensions, four ceilings (§3.7): the bucket says how expensive the operation is,
    # the identity kind says what the ceiling counts. A service token's counter is one
    # aggregate for the calling service; an exchanged token's is per user of that client.
    # One number for both would starve a busy integration or hand each of its users the
    # whole integration's allowance.
    rate_limit_user_ingest: int = Field(gt=0)
    rate_limit_user_read: int = Field(gt=0)
    rate_limit_service_ingest: int = Field(gt=0)
    rate_limit_service_read: int = Field(gt=0)

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
