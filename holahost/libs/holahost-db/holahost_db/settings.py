"""The two Postgres identities a Holahost service holds, as typed settings.

They are separate models rather than fields on one, and the split is load-bearing in both
directions. The serving application must never hold superuser credentials — that is what
makes its own role's inability to bypass row-level security mean anything. And the
deploy-time entry points (``alembic``'s ``env.py``, role provisioning) must be able to
construct exactly the credentials they use without supplying every unrelated required field
a service's own ``Settings`` has.
"""

from __future__ import annotations

from pydantic import Field, PostgresDsn, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


def postgres_dsn(*, username: str, password: SecretStr, host: str, port: int, db: str) -> SecretStr:
    """Assemble a Postgres DSN from its parts.

    ``PostgresDsn.build`` rather than an f-string: it percent-encodes ``@``, ``:`` and a
    space in the password, where interpolation would let a ``@`` end the userinfo section
    and silently address a different host.

    One character it does **not** encode: a ``/`` in the password raises
    ``ValidationError`` here instead. Loud and at startup, which is the right end of the
    trade, but it means a generated password containing one never reaches a running
    process — worth knowing when creating the secret, since AWS Secrets Manager's
    ``generate-random-password`` includes ``/`` unless ``--exclude-characters`` says
    otherwise.

    The scheme carries the driver dialect, ``postgresql+psycopg``: every consumer reaches
    Postgres through SQLAlchemy, so the dialect is not a per-caller decision.

    Raises:
        ValidationError: the assembled URL does not parse — in practice, a ``/`` in the
            password.
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


class PostgresLocation(BaseSettings):
    """*Which* database — the half of a connection that does not depend on who connects.

    Declared once and inherited by both identities, which is what keeps them unable to
    drift apart.
    """

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    postgres_db: str = Field(min_length=1)
    # Defaults match the compose service name and standard port — real for every
    # environment. Overridden only by integration tests pointing at a container on a
    # random host port.
    postgres_host: str = "postgres"
    postgres_port: int = 5432


class AppRoleSettings(PostgresLocation):
    """The credentials the *application* authenticates with — an unprivileged role."""

    postgres_user: str = Field(min_length=1)
    postgres_password: SecretStr = Field(min_length=1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> SecretStr:
        """Postgres DSN, assembled from the fields above, not read from its own env var."""
        return postgres_dsn(
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            db=self.postgres_db,
        )


class SuperuserSettings(PostgresLocation):
    """The credentials the deploy-time elevated entry points authenticate with.

    Read by two callers, both run once per deploy: ``alembic``'s ``env.py`` and role
    provisioning. Neither inherits ``AppRoleSettings`` — the deploy passes the app role's
    password only to the provisioning step.
    """

    # The compose ``postgres`` service reads this same variable to name the role its initdb
    # creates — one variable for both sides of the identity. Effectively fixed per
    # environment: the name is baked into the data volume at initdb, so changing it later
    # renames nothing.
    postgres_superuser: str = Field(default="postgres", min_length=1)
    postgres_superuser_password: SecretStr = Field(min_length=1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> SecretStr:
        """Postgres DSN for the elevated connection, assembled the same way."""
        return postgres_dsn(
            username=self.postgres_superuser,
            password=self.postgres_superuser_password,
            host=self.postgres_host,
            port=self.postgres_port,
            db=self.postgres_db,
        )
