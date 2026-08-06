"""Configuration for holahost-auth's JWT validation."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthConfig:
    """Explicit, required configuration for validating this service's JWTs.

    No field has a library-side default — values come from the consuming
    service's own typed settings (no implicit defaults, per project convention).

    :param jwks_url: URL of the JWKS endpoint.
    :param expected_algorithm: The single signing algorithm this service
        accepts (e.g. ``"RS256"``); never read from the token itself.
    :param expected_issuer: Expected ``iss`` claim value.
    :param expected_audience: Expected ``aud`` entry for this service.
    :param clock_skew_seconds: Allowed leeway when checking ``exp``/``iat``.
    """

    jwks_url: str
    expected_algorithm: str
    expected_issuer: str
    expected_audience: str
    clock_skew_seconds: int

    def __post_init__(self) -> None:
        if not self.jwks_url:
            raise ValueError("jwks_url must not be empty")
        if not self.expected_algorithm:
            raise ValueError("expected_algorithm must not be empty")
        if not self.expected_issuer:
            raise ValueError("expected_issuer must not be empty")
        if not self.expected_audience:
            raise ValueError("expected_audience must not be empty")
        if self.clock_skew_seconds < 0:
            raise ValueError("clock_skew_seconds must not be negative")
