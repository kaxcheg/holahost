from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, PostgresDsn, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _postgres_dsn(
    *, username: str, password: SecretStr, host: str, port: int, db: str
) -> SecretStr:
    """Assemble a Postgres DSN from its parts.

    `PostgresDsn.build` over f-string interpolation: it percent-encodes user and password
    correctly, where an f-string would turn a `@` in a generated password into a malformed
    URL rather than an error.

    The scheme carries the driver dialect, `postgresql+psycopg`: every consumer reaches
    Postgres through SQLAlchemy, so the dialect is not a per-caller decision.
    """
    dsn = PostgresDsn.build(
        scheme="postgresql+psycopg",
        username=username,
        password=password.get_secret_value(),
        host=host,
        port=port,
        path=db,
    )
    return SecretStr(str(dsn))


class _PostgresLocation(BaseSettings):
    """*Which* database — the half of a connection that does not depend on who is connecting.

    Shared base rather than repeated per identity: this service has two Postgres identities
    (see `AppRoleSettings` and `SuperuserSettings`), and they always address the same database.
    Declaring db/host/port once is what keeps them unable to drift apart.
    """

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    postgres_db: str = Field(min_length=1)
    # Defaults match docker-compose.yml's `postgres` service (DNS name on the compose
    # network, standard port) — real for dev/staging/prod. Overridden only by
    # integration tests, which point at a testcontainers instance on a random port
    # instead (tests/integration/interface/http/conftest.py's `client` fixture).
    postgres_host: str = "postgres"
    postgres_port: int = 5432


class AppRoleSettings(_PostgresLocation):
    """The credentials the *application* authenticates with — an unprivileged role.

    Split out of `Settings` so `scripts/provision_app_role.py` can read exactly this pair —
    it creates the role and applies the password — without having to supply JWKS, chunking
    or rate-limit config. `Settings` inherits it rather than redeclaring it.
    """

    postgres_user: str = Field(min_length=1)
    postgres_password: SecretStr = Field(min_length=1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> SecretStr:
        """Postgres DSN, assembled from the fields above, not read from its own env var."""
        return _postgres_dsn(
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            db=self.postgres_db,
        )


class SuperuserSettings(_PostgresLocation):
    """The credentials the deploy-time elevated entry points authenticate with (§8.0).

    A separate model rather than extra fields on `Settings`, for the reason the two Postgres
    roles exist at all: the serving application must never hold superuser credentials, which
    is what makes its own role's inability to bypass RLS mean anything
    (`scripts/bootstrap.py::_assert_rls_is_enforced`). A field on `Settings` would be either
    required — forcing every api container to carry the one credential it must not have — or
    optional, which is an invitation to set it.

    Read by two elevated callers, both run once per deploy: `migrations/env.py` and
    `scripts/provision_app_role.py`. Neither inherits `AppRoleSettings`: the deploy passes the
    app role's password only to the provisioning step.
    """

    # docker-compose.yml's `postgres` service reads this same variable to name the role its
    # initdb creates — one variable for both sides of the identity. Effectively fixed per
    # environment: the name is baked into the `pgdata` volume at initdb, so changing it
    # later renames nothing.
    postgres_superuser: str = Field(default="postgres", min_length=1)
    postgres_superuser_password: SecretStr = Field(min_length=1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> SecretStr:
        """Postgres DSN for the elevated connection, assembled the same way as the app's."""
        return _postgres_dsn(
            username=self.postgres_superuser,
            password=self.postgres_superuser_password,
            host=self.postgres_host,
            port=self.postgres_port,
            db=self.postgres_db,
        )


class Settings(AppRoleSettings):
    """Typed runtime configuration loaded from environment variables (§3.7/§3.8).

    One class with an `env` discriminator rather than per-env subclasses: there is a single
    config source (`os.environ`), and staging/prod populate `POSTGRES_PASSWORD` via
    `scripts.bootstrap._fetch_password_if_needed` before this class is constructed.

    Inherits the application's Postgres identity from `AppRoleSettings`, so those
    credentials have one declaration shared with `scripts/provision_app_role.py`. The
    superuser pair lives in `SuperuserSettings` and never reaches this class.

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
