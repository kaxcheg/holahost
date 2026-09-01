"""The two identities, and the DSN assembly that has to survive a generated password."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from holahost_db import AppRoleSettings, SuperuserSettings, postgres_dsn

_ENV = {
    "POSTGRES_DB": "ragdocs",
    "POSTGRES_USER": "app",
    "POSTGRES_PASSWORD": "app-secret",
    "POSTGRES_SUPERUSER_PASSWORD": "root-secret",
}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)


class TestDsnAssembly:
    def test_a_password_with_url_syntax_is_percent_encoded(self) -> None:
        # The reason this is a function and not an f-string. `@` unencoded ends the
        # userinfo section, so the DSN silently addresses a different host — an error only
        # at connect time, and only once a generated password happens to contain one.
        dsn = postgres_dsn(
            username="app", password=SecretStr("p@ss:w rd"), host="postgres", port=5432, db="db"
        ).get_secret_value()

        assert "p%40ss%3Aw%20rd" in dsn
        assert "@postgres:5432/db" in dsn

    def test_a_slash_in_the_password_fails_loudly_rather_than_silently(self) -> None:
        # The one character `PostgresDsn.build` refuses instead of encoding. Pinned
        # because it is a real operational trap, not a bug to route around: a generated
        # password containing `/` stops the process at startup with a parse error rather
        # than producing a DSN that addresses the wrong thing. AWS Secrets Manager's
        # `generate-random-password` includes `/` unless told not to.
        with pytest.raises(ValidationError):
            postgres_dsn(
                username="app", password=SecretStr("p/ss"), host="postgres", port=5432, db="db"
            )

    def test_the_driver_dialect_is_not_a_per_caller_decision(self) -> None:
        dsn = postgres_dsn(
            username="app", password=SecretStr("x"), host="h", port=1, db="d"
        ).get_secret_value()

        assert dsn.startswith("postgresql+psycopg://")


class TestTheTwoIdentities:
    def test_the_app_role_addresses_the_database_as_itself(self) -> None:
        url = AppRoleSettings().database_url.get_secret_value()

        assert "//app:app-secret@postgres:5432/ragdocs" in url

    def test_the_superuser_addresses_the_same_database_as_someone_else(self) -> None:
        # Same location — inherited from one declaration, so the two cannot drift apart —
        # different credentials.
        url = SuperuserSettings().database_url.get_secret_value()

        assert "//postgres:root-secret@postgres:5432/ragdocs" in url

    def test_the_app_role_model_cannot_reach_the_superuser_password(self) -> None:
        # The split is what keeps a serving process from holding the credential that
        # bypasses row-level security. A field on one model would be either required of
        # every process or optional, which is an invitation to set it.
        assert not hasattr(AppRoleSettings(), "postgres_superuser_password")

    def test_a_deploy_entry_point_needs_only_its_own_half(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `migrations/env.py` and role provisioning construct `SuperuserSettings` alone.
        # If it demanded the app role's fields too, every elevated entry point would have
        # to be handed credentials it has no business holding.
        monkeypatch.delenv("POSTGRES_USER")
        monkeypatch.delenv("POSTGRES_PASSWORD")

        assert SuperuserSettings().postgres_superuser == "postgres"

    def test_an_unrelated_variable_is_ignored_not_rejected(self) -> None:
        # A service's own `Settings` inherits `AppRoleSettings` and adds its own fields;
        # the environment holds both sets plus whatever else the container was given.
        AppRoleSettings(_env_file=None, **{"UNRELATED": "x"})  # type: ignore[arg-type]
