"""`AuthConfig` — one object that is both the environment's shape and the validator's."""

from typing import ClassVar

import pytest
from pydantic import ValidationError

from holahost_auth.config import AuthConfig

_ENV: dict[str, str] = {
    "JWKS_URL": "https://auth.example/.well-known/jwks.json",
    "EXPECTED_ALGORITHM": "RS256",
    "EXPECTED_ISSUER": "auth",
    "EXPECTED_AUDIENCE": "rag-documents",
    "JWT_CLOCK_SKEW_SECONDS": "30",
}


@pytest.fixture
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)


@pytest.mark.usefixtures("_env")
class TestLoadingFromTheEnvironment:
    """A composition root builds it with no arguments; the field names are the variable
    names, which is the whole mapping rule."""

    def test_every_field_comes_from_its_variable(self) -> None:
        config = AuthConfig()

        assert config.jwks_url == _ENV["JWKS_URL"]
        assert config.expected_algorithm == "RS256"
        assert config.expected_issuer == "auth"
        assert config.expected_audience == "rag-documents"
        assert config.jwt_clock_skew_seconds == 30

    def test_unrelated_variables_are_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The process environment carries a whole service's configuration, not just these.
        monkeypatch.setenv("POSTGRES_DB", "ragdocs")

        AuthConfig()

    def test_it_cannot_be_rewritten_after_construction(self) -> None:
        # The middleware holds this object for the life of the process; nothing should be
        # able to move an authentication parameter under it.
        config = AuthConfig()

        with pytest.raises(ValidationError):
            config.expected_audience = "someone-else"  # type: ignore[misc]


@pytest.mark.usefixtures("_env")
class TestNothingHasADefault:
    """An authentication parameter a service forgot to set must stop it starting, not fall
    back to something plausible."""

    _REQUIRED: ClassVar[list[str]] = list(_ENV)

    @pytest.mark.parametrize("variable", _REQUIRED)
    def test_an_unset_variable_is_refused(
        self, variable: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(variable)

        with pytest.raises(ValidationError, match=variable.lower()):
            AuthConfig()

    def test_a_blank_string_is_refused_as_well_as_an_absent_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `EXPECTED_ISSUER=` present but empty in an env file is a different mistake from
        # omitting the line, and reaches the process as a set-but-empty value.
        monkeypatch.setenv("EXPECTED_ISSUER", "")

        with pytest.raises(ValidationError, match="expected_issuer"):
            AuthConfig()

    def test_a_negative_skew_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JWT_CLOCK_SKEW_SECONDS", "-1")

        with pytest.raises(ValidationError, match="jwt_clock_skew_seconds"):
            AuthConfig()


class TestExplicitConstruction:
    """What a test, or any caller holding its own values, does. Arguments take precedence
    over the environment, so this works whether or not the five variables are set."""

    @pytest.fixture(autouse=True)
    def _no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in _ENV:
            monkeypatch.delenv(key, raising=False)

    def test_all_five_given_explicitly(self) -> None:
        config = AuthConfig(
            jwks_url="https://auth.example/.well-known/jwks.json",
            expected_algorithm="RS256",
            expected_issuer="auth",
            expected_audience="llm-client",
            jwt_clock_skew_seconds=0,
        )

        assert config.expected_audience == "llm-client"

    def test_an_empty_value_is_refused_here_too(self) -> None:
        with pytest.raises(ValidationError, match="jwks_url"):
            AuthConfig(
                jwks_url="",
                expected_algorithm="RS256",
                expected_issuer="auth",
                expected_audience="rag-documents",
                jwt_clock_skew_seconds=30,
            )
