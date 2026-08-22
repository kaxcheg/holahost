from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, PostgresDsn, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _postgres_dsn(
    *, username: str, password: SecretStr, host: str, port: int, db: str
) -> SecretStr:
    """Assemble a Postgres DSN from its parts.

    `PostgresDsn.build` over f-string interpolation: it percent-encodes special characters in
    user/password correctly (an f-string wouldn't — a `@` or `:` in a generated Secrets Manager
    password would silently produce a malformed URL, not an error).

    `postgresql+psycopg`, the driver dialect included, rather than a bare `postgresql` scheme
    each caller rewrites: every consumer of these DSNs reaches Postgres through SQLAlchemy, so
    the dialect is not a per-caller decision to defer. It used to be bare because
    `scripts/provision_app_role.py` handed the string straight to `psycopg.connect`, and libpq
    rejects the `+driver` form — but that made one script's choice of client dictate the
    spelling for the whole codebase, and paid for it with the same `.replace("postgresql://",
    "postgresql+psycopg://", 1)` written out at six call sites. That script now builds an
    `Engine` like everything else, so the exception, and all six rewrites, are gone.
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

    Split out of `Settings` so that `scripts/provision_app_role.py` can read exactly this and
    nothing else: it needs the app role's name and password (it is the code that creates the
    role and applies that password), but it is a standalone entry point with no business
    supplying JWKS, chunking or rate-limit config. `Settings` inherits the pair rather than
    redeclaring it, so there is one declaration of the app's own identity, not two.
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

    A separate model, not extra fields on `Settings`, and the separation is the same one the
    two Postgres roles exist for at all: the running application must never hold superuser
    credentials — that is what makes its own role's inability to bypass row-level security mean
    anything (`scripts/bootstrap.py::_assert_rls_is_enforced`). A `postgres_superuser_*` field
    on `Settings` would be either required — forcing every api container to carry the one
    credential it must not have — or optional, which is dead weight plus a standing invitation
    to set it.

    Read by exactly two callers, both elevated, both run once per deploy and never by the
    serving process: `migrations/env.py` (CREATE EXTENSION, CREATE POLICY, table ownership) and
    `scripts/provision_app_role.py` (creates the app role, applies its password). Note that
    neither carries `AppRoleSettings`' fields by inheritance, deliberately: the deploy passes
    the app role's password only to the provisioning step, so requiring it here would break the
    migration step, which has no reason to know it.
    """

    # docker-compose.yml's `postgres` service reads this same variable, with this same default,
    # to name the role its initdb creates — one variable for both sides of the identity, since a
    # client authenticating as a role the server never created just fails the deploy. The default
    # is chosen so it cannot collide with the app role named by POSTGRES_USER in
    # infra/envs/<env>/.env. Effectively fixed once per environment: the name is baked into the
    # `pgdata` volume at initdb, so changing it later renames nothing (see that file's comment).
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

    One class with an `env` discriminator (not per-env subclasses) — per-environment
    behavior branches inside validators such as `_validate_chunking_window`, since
    there is a single config source (`os.environ`); staging/prod populate
    `POSTGRES_PASSWORD` via `scripts.bootstrap._fetch_password_if_needed` BEFORE this class is
    constructed (R-24 composition root reads `env` first to decide whether to run it —
    out of scope here).

    Inherits the application's own Postgres identity and location from `AppRoleSettings` /
    `_PostgresLocation` rather than declaring them here, so the app role's credentials have
    one declaration shared with `scripts/provision_app_role.py`, which needs exactly that pair
    and nothing else. The *superuser* pair lives in `SuperuserSettings` and deliberately never
    reaches this class — see its docstring.

    Field set originally covered the R-11..R-19 subsystems; the four `jwks_url`/
    `expected_*` fields were added by R-20/R-24 for `holahost-auth` wiring. Deliberately
    does *not* carry `ALLOWED_MIME_TYPES`/`MAX_UPLOAD_SIZE`: those stay domain/
    application-owned constants (`domain.value_objects.mime_type.ALLOWED_MIME_TYPES`,
    `application.limits.MAX_UPLOAD_SIZE`) — the interface layer never needs its own
    copy of either, matching the project's "co-located with the adapter that reads it"
    convention.
    """

    env: Literal["dev", "staging", "prod"]
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
