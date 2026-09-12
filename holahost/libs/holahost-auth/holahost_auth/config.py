"""What a service needs in order to validate a token, and where it comes from.

One class, not two: the field names *are* the environment variable names, lower-cased, and
that is the whole rule. A separate settings class with a mapping function between them
would be three declarations of one fact, and the mapping is the half that fails silently.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthConfig(BaseSettings):
    """The five variables every Holahost service reads to validate JWTs.

    Loads itself from the environment, so a composition root builds it with no arguments::

        def get_auth_config() -> AuthConfig:
            return AuthConfig()

    and a test builds it with all five explicit, which take precedence over the
    environment.

    The names are a platform contract rather than a per-service choice: the same five
    appear in every service's `.env.example`, every service validates tokens from the same
    issuer against the same JWKS, and the only value that differs between services is
    `expected_audience`. That is also why this is not mixed into a service's own `Settings`
    — the auth library's configuration is the auth library's, and handing a middleware an
    object that also carries a database password widens what the library can see for no
    gain.

    No field has a default. An authentication parameter a service forgot to set must stop
    it starting, not fall back to something plausible — so all five are required, and each
    is rejected empty (or negative) rather than merely present.

    :param jwks_url: URL of the JWKS endpoint.
    :param expected_algorithm: The single signing algorithm this service accepts
        (e.g. ``"RS256"``); never read from the token itself.
    :param expected_issuer: Expected ``iss`` claim value.
    :param expected_audience: Expected ``aud`` entry for this service.
    :param jwt_clock_skew_seconds: Allowed leeway when checking ``exp``/``iat``.
    """

    # `frozen`: nothing should rewrite an authentication parameter after startup, and the
    # middleware holds this object for the life of the process.
    model_config = SettingsConfigDict(frozen=True, case_sensitive=False, extra="ignore")

    jwks_url: str = Field(min_length=1)
    expected_algorithm: str = Field(min_length=1)
    expected_issuer: str = Field(min_length=1)
    expected_audience: str = Field(min_length=1)
    jwt_clock_skew_seconds: int = Field(ge=0)
